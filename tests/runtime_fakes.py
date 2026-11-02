"""会话循环测试用的假件（不是产品代码）：记录型输出、假时钟、假 Worker、线程栅栏"""

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecordedOp:
    """输出端口的一次 apply；locked = 套用时会话循环那把锁有没有被当前线程持有"""

    op: tuple
    locked: bool


class RecordingOutput:
    """按顺序记下每个 op；绑定 loop 以后连「是不是在锁里套用」一起记"""

    def __init__(self):
        self.ops: list[RecordedOp] = []
        self.loop = None

    def bind(self, loop):
        self.loop = loop
        return self

    def apply(self, op):
        locked = bool(self.loop is not None and self.loop.lock_held_by_me())
        self.ops.append(RecordedOp(op, locked))

    # ---------------------------------------------------------------- 查询助手
    def kinds(self):
        return [r.op[0] for r in self.ops]

    def published(self, kind=None):
        return [
            r.op[1:]
            for r in self.ops
            if r.op[0] == "bus" and (kind is None or r.op[1] == kind)
        ]

    def live_events(self):
        return [data for (name, data) in self.published("live")]

    def hud(self):
        return [r.op for r in self.ops if r.op[0] in ("hud.set", "hud.clear")]

    def records(self):
        return [r.op for r in self.ops if r.op[0] == "record"]

    def logs(self):
        return [r.op for r in self.ops if r.op[0] == "log"]

    def texts(self):
        return [r.op[1] for r in self.ops if r.op[0] == "note"]

    def clear(self):
        self.ops.clear()


class FakeClock:
    """可推进的假时钟：整段会话不睡觉，时间由测试推"""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds
        return self.t


class Gate:
    """线程栅栏：让某个 Worker 方法第一次进来时停住，等测试放行（不靠 sleep）"""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.held = None

    def hold(self):
        """第一次进来卡住；之后直接过。返回是不是被卡住的那一次"""
        if self.held is None:
            self.held = threading.current_thread()
            self.entered.set()
            assert self.release.wait(30)
            return True
        return False


class TickGate:
    """tick 每轮都停在闸上：测试放一步、走一步（卡时机不靠 sleep）"""

    def __init__(self):
        self.arrived = threading.Semaphore(0)
        self.release = threading.Semaphore(0)

    def hold(self):
        self.arrived.release()
        assert self.release.acquire(timeout=30), "测试没放行 tick"

    def step(self):
        self.release.release()

    def wait(self, n=1):
        for _ in range(n):
            assert self.arrived.acquire(timeout=30), "tick 没到闸"


@dataclass
class FakeWorker:
    """按脚本走的假 Worker：记录调用顺序，tick 可以卡在栅栏上"""

    name: str = "fake"
    retries: int = 3
    idle_close: float | None = None
    stale_after: dict = field(default_factory=dict)
    needs_foreground: bool = False
    pause_wait: float = 0.02
    restart_while_stopping: bool = False
    wait: float = 0.02
    observed: dict = field(default_factory=dict)
    start_ops_list: list = field(default_factory=list)
    stop_ops_list: list = field(default_factory=list)
    pause_ops: list = field(default_factory=list)
    resume_ops: list = field(default_factory=list)
    stale_ops: list = field(default_factory=list)
    retry_ops_list: list = field(default_factory=list)
    finish_ops_list: list = field(default_factory=list)
    ticks: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    finished: list = field(default_factory=list)
    last_stop_info: Any = None
    loop: Any = None
    session: Any = None
    ctx: Any = None
    started: threading.Event = field(default_factory=threading.Event)
    ticked: threading.Event = field(default_factory=threading.Event)
    gate: Any = None  # 卡住 tick 的栅栏（Gate / TickGate）
    fail_times: int = 0  # 前几次 tick 直接抛错（试重试用）
    fail_at: int = 0  # 第几次 tick 抛错（1 起算；和 fail_times 二选一）
    failure: str = "坏了"
    setup_fail_times: int = 0  # 前几次 setup 直接抛错
    finish_gate: Any = None  # 卡住 finish 的栅栏（测「已停写 Ctx」的顺序）
    resume_gate: Any = None  # 卡住 on_resume 的栅栏（测回调 op 在停止后被丢）

    # ---- 纯函数 op 列表
    def start_ops(self, session):
        self.calls.append(("start_ops", session.id))
        return list(self.start_ops_list) or [("bus", "live", {"running": True})]

    def stop_ops(self, session, info):
        sid = None if session is None else session.id
        self.calls.append(("stop_ops", sid, info.reason))
        self.last_stop_info = info
        return list(self.stop_ops_list) or [
            ("bus", "live", {"running": False}),
            ("record", "FAKE", "引擎已停止", "", "", "INFO"),
        ]

    # ---- 工作线程
    def setup(self, session):
        self.calls.append(("setup", session.id))
        if self.setup_fail_times > 0:
            self.setup_fail_times -= 1
            raise RuntimeError("setup 坏了")
        ctx = object()
        self.ctx = ctx
        self.started.set()
        return ctx

    def tick(self, session, ctx, now):
        from astral_toolkit.runtime.session import Tick

        self.session = session
        self.calls.append(("tick", session.id, now))
        self.ticks.append(now)
        if self.gate is not None:
            self.gate.hold()
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError(self.failure)
        if self.fail_at and len(self.ticks) == self.fail_at:
            raise RuntimeError(self.failure)
        self.ticked.set()
        return Tick(self.wait, dict(self.observed))

    def on_pause(self, session, ctx):
        self.calls.append(("on_pause", session.id))
        return list(self.pause_ops)

    def on_resume(self, session, ctx, gap):
        self.calls.append(("on_resume", session.id, gap))
        if self.resume_gate is not None:
            self.resume_gate.hold()
        return list(self.resume_ops)

    def on_stale(self, session, ctx, channel):
        self.calls.append(("on_stale", session.id, channel))
        return list(self.stale_ops)

    def on_error(self, session, ctx, exc):
        self.calls.append(("on_error", session.id, repr(exc)))

    def before_retry(self, session, ctx, error):
        self.calls.append(("before_retry", session.id, error))
        return list(self.retry_ops_list) or [("hud.clear", "信号")]

    def finish(self, session, ctx, info):
        self.calls.append(("finish", session.id, info.reason))
        self.finished.append(info.reason)
        if self.finish_gate is not None:
            self.finish_gate.hold()
        return list(self.finish_ops_list)

    def teardown(self, session, ctx):
        self.calls.append(("teardown", session.id))


def make_loop(
    worker=None,
    *,
    results=None,
    output=None,
    foreground=None,
    clock=None,
    run_flag=None,
    closing=None,
    join_timeout=3.0,
):
    """按测试默认值建一个会话循环：假 Worker、假时钟、记录输出，并把输出绑到循环上"""
    from astral_toolkit.runtime.results import ResultStore
    from astral_toolkit.runtime.session import SessionLoop

    worker = worker if worker is not None else FakeWorker()
    out = output if output is not None else RecordingOutput()
    loop = SessionLoop(
        worker,
        results=results if results is not None else ResultStore(),
        output=out,
        foreground=foreground if foreground is not None else (lambda: None),
        clock=clock if clock is not None else FakeClock(),
        join_timeout=join_timeout,
        run_flag=run_flag,
        closing=closing if closing is not None else (lambda: False),
    )
    out.bind(loop)
    return loop, worker, out
