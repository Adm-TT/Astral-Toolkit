"""会话循环（设计稿 v4 §2）：一个引擎的线程、状态、停止、提交边界和计时都收在这里

总规矩（v4 §2.0）：
1. Worker 实例上不放跟会话有关的可变状态：会话 / 尝试的状态全在 Worker 自己定义的 `Ctx`；
   启动时定下来、整个会话不变的东西（导航目标、盘点地点）放 `Session.payload`。
   热键名**不**进 payload：收尾提示要用收尾那一刻的设置，由调用方在锁外读好放进 `StopInfo.hotkey`。
2. 旧会话不能改新会话：每个会改共享状态的入口都先在锁内核对「传进来的会话就是当前会话、没被取消」。
3. 只有一条共享输出通道：`commit`；回调返回的 op 也走 `_apply_checked`。

线程还活着就永远不进 FAILED：停止再久也只是 STOPPING + `stop_timeout`。

锁规矩：loop 锁内不调 Worker 方法（`start_ops / stop_ops` 纯函数例外）、不做 OCR / 截图 / 网络 /
文件 / sleep / join；`_flag_lock` 先于 loop 锁。任一钩子抛异常都记 `HOOK_ERROR` 并照常走状态机。
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
    """会话状态（架构稿 §7.4）。FAILED 只在工作线程已经退出后出现（出错用尽）"""

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
    """一次停止的原因；error 是出错用尽时的最后一条错误文本；hotkey 是收尾提示里的热键名（锁外现读）"""

    reason: str  # user / idle / error / shutdown / replaced
    error: str = ""
    hotkey: str = ""


@dataclass(frozen=True)
class StopAttempt:
    """`_Live.stop()` 的返回：这次停的是哪个会话、线程有没有在超时内退出"""

    session_id: int | None
    joined: bool
    timed_out: bool


@dataclass(frozen=True)
class Tick:
    """一轮的回报：下一轮前等多久、这轮**看到了**哪些通道（与有没有提交无关）

    `observed` 的值是**观测时刻**（与循环同一个时钟，一般填这一轮开始的 `now`），不是持续时长；
    循环把它换算到活动时钟再记 `last_seen`——慢 tick 不会把「看到」往后推（v4.2 2-3）。
    """

    wait: float
    observed: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingView:
    """一条「已经请求停止、线程还没退」的记录"""

    session_id: int
    since: float
    deadline: float
    alive: bool
    stop_timeout: bool = False
    confirm_sent: bool = False


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
    stop_timeout: bool = False
    current_alive: bool = False

    @property
    def prev_stop_pending(self) -> bool:
        """「上次停止还没结束」：正在 STOPPING 且线程还活着，或有待结束记录没退"""
        return (
            self.stop_timeout
            or any(p.alive for p in self.pending)
            or (self.state is RunState.STOPPING and self.current_alive)
        )

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
    stale_after: dict[str, float]
    needs_foreground: bool
    restart_while_stopping: bool
    loop: "SessionLoop"  # 由 SessionLoop 绑上：tick 里用 loop.stamp / loop.commit / loop.config_rev

    @property
    def pause_wait(self) -> float: ...

    def hotkey(self) -> str:
        """收尾提示里的热键名：由循环在工作线程里、锁外调用（现读设置）"""
        ...

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
    confirm_sent: bool = False  # 「已停止」确认发过没
    superseded: bool = False  # 已被新会话取代（在 _pending 里）
    stop_timeout: bool = False  # 看门狗判过停止超时（状态仍留 STOPPING）
    join_timed_out: bool = (
        False  # join 已超时过一次（只有超时后，采矿才允许被新会话取代）
    )
    error: str = ""
    stop_reason: str | None = None
    stop_info: StopInfo | None = None
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
        self._shared: dict[str, Any] = {}
        self._hook_logs: list[Op] = []
        self._hook_logs_lock = threading.Lock()
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
                    p.stop_timeout,
                    p.confirm_sent,
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
                stop_timeout=bool(cur is not None and cur.stop_timeout),
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

    def shared_get(self, name: str) -> Any:
        with self._lock:
            return self._shared.get(name)

    def lock_held_by_me(self) -> bool:
        """测试辅助：当前线程是否持有 loop 锁"""
        return self._lock.held_by_me()

    def can_start(self) -> bool:
        if self._closing():
            return False
        with self._lock:
            cur = self._current
            if cur is None:
                return True
            if cur.state in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED):
                return False
            if not cur.thread.is_alive():
                return True
            return self._may_replace_locked(cur)

    def _may_replace_locked(self, run: _Run) -> bool:
        """停产中的会话能不能被新会话取代（v4.1/4.2 §2.3）：要允许重开、join 已超时（或看门狗已判超时）、
        且同时没有别的活着的旧线程在收尾"""
        if not run.join_timed_out and not run.stop_timeout:
            return False
        if not self._worker.restart_while_stopping:
            return False
        return not any(p.thread.is_alive() for p in self._pending.values())

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
            if cur is not None and (
                cur.state is RunState.STOPPING
                or (
                    cur.state in (RunState.STOPPED, RunState.FAILED)
                    and cur.thread.is_alive()
                )
            ):
                if cur.thread.is_alive():
                    if not self._may_replace_locked(cur):
                        return None
                    # 旧线程还在停：已被新会话取代，交给它自己的看门狗，以后不再发「已停止」
                    cur.superseded = True
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
            self._apply_locked(self._ops_safe(worker.start_ops, session), deferred)
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

    def request_stop_current(self, info: StopInfo | None = None) -> int | None:
        """按「当前会话」停止；没有在跑的会话时也发一次「已停止」确认（和 dev 一致）"""
        info = info if info is not None else StopInfo("user")
        # 没有会话时的确认先锁外算好（热键已经在 info 里）；第一次持锁若判定无会话就当场套用，
        # 不再二次拿锁复核——并发的 start() 只能在它之前或之后（2-6）
        none_ops = self._ops_safe(self._worker.stop_ops, None, info)
        deferred: list[Op] = []
        sid: int | None = None
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
                self._apply_locked(none_ops, deferred)
        self._run_ops(deferred)
        self._write_flag()
        return sid

    def request_shutdown(self) -> int | None:
        """退出专用：有活会话就按 shutdown 停；没有会话不发任何确认"""
        with self._lock:
            cur = self._current
            if cur is not None and cur.state in (
                RunState.STARTING,
                RunState.RUNNING,
                RunState.PAUSED,
            ):
                self._stop_locked(cur, StopInfo("shutdown"))
                sid = cur.session.id
            elif cur is not None and cur.state is RunState.STOPPING:
                sid = cur.session.id
            else:
                sid = None
        self._write_flag()
        return sid

    def _stop_locked(self, run: _Run, info: StopInfo) -> None:
        run.session.cancel.set()
        self._epoch += 1
        self._results.end(run.session.id)
        run.state = RunState.STOPPING
        run.stop_reason = info.reason
        run.stop_info = info
        if info.error:
            run.error = info.error
        run.paused_at = None
        run.paused_since = None
        run.join_timed_out = False  # 新的一次停止：之前的 join 超时记录不算数（3-5）
        self._flag_for(info)
        if info.reason in ("idle", "error"):
            # 自动关闭 / 出错用尽没人 join：自己起看门狗，否则线程卡住后 stop_timeout 永远不置（3-1）
            self._ensure_watchdog_locked(run)

    def _flag_for(self, info: StopInfo) -> None:
        if info.reason in ("user", "idle", "error"):
            self._flag_want = False

    def _confirm_stop_locked(
        self, run: _Run, info: StopInfo, deferred: list[Op]
    ) -> None:
        """唯一发「已停止」的地方：① 没确认过 ② 已发过就不发 ③ 被取代只记一条 record ④ 否则套 stop_ops"""
        if run.confirm_sent:
            return
        if run.superseded:
            run.confirm_sent = True
            deferred.append(
                ("record", "MINING", "采矿助手引擎已停止（已被新会话取代）", "")
            )
            return
        run.confirm_sent = True
        self._apply_locked(
            self._ops_safe(self._worker.stop_ops, run.session, info), deferred
        )

    def join(self, timeout: float | None = None, *, session_id: int) -> bool:
        """只等 `session_id` 那个会话自己的线程。超时 → 发确认、留 STOPPING、起它自己的看门狗"""
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
            if not run.thread.is_alive():
                return True  # 等在锁外这段时间里退出了（2-17）
            stopped = run.stop_info is not None or run.state is RunState.STOPPING
            if stopped:
                # 只有「已经按过停止」的会话才算 join 超时；还在跑的不置位、不起看门狗（3-5）
                run.join_timed_out = True
                self._confirm_stop_locked(run, self._info_of(run), deferred)
                run.since = self._clock()
                run.deadline = run.since + self._join_timeout
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
            return [
                PendingView(
                    p.session.id,
                    p.since,
                    p.deadline,
                    p.thread.is_alive(),
                    p.stop_timeout,
                    p.confirm_sent,
                )
                for p in list(self._pending.values())
                + ([self._current] if self._current is not None else [])
                if p.thread.is_alive()
            ]

    def _find_locked(self, session_id: int) -> _Run | None:
        cur = self._current
        if cur is not None and cur.session.id == session_id:
            return cur
        return self._pending.get(session_id)

    def _ensure_watchdog_locked(self, run: _Run) -> None:
        """每条记录最多一个看门狗（幂等）"""
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
            run = self._find_locked(session_id)
        if run is None:
            return
        run.thread.join(self._join_timeout * 3)
        deferred: list[Op] = []
        with self._lock:
            run = self._find_locked(session_id)
            if run is None:
                return
            if not run.thread.is_alive():
                return  # 已经退了：finally 收尾，别抢
            if run.stop_info is None and run.state is not RunState.STOPPING:
                return  # 没被按过停止：不算停止超时（3-5）
            run.stop_timeout = True  # 线程没退就不进 FAILED，只标出来
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
            if stamp is not None and (
                stamp.session_id != session.id or stamp.epoch != self._epoch
            ):
                return False
            if slot is not None:
                if stamp is None or not self._results.accept(
                    slot,
                    value,
                    stamp.session_id,
                    stamp.epoch,
                    stamp.seq,
                    stamp.mono,
                    stamp.wall,
                    quality,
                ):
                    return False
            self._apply_locked(ops, deferred)
        self._run_ops(deferred)
        return True

    # ---------------------------------------------------------------- 套用输出
    def _apply_locked(self, ops: Iterable[Op], deferred: list[Op]) -> None:
        """锁内调用：锁内类立刻套用（shared 写循环自己的表），锁后类排到释放锁之后"""
        for op in ops:
            if op[0] == "shared":
                self._shared[op[1]] = op[2]
            elif op[0] in POST_LOCK_KINDS:
                deferred.append(op)
            else:
                self._output.apply(op)

    def _run_ops(self, deferred: Iterable[Op]) -> None:
        for op in deferred:
            self._output.apply(op)
        self._flush_hook_logs()

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

    def _ops_safe(self, fn: Callable[..., Any], *args: Any) -> list[Op]:
        """调 Worker 的纯函数钩子：抛异常、返回 None / 不可迭代 / 非法 op 都记 HOOK_ERROR 当空列表（3-3）"""
        name = getattr(fn, "__name__", "hook")
        try:
            ops = list(fn(*args))  # 生成器也收下；None / 不可迭代在这里抛 TypeError
        except Exception as exc:  # noqa: BLE001 —— 钩子异常不能破坏状态机
            self._hook_error(name, exc)
            return []
        return self._ops_checked(name, ops)

    def _ops_checked(self, name: str, ops: Any) -> list[Op]:
        """钩子返回值统一先校验（锁外）：不合格记 HOOK_ERROR、当空列表（2-4）"""
        try:
            # 先落成列表：生成器只读一遍，否则校验读空后 op 被吞
            ops = list(ops)
            validate_ops(ops)
        except (TypeError, ValueError) as exc:
            self._hook_error(name, exc)
            return []
        return ops

    def _hook(self, name: str, fn: Callable[..., Any], *args: Any, default: Any) -> Any:
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 —— 钩子异常照常走状态机
            self._hook_error(name, exc)
            return default

    def _hook_error(self, name: str, exc: BaseException) -> None:
        """钩子自身出错：只排队一条锁后 log，绝不在锁内写文件（2-5）"""
        with self._hook_logs_lock:
            self._hook_logs.append(("log", f"HOOK_ERROR {name}: {exc!r}", "MINING"))

    def _flush_hook_logs(self) -> None:
        with self._hook_logs_lock:
            ops, self._hook_logs = self._hook_logs, []
        if ops:
            self._run_ops(ops)

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

    def _hotkey_now(self) -> str:
        """收尾提示里的热键名：锁外现读（Worker 实例上不留）"""
        hook = getattr(self._worker, "hotkey", None)
        if hook is None:
            return ""
        try:
            return str(hook())
        except Exception as exc:  # noqa: BLE001
            self._hook_error("hotkey", exc)
            return ""

    # ---------------------------------------------------------------- 工作线程
    def _run(self, session: Session) -> None:
        worker = self._worker
        attempts = max(1, int(worker.retries))
        ctx: Any = None
        try:
            for attempt in range(attempts):
                try:
                    try:
                        ctx = worker.setup(session)
                    except Exception as exc:  # noqa: BLE001 —— setup 抛算一次尝试失败，照常走重试
                        self._hook_error("setup", exc)
                        raise
                    if not self._begin_attempt(session):
                        break
                    self._loop(session, ctx)
                    break
                except Exception as exc:  # noqa: BLE001 —— 引擎出错要重试 / 收尾
                    if not session.alive():
                        break
                    self._hook(
                        "on_error", worker.on_error, session, ctx, exc, default=None
                    )
                    if ctx is None:
                        self._run_ops([("log", f"ERROR {exc!r}", "MINING")])
                    if not self._is_current(session):
                        break
                    if attempt + 1 >= attempts:
                        info = StopInfo("error", str(exc), hotkey=self._hotkey_now())
                        self.request_stop(session, info)
                        break
                    self._apply_checked(
                        session,
                        self._ops_safe(worker.before_retry, session, ctx, str(exc)),
                    )
                    self._hook("teardown", worker.teardown, session, ctx, default=None)
                    ctx = None
                    session.cancel.wait(1.0)
                    if session.cancel.is_set():
                        break  # 等在重试间隔里被停：别再开下一次尝试（2-19）
        finally:
            info = self._info_of_session(session)
            ops = self._ops_checked(
                "finish",
                self._hook("finish", worker.finish, session, ctx, info, default=[]),
            )
            self._hook("teardown", worker.teardown, session, ctx, default=None)
            self._finish_thread(session, info, ops if isinstance(ops, list) else [])

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
                self.request_stop(session, StopInfo("idle", hotkey=self._hotkey_now()))
                return
            tick = worker.tick(session, ctx, now)
            if not isinstance(tick, Tick):
                raise TypeError("tick 必须返回 Tick")
            if self._after_tick(session, ctx, tick):
                self.request_stop(session, StopInfo("idle", hotkey=self._hotkey_now()))
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
        self._apply_checked(
            session, self._ops_safe(self._worker.on_pause, session, ctx)
        )

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
        self._apply_checked(
            session, self._ops_safe(self._worker.on_resume, session, ctx, gap)
        )

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
        return self._active_at(run, now)

    def _active_at(self, run: _Run, stamp: float) -> float:
        """某个时刻（与循环同一个时钟）对应的活动时钟"""
        total = stamp - run.active_origin - run.paused_accum
        if run.paused_at is not None and stamp > run.paused_at:
            total -= stamp - run.paused_at
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
            for channel, stamp in tick.observed.items():
                # observed 的值是**观测时刻**（和循环同一个时钟），换算到活动时钟再记（2-3）
                cur.last_seen[channel] = min(active, self._active_at(cur, float(stamp)))
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
            self._apply_checked(
                session, self._ops_safe(self._worker.on_stale, session, ctx, channel)
            )
        return False

    def _is_current(self, session: Session) -> bool:
        with self._lock:
            cur = self._current
            return (
                cur is not None
                and cur.session is session
                and session.alive()
                and cur.state in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED)
            )

    def _info_of(self, run: _Run) -> StopInfo:
        return run.stop_info or StopInfo(run.stop_reason or "user", run.error)

    def _info_of_session(self, session: Session) -> StopInfo:
        with self._lock:
            cur = self._current
            if cur is not None and cur.session is session:
                return self._info_of(cur)
            pending = self._pending.get(session.id)
            if pending is not None:
                return self._info_of(pending)
            return StopInfo("user")

    def _finish_thread(self, session: Session, info: StopInfo, ops: list[Op]) -> None:
        """工作线程退出：finish / teardown 已做完，这里收尾状态和「已停止」"""
        deferred: list[Op] = []
        with self._lock:
            cur = self._current
            if cur is not None and cur.session is session:
                self._apply_locked(ops, deferred)  # finish 的锁内类 op（含 shared）
                self._confirm_stop_locked(cur, info, deferred)
                cur.stop_timeout = False  # 线程这会儿已经退了
            else:
                pending = self._pending.get(
                    session.id
                )  # 先留着：线程真退出前一步才移出（3-4）
                if pending is not None:
                    # 已被新会话取代：只执行锁后类 log，不碰 HUD / 事件 / 状态 / 共享结果
                    for op in ops:
                        if op and op[0] == "log":
                            deferred.append(op)
                    self._confirm_stop_locked(pending, info, deferred)
        # 锁外把收尾输出发完，最后才写最终状态 / 移出 pending：这期间线程还活着，
        # 任何时刻都在 _current 或 _pending 里（3-4），start() 会按「仍在停止」处理（2-2）
        self._run_ops(deferred)
        with self._lock:
            cur = self._current
            if cur is not None and cur.session is session:
                cur.stop_timeout = False
                cur.state = (
                    RunState.FAILED if info.reason == "error" else RunState.STOPPED
                )
                if info.reason == "error" and info.error:
                    cur.error = info.error
            else:
                # 收尾期间被取代（或本来就在 pending）：这一步线程才算真退出
                pending = self._pending.pop(session.id, None)
                if pending is not None:
                    pending.stop_timeout = False
