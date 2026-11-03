"""UI-K0c：导航活动接新展示流 + 导航磁贴。"""

import queue
import threading
import time
from types import SimpleNamespace

from astral_toolkit.app import bus, ui_stream
from astral_toolkit.app.engines import nav as navmod
from astral_toolkit.app.output import BusOutput
from astral_toolkit.navigation import navigate
from astral_toolkit.runtime.results import ResultStore

WAIT = 10
_ORIG_READ_SWITCHES = ui_stream.read_switches


def _reset(monkeypatch):
    ui_stream.reset_for_tests()
    monkeypatch.setattr(ui_stream, "read_switches", lambda: {})
    ui_stream._QUEUE_MAX = 2000
    ui_stream.ENDED_MAX = 256
    return ui_stream


def _wait_until(predicate, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return False


def _drain_ui(ui, q):
    out = []
    while True:
        try:
            msg = q.get_nowait()
        except queue.Empty:
            return out
        ui.mark_dequeued(q)
        out.append(msg)


def _collect_until(ui, q, predicate, timeout=WAIT):
    got = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remain = max(0.01, deadline - time.monotonic())
        try:
            msg = q.get(timeout=remain)
        except queue.Empty:
            break
        ui.mark_dequeued(q)
        got.append(msg)
        if predicate(msg):
            return got
    raise AssertionError("等不到预期的新展示流消息")


class _FakePos:
    def __init__(self):
        self.current = (time.time(), None, None)
        self.latest = (0.0, None, None)
        self.read_at = 0.0
        self.reader_active = False
        self.reader_ok_at = 0.0
        self.demand = []

    def snapshot(self):
        return SimpleNamespace(
            current=self.current,
            latest=self.latest,
            read_at=self.read_at,
            reader_active=self.reader_active,
            reader_ok_at=self.reader_ok_at,
        )

    def request_read_now(self):
        pass

    def set_demand(self, key, until):
        self.demand.append((key, until))


class _FakeCam:
    def check(self, cam, fast=False):
        return cam


class _FakeNavModule:
    DI_HELP = "di help"
    LIVE_STALE = 30.0

    @staticmethod
    def fix_key_hint():
        return "X", "一键定位：按 X"

    @staticmethod
    def _wp_log(msg):
        pass

    @staticmethod
    def settings_key(key, default=None):
        return default

    @staticmethod
    def _place_row(target):
        return {"key": "x", "label": "目标A"}


class _FakeMiningModule:
    @staticmethod
    def _mark_hud(value):
        pass

    @staticmethod
    def _marker_tick(*args, **kwargs):
        return None


def _fake_T(name):
    if name == "navigation":
        return _FakeNavModule
    if name == "mining":
        return _FakeMiningModule
    raise ImportError(name)


def _patch_nav(monkeypatch, arrived=False):
    monkeypatch.setattr(navmod, "_T", _fake_T)
    monkeypatch.setattr(navigate, "label", lambda target: "目标A")
    monkeypatch.setattr(navigate, "read_clipboard", lambda: "")
    monkeypatch.setattr(navigate, "parse_clip", lambda clip: None)

    def fix_guide(fixes, target, prev_arrived=False):
        return {
            "same_system": True,
            "direct": 123,
            "arrived": arrived,
            "city": None,
            "close": False,
            "deviation": None,
            "delta": None,
            "eta": None,
            "qt": None,
            "aim": None,
        }

    monkeypatch.setattr(navigate, "fix_guide", fix_guide)
    monkeypatch.setattr(
        navigate,
        "fix_text",
        lambda f, key: "已到达" if f.get("arrived") else "距离 123",
    )


def _new_nav(monkeypatch, arrived=False, retries=None, join_timeout=0.5):
    ui = _reset(monkeypatch)
    _patch_nav(monkeypatch, arrived=arrived)
    nav = navmod._Nav(
        _FakePos(),
        _FakeCam(),
        None,
        results=ResultStore(),
        output=BusOutput(),
        join_timeout=join_timeout,
    )
    if retries is not None:
        nav._worker.retries = retries
    return ui, nav, nav._positions


def _start(nav, target, row, space=True):
    result = nav.start(target, target_row=row, space_mode=space)
    assert result.status == "started", result
    return result.session_id


def test_activity_sequence_start_fix_stop_user(monkeypatch):
    ui, nav, _ = _new_nav(monkeypatch)
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    sid = None
    try:
        sid = _start(nav, {"n": "X"}, {"label": "目标A"})
        msgs = _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity"
                and m["activity"].get("state") == "starting"
            ),
        )
        assert msgs[-1]["activity"]["activity_id"] == f"nav:{sid}"
        assert nav.add_fix((1, 2, 3), "clip1", session=sid) is not None
        msgs += _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity"
                and m["activity"].get("state") == "running"
            ),
        )
        running = [
            m["activity"]
            for m in msgs
            if m.get("kind") == "ui.activity"
            and m["activity"].get("state") == "running"
        ][-1]
        assert running["primary"]["value"] == "目标A"
        assert running["kind"] == "nav"
        assert running["action"] == {"id": "stop", "label": "结束导航"}
        nav.stop()
        msgs += _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity_end"
                and m.get("activity_id") == f"nav:{sid}"
            ),
        )
        ends = [
            m
            for m in msgs
            if m.get("kind") == "ui.activity_end"
            and m.get("activity_id") == f"nav:{sid}"
        ]
        assert len(ends) == 1
        assert ends[0]["end_reason"] == "user"
        end_at = msgs.index(ends[0])
        assert any(
            m.get("kind") == "ui.notice"
            and m["notice"]["notice_id"] == ends[0]["summary_notice_id"]
            for m in msgs[:end_at]
        )
    finally:
        if sid:
            nav.loop.join(session_id=sid, timeout=WAIT)
        ui.unsubscribe(q)


def test_retarget_ends_only_old_activity(monkeypatch):
    ui, nav, _ = _new_nav(monkeypatch)
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    sid_a = sid_b = None
    try:
        sid_a = _start(nav, {"n": "A"}, {"label": "A"})
        _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity"
                and m["activity"]["activity_id"] == f"nav:{sid_a}"
            ),
        )
        session_a = nav.loop._current.session
        sid_b = _start(nav, {"n": "B"}, {"label": "B"})
        msgs = _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity"
                and m["activity"]["activity_id"] == f"nav:{sid_b}"
            ),
        )
        end_a = [
            m
            for m in msgs
            if m.get("kind") == "ui.activity_end"
            and m.get("activity_id") == f"nav:{sid_a}"
        ]
        assert len(end_a) == 1 and end_a[0]["end_reason"] == "user"
        assert not nav.loop.commit(
            session_a,
            ("ui", "ui.activity", {"activity_id": f"nav:{sid_a}"}),
        )
        assert not [
            m
            for m in _drain_ui(ui, q)
            if m.get("kind") == "ui.activity"
            and m["activity"].get("activity_id") == f"nav:{sid_a}"
        ]
        snap = ui.snapshot(1)
        ids = [a["activity_id"] for a in snap["activities"]]
        assert f"nav:{sid_a}" not in ids
        assert f"nav:{sid_b}" in ids
    finally:
        if nav.loop.running():
            nav.stop()
        if sid_b:
            nav.loop.join(session_id=sid_b, timeout=WAIT)
        ui.unsubscribe(q)


def test_stop_timeout_rejects_start_and_tile_shows_stopping(monkeypatch):
    ui, nav, _ = _new_nav(monkeypatch, join_timeout=0.02)
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    entered = threading.Event()
    gate = threading.Event()
    real_space_tick = nav._worker._space_tick

    def stuck_space_tick(session, ctx, now):
        if session.id == 1:
            entered.set()
            assert gate.wait(WAIT)
        return real_space_tick(session, ctx, now)

    monkeypatch.setattr(nav._worker, "_space_tick", stuck_space_tick)
    sid = None
    try:
        sid = _start(nav, {"n": "A"}, {"label": "A"})
        assert entered.wait(WAIT)
        attempt = nav.stop()
        assert attempt.timed_out
        assert _wait_until(lambda: nav.loop.state().prev_stop_pending, WAIT)
        rejected = nav.start({"n": "B"}, target_row={"label": "B"}, space_mode=True)
        assert rejected.status == "busy_stopping"
        assert rejected.session_id == sid
        monkeypatch.setattr(ui_stream, "read_switches", _ORIG_READ_SWITCHES)
        from astral_toolkit.tasks.system import common

        monkeypatch.setattr(common, "_engines", lambda: SimpleNamespace(nav=nav))
        ui.refresh_switches()
        tile = next(t for t in ui.snapshot(1)["tiles"] if t["tile_id"] == "nav")
        assert not tile["available"]["ok"]
        assert tile["status_line"] == "正在停止导航，请稍候"
        gate.set()
        assert nav.loop.join(session_id=sid, timeout=WAIT)
        ui.refresh_switches()
        tile = next(t for t in ui.snapshot(1)["tiles"] if t["tile_id"] == "nav")
        assert tile["available"]["ok"]
        assert tile["status_line"] == "已关闭"
        ends = [
            m
            for m in _drain_ui(ui, q)
            if m.get("kind") == "ui.activity_end"
            and m.get("activity_id") == f"nav:{sid}"
        ]
        assert len(ends) == 1
    finally:
        gate.set()
        if sid:
            nav.loop.join(session_id=sid, timeout=WAIT)
        ui.unsubscribe(q)


def test_error_exhausted_emits_error_activity_end_once(monkeypatch):
    ui, nav, _ = _new_nav(monkeypatch, retries=1)
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    sid = None

    def boom(session, ctx, now):
        raise RuntimeError("坏了")

    monkeypatch.setattr(nav._worker, "tick", boom)
    try:
        sid = _start(nav, {"n": "A"}, {"label": "A"})
        msgs = _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity_end"
                and m.get("activity_id") == f"nav:{sid}"
            ),
        )
        ends = [
            m
            for m in msgs
            if m.get("kind") == "ui.activity_end"
            and m.get("activity_id") == f"nav:{sid}"
        ]
        assert len(ends) == 1
        assert ends[0]["end_reason"] == "error"
        assert ends[0]["error"] == "坏了"
        assert not [m for m in _drain_ui(ui, q) if m.get("kind") == "ui.activity_end"]
    finally:
        if sid:
            nav.loop.join(session_id=sid, timeout=WAIT)
        ui.unsubscribe(q)


def test_arrived_marks_secondary_without_terminal(monkeypatch):
    ui, nav, _ = _new_nav(monkeypatch, arrived=True)
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    sid = None
    try:
        sid = _start(nav, {"n": "A"}, {"label": "A"})
        _collect_until(ui, q, lambda m: m.get("kind") == "ui.activity")
        assert nav.add_fix((1, 2, 3), "clip-arrive", session=sid) is not None
        msgs = _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity"
                and m["activity"].get("state") == "running"
            ),
        )
        running = [
            m["activity"]
            for m in msgs
            if m.get("kind") == "ui.activity"
            and m["activity"].get("state") == "running"
        ][-1]
        assert {"label": "到达", "value": "已到达"} in running["secondary"]
        assert not [m for m in _drain_ui(ui, q) if m.get("kind") == "ui.activity_end"]
        assert nav.loop.state().session_id == sid
        assert nav.loop.running()
    finally:
        nav.stop()
        if sid:
            nav.loop.join(session_id=sid, timeout=WAIT)
        ui.unsubscribe(q)


def test_snapshot_reconnect_has_current_and_ended(monkeypatch):
    ui, nav, _ = _new_nav(monkeypatch)
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    sid_a = sid_b = None
    try:
        sid_a = _start(nav, {"n": "A"}, {"label": "A"})
        _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity"
                and m["activity"]["activity_id"] == f"nav:{sid_a}"
            ),
        )
        nav.stop()
        _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity_end"
                and m.get("activity_id") == f"nav:{sid_a}"
            ),
        )
        snap = ui.snapshot(1)
        assert f"nav:{sid_a}" not in [a["activity_id"] for a in snap["activities"]]
        assert f"nav:{sid_a}" in snap["ended"]
        sid_b = _start(nav, {"n": "B"}, {"label": "B"})
        _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity"
                and m["activity"]["activity_id"] == f"nav:{sid_b}"
            ),
        )
        snap = ui.snapshot(1)
        ids = [a["activity_id"] for a in snap["activities"]]
        assert f"nav:{sid_a}" not in ids
        assert f"nav:{sid_b}" in ids
        assert f"nav:{sid_a}" in snap["ended"]
    finally:
        if nav.loop.running() or nav.loop.state().state.value == "stopping":
            nav.stop()
        if sid_b:
            nav.loop.join(session_id=sid_b, timeout=WAIT)
        ui.unsubscribe(q)


def test_bus_nav_output_updates_switch_without_reading_runtime(monkeypatch):
    ui = _reset(monkeypatch)

    def forbidden():
        raise AssertionError("锁内不许回调运行层")

    monkeypatch.setattr(ui, "read_switches", forbidden)
    monkeypatch.setattr(ui, "refresh_switches", forbidden)
    calls = []
    real = ui.set_switches

    def spy(switches, read_mono=None):
        calls.append(dict(switches))
        return real(switches, read_mono=read_mono)

    monkeypatch.setattr(ui, "set_switches", spy)
    monkeypatch.setattr(bus, "publish", lambda *a: None)
    BusOutput().apply(("bus", "nav", {"active": False}))
    BusOutput().apply(("bus", "nav", {"active": True}))
    assert calls == [{"nav_running": False}, {"nav_running": True}]
    assert ui._tiles["nav"]["on"] is True


def test_nav_tile_bus_stop_before_sample_not_overridden(monkeypatch):
    """bus「导航已停止」比下一次运行采样先到：磁贴马上不是「导航中」，也不能报可开（K0c 审查）"""
    _reset(monkeypatch)
    running = {
        "state": "running",
        "running": True,
        "draining": False,
        "can_start": False,
    }
    ui_stream.set_switches({"nav_running": True, "nav_runtime": running})
    assert ui_stream._tiles["nav"]["on"] is True
    BusOutput().apply(("bus", "nav", {"active": False}))
    tile = ui_stream._tiles["nav"]
    assert tile["on"] is False
    assert tile["available"]["ok"] is False
    assert "正在停止" in tile["status_line"]


def test_nav_tile_runtime_cleared_when_loop_gone(monkeypatch):
    """本轮确认没有导航循环：旧运行事实清掉，磁贴回落到 nav_running"""
    _reset(monkeypatch)
    draining = {
        "state": "stopping",
        "running": False,
        "draining": True,
        "can_start": False,
    }
    ui_stream.set_switches({"nav_running": False, "nav_runtime": draining})
    assert "正在停止" in ui_stream._tiles["nav"]["status_line"]
    ui_stream.set_switches({"nav_running": False, "nav_runtime": None})
    assert "nav_runtime" in ui_stream._switches
    assert ui_stream._switches["nav_runtime"] is None
    assert "正在停止" not in ui_stream._tiles["nav"]["status_line"]
