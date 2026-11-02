"""会话循环（设计稿 v3 §2）：一个引擎的线程、状态、停止、提交边界和计时都收在这里

三条总规矩（v3 §2.0）：
1. Worker 实例上不放跟会话有关的可变状态：会话 / 尝试的状态全在 Worker 自己定义的 `Ctx`，
   启动时定下来、整个会话不变的东西（热键名、导航目标）放进 `Session.payload`。
2. 旧会话不能改新会话：每个会改共享状态的入口都先在锁内核对「传进来的会话就是当前会话、没被取消」。
3. 只有一条共享输出通道：`commit`；回调返回的 op 也走 `_apply_checked`。

锁规矩：loop 锁内不调 Worker 方法（`start_ops / stop_ops` 纯函数例外）、不做 OCR / 截图 / 网络 /
文件 / sleep / join；`_flag_lock` 先于 loop 锁。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Protocol

from .output import POST_LOCK_KINDS, Output, validate_ops
from .results import ResultStore

Clock = Callable[[], float]
Op = tuple


def _never() -> bool:
    return False


class RunState(Enum):
    """会话状态（架构稿 §7.4）"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    FAILED = "failed"


class Freshness(Enum):
    """一个通道的新鲜度，和 RunState 独立"""

    EMPTY = "empty"
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True)
class Session:
    """一次会话的令牌：工作线程只拿它，拿不到循环本体的开关。payload 整个会话不变"""

    id: int
    cancel: threading.Event
    payload: Any = None

    def alive(self) -> bool:
        return not self.cancel.is_set()


@dataclass(frozen=True)
class Stamp:
    """一帧开始时的控制状态：算完提交时用它判断结果是不是还算数"""

    session_id: int
    epoch: int
    seq: int
    mono: float
    wall: float


@dataclass(frozen=True)
class StopInfo:
    """一次停止的原因；error 是出错用尽时的最后一条错误文本"""

    reason: str  # user / idle / error / shutdown / replaced
    error: str = ""


@dataclass(frozen=True)
class Tick:
    """一轮的回报：下一轮前等多久、这轮**看到了**哪些通道（与有没有提交无关）"""

    wait: float
    observed: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingView:
    """一条「已经请求停止、线程还没退」的记录"""

    session_id: int
    since: float
    deadline: float
    alive: bool
    failed: bool


@dataclass(frozen=True)
class StateView:
    """给 status / 反馈 / HTTP 读的快照"""

    state: RunState
    session_id: int
    epoch: int
    paused_since: float | None
    last_error: str | None
    stop_reason: str | None
    pending: tuple[PendingView, ...]
    current_alive: bool = False

    @property
    def prev_stop_pending(self) -> bool:
        """还有没有上次停止留下的、没退出的线程"""
        return any(p.alive for p in self.pending)

    @property
    def worker_alive(self) -> bool:
        return self.current_alive or any(p.alive for p in self.pending)


@dataclass(frozen=True)
class RunFlag:
    """循环独占的开关（采矿 = live_on）：key 和写盘函数都由外面给"""

    key: str
    write: Callable[[str, bool], None]


class Worker(Protocol):
    """每个引擎实现：只写业务，不写线程"""

    name: str
    retries: int
    idle_close: float | None
    stale_after: Mapping[str, float]
    needs_foreground: bool
    pause_wait: float
    restart_while_stopping: bool
    loop: "SessionLoop"  # 由 SessionLoop 绑上：tick 里用 loop.stamp / loop.commit / loop.config_rev

    def start_ops(self, session: Session) -> list[Op]: ...
    def stop_ops(self, session: Session | None, info: StopInfo) -> list[Op]: ...
    def setup(self, session: Session) -> Any: ...
    def tick(self, session: Session, ctx: Any, now: float) -> Tick: ...
    def on_pause(self, session: Session, ctx: Any) -> list[Op]: ...
    def on_resume(self, session: Session, ctx: Any, gap: float) -> list[Op]: ...
    def on_stale(self, session: Session, ctx: Any, channel: str) -> list[Op]: ...
    def on_error(self, session: Session, ctx: Any, exc: BaseException) -> None: ...
    def before_retry(self, session: Session, ctx: Any, error: str) -> list[Op]: ...
    def finish(self, session: Session, ctx: Any, info: StopInfo) -> list[Op]: ...
    def teardown(self, session: Session, ctx: Any) -> None: ...


class _OwnedLock:
    """带持有者记录的锁：`lock_held_by_me()` 给测试记录「这次输出是不是在锁里」"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: int | None = None

    def __enter__(self) -> "_OwnedLock":
        self._lock.acquire()
        self._owner = threading.get_ident()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._owner = None
        self._lock.release()

    def held_by_me(self) -> bool:
        return self._owner is not None and self._owner == threading.get_ident()


@dataclass
class _Run:
    """当前会话 / 一条待结束会话的全部状态（计时按会话存在这里）"""

    session: Session
    thread: threading.Thread
    state: RunState = RunState.STARTING
    confirmed: bool = False  # 「已停止」确认发过没
    suppressed: bool = False  # 已有更新会话：确认永远不发，只记一条 record
    failed: bool = False  # 看门狗判过停止超时
    error: str = ""
    stop_reason: str | None = None
    since: float = 0.0
    deadline: float = 0.0
    active_origin: float = 0.0
    paused_accum: float = 0.0
    paused_at: float | None = None
    paused_since: float | None = None
    attempt_started: float = 0.0
    last_seen: dict[str, float] = field(default_factory=dict)
    freshness: dict[str, Freshness] = field(default_factory=dict)
    wait: float = 0.25
    watchdog: threading.Thread | None = None


class SessionLoop:
    def __init__(
        self,
        worker: Worker,
        *,
        results: ResultStore,
        output: Output,
        foreground: Callable[[], bool | None],
        clock: Clock | None = None,
        join_timeout: float = 3.0,
        run_flag: RunFlag | None = None,
        closing: Callable[[], bool] = _never,
    ) -> None:
        self._worker = worker
        self._results = results
        self._output = output
        self._foreground = foreground
        self._clock: Clock = clock if clock is not None else time.monotonic
        self._join_timeout = join_timeout
        self._run_flag = run_flag
        self._closing = closing
        self._lock = _OwnedLock()
        self._flag_lock = threading.Lock()
        self._flag_want: bool | None = None
        self._flag_last: bool | None = None
        self._current: _Run | None = None
        self._pending: dict[int, _Run] = {}
        self._session_id = 0
        self._epoch = 0
        self._config_rev = 0
        self._seq = 0
        worker.loop = (
            self  # 工作者的 tick 要用 loop.commit / loop.stamp / loop.config_rev
        )

    # ---------------------------------------------------------------- 查询
    def state(self) -> StateView:
        with self._lock:
            cur = self._current
            pending = tuple(
                PendingView(
                    p.session.id,
                    p.since,
                    p.deadline,
                    p.thread.is_alive(),
                    p.failed,
                )
                for p in self._pending.values()
            )
            return StateView(
                state=cur.state if cur is not None else RunState.STOPPED,
                session_id=cur.session.id if cur is not None else 0,
                epoch=self._epoch,
                paused_since=cur.paused_since if cur is not None else None,
                last_error=(cur.error or None) if cur is not None else None,
                stop_reason=cur.stop_reason if cur is not None else None,
                pending=pending,
                current_alive=bool(cur is not None and cur.thread.is_alive()),
            )

    def running(self) -> bool:
        """逻辑运行中：当前会话 ∈ STARTING / RUNNING / PAUSED（STOPPING 时为 False）"""
        with self._lock:
            return self._current is not None and self._current.state in (
                RunState.STARTING,
                RunState.RUNNING,
                RunState.PAUSED,
            )

    def worker_alive(self) -> bool:
        return self.state().worker_alive

    def freshness(self, channel: str) -> Freshness:
        with self._lock:
            cur = self._current
            if cur is None:
                return Freshness.EMPTY
            return cur.freshness.get(channel, Freshness.EMPTY)

    @property
    def config_rev(self) -> int:
        with self._lock:
            return self._config_rev

    def lock_held_by_me(self) -> bool:
        """测试辅助：当前线程是否持有 loop 锁"""
        return self._lock.held_by_me()

    def can_start(self) -> bool:
        if self._closing():
            return False
        with self._lock:
            cur = self._current
            if cur is None or not cur.thread.is_alive():
                return True
            if cur.state in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED):
                return False
            return bool(self._worker.restart_while_stopping)

    # ---------------------------------------------------------------- 起停
    def start(self, payload: Any = None) -> int | None:
        """开新会话；返回会话号，被拒返回 None"""
        if self._closing():
            return None
        deferred: list[Op] = []
        worker = self._worker
        with self._lock:
            cur = self._current
            if cur is not None and cur.state in (
                RunState.STARTING,
                RunState.RUNNING,
                RunState.PAUSED,
            ):
                return cur.session.id if cur.session.payload == payload else None
            if cur is not None and cur.state is RunState.STOPPING:
                if cur.thread.is_alive():
                    if not worker.restart_while_stopping:
                        return None
                    # 旧线程还在停：交给看门狗，它永远不发「已停止」，只记一条记录
                    if not cur.confirmed:
                        cur.suppressed = True
                    cur.since = self._clock()
                    cur.deadline = cur.since + self._join_timeout
                    self._pending[cur.session.id] = cur
                    self._ensure_watchdog_locked(cur)
                else:
                    cur.state = RunState.STOPPED
            pending_alive = any(p.thread.is_alive() for p in self._pending.values())
            self._session_id += 1
            session = Session(self._session_id, threading.Event(), payload)
            run = _Run(
                session=session,
                thread=threading.Thread(
                    target=self._run, args=(session,), daemon=True, name=worker.name
                ),
                active_origin=self._clock(),
                state=RunState.STARTING,
            )
            self._current = run
            self._flag_want = True
            run.thread.start()
            if pending_alive:
                self._apply_locked(
                    [
                        ("log", "上次停止还没结束，已开新会话", "MINING"),
                        (
                            "record",
                            "MINING",
                            "采矿助手上次停止还没结束，已开新会话",
                            "",
                        ),
                    ],
                    deferred,
                )
            self._apply_locked(worker.start_ops(session), deferred)
            sid = session.id
        self._run_ops(deferred)
        self._write_flag()
        return sid

    def request_stop(self, session: Session, info: StopInfo) -> bool:
        """结束指定会话。只有它仍是当前会话、没停过才有效"""
        with self._lock:
            cur = self._current
            if (
                cur is None
                or cur.session is not session
                or not session.alive()
                or cur.state
                not in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED)
            ):
                return False
            self._stop_locked(cur, info)
        self._write_flag()
        return True

    def request_stop_current(
        self,
        info: StopInfo | None = None,
        *,
        no_session_ops: list[Op] | None = None,
    ) -> int | None:
        """按「当前会话」停止；没有在跑的会话时也发一次「已停止」确认（和 dev 一致）"""
        info = info if info is not None else StopInfo("user")
        deferred: list[Op] = []
        sid: int | None = None
        need_none_ops = False
        with self._lock:
            cur = self._current
            if cur is not None and cur.state in (
                RunState.STARTING,
                RunState.RUNNING,
                RunState.PAUSED,
            ):
                self._stop_locked(cur, info)
                sid = cur.session.id
            elif cur is not None and cur.state is RunState.STOPPING:
                sid = cur.session.id
            else:
                self._flag_for(info)
                need_none_ops = True
        if need_none_ops:
            ops = (
                no_session_ops
                if no_session_ops is not None
                else self._worker.stop_ops(None, info)  # 锁外：可能现读设置
            )
            validate_ops(ops)
            with self._lock:
                cur = self._current
                if cur is None or cur.state not in (
                    RunState.STARTING,
                    RunState.RUNNING,
                    RunState.PAUSED,
                ):
                    self._apply_locked(ops, deferred)
        self._run_ops(deferred)
        self._write_flag()
        return sid

    def _stop_locked(self, run: _Run, info: StopInfo) -> None:
        run.session.cancel.set()
        self._epoch += 1
        self._results.end(run.session.id)
        run.state = RunState.STOPPING
        run.stop_reason = info.reason
        if info.error:
            run.error = info.error
        run.paused_at = None
        run.paused_since = None
        self._flag_for(info)

    def _flag_for(self, info: StopInfo) -> None:
        if info.reason in ("user", "idle", "error"):
            self._flag_want = False

    def _confirm_stop_locked(
        self, run: _Run, info: StopInfo, deferred: list[Op]
    ) -> None:
        """唯一发「已停止」的地方：每个会话一次；被新会话取代的只记一条 record"""
        if run.confirmed:
            return
        if run.suppressed:
            run.confirmed = True  # 只记一条
            deferred.append(
                ("record", "MINING", "采矿助手引擎已停止（已被新会话取代）", "")
            )
            return
        run.confirmed = True
        self._apply_locked(self._worker.stop_ops(run.session, info), deferred)

    def join(self, timeout: float | None = None, *, session_id: int) -> bool:
        """只等 `session_id` 那个会话自己的线程。超时 → 发确认、留 STOPPING、交给它自己的看门狗"""
        with self._lock:
            run = self._find_locked(session_id)
        if run is None:
            return True
        thread = run.thread
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(self._join_timeout if timeout is None else timeout)
        if not thread.is_alive():
            return True
        deferred: list[Op] = []
        with self._lock:
            run = self._find_locked(session_id)
            if run is None:
                return True
            if run.thread.is_alive():
                self._confirm_stop_locked(
                    run, StopInfo(run.stop_reason or "user", run.error), deferred
                )
                run.since = self._clock()
                run.deadline = run.since + self._join_timeout
                self._pending[session_id] = run
                self._ensure_watchdog_locked(run)
        self._run_ops(deferred)
        return False

    def join_all(self, timeout: float) -> list[PendingView]:
        """把所有活着的线程在预算内等一遍，返回还没退的（B6 退出用）"""
        deadline = self._clock() + timeout
        with self._lock:
            runs = list(self._pending.values())
            if self._current is not None:
                runs.append(self._current)
        for run in runs:
            left = deadline - self._clock()
            if left <= 0:
                break
            if run.thread.is_alive() and run.thread is not threading.current_thread():
                run.thread.join(left)
        with self._lock:
            every = list(self._pending.values())
            if self._current is not None:
                every.append(self._current)
            return [
                PendingView(
                    p.session.id, p.since, p.deadline, p.thread.is_alive(), p.failed
                )
                for p in every
                if p.thread.is_alive()
            ]

    def _find_locked(self, session_id: int) -> _Run | None:
        cur = self._current
        if cur is not None and cur.session.id == session_id:
            return cur
        return self._pending.get(session_id)

    def _ensure_watchdog_locked(self, run: _Run) -> None:
        if run.watchdog is not None:
            return
        watchdog = threading.Thread(
            target=self._watch,
            args=(run.session.id,),
            daemon=True,
            name=f"{self._worker.name}-watchdog",
        )
        run.watchdog = watchdog
        watchdog.start()

    def _watch(self, session_id: int) -> None:
        with self._lock:
            run = self._pending.get(session_id)
        if run is None:
            return
        run.thread.join(self._join_timeout * 3)
        deferred: list[Op] = []
        with self._lock:
            run = self._pending.get(session_id)
            if run is None:
                return
            if not run.thread.is_alive():
                return  # 已经退了：finally 收尾，别抢
            run.failed = True
            if self._current is run:
                self._current.state = RunState.FAILED
                self._current.error = "stop_timeout"
            deferred.append(
                ("record", "MINING", "采矿助手停止超时：旧线程仍未退出", "")
            )
        self._run_ops(deferred)

    # ---------------------------------------------------------------- 提交边界
    def config_changed(self) -> None:
        """配装变了：正在算的结果作废（epoch+1），tick 的 shown 键读 config_rev"""
        with self._lock:
            self._epoch += 1
            self._config_rev += 1

    def stamp(self, session: Session, wall: float) -> Stamp | None:
        """一帧开始时的序号；会话 / 状态 / 取消任一项不过就返回 None"""
        with self._lock:
            cur = self._current
            if (
                cur is None
                or cur.session is not session
                or not session.alive()
                or cur.state not in (RunState.RUNNING, RunState.PAUSED)
            ):
                return None
            self._seq += 1
            return Stamp(session.id, self._epoch, self._seq, self._clock(), wall)

    def commit(
        self,
        session: Session,
        *ops: Op,
        slot: str | None = None,
        value: Any = None,
        stamp: Stamp | None = None,
        quality: str = "complete",
    ) -> bool:
        """提交边界（架构稿 §7.5）：三查 → 看 epoch → 存结果 → 输出。任一不过整个不做"""
        validate_ops(ops)
        deferred: list[Op] = []
        with self._lock:
            cur = self._current
            if (
                cur is None
                or cur.session is not session
                or not session.alive()
                or cur.state not in (RunState.RUNNING, RunState.PAUSED)
            ):
                return False
            if slot is not None:
                if (
                    stamp is None
                    or stamp.session_id != session.id
                    or stamp.epoch != self._epoch
                    or not self._results.accept(
                        slot,
                        value,
                        stamp.session_id,
                        stamp.epoch,
                        stamp.seq,
                        stamp.mono,
                        stamp.wall,
                        quality,
                    )
                ):
                    return False
            self._apply_locked(ops, deferred)
        self._run_ops(deferred)
        return True

    # ---------------------------------------------------------------- 套用输出
    def _apply_locked(self, ops: Iterable[Op], deferred: list[Op]) -> None:
        """锁内调用：锁内类立刻套用，锁后类排到释放锁之后"""
        for op in ops:
            if op[0] in POST_LOCK_KINDS:
                deferred.append(op)
            else:
                self._output.apply(op)

    def _run_ops(self, deferred: Iterable[Op]) -> None:
        for op in deferred:
            self._output.apply(op)

    def _apply_checked(self, session: Session, ops: list[Op]) -> None:
        """回调返回的 op：锁内三查通过才套用，否则整批丢弃"""
        if not ops:
            return
        validate_ops(ops)
        deferred: list[Op] = []
        with self._lock:
            cur = self._current
            if (
                cur is None
                or cur.session is not session
                or not session.alive()
                or cur.state
                not in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED)
            ):
                return
            self._apply_locked(ops, deferred)
        self._run_ops(deferred)

    def _write_flag(self) -> None:
        """锁外、_flag_lock 里按**最新**期望值写盘；锁序：_flag_lock → loop 锁"""
        flag = self._run_flag
        if flag is None:
            return
        with self._flag_lock:
            with self._lock:
                want = self._flag_want
            if want is None or want == self._flag_last:
                return
            try:
                flag.write(flag.key, want)
            except Exception:  # noqa: BLE001 —— 设置写不进去也不能让收尾半路炸掉
                pass
            self._flag_last = want

    # ---------------------------------------------------------------- 工作线程
    def _run(self, session: Session) -> None:
        worker = self._worker
        attempts = max(1, int(worker.retries))
        ctx: Any = None
        try:
            for attempt in range(attempts):
                try:
                    ctx = worker.setup(session)
                    if not self._begin_attempt(session):
                        break
                    self._loop(session, ctx)
                    break
                except Exception as exc:  # noqa: BLE001 —— 引擎出错要重试 / 收尾
                    if not session.alive():
                        break
                    worker.on_error(session, ctx, exc)
                    if not self._is_current(session):
                        break
                    if attempt + 1 >= attempts:
                        self.request_stop(session, StopInfo("error", str(exc)))
                        break
                    self._before_retry(session, ctx, str(exc))
                    worker.teardown(session, ctx)
                    ctx = None
                    session.cancel.wait(1.0)
        finally:
            info = self._info(session)
            ops = worker.finish(session, ctx, info)
            worker.teardown(session, ctx)
            self._finish_thread(session, info, ops)

    def _begin_attempt(self, session: Session) -> bool:
        with self._lock:
            cur = self._current
            if cur is None or cur.session is not session or not session.alive():
                return False
            cur.state = RunState.RUNNING
            active = self._active(cur, self._clock())
            cur.attempt_started = active
            for channel in self._worker.stale_after:
                cur.last_seen[channel] = active
                cur.freshness[channel] = Freshness.FRESH
            return True

    def _loop(self, session: Session, ctx: Any) -> None:
        worker = self._worker
        while True:
            if session.cancel.is_set():
                return
            now = self._clock()
            if worker.needs_foreground and self._foreground() is False:
                # 进暂停的时刻在「读前台窗口」之后取：读窗口本身也花时间（假时钟里这一步还会走时间）
                self._enter_pause(session, ctx, self._clock())
                session.cancel.wait(max(0.0, float(worker.pause_wait)))
                continue
            if self._is_paused(session):
                self._leave_pause(session, ctx, now)
            if self._idle_expired(session):
                self.request_stop(session, StopInfo("idle"))
                return
            tick = worker.tick(session, ctx, now)
            if self._after_tick(session, ctx, tick):
                self.request_stop(session, StopInfo("idle"))
                return
            session.cancel.wait(max(0.0, float(tick.wait)))

    def _enter_pause(self, session: Session, ctx: Any, now: float) -> None:
        with self._lock:
            cur = self._current
            if (
                cur is None
                or cur.session is not session
                or not session.alive()
                or cur.state not in (RunState.STARTING, RunState.RUNNING)
            ):
                return
            cur.state = RunState.PAUSED
            cur.paused_since = now
            cur.paused_at = now
        self._apply_checked(session, self._worker.on_pause(session, ctx))

    def _leave_pause(self, session: Session, ctx: Any, now: float) -> None:
        with self._lock:
            cur = self._current
            if cur is None or cur.session is not session or not session.alive():
                return
            if cur.state is not RunState.PAUSED:
                return
            paused_at = cur.paused_at if cur.paused_at is not None else now
            gap = max(0.0, now - paused_at)
            cur.paused_accum += gap
            cur.paused_at = None
            cur.paused_since = None
            cur.state = RunState.RUNNING
        self._apply_checked(session, self._worker.on_resume(session, ctx, gap))

    def _is_paused(self, session: Session) -> bool:
        with self._lock:
            cur = self._current
            return (
                cur is not None
                and cur.session is session
                and cur.state is RunState.PAUSED
            )

    def _active(self, run: _Run, now: float) -> float:
        """扣掉暂停段的活动时钟"""
        total = now - run.active_origin - run.paused_accum
        if run.paused_at is not None:
            total -= now - run.paused_at
        return total

    def _idle_expired(self, session: Session) -> bool:
        limit = self._worker.idle_close
        if limit is None:
            return False
        with self._lock:
            cur = self._current
            if cur is None or cur.session is not session or not session.alive():
                return False
            active = self._active(cur, self._clock())
            last = max(cur.last_seen.values(), default=cur.attempt_started)
            return active - last > float(limit)

    def _after_tick(self, session: Session, ctx: Any, tick: Tick) -> bool:
        """记 observed、判过期；返回要不要自动关闭"""
        stale: list[str] = []
        idle = False
        with self._lock:
            cur = self._current
            if (
                cur is None
                or cur.session is not session
                or not session.alive()
                or cur.state not in (RunState.STARTING, RunState.RUNNING)
            ):
                return False
            active = self._active(cur, self._clock())
            for channel in tick.observed:
                cur.last_seen[channel] = active
                cur.freshness[channel] = Freshness.FRESH
            for channel, limit in (self._worker.stale_after or {}).items():
                if cur.freshness.get(channel) is not Freshness.FRESH:
                    continue
                if active - cur.last_seen.get(channel, active) > float(limit):
                    cur.freshness[channel] = Freshness.STALE
                    stale.append(channel)
            limit_idle = self._worker.idle_close
            if limit_idle is not None:
                last = max(cur.last_seen.values(), default=cur.attempt_started)
                idle = active - last > float(limit_idle)
            cur.wait = max(0.0, float(tick.wait))
        if idle:
            return True
        for channel in stale:
            self._apply_checked(session, self._worker.on_stale(session, ctx, channel))
        return False

    def _before_retry(self, session: Session, ctx: Any, error: str) -> None:
        self._apply_checked(session, self._worker.before_retry(session, ctx, error))

    def _is_current(self, session: Session) -> bool:
        with self._lock:
            cur = self._current
            return (
                cur is not None
                and cur.session is session
                and session.alive()
                and cur.state in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED)
            )

    def _info(self, session: Session) -> StopInfo:
        with self._lock:
            cur = self._current
            if cur is not None and cur.session is session:
                return StopInfo(
                    cur.stop_reason or ("error" if cur.error else "user"), cur.error
                )
            pending = self._pending.get(session.id)
            if pending is not None:
                return StopInfo(
                    pending.stop_reason or ("error" if pending.error else "user"),
                    pending.error,
                )
            return StopInfo("user")

    def _finish_thread(self, session: Session, info: StopInfo, ops: list[Op]) -> None:
        """工作线程退出：finish 已经做完，这里收尾状态和「已停止」"""
        validate_ops(ops)
        deferred: list[Op] = []
        with self._lock:
            cur = self._current
            if cur is not None and cur.session is session:
                self._confirm_stop_locked(cur, info, deferred)
                if cur.state in (
                    RunState.STARTING,
                    RunState.RUNNING,
                    RunState.PAUSED,
                    RunState.STOPPING,
                ):
                    self._apply_locked(ops, deferred)
                    cur.state = (
                        RunState.FAILED if info.reason == "error" else RunState.STOPPED
                    )
                    if info.reason == "error" and info.error:
                        cur.error = info.error
                self._pending.pop(session.id, None)
            else:
                pending = self._pending.pop(session.id, None)
                if pending is not None:
                    # 已有更新会话：只执行锁后类 op，不碰 HUD、事件、状态
                    for op in ops:
                        if op[0] in POST_LOCK_KINDS:
                            deferred.append(op)
        self._run_ops(deferred)
