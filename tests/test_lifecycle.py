"""RT-B6 提交 1：Lifecycle 核心、登记、退出路径的测试"""

import threading
import time

from astral_toolkit.runtime.workers import hotkeys as hotkeys_worker
from astral_toolkit.runtime.lifecycle import (
    Lifecycle,
    OneShot,
    Phase,
    ServiceThread,
    SessionLoopService,
)


class _FakeService:
    def __init__(
        self,
        name,
        phase,
        events,
        *,
        join_result=True,
        stop_error=False,
        join_error=False,
    ):
        self.name = name
        self.phase = phase
        self.events = events
        self.join_result = join_result
        self.stop_error = stop_error
        self.join_error = join_error

    def start(self):
        self.events.append(("start", self.name))

    def request_stop(self):
        self.events.append(("stop", self.name))
        if self.stop_error:
            raise RuntimeError("stop boom")

    def join(self, timeout):
        self.events.append(("join", self.name, timeout))
        if self.join_error:
            raise RuntimeError("join boom")
        return self.join_result


class _NeverService:
    name = "never"
    phase = Phase.WORKERS

    def __init__(self):
        self.release = threading.Event()
        self.thread = threading.Thread(target=self.release.wait, daemon=True)

    def start(self):
        self.thread.start()

    def request_stop(self):
        pass

    def join(self, timeout):
        self.thread.join(timeout)
        return not self.thread.is_alive()


def test_stop_orders_phases_and_requests_all_before_join(monkeypatch):
    from astral_toolkit.runtime import lifecycle

    monkeypatch.setattr(lifecycle, "_write_run_record", lambda text: None)

    events = []
    lc = Lifecycle()
    lc.register(_FakeService("s1", Phase.SESSIONS, events))
    lc.register(_FakeService("s2", Phase.SESSIONS, events))
    lc.register(_FakeService("a1", Phase.AMBIENT, events))

    report = lc.stop_all(1.0)
    assert report.ok
    assert ["%s:%s" % (e[0], e[1]) for e in events] == [
        "stop:s1",
        "stop:s2",
        "join:s1",
        "join:s2",
        "stop:a1",
        "join:a1",
    ]


def test_start_all_stops_when_closing(monkeypatch):
    from astral_toolkit.runtime import lifecycle

    monkeypatch.setattr(lifecycle, "_write_run_record", lambda text: None)

    events = []
    lc = Lifecycle()
    lc.register(_FakeService("s", Phase.SESSIONS, events))
    lc.stop_all(0.0)
    assert lc.start_all() is False
    assert not [
        e for e in events if e[0] == "start"
    ]  # 退出后不再启动（stop_all 自己的 stop / join 不算）


def test_stop_budget_and_still_alive(monkeypatch):
    from astral_toolkit.runtime import lifecycle

    monkeypatch.setattr(lifecycle, "_write_run_record", lambda text: None)

    service = _NeverService()
    lc = Lifecycle()
    lc.register(service)
    assert lc.start_all() is True

    started = time.monotonic()
    report = lc.stop_all(0.3)
    elapsed = time.monotonic() - started
    service.release.set()
    service.thread.join(1.0)

    assert elapsed < 2.0
    assert len(report.records) == 1
    assert report.records[0].still_alive is True
    assert "仍存活" in report.summary


def test_stop_is_idempotent_and_request_error_does_not_block_others(monkeypatch):
    from astral_toolkit.runtime import lifecycle

    monkeypatch.setattr(lifecycle, "_write_run_record", lambda text: None)

    events = []
    lc = Lifecycle()
    lc.register(_FakeService("bad", Phase.AMBIENT, events, stop_error=True))
    lc.register(_FakeService("good", Phase.AMBIENT, events))

    first = lc.stop_all(1.0)
    second = lc.stop_all(1.0)

    assert second is first
    assert first.records[0].ok is False
    assert "request_stop" in first.records[0].error
    assert first.records[1].ok is True
    assert ("join", "bad") in [(e[0], e[1]) for e in events]
    assert ("join", "good") in [(e[0], e[1]) for e in events]


def test_hotkeys_worker_starts_and_stops(monkeypatch):
    """热键线程（目录迁移 R4 起在 runtime/workers/hotkeys）：起得来，叫停以后等得到退出"""
    started = threading.Event()

    def fake_run(self):
        started.set()
        self.stop_ev.wait()

    monkeypatch.setattr(hotkeys_worker.HotkeyWorker, "_run", fake_run)

    worker = hotkeys_worker.HotkeyWorker(
        hotkeys_worker.HotkeyLinks(
            bindings=lambda: [],
            code=lambda key: None,
            down=lambda vk: False,
            pressed=lambda name, key: None,
            failed=lambda: None,
        ),
        enabled=True,
    )
    worker.start()
    assert started.wait(2.0)
    worker.request_stop()
    assert worker.join(2.0) is True


def test_count_service_stops_session_loop(monkeypatch):
    from astral_toolkit.app import lifecycle_gate
    from tests.count_helpers import (
        count as _Count,
    )  # 分析、排版、外面的东西、output 由测试工具补上（R5）
    from astral_toolkit.crafting import stockplaces
    from astral_toolkit.tasks import navigation
    from tests.runtime_fakes import RecordingOutput

    monkeypatch.setattr(lifecycle_gate, "closing_error", lambda: None)
    monkeypatch.setattr(stockplaces, "current_place", lambda: {"label": "测试站"})
    monkeypatch.setattr(navigation, "settings_key", lambda key, default=None: default)
    ticks = iter(range(100000))
    count = _Count(
        output=RecordingOutput(),
        foreground=lambda: True,
        cursor_pos=lambda: (next(ticks), 0),
    )
    try:
        assert count.start() == {"running": True, "place": "测试站"}
        service = SessionLoopService("count", Phase.SESSIONS, count.loop)
        service.request_stop()
        assert service.join(2.0) is True
        assert count.running() is False
    finally:
        if count.running():
            count.stop()
        count.loop.join_all(2.0)


def test_live_gets_closing_before_new_session():
    from tests.mining_helpers import (
        live as _Live,
    )  # 分析、活动磁贴、外面的东西、output 由测试工具补上（R3）

    live = _Live(closing=lambda: True)
    assert live.start() is None


def test_nav_gets_closing_before_new_session():
    from tests.nav_helpers import nav as _Nav  # 分析、排版、output 由测试工具补上（R2）

    captured = {}

    class _Loop:
        def request_shutdown(self):
            return None

        def join_all(self, timeout):
            return []

        def running(self):
            return False

    def factory(*args, **kwargs):
        captured["closing"] = kwargs["closing"]
        return _Loop()

    nav = _Nav(
        object(),
        object(),
        None,
        _loop_factory=factory,
        closing=lambda: True,
    )
    assert captured["closing"]() is True
    result = nav.start(object())
    assert getattr(result, "session_id", None) is None


def test_final_service_drains_before_http_shutdown():
    from astral_toolkit.app import server as server_mod

    events = []

    class _UI:
        def drain_and_bye(self, timeout):
            events.append(("drain", timeout))

    class _Server:
        def shutdown(self):
            events.append("shutdown")

        def server_close(self):
            events.append("server_close")

    service = server_mod._FinalService(_UI(), _Server(), None)
    assert service.join(5.0) is True
    assert [e[0] if isinstance(e, tuple) else e for e in events] == [
        "drain",
        "shutdown",
        "server_close",
    ]


def test_exit_closes_window_and_tray_before_stop_all():
    from astral_toolkit.app import server as server_mod

    events = []

    class _Tray:
        def remove(self):
            events.append("tray")

    class _Lifecycle:
        def stop_all(self, budget):
            events.append(("stop_all", budget))
            return None

    class _App:  # RT-B7：_exit_sequence 拿的是装配出来的 app，经 bootstrap.shutdown 停 lifecycle
        lifecycle = _Lifecycle()

    server_mod._exit_sequence(
        _App(),
        _Tray(),
        budget=5.0,
        publish=lambda topic, data: events.append(("publish", topic)),
        close_edge=lambda: events.append("window"),
    )
    assert events == [
        ("publish", "quit"),
        "window",
        "tray",
        ("stop_all", 5.0),
    ]


def test_service_thread_and_one_shot_join_without_start():
    thread_service = ServiceThread("noop", Phase.WORKERS, lambda stop_ev: None)
    assert thread_service.join(0.0) is True

    one = OneShot("one", Phase.WORKERS)
    one.start()
    assert one.join(0.0) is True


def test_session_loop_service_join_all_result():
    class _Loop:
        def __init__(self, alive):
            self.alive = alive
            self.stopped = False

        def request_shutdown(self):
            self.stopped = True

        def join_all(self, timeout):
            return [1] if self.alive else []

    service = SessionLoopService("nav", Phase.SESSIONS, _Loop(True))
    service.request_stop()
    assert service.join(0.0) is False
    service = SessionLoopService("nav", Phase.SESSIONS, _Loop(False))
    assert service.join(0.0) is True
