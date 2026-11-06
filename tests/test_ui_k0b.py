"""UI-K0b：采矿活动接新广播通路 + K0a 遗留。"""

import json
import queue
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from astral_toolkit.app import bus, hud_state, http_server, ui_stream
from astral_toolkit.app.engines import live as live_mod
from astral_toolkit.app.output import BusOutput
from astral_toolkit.core import paths
from astral_toolkit.mining import screen, signals
from astral_toolkit.mining.parse import Scan
from astral_toolkit.runtime.results import MINING_SCAN, ResultStore
from astral_toolkit.runtime.session import Session, SessionLoop, StopInfo, Tick
from astral_toolkit.tasks import mining as t_mining

WAIT = 10


def _reset(monkeypatch):
    ui_stream.reset_for_tests()
    monkeypatch.setattr(ui_stream, "read_switches", lambda: {})
    ui_stream._QUEUE_MAX = 2000
    ui_stream.ENDED_MAX = 256
    http_server.UI_HEARTBEAT_INTERVAL = 5.0
    return ui_stream


def _rock(rock=None):
    return Scan(
        rock=rock,
        mass=10000.0,
        resistance=20,
        instability=5.0,
        total_scu=10.0,
        composition=[("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)],
    )


def _fake_view(rock="铜", **extra):
    view = {
        "rock": rock,
        "hud": f"HUD {rock}",
        "hud_rich": "",
        "bag_text": "",
        "at": "12:00:00",
        "mass": 10000,
        "total_scu": 10.0,
        "difficulty": "简单",
    }
    view.update(extra)
    return view


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


def _activity(session_id, state="starting"):
    return {
        "activity_id": f"mining:{session_id}",
        "kind": "mining",
        "title": "采矿助手",
        "state": state,
        "primary": {"value": None, "unit": ""},
        "secondary": [],
    }


class _LoopWorker:
    name = "ui-k0b"
    activity_kind = "mining"
    retries = 1
    idle_close: float | None = None
    stale_after: dict[str, float] = {}
    needs_foreground = False
    restart_while_stopping = True

    def __init__(self, gate_session=None):
        self.gate_session = gate_session
        self.gate_used = False
        self.gate = threading.Event()
        self.entered = threading.Event()

    @property
    def pause_wait(self):
        return 0.01

    def hotkey(self):
        return "F5"

    def start_ops(self, session):
        return [("ui", "ui.activity", _activity(session.id))]

    def stop_ops(self, session, info):
        return []

    def setup(self, session):
        return None

    def tick(self, session, ctx, now):
        if self.gate_session == session.id and not self.gate_used:
            self.gate_used = True
            self.entered.set()
            assert self.gate.wait(WAIT)
        return Tick(0.01)

    def on_pause(self, session, ctx):
        return []

    def on_resume(self, session, ctx, gap):
        return []

    def on_stale(self, session, ctx, channel):
        return []

    def on_error(self, session, ctx, exc):
        return None

    def before_retry(self, session, ctx, error):
        return []

    def finish(self, session, ctx, info):
        return []

    def teardown(self, session, ctx):
        return None


def _new_loop(monkeypatch, gate_session=None, join_timeout=0.02):
    ui = _reset(monkeypatch)
    worker = _LoopWorker(gate_session)
    loop = SessionLoop(
        worker,  # pyright: ignore[reportArgumentType]  # 测试用的最小 Worker
        results=ResultStore(),
        output=BusOutput(),
        foreground=lambda: None,
        join_timeout=join_timeout,
    )
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    return ui, worker, loop, q


def _stop_loop(loop):
    sid = loop.state().session_id
    if sid:
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=sid, timeout=WAIT)


def _read_loop_switches(monkeypatch, ui, loop, read_switches):
    from astral_toolkit.app import ui_stream
    from astral_toolkit.core import settings

    monkeypatch.setattr(settings, "load", lambda: {"live_on": False})
    live = SimpleNamespace(loop=loop, running=loop.running)
    monkeypatch.setattr(ui_stream, "_SOURCES", ui_stream._SOURCES)
    ui_stream.bind_switches(live, None, None, replace=True)
    monkeypatch.setattr(ui, "read_switches", read_switches)


def _mining_tile(ui):
    return next(t for t in ui.snapshot(1)["tiles"] if t["tile_id"] == "mining")


def test_mining_tile_tracks_real_cleanup_without_reviving_activity(monkeypatch):
    """终态不会清掉收尾提示；新会话仍可停止，真实退出后的刷新才清提示。"""
    read_switches = ui_stream.read_switches
    ui, worker, loop, q = _new_loop(monkeypatch, gate_session=1)
    _read_loop_switches(monkeypatch, ui, loop, read_switches)
    try:
        old = loop.start()
        assert old is not None
        assert worker.entered.wait(WAIT)
        ui.refresh_switches()
        assert _mining_tile(ui)["on"]
        assert _mining_tile(ui)["available"]["ok"]

        loop.request_stop_current(StopInfo("user"))
        ui.refresh_switches()
        stopping = _mining_tile(ui)
        assert not stopping["on"]
        assert not stopping["available"]["ok"]
        assert "收尾" in stopping["status_line"]
        assert not loop.join(session_id=old, timeout=0.01)
        ui.refresh_switches()
        ended = _mining_tile(ui)
        assert ended["available"]["ok"]
        assert "收尾" in ended["status_line"]
        assert not ui.snapshot(1)["activities"]

        # 新连接的快照也得记住收尾，不能靠前端保留旧活动。
        hello, reconnect = ui.subscribe()
        assert reconnect is not None
        ui.unsubscribe(reconnect)
        assert "收尾" in ui.snapshot(hello["conn"])["tiles"][0]["status_line"]

        new = loop.start()
        assert new is not None and new != old
        ui.refresh_switches()
        running = _mining_tile(ui)
        assert running["on"] and running["available"]["ok"]
        assert running["activity_id"] == f"mining:{new}"
        assert "收尾" in running["status_line"]
        ui.publish_ui("ui.activity", {"activity": _activity(old)})
        ui.publish_ui("ui.notice", {"notice": {"notice_id": "drain-probe"}})
        ui.dismiss_notice("drain-probe")
        assert _mining_tile(ui) == running

        worker.gate.set()
        assert _wait_until(lambda: not loop.state().pending)
        ui.refresh_switches()
        clean = _mining_tile(ui)
        assert clean["on"] and clean["available"]["ok"]
        assert "收尾" not in clean["status_line"]
        assert clean["activity_id"] == f"mining:{new}"
        ends = [m for m in _drain_ui(ui, q) if m["kind"] == "ui.activity_end"]
        assert [m["activity_id"] for m in ends] == [f"mining:{old}"]
    finally:
        worker.gate.set()
        _stop_loop(loop)
        loop.join_all(timeout=WAIT)
        ui.unsubscribe(q)


def test_mining_tile_blocks_another_start_while_two_workers_stop(monkeypatch):
    read_switches = ui_stream.read_switches
    ui, worker, loop, q = _new_loop(monkeypatch)
    _read_loop_switches(monkeypatch, ui, loop, read_switches)
    gates = {sid: threading.Event() for sid in (1, 2)}
    entered = {sid: threading.Event() for sid in (1, 2)}

    def tick(session, ctx, now):
        entered[session.id].set()
        assert gates[session.id].wait(WAIT)
        return Tick(0.01)

    monkeypatch.setattr(worker, "tick", tick)
    try:
        first = loop.start()
        assert first is not None
        assert entered[1].wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=first, timeout=0.01)
        second = loop.start()
        assert second is not None
        assert entered[2].wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=second, timeout=0.01)
        ui.refresh_switches()
        tile = _mining_tile(ui)
        assert not tile["on"] and not tile["available"]["ok"]
        assert tile["available"]["reason"]
        assert "收尾" in tile["status_line"]
        assert loop.start() is None
    finally:
        for gate in gates.values():
            gate.set()
        _stop_loop(loop)
        loop.join_all(timeout=WAIT)
        ui.unsubscribe(q)


def test_mining_tile_discards_sample_if_session_changes_during_read(monkeypatch):
    """state/can_start 之间开启新会话时，不发布拼接出的旧状态。"""
    read_switches = ui_stream.read_switches
    ui, worker, loop, q = _new_loop(monkeypatch, gate_session=1)
    _read_loop_switches(monkeypatch, ui, loop, read_switches)
    ui.refresh_switches()
    can_start = loop.can_start

    def start_during_read():
        allowed = can_start()
        assert loop.start() is not None
        assert worker.entered.wait(WAIT)
        return allowed

    monkeypatch.setattr(loop, "can_start", start_during_read)
    try:
        values = ui.read_switches()
        assert "mining_runtime" not in values
        assert "live_on" not in values
        assert "live_running" not in values
        monkeypatch.setattr(loop, "can_start", can_start)
        ui.refresh_switches()
        tile = _mining_tile(ui)
        assert tile["on"] and tile["available"]["ok"]
    finally:
        worker.gate.set()
        _stop_loop(loop)
        loop.join_all(timeout=WAIT)
        ui.unsubscribe(q)


def test_mining_tile_switch_update_keeps_drain_and_rejects_older_read(monkeypatch):
    ui = _reset(monkeypatch)
    ui.set_switches(
        {
            "live_on": False,
            "live_running": False,
            "mining_runtime": {
                "state": "stopping",
                "running": False,
                "draining": True,
                "can_start": False,
            },
        },
        read_mono=10,
    )
    assert not _mining_tile(ui)["available"]["ok"]
    # 新会话的开关消息先到，运行快照稍后到：保留旧收尾，但停止新会话可用。
    ui.set_switches({"live_on": True, "live_running": True}, read_mono=12)
    current = _mining_tile(ui)
    assert current["on"] and current["available"]["ok"]
    assert "收尾" in current["status_line"]
    ui.set_switches(
        {
            "live_on": False,
            "live_running": False,
            "mining_runtime": {
                "state": "stopped",
                "running": False,
                "draining": False,
                "can_start": True,
            },
        },
        read_mono=11,
    )
    assert _mining_tile(ui) == current


def test_mining_tile_stop_message_does_not_reuse_running_availability(monkeypatch):
    ui = _reset(monkeypatch)
    ui.set_switches(
        {
            "live_on": True,
            "live_running": True,
            "mining_runtime": {
                "state": "running",
                "running": True,
                "draining": False,
                "can_start": False,
            },
        }
    )
    BusOutput().apply(("bus", "live", {"running": False}))
    tile = _mining_tile(ui)
    assert not tile["on"] and not tile["available"]["ok"]
    assert tile["available"]["reason"]


def test_mining_tile_quick_start_stop_waits_for_runtime_confirmation(monkeypatch):
    """一轮采样之间快速开停，不得沿用上次 STOPPED 时允许开启的旧答案。"""
    ui = _reset(monkeypatch)
    stopped = {
        "state": "stopped",
        "running": False,
        "draining": False,
        "can_start": True,
    }
    ui.set_switches({"live_on": False, "mining_runtime": stopped})
    output = BusOutput()
    output.apply(("bus", "live", {"running": True}))
    assert _mining_tile(ui)["available"]["ok"]
    output.apply(("bus", "live", {"running": False}))
    tile = _mining_tile(ui)
    assert not tile["on"] and not tile["available"]["ok"]
    ui.set_switches(
        {"live_on": False, "live_running": False, "mining_runtime": stopped}
    )
    assert _mining_tile(ui)["available"]["ok"]


def test_mining_tile_equal_clock_old_sample_cannot_override_new_switch(monkeypatch):
    """Windows 同一时钟刻度内，迟到的采样也不能盖掉已发布的新会话。"""
    ui = _reset(monkeypatch)
    old = {
        "live_on": False,
        "live_running": False,
        "mining_runtime": {
            "state": "stopping",
            "running": False,
            "draining": True,
            "can_start": True,
        },
    }
    monkeypatch.setattr(ui.time, "monotonic", lambda: 10.0)
    ui.set_switches(old, read_mono=10.0)

    def delayed_sample():
        BusOutput().apply(("bus", "live", {"running": True}))
        ui.publish_ui("ui.activity", {"activity": _activity(2)})
        return old

    monkeypatch.setattr(ui, "read_switches", delayed_sample)
    ui.refresh_switches()
    tile = _mining_tile(ui)
    assert tile["on"] and tile["available"]["ok"]
    assert tile["activity_id"] == "mining:2"
    # 同刻度内真实的新停止消息仍要接受，不能把时间比较简单改成 <=。
    BusOutput().apply(("bus", "live", {"running": False}))
    assert not _mining_tile(ui)["on"]


class _Hud:
    def __init__(self):
        self.calls = []
        self.notes = []

    def set(self, section, text, rich=None):
        self.calls.append(("set", section, text))

    def clear(self, section):
        self.calls.append(("clear", section))

    def note(self, text, secs=6):
        self.notes.append(text)


def _world(monkeypatch, tmp_path, analyse=None):
    imgs = [Image.new("RGB", (320, 180), (20 + 40 * k, 20, 20)) for k in range(5)]
    idx = {"i": 0}

    def grab():
        idx["i"] += 1
        return imgs[idx["i"] % len(imgs)]

    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(paths, "shots", lambda name: tmp_path)
    monkeypatch.setattr(screen, "grab", grab)
    monkeypatch.setattr(
        screen, "analyse", analyse or (lambda img: (_rock(), ({}, None, None)))
    )
    monkeypatch.setattr(screen, "INTERVAL", 0)
    monkeypatch.setattr(screen, "LAST_RAW", {})
    monkeypatch.setattr(screen, "LAST_PANEL", {})
    monkeypatch.setattr(signals, "find_signatures", lambda img: [])
    monkeypatch.setattr(t_mining, "_game_front", lambda: None)
    hud = _Hud()
    monkeypatch.setattr(hud_state, "_hud", lambda: hud)
    return hud


def _kill_live(live, q):
    live.stop_ev.set()
    sid = live.loop.state().session_id
    if sid:
        live.loop.join(session_id=sid, timeout=WAIT)
    ui_stream.unsubscribe(q)


def test_activity_sequence_start_scan_stop_user(monkeypatch, tmp_path):
    ui = _reset(monkeypatch)
    _world(monkeypatch, tmp_path)
    monkeypatch.setattr(t_mining, "scan_view", lambda *a, **k: _fake_view("铜"))
    live = live_mod._Live()
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    sid = None
    msgs = []
    try:
        sid = live.start()
        assert sid is not None
        msgs = _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity"
                and m["activity"].get("state") == "running"
            ),
        )
        live.stop()
        msgs += _collect_until(ui, q, lambda m: m.get("kind") == "ui.activity_end")
    finally:
        _kill_live(live, q)

    starts = [m["activity"] for m in msgs if m.get("kind") == "ui.activity"]
    assert starts and starts[0]["state"] == "starting"
    running = [a for a in starts if a.get("state") == "running"]
    assert running and running[0]["primary"]["value"] == "铜"

    ends = [m for m in msgs if m.get("kind") == "ui.activity_end"]
    assert len(ends) == 1
    end = ends[0]
    assert end["activity_id"] == f"mining:{sid}"
    assert end["end_reason"] == "user"
    end_at = msgs.index(end)
    assert any(
        m.get("kind") == "ui.notice"
        and m["notice"]["notice_id"] == end["summary_notice_id"]
        for m in msgs[:end_at]
    )


def test_late_commit_after_stop_emits_no_activity(monkeypatch):
    ui, _, loop, q = _new_loop(monkeypatch)
    try:
        sid = loop.start()
        assert sid is not None
        cur = loop._current
        assert cur is not None
        session = cur.session
        loop.request_stop_current(StopInfo("user"))
        assert loop.join(session_id=sid)
        _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity_end"
                and m.get("activity_id") == f"mining:{sid}"
            ),
        )
        _drain_ui(ui, q)
        assert not loop.commit(
            session, ("ui", "ui.activity", _activity(sid, "running"))
        )
        assert not [m for m in _drain_ui(ui, q) if m.get("kind") == "ui.activity"]
    finally:
        _stop_loop(loop)
        ui.unsubscribe(q)


def test_stop_timeout_new_session_replaces_old_only(monkeypatch):
    ui, worker, loop, q = _new_loop(monkeypatch, gate_session=1)
    new_sid = None
    try:
        old_sid = loop.start()
        assert old_sid == 1
        assert worker.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("idle"))
        assert _wait_until(lambda: loop.state().stop_timeout, WAIT)

        new_sid = loop.start()
        assert new_sid is not None and new_sid != old_sid
        assert _wait_until(lambda: loop.state().session_id == new_sid, WAIT)

        worker.gate.set()
        msgs = _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity_end"
                and m.get("activity_id") == f"mining:{old_sid}"
            ),
        )
        ends = [m for m in msgs if m.get("kind") == "ui.activity_end"]
        assert len(ends) == 1
        assert ends[0]["activity_id"] == f"mining:{old_sid}"
        # 自停卡住时看门狗已按真实原因（idle）发了终态；被取代时不再发第二条
        assert ends[0]["end_reason"] == "idle"

        ids = [a["activity_id"] for a in ui.snapshot(0)["activities"]]
        assert f"mining:{old_sid}" not in ids
        assert f"mining:{new_sid}" in ids
    finally:
        worker.gate.set()
        _stop_loop(loop)
        ui.unsubscribe(q)


def test_new_session_activity_is_empty_before_first_frame(monkeypatch):
    _reset(monkeypatch)
    live = live_mod._Live()
    assert live.results.accept(
        MINING_SCAN, {"rock": "上一会话的矿"}, 99, 0, 1, 0.0, 0.0
    )
    ops = live.start_ops(Session(42, threading.Event()))
    activities = [op[2] for op in ops if op[0] == "ui" and op[1] == "ui.activity"]
    assert activities
    activity = activities[0]
    assert activity["activity_id"] == "mining:42"
    assert activity["primary"]["value"] is None


def test_terminal_reasons_once_and_error_text(monkeypatch):
    ui, _, loop, q = _new_loop(monkeypatch)
    try:
        for reason, error in (("idle", ""), ("error", "坏了"), ("shutdown", "")):
            sid = loop.start()
            assert sid is not None
            loop.request_stop_current(StopInfo(reason, error))
            assert loop.join(session_id=sid)
            msgs = _collect_until(
                ui,
                q,
                lambda m: (
                    m.get("kind") == "ui.activity_end"
                    and m.get("activity_id") == f"mining:{sid}"
                ),
            )
            ends = [
                m
                for m in msgs
                if m.get("kind") == "ui.activity_end"
                and m.get("activity_id") == f"mining:{sid}"
            ]
            assert len(ends) == 1
            end = ends[0]
            assert end["end_reason"] == reason
            if error:
                assert end.get("error") == error
            else:
                assert "error" not in end

            run = loop._current
            assert run is not None
            deferred = []
            with loop._lock:
                loop._confirm_stop_locked(run, StopInfo(reason, error), deferred)
            assert deferred == []
            assert not [
                m for m in _drain_ui(ui, q) if m.get("kind") == "ui.activity_end"
            ]
    finally:
        _stop_loop(loop)
        ui.unsubscribe(q)


def test_tick_scan_rolls_back_ui_when_commit_fails(monkeypatch):
    _reset(monkeypatch)
    live = live_mod._Live()
    ctx = live_mod._Ctx(_Log(), Path("."), time.time())
    scan = _rock("坏")
    bag = ({}, "bag")
    ctx.recent.append((scan, bag))
    ctx.recent.append((scan, bag))
    monkeypatch.setattr(screen, "enqueue_rock", lambda q, s, b: False)
    monkeypatch.setattr(screen, "vote", lambda scans: (scan, True))
    monkeypatch.setattr(
        t_mining,
        "scan_view",
        lambda *a, **k: _fake_view("坏", mass=10000, total_scu=10.0),
    )
    calls = []

    def commit(session, *ops, **kwargs):
        calls.append((ops, kwargs))
        return False

    monkeypatch.setattr(live.loop, "commit", commit)
    live_mod._Live._tick_scan(
        live, Session(7, threading.Event()), ctx, scan, {}, None, 1.0, None
    )
    assert calls
    attempted = [op for op in calls[0][0] if op[0] == "ui"]
    assert attempted and attempted[0][2]["primary"]["value"] == "坏"
    assert ctx.ui["scan"] is None
    assert ctx.ui["state"] == "starting"


class _Log:
    def write(self, *args):
        pass

    def flush(self):
        pass

    def close(self):
        pass


def test_switch_read_mono_discards_older(monkeypatch):
    ui = _reset(monkeypatch)
    ui.set_switches({"live_on": True}, read_mono=10.0)
    ui.set_switches({"live_on": False}, read_mono=9.0)
    tile = [t for t in ui.snapshot(0)["tiles"] if t["tile_id"] == "mining"][0]
    assert tile["on"] is True

    ui.set_switches({"live_on": False}, read_mono=11.0)
    tile = [t for t in ui.snapshot(0)["tiles"] if t["tile_id"] == "mining"][0]
    assert tile["on"] is False


class _FakeUiStream:
    def __init__(self, q, events):
        self.q = q
        self.events = events
        self.conn = 7

    def subscribe(self, maxsize=None):
        return {"conn": self.conn}, self.q

    def encode(self, msg):
        return json.dumps(msg, ensure_ascii=False)

    def is_connected(self, q):
        return True

    def heartbeat(self, conn):
        return {"kind": "ui.heartbeat", "conn": conn}

    def mark_dequeued(self, q):
        self.events.append(("mark",))

    def unsubscribe(self, q):
        pass


class _FakeWFile:
    def __init__(self, events, fail_on=None):
        self.events = events
        self.fail_on = fail_on
        self.writes = 0

    def write(self, data):
        self.writes += 1
        self.events.append(("write", data.decode("utf-8", "replace")))
        if self.fail_on == self.writes:
            raise OSError("boom")

    def flush(self):
        self.events.append(("flush",))


class _FakeHandler:
    def __init__(self, wfile):
        self.wfile = wfile
        self.close_connection = False

    def send_response(self, code):
        pass

    def send_header(self, key, value):
        pass

    def end_headers(self):
        pass


def test_mark_dequeued_after_write_and_flush(monkeypatch):
    _reset(monkeypatch)
    q = queue.Queue()
    q.put({"kind": "ui.notice", "notice": {"notice_id": "n"}})
    q.put({"kind": "ui.bye", "conn": 7})
    events = []
    monkeypatch.setattr(http_server, "ui_stream", _FakeUiStream(q, events))
    http_server.Handler._ui_events(_FakeHandler(_FakeWFile(events)))  # pyright: ignore[reportArgumentType]

    notice_i = next(
        i
        for i, event in enumerate(events)
        if event[0] == "write" and "ui.notice" in event[1]
    )
    bye_i = next(
        i
        for i, event in enumerate(events)
        if event[0] == "write" and "ui.bye" in event[1]
    )
    assert events[notice_i + 1] == ("flush",)
    assert events[notice_i + 2] == ("mark",)
    assert events[bye_i + 1] == ("flush",)
    assert events[bye_i + 2] == ("mark",)

    q2 = queue.Queue()
    q2.put({"kind": "ui.notice", "notice": {"notice_id": "fail"}})
    events2 = []
    monkeypatch.setattr(http_server, "ui_stream", _FakeUiStream(q2, events2))
    handler = _FakeHandler(_FakeWFile(events2, fail_on=2))
    http_server.Handler._ui_events(handler)  # pyright: ignore[reportArgumentType]
    assert ("mark",) in events2


def test_notice_cleanup_summary_dismiss_until_ack(monkeypatch):
    ui = _reset(monkeypatch)
    ui.publish_ui(
        "ui.notice",
        {"notice": {"notice_id": "summary-old", "lifetime": "summary"}},
    )
    ui._notice_times["summary-old"] = time.monotonic() - ui.SUMMARY_KEEP - 1

    ui.publish_ui(
        "ui.notice",
        {"notice": {"notice_id": "dismissed", "lifetime": "until_ack"}},
    )
    assert ui.dismiss_notice("dismissed")

    ui.publish_ui(
        "ui.notice",
        {"notice": {"notice_id": "until-ack", "lifetime": "until_ack"}},
    )
    ui._notice_times["until-ack"] = time.monotonic() - ui.SUMMARY_KEEP - 1

    ui.publish_ui(
        "ui.notice",
        {"notice": {"notice_id": "transient-old", "lifetime": "transient"}},
    )
    ui._notice_times["transient-old"] = time.monotonic() - 11

    snap = ui.snapshot(0)
    ids = [n["notice_id"] for n in snap["notices"]]
    assert "summary-old" not in ids
    assert "dismissed" not in ids
    assert "transient-old" not in ids
    assert "until-ack" in ids
    assert "summary-old" not in ui._notices
    assert "dismissed" not in ui._notices
    assert "transient-old" not in ui._notices


def test_bus_live_output_sets_switch_without_reading_runtime(monkeypatch):
    """BusOutput 在会话循环锁内执行：只用消息本身更新开关，不调 read_switches / refresh_switches"""
    _reset(monkeypatch)
    events = []
    monkeypatch.setattr(bus, "publish", lambda *a: events.append(("bus",) + a))

    def forbidden():
        raise AssertionError("锁内不许回调运行层")

    monkeypatch.setattr(ui_stream, "read_switches", forbidden)
    monkeypatch.setattr(ui_stream, "refresh_switches", forbidden)
    calls = []
    real = ui_stream.set_switches

    def spy(switches, read_mono=None):
        calls.append(dict(switches))
        return real(switches, read_mono=read_mono)

    monkeypatch.setattr(ui_stream, "set_switches", spy)
    BusOutput().apply(("bus", "live", {"running": True, "paused": True}))
    BusOutput().apply(("bus", "live", {"running": False}))
    BusOutput().apply(("bus", "scan", {"rock": "x"}))
    assert [e[0] for e in events] == ["bus", "bus", "bus"]
    assert calls == [
        {"live_on": True, "live_running": True},
        {"live_on": False, "live_running": False},
    ]
    assert ui_stream._tiles["mining"]["on"] is False


def test_runtime_does_not_import_app():
    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(
        r"from\s+\.{2,}app\b|from\s+astral_toolkit\.app\b|import\s+astral_toolkit\.app\b"
    )
    bad = []
    for path in (root / "astral_toolkit" / "runtime").rglob("*.py"):
        if pattern.search(path.read_text(encoding="utf-8")):
            bad.append(str(path.relative_to(root)))
    assert not bad, bad


class _StuckFinishWorker(_LoopWorker):
    def __init__(self):
        super().__init__()
        self.finish_gate = threading.Event()

    def finish(self, session, ctx, info):
        self.finish_gate.wait(WAIT)
        return []


def test_watchdog_sends_activity_end_when_self_stop_hangs(monkeypatch):
    """自停（idle）后线程卡在 finish：看门狗超时补发终态，不会永远挂在全家福里"""
    ui = _reset(monkeypatch)
    worker = _StuckFinishWorker()
    loop = SessionLoop(
        worker,  # pyright: ignore[reportArgumentType]  # 测试用的最小 Worker
        results=ResultStore(),
        output=BusOutput(),
        foreground=lambda: None,
        join_timeout=0.02,
    )
    _, q = ui.subscribe(maxsize=500)
    assert q is not None
    try:
        sid = loop.start()
        assert sid is not None
        cur = loop._current
        assert cur is not None
        assert loop.request_stop(cur.session, StopInfo("idle"))
        msgs = _collect_until(
            ui,
            q,
            lambda m: (
                m.get("kind") == "ui.activity_end"
                and m.get("activity_id") == f"mining:{sid}"
            ),
        )
        ends = [m for m in msgs if m.get("kind") == "ui.activity_end"]
        assert len(ends) == 1 and ends[0]["end_reason"] == "idle"
        assert f"mining:{sid}" not in [
            a["activity_id"] for a in ui.snapshot(0)["activities"]
        ]
        worker.finish_gate.set()
        loop.join(session_id=sid, timeout=WAIT)
        assert not [m for m in _drain_ui(ui, q) if m.get("kind") == "ui.activity_end"]
    finally:
        worker.finish_gate.set()
        ui.unsubscribe(q)


def test_partial_quality_kept_for_later_activity_updates():
    ui = {"state": "running", "scan": {"rock": "铜"}, "quality": "partial"}
    assert live_mod._mining_activity(3, ui)["quality"] == "partial"
    ui["state"] = "paused"
    assert live_mod._mining_activity(3, ui)["quality"] == "partial"
    assert live_mod._mining_activity(3, {"scan": None})["quality"] == "complete"
