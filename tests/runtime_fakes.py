"""会话循环测试用的假件（不是产品代码）：记录型输出、假时钟、假 Worker"""

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecordedCall:
    """输出端口的一次调用；locked = 调用时会话循环那把锁有没有被持有"""

    op: str
    args: tuple
    locked: bool


class RecordingOutput:
    """按顺序记下每次输出。绑定 SessionLoop 的锁以后，连「调用时锁是否被持有」一起记"""

    def __init__(self):
        self.calls: list[RecordedCall] = []
        self.lock = None

    def bind(self, lock):
        self.lock = lock
        return self

    def _record(self, op, *args):
        held = bool(self.lock is not None and self.lock.locked())
        self.calls.append(RecordedCall(op, args, held))

    def publish(self, kind, data):
        self._record("publish", kind, data)

    def hud_set(self, section, text, rich=None):
        self._record("hud_set", section, text, rich)

    def hud_clear(self, *sections):
        self._record("hud_clear", *sections)

    def note_hud(self, section, text, secs=None):
        self._record("note_hud", section, text, secs)

    def log(self, line, tag, level="INFO"):
        self._record("log", line, tag, level)

    # ---------------------------------------------------------------- 查询助手
    def ops(self):
        return [c.op for c in self.calls]

    def published(self, kind=None):
        return [
            c.args
            for c in self.calls
            if c.op == "publish" and (kind is None or c.args[0] == kind)
        ]

    def live_events(self):
        return [data for kind, data in self.published("live")]

    def clear(self):
        self.calls.clear()


class FakeClock:
    """可推进的假时钟：整段会话不睡觉，时间由测试推"""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds
        return self.t


@dataclass
class FakeWorker:
    """按脚本走的假 Worker：记录调用顺序，tick 可以卡在栅栏上"""

    name: str = "fake"
    retries: int = 3
    idle_close: float | None = None
    stale_after: float | None = None
    needs_foreground: bool = False
    restart_while_stopping: bool = False
    wait: float = 0.02
    active: bool = True
    seen: frozenset = frozenset()
    ticks: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    finished: list = field(default_factory=list)
    loop: Any = None
    session: Any = None
    started: threading.Event = field(default_factory=threading.Event)
    ticked: threading.Event = field(default_factory=threading.Event)
    gate: Any = None  # 卡住 tick 的线程栅栏（tests.runtime_fakes.Gate）

    def setup(self, session):
        self.session = session
        self.calls.append(("setup", session.id))
        self.started.set()

    def tick(self, session, now):
        from astral_toolkit.runtime.session import Tick

        self.session = session
        self.calls.append(("tick", session.id, now))
        self.ticks.append(now)
        if self.gate is not None:
            self.gate.hold()
        self.ticked.set()
        return Tick(self.wait, self.active, self.seen)

    def on_pause(self, session):
        self.calls.append(("on_pause", session.id))

    def on_resume(self, session, gap):
        self.calls.append(("on_resume", session.id, gap))

    def on_stale(self, session, slot):
        self.calls.append(("on_stale", session.id, slot))

    def start_ops(self, session):
        self.calls.append(("start_ops", session.id))
        return [("bus", "live", {"running": True})]

    def retry_ops(self, session):
        self.calls.append(("retry_ops", session.id))
        return [("hud.clear", "信号")]

    def on_error(self, attempt, exc):
        self.calls.append(("on_error", attempt, repr(exc)))

    def on_stop(self, session, reason):
        self.calls.append(("on_stop", session.id, reason))

    def finish_ops(self, session, reason):
        self.calls.append(("finish_ops", session.id, reason))
        self.finished.append(reason)
        return []

    def teardown(self, session):
        self.calls.append(("teardown", session.id))


class Gate:
    """线程栅栏：让某个 Worker 方法停在这里，等测试放行（不靠 sleep）"""

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
