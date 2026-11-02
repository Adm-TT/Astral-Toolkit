"""会话循环（设计稿 §2）：一个引擎的线程、状态、停止、提交边界和计时都收在这里

引擎（Worker）只写业务：`setup / tick / on_* / start_ops / retry_ops / finish_ops / teardown`，
不自己起线程、不自己判断前台 / 自动关闭 / 过期、不自己重试。全部状态在 `self._lock` 里改，
锁内只做小操作（同 RT-B3）：不 OCR、不截图、不网络、不写文件、不 sleep、不 join。
收尾事件（`finish_ops` 交给循环的输出）在锁内发（RT-B3 遗留②）；事件之前要写日志文件这类事
由 `on_stop` / `on_error` 在锁外做。

计时用「扣掉暂停段的活动时钟」：切出游戏时自动关闭和过期都冻结，回来后接着算。
时钟可注入（测试用假时钟）；默认取 `time.time`，和 live 现在的计时一致。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol

from ..core import run_records
from .output import Output
from .results import ResultStore

Clock = Callable[[], float]
Op = tuple  # ("bus", kind, data) / ("hud.set", section, text[, rich]) / ("hud.clear", *sections) / ("log", line, tag) / ("note", section, text[, secs])


class RunState(Enum):
    """会话状态（架构稿 §7.4）"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    FAILED = "failed"


class Freshness(Enum):
    """一个结果槽的新鲜度，和 RunState 独立"""

    EMPTY = "empty"
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True)
class Session:
    """一次会话的令牌：工作线程只拿它，拿不到循环本体的开关"""

    id: int
    cancel: threading.Event

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
class StateView:
    """给 status / 反馈 / HTTP 读的快照，代替直接读引擎内部字段"""

    state: RunState
    session_id: int
    epoch: int
    paused_since: float | None
    last_error: str | None
    stop_reason: str | None
    worker_alive: bool
    prev_stop_pending: bool


@dataclass(frozen=True)
class Tick:
    """工作者一轮的回报：下一轮前等多久、这轮有没有看到有效目标、刷新了哪些结果槽"""

    wait: float
    active: bool
    seen: frozenset[str]


class Worker(Protocol):
    """每个引擎实现：只写业务，不写线程"""

    name: str
    retries: int
    idle_close: float | None
    stale_after: float | None
    needs_foreground: bool
    restart_while_stopping: bool
    loop: "SessionLoop"  # 由 SessionLoop 绑上：tick 里用 loop.commit / loop.stamp

    def setup(self, session: Session) -> None: ...
    def tick(self, session: Session, now: float) -> Tick: ...
    def on_pause(self, session: Session) -> None: ...
    def on_resume(self, session: Session, gap: float) -> None: ...
    def on_stale(self, session: Session, slot: str) -> None: ...
    def start_ops(self, session: Session) -> list[Op]: ...
    def retry_ops(self, session: Session) -> list[Op]: ...
    def on_error(self, attempt: int, exc: BaseException) -> None: ...
    def on_stop(self, session: Session, reason: str) -> None: ...
    def finish_ops(self, session: Session, reason: str) -> list[Op]: ...
    def teardown(self, session: Session) -> None: ...


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
        settings_flag: str | None = None,
    ) -> None:
        self._worker = worker
        self._results = results
        self._output = output
        self._foreground = foreground
        self._clock: Clock = clock if clock is not None else time.time
        self._join_timeout = join_timeout
        self._settings_flag = settings_flag
        self._lock = threading.Lock()
        self._state = RunState.STOPPED
        self._session: Session | None = None
        self._session_id = 0
        self._epoch = 0
        self._seq = 0
        self._thread: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None
        self._paused_since: float | None = None
        self._last_error: str | None = None
        self._stop_reason: str | None = None
        self._prev_stop_pending = False
        self._wait = 0.25  # 没有 Tick 之前的轮询间隔；之后用 Tick.wait
        self._active_origin = 0.0
        self._paused_accum = 0.0
        self._paused_at: float | None = None
        self._last_active = 0.0
        self._last_seen: dict[str, float] = {}
        self._slots: dict[str, Freshness] = {}
        worker.loop = self  # 工作者的 tick 要用 loop.commit / loop.stamp

    # ---------------------------------------------------------------- 查询
    def state(self) -> StateView:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> StateView:
        session, thread = self._session, self._thread
        return StateView(
            state=self._state,
            session_id=session.id if session is not None else 0,
            epoch=self._epoch,
            paused_since=self._paused_since,
            last_error=self._last_error,
            stop_reason=self._stop_reason,
            worker_alive=bool(thread is not None and thread.is_alive()),
            prev_stop_pending=self._prev_stop_pending,
        )

    def running(self) -> bool:
        """兼容旧调用：STARTING / RUNNING / PAUSED 算在跑"""
        with self._lock:
            return self._state in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED)

    def freshness(self, slot: str) -> Freshness:
        with self._lock:
            return self._slots.get(slot, Freshness.EMPTY)

    # ---------------------------------------------------------------- 起停
    def start(self) -> int | None:
        """开一个新会话；已经在跑就幂等。旧线程还卡在停止里：采矿照常开新会话、状态里记 prev_stop_pending，
        盘点 / 导航（restart_while_stopping=False）拒绝、返回 None"""
        worker = self._worker
        with self._lock:
            if self._state in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED):
                assert self._session is not None
                return self._session.id
            thread = self._thread
            pending = bool(thread is not None and thread.is_alive())
            if pending and not worker.restart_while_stopping:
                return None
            self._session_id += 1
            self._epoch += 1
            old = self._session
            session = Session(self._session_id, threading.Event())
            self._session = session
            if old is not None:
                old.cancel.set()  # 按旧开关：旧线程哪怕没退出也只认自己的令牌
            self._state = RunState.STARTING
            self._stop_reason = None
            self._last_error = None
            self._paused_since = None
            self._paused_at = None
            self._paused_accum = 0.0
            self._active_origin = self._clock()
            self._last_active = 0.0
            self._last_seen.clear()
            self._slots.clear()
            self._wait = 0.25
            self._prev_stop_pending = pending
            self._thread = thread = threading.Thread(
                target=self._run, args=(session,), daemon=True, name=worker.name
            )
            thread.start()
            if pending:
                self._output.log(
                    "上次停止还没结束，先开新会话（旧线程交给看门狗）",
                    worker.name.upper(),
                    "WARN",
                )
            for op in worker.start_ops(session):
                self._apply(op)
            return session.id

    def request_stop(self, reason: str = "user") -> None:
        """结束当前会话：按开关、作废旧结果、套用工作者的收尾输出（锁内）、落设置开关（锁外）"""
        with self._lock:
            session = self._session
            active = self._state in (
                RunState.STARTING,
                RunState.RUNNING,
                RunState.PAUSED,
            )
        if active and session is not None:
            self._worker.on_stop(session, reason)  # 锁外：写日志文件这类事
        with self._lock:
            session = self._session
            if session is None or self._state not in (
                RunState.STARTING,
                RunState.RUNNING,
                RunState.PAUSED,
            ):
                return
            session.cancel.set()
            self._epoch += 1
            self._results.end(session.id)
            self._state = RunState.FAILED if reason == "error" else RunState.STOPPING
            self._stop_reason = reason
            self._paused_since = None
            self._paused_at = None
            for op in self._worker.finish_ops(session, reason):
                self._apply(op)
        self._write_settings_flag(reason)

    def join(self, timeout: float | None = None) -> bool:
        """等工作线程退出。超时就把状态留在 STOPPING / FAILED(worker_alive)，交给看门狗收"""
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(self._join_timeout if timeout is None else timeout)
        if thread.is_alive():
            self._start_watchdog(thread)
            return False
        with self._lock:
            if self._thread is thread and self._state is RunState.STOPPING:
                self._state = RunState.STOPPED
        return True

    # ---------------------------------------------------------------- 提交边界
    def config_changed(self) -> None:
        """配装变了：正在算的结果作废（epoch+1），下一次取 stamp 才有效"""
        with self._lock:
            self._epoch += 1

    def stamp(self, session: Session, wall: float) -> Stamp | None:
        """一帧开始时的序号和 epoch；会话已经不是当前的就返回 None（工作者拿到 None 就跳过提交）"""
        with self._lock:
            current = self._session
            if current is None or session.id != current.id or session.cancel.is_set():
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
        """提交边界（架构稿 §7.5）：查会话 → 查 epoch → 存结果 → 按序输出，和停止用同一把锁串行。
        三项检查任何一项不过就整个不做（带 slot 的连输出也不发）"""
        with self._lock:
            current = self._session
            if current is None or session.id != current.id or session.cancel.is_set():
                return False
            if slot is not None:
                if (
                    stamp is None
                    or stamp.epoch != self._epoch
                    or stamp.session_id != session.id
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
            for op in ops:
                self._apply(op)
            return True

    def _apply(self, op: Op) -> None:
        """套用一条输出指令（锁内调用；实现只入队 / 写状态）"""
        kind, *args = op
        if kind == "bus":
            self._output.publish(*args)
        elif kind == "log":
            self._output.log(*args)
        elif kind == "hud.set":
            self._output.hud_set(*args)
        elif kind == "hud.clear":
            self._output.hud_clear(*args)
        elif kind == "note":
            self._output.note_hud(*args)
        else:
            raise ValueError(f"未知输出类型：{kind!r}")

    # ---------------------------------------------------------------- 工作线程
    def _run(self, session: Session) -> None:
        worker = self._worker
        attempts = max(1, int(worker.retries))
        try:
            for attempt in range(attempts):
                try:
                    self._attempt(session)
                    return
                except Exception as exc:  # noqa: BLE001 —— 引擎出错要重试 / 收尾，不能让线程带着异常死掉
                    if session.cancel.is_set():
                        return
                    worker.on_error(attempt, exc)  # 锁外：写错误日志
                    if attempt + 1 >= attempts:
                        with self._lock:
                            if session is not self._session:
                                return
                            self._last_error = str(exc)
                        self.request_stop("error")
                        return
                    with self._lock:
                        if session is self._session and not session.cancel.is_set():
                            for op in worker.retry_ops(session):
                                self._apply(op)
                    session.cancel.wait(1.0)
        finally:
            with self._lock:
                if session is self._session and self._state is RunState.STOPPING:
                    self._state = RunState.STOPPED

    def _attempt(self, session: Session) -> None:
        worker = self._worker
        worker.setup(session)
        with self._lock:
            if session is not self._session or session.cancel.is_set():
                return
            if self._state is RunState.STARTING:
                self._state = RunState.RUNNING
        try:
            while True:
                if session.cancel.is_set():
                    return
                now = self._clock()
                if worker.needs_foreground and self._foreground() is False:
                    self._pause(session, now)
                    session.cancel.wait(min(self._wait, 0.25))
                    continue
                if self._state is RunState.PAUSED:
                    self._resume(session, now)
                if self._idle(now):
                    self.request_stop("idle")
                    return
                self._poll_stale(session, now)
                tick = worker.tick(session, now)
                after = self._clock()
                active = self._active(after)
                for slot in sorted(
                    tick.seen
                ):  # 固定顺序：两个槽同时过期时输出顺序不随机
                    self._last_seen[slot] = active
                    self._slots[slot] = Freshness.FRESH
                if tick.active:
                    self._last_active = active
                self._wait = max(0.0, float(tick.wait))
                session.cancel.wait(self._wait)
        finally:
            worker.teardown(session)

    def _pause(self, session: Session, now: float) -> None:
        with self._lock:
            if self._state not in (RunState.STARTING, RunState.RUNNING):
                return
            self._state = RunState.PAUSED
            self._paused_since = now
            self._paused_at = now
        self._worker.on_pause(session)

    def _resume(self, session: Session, now: float) -> None:
        with self._lock:
            if self._state is not RunState.PAUSED:
                return
            paused_at = self._paused_at if self._paused_at is not None else now
            gap = max(0.0, now - paused_at)
            self._paused_accum += gap
            self._paused_at = None
            self._paused_since = None
            self._state = RunState.RUNNING
        self._worker.on_resume(session, gap)

    def _active(self, now: float) -> float:
        """扣掉暂停段的活动时钟"""
        total = now - self._active_origin - self._paused_accum
        if self._paused_at is not None:
            total -= now - self._paused_at
        return total

    def _idle(self, now: float) -> bool:
        limit = self._worker.idle_close
        if limit is None:
            return False
        return self._active(now) - self._last_active > limit

    def _poll_stale(self, session: Session, now: float) -> None:
        limit = self._worker.stale_after
        if limit is None:
            return
        active = self._active(now)
        for slot in sorted(self._last_seen):
            if self._slots.get(slot) is not Freshness.FRESH:
                continue
            if active - self._last_seen[slot] <= limit:
                continue
            self._slots[slot] = Freshness.STALE
            self._worker.on_stale(session, slot)

    # ---------------------------------------------------------------- 看门狗
    def _start_watchdog(self, thread: threading.Thread) -> None:
        with self._lock:
            if self._watchdog is not None:
                return
            self._watchdog = threading.Thread(
                target=self._watch,
                args=(thread,),
                daemon=True,
                name=f"{self._worker.name}-watchdog",
            )
            self._watchdog.start()

    def _watch(self, thread: threading.Thread) -> None:
        thread.join(self._join_timeout * 3)
        stuck = thread.is_alive()
        with self._lock:
            self._watchdog = None
            if self._thread is not thread:
                return  # 换了新会话：旧线程的结局不写到新会话的状态上
            if stuck:
                self._state = RunState.FAILED
                self._last_error = self._last_error or "stop_timeout"
                self._stop_reason = "stop_timeout"
            elif self._state is RunState.STOPPING:
                self._state = RunState.STOPPED
        if stuck:
            run_records.record(
                self._worker.name.upper(),
                "停止超时：旧工作线程还没退出",
                level="WARN",
                ui_tag=self._worker.name.upper(),
            )

    def _write_settings_flag(self, reason: str) -> None:
        """自动关闭 / 出错时把 live_on 这类开关落盘（锁外、写文件）"""
        if self._settings_flag is None or reason not in ("idle", "error"):
            return
        try:
            from ..core import settings

            settings.update(**{self._settings_flag: False})
        except Exception:  # noqa: BLE001 —— 设置写不进去也不能让收尾半路炸掉
            pass
