"""采矿助手的提交边界（架构稿 §7.5、§11.2）：停止、重开、改配装时，迟到的结果不能发布、不能进 ResultStore

RT-B4：线程 / 停止 / 提交边界在 SessionLoop 里。这里全部走真实路径（`live.start / stop / loop.request_stop`），
要卡在「算完、提交之前」就卡在 `scan_view` 的栅栏上；不手改循环的内部状态，不靠 sleep。
"""

import threading
import time

from PIL import Image

from astral_toolkit.app import bus, hud_state
from astral_toolkit.app.engines import live as live_mod
from astral_toolkit.core import paths
from astral_toolkit.mining import screen, signals
from astral_toolkit.mining.parse import Scan
from astral_toolkit.runtime.results import MINING_SCAN, MINING_SIGNALS
from astral_toolkit.runtime.session import StopInfo
from astral_toolkit.tasks import mining as t_mining
from astral_toolkit.tasks import navigation as t_nav

WAIT = 30


def _rock(mass=10000.0):
    return Scan(
        rock=None,
        mass=mass,
        resistance=20,
        instability=5.0,
        total_scu=10.0,
        composition=[("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)],
    )


class _Hud:
    def __init__(self):
        self.calls = []

    def set(self, section, text, rich=None):
        self.calls.append(("set", section, text))

    def clear(self, section):
        self.calls.append(("clear", section))

    def note(self, text, secs=6):
        pass


def _fake_view(rock="铜"):
    return {"rock": rock, "hud": f"HUD {rock}", "bag_text": "", "at": "12:00:00"}


def _world(monkeypatch, tmp_path, analyse=None):
    """假画面：每帧图不同（不触发省电跳过），analyse 默认一直读到同一块石头"""
    imgs = [Image.new("RGB", (320, 180), (20 + 40 * k, 20, 20)) for k in range(5)]
    n = {"i": 0}

    def grab():
        n["i"] += 1
        return imgs[n["i"] % len(imgs)]

    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(paths, "shots", lambda name: tmp_path)
    monkeypatch.setattr(screen, "grab", grab)
    monkeypatch.setattr(
        screen, "analyse", analyse or (lambda img: (_rock(), ({}, None, None)))
    )
    monkeypatch.setattr(screen, "INTERVAL", 0)
    monkeypatch.setattr(screen, "LAST_RAW", {})  # 别的测试留下的识别结果不算数
    monkeypatch.setattr(screen, "LAST_PANEL", {})
    monkeypatch.setattr(signals, "find_signatures", lambda img: [])
    monkeypatch.setattr(t_mining, "_game_front", lambda: None)
    monkeypatch.setattr(hud_state, "_off", lambda feature: None)
    hud = _Hud()
    monkeypatch.setattr(hud_state, "_hud", lambda: hud)
    return hud, n


class _Gate:
    """让第一个进 scan_view 的线程停在「算完、提交之前」"""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.held = None

    def view(self, *a, **k):
        if self.held is None:
            self.held = threading.current_thread()
            self.entered.set()
            assert self.release.wait(WAIT)
            return _fake_view("旧")
        return _fake_view("新")

    def lines(self, *a, **k):
        return ["旧" if self._hold() else "新"]

    def _hold(self):
        if self.held is None:
            self.held = threading.current_thread()
            self.entered.set()
            assert self.release.wait(WAIT)
            return True
        return False


def _subscribe():
    q = bus.subscribe()
    while not q.empty():  # 总线补发的旧消息不算
        q.get_nowait()
    return q


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _wait_kind(q, kind):
    """等一条 kind 消息；前面收到的一起返回"""
    got = []
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        try:
            m = q.get(timeout=WAIT)
        except Exception:
            break
        got.append(m)
        if m["kind"] == kind:
            return got
    raise AssertionError(f"等不到 {kind}")


def _finish(live, q, gate=None):
    """断言失败也要收掉工作线程：补丁还原后它会去读真屏幕"""
    if gate:
        gate.release.set()
    live.stop_ev.set()
    sid = live.loop.state().session_id
    if sid:
        live.loop.join(session_id=sid, timeout=5)
    bus.unsubscribe(q)


def _start_stuck(monkeypatch, tmp_path, join_timeout=0.02):
    """开一个会话，工作线程卡在 scan_view 里（会话是 RUNNING，但还没提交）"""
    hud, _ = _world(monkeypatch, tmp_path)
    gate = _Gate()
    monkeypatch.setattr(t_mining, "scan_view", gate.view)
    live = live_mod._Live()
    live.loop._join_timeout = join_timeout
    q = _subscribe()
    assert live.start() is not None
    assert gate.entered.wait(WAIT)
    return live, gate, q, hud


def _session(live):
    return live.loop._current.session  # type: ignore[union-attr]


def test_stop_between_analyze_and_commit_publishes_nothing(monkeypatch, tmp_path):
    """① 停止恰好落在算完和提交之间：什么都不发布，ResultStore 不变"""
    live, gate, q, hud = _start_stuck(monkeypatch, tmp_path)
    try:
        sid = live.stop()
        assert sid is not None and not live.loop.running()
        gate.release.set()
        assert live.loop.join(session_id=sid, timeout=WAIT)
        msgs = _drain(q)
        assert not [m for m in msgs if m["kind"] == "scan"]
        assert not [c for c in hud.calls if c[0] == "set"]
        assert live.results.get(MINING_SCAN) is None
        monkeypatch.setattr(t_nav._M, "results", live.results)
        monkeypatch.setattr(t_nav, "_note_hud", lambda *a, **k: None)
        assert "暂无扫描结果" in t_nav.ore_record()["error"]
    finally:
        _finish(live, q, gate)


def test_restart_rejects_late_result_of_old_session(monkeypatch, tmp_path):
    """② 停了马上重开：旧线程迟到的结果不能盖新会话，也不能重新点亮悬浮窗"""
    live, gate, q, hud = _start_stuck(monkeypatch, tmp_path)
    try:
        first = live.session_id
        old_sid = live.stop()
        assert old_sid == first
        assert live.start() is not None
        assert live.session_id > first
        _wait_kind(q, "scan")
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.value["rock"] == "新"
        before = (e.session_id, e.sequence)
        hud_before = len(hud.calls)
        gate.release.set()
        assert live.loop.join(session_id=old_sid, timeout=WAIT)
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.value["rock"] == "新"
        assert (e.session_id, e.sequence) >= before
        assert not [c for c in hud.calls[hud_before:] if "旧" in str(c)]
        live.stop()
        assert not [
            m for m in _drain(q) if m["kind"] == "scan" and m["data"]["rock"] == "旧"
        ]
    finally:
        _finish(live, q, gate)


def test_older_frame_arriving_late_is_rejected(monkeypatch, tmp_path):
    """③ 同一会话里旧帧晚到（工作线程卡在 scan_view，测试自己取表、提交）"""
    live, gate, q, _ = _start_stuck(monkeypatch, tmp_path)
    try:
        session = _session(live)
        older = live.loop.stamp(session, 1.0)
        newer = live.loop.stamp(session, 2.0)
        assert older is not None and newer is not None
        kw = {"slot": MINING_SCAN, "quality": "complete"}
        assert live.loop.commit(
            session,
            live_mod._pub("scan", {"rock": "新"}),
            value="新",
            stamp=newer,
            **kw,
        )
        assert not live.loop.commit(
            session,
            live_mod._pub("scan", {"rock": "旧"}),
            value="旧",
            stamp=older,
            **kw,
        )
        assert [m["data"]["rock"] for m in _drain(q) if m["kind"] == "scan"] == ["新"]
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.value == "新" and e.sequence == newer.seq
    finally:
        _finish(live, q, gate)


def test_old_epoch_rejected_after_config_change(monkeypatch, tmp_path):
    """④ 配装变了：旧 epoch 的结果作废，下一帧按新配装算出来再发布，采矿助手不退出"""
    hud, _ = _world(monkeypatch, tmp_path)
    live = live_mod._Live()
    calls = []

    def view(*a, **k):
        calls.append(live.loop.config_rev)
        if len(calls) == 1:
            live.config_changed()  # 算到一半改了配装
            return _fake_view("旧配装")
        return _fake_view("新配装")

    monkeypatch.setattr(t_mining, "scan_view", view)
    q = _subscribe()
    try:
        assert live.start() is not None
        _wait_kind(q, "scan")
        live.stop()
        scans = [m for m in _drain(q) if m["kind"] == "scan"]
        assert not [m for m in scans if m["data"]["rock"] == "旧配装"]
        assert len(calls) >= 2 and calls[1] == calls[0] + 1
        assert ("set", "扫描", "HUD 旧配装") not in hud.calls
        assert ("set", "扫描", "HUD 新配装") in hud.calls
    finally:
        _finish(live, q)


def test_old_epoch_commit_changes_nothing(monkeypatch, tmp_path):
    live, gate, q, _ = _start_stuck(monkeypatch, tmp_path)
    try:
        session = _session(live)
        old = live.loop.stamp(session, 1.0)
        assert old is not None
        live.config_changed()
        assert not live.loop.commit(
            session,
            live_mod._pub("scan", {"rock": "旧"}),
            slot=MINING_SCAN,
            value="旧",
            stamp=old,
        )
        assert not [m for m in _drain(q) if m["kind"] == "scan"]
        assert live.results.get(MINING_SCAN) is None
    finally:
        _finish(live, q, gate)


def test_stale_republish_does_not_touch_store(monkeypatch, tmp_path):
    """⑤ 过期重发：内容从 ResultStore 取、带 stale，存着的那条不变（不重新 accept）。时钟是假的"""
    clock = {"t": 1000.0}
    frames = {"n": 0}

    def analyse(img):
        frames["n"] += 1
        return (_rock() if frames["n"] <= 3 else Scan(), ({}, None, None))

    _world(monkeypatch, tmp_path, analyse)
    real_grab = screen.grab
    seen = {}
    done = threading.Event()

    def grab():
        clock["t"] += 5.0
        if frames["n"] > 100:
            done.set()  # 兜底：等不到过期也别卡住
        return real_grab()

    monkeypatch.setattr(screen, "grab", grab)
    monkeypatch.setattr(time, "time", lambda: clock["t"])
    monkeypatch.setattr(t_mining, "scan_view", lambda *a, **k: _fake_view())
    live = live_mod._Live(clock=lambda: clock["t"])
    real_publish = bus.publish

    def publish(kind, data):
        if kind == "scan":
            if data.get("stale"):
                seen["stale"] = data
                seen["after"] = live.results.get(MINING_SCAN)
                done.set()
            else:
                seen["fresh"] = data
                seen["before"] = live.results.get(MINING_SCAN)
        real_publish(kind, data)

    monkeypatch.setattr(bus, "publish", publish)
    q = _subscribe()
    try:
        assert live.start() is not None
        assert done.wait(WAIT), "没有过期重发"
        live.stop()
        assert seen.get("stale"), "没有过期重发"
        assert seen["stale"] == {**seen["fresh"], "stale": seen["stale"]["stale"]}
        assert seen["before"] == seen["after"]
        assert "stale" not in seen["after"].value
    finally:
        _finish(live, q)


def test_live_false_comes_after_last_scan(monkeypatch, tmp_path):
    """⑥ running=False 排在最后一条 scan 之后，旧线程迟到也不例外"""
    live, gate, q, _ = _start_stuck(monkeypatch, tmp_path)
    try:
        sid = live.stop()
        gate.release.set()
        assert live.loop.join(session_id=sid, timeout=WAIT)
        msgs = _drain(q)
        kinds = [m["kind"] for m in msgs if m["kind"] in ("scan", "live")]
        assert kinds[-1] == "live"
        assert [m["data"] for m in msgs if m["kind"] == "live"][-1] == {
            "running": False
        }
        assert "scan" not in kinds
    finally:
        _finish(live, q, gate)


def test_live_false_after_published_scan(monkeypatch, tmp_path):
    _world(monkeypatch, tmp_path)
    monkeypatch.setattr(t_mining, "scan_view", lambda *a, **k: _fake_view())
    live = live_mod._Live()
    q = _subscribe()
    try:
        assert live.start() is not None
        got = _wait_kind(q, "scan")
        live.stop()
        msgs = got + _drain(q)
        kinds = [m["kind"] for m in msgs if m["kind"] in ("scan", "live")]
        # running=True 在 start 的锁里发，工作线程的结果排不到它前面
        assert kinds[0] == "live" and "scan" in kinds and kinds[-1] == "live"
        live_msgs = [m["data"] for m in msgs if m["kind"] == "live"]
        assert live_msgs[0] == {"running": True}
        assert live_msgs[-1] == {"running": False}
    finally:
        _finish(live, q)


def _wait_scan(live, q):
    _wait_kind(q, "scan")
    return live.loop._current.session  # type: ignore[union-attr]


def test_every_way_of_stopping_keeps_results_and_rejects_late(monkeypatch, tmp_path):
    """停止只封会话：最后一份结果留着（记录、反馈照常读，和基线一样），迟到的写不进来"""
    from astral_toolkit.core import settings
    from astral_toolkit.tasks.system.feedback import FeedbackContext

    monkeypatch.setattr(settings, "update", lambda **kw: None)
    monkeypatch.setattr(hud_state, "_note_hud", lambda *a, **k: None)
    monkeypatch.setattr(t_mining, "scan_view", lambda *a, **k: _fake_view())

    def _stops(live, session):
        return {
            "stop": lambda: live.loop.request_stop(session, StopInfo("user")),
            "auto_off": lambda: live.loop.request_stop(session, StopInfo("idle")),
            "fail_off": lambda: live.loop.request_stop(
                session, StopInfo("error", "坏了")
            ),
            "退出": lambda: live.stop_ev.set(),  # manager.stop_all
        }

    for name in ("stop", "auto_off", "fail_off", "退出"):
        _world(monkeypatch, tmp_path)
        live = live_mod._Live()
        q = _subscribe()
        try:
            assert live.start() is not None
            session = _wait_scan(live, q)
            _stops(live, session)[name]()
            assert live.loop.join(session_id=session.id)
            e = live.results.get(MINING_SCAN)
            assert e is not None and e.value["rock"] == "铜", name
            shown = FeedbackContext.from_results(live.results)
            assert shown.shown_scan and shown.shown_scan["rock"] == "铜", name
            assert not live.loop.commit(
                session,
                slot=MINING_SCAN,
                value={"rock": "迟到"},
                stamp=live.loop.stamp(session, 2.0),
            ), name
            e = live.results.get(MINING_SCAN)
            assert e is not None and e.value["rock"] == "铜", name
        finally:
            _finish(live, q)


def test_new_session_first_result_replaces_last_one(monkeypatch, tmp_path):
    _world(monkeypatch, tmp_path)
    monkeypatch.setattr(t_mining, "scan_view", lambda *a, **k: _fake_view("一"))
    live = live_mod._Live()
    q = _subscribe()
    try:
        assert live.start() is not None
        first = _wait_scan(live, q)
        live.stop()
        assert live.loop.join(session_id=first.id)
        assert live.start() is not None
        _wait_scan(live, q)
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.session_id > first.id
        late = live.loop.stamp(first, 3.0)
        assert late is None, "旧线程停完才来取 stamp 要被拒"
    finally:
        _finish(live, q)


def test_start_presses_old_switch(monkeypatch, tmp_path):
    _world(monkeypatch, tmp_path)
    live = live_mod._Live()
    try:
        assert live.start() is not None
        old = live.stop_ev
        live.stop()
        assert old.is_set()
        assert live.start() is not None
        assert not live.stop_ev.is_set()
    finally:
        _finish(live, _subscribe())


def test_zombie_worker_cannot_end_new_session(monkeypatch, tmp_path):
    """旧会话的停止命令迟到：结束不了后来开的会话"""
    _world(monkeypatch, tmp_path)
    monkeypatch.setattr(t_mining, "scan_view", lambda *a, **k: _fake_view())
    live = live_mod._Live()
    q = _subscribe()
    try:
        assert live.start() is not None
        old = _wait_scan(live, q)
        live.stop()
        assert live.loop.join(session_id=old.id)
        assert live.start() is not None
        _wait_scan(live, q)
        new_id = live.session_id
        q2 = _subscribe()
        try:
            assert live.loop.request_stop(old, StopInfo("idle")) is False
            assert live.loop.request_stop(old, StopInfo("error", "坏")) is False
            assert not [m for m in _drain(q2) if m["kind"] == "live"]
        finally:
            bus.unsubscribe(q2)
        assert live.session_id == new_id and live.running()
        assert live.loop.stamp(old, 1.0) is None
    finally:
        _finish(live, q)


def test_stop_leaves_session_started_during_join_alone(monkeypatch, tmp_path):
    """等线程的时候新会话开了：旧会话的收尾不碰它的悬浮窗、也不说「已停止」"""
    live, gate, q, hud = _start_stuck(monkeypatch, tmp_path)
    try:
        old = _session(live)
        old_sid = live.stop()
        assert old_sid is not None and not live.loop.running()
        hud_before = len(hud.calls)
        assert live.start() is not None
        new_sid = live.session_id
        _wait_scan(live, q)
        gate.release.set()
        assert live.loop.join(session_id=old_sid, timeout=WAIT)
        assert not [c for c in hud.calls[hud_before:] if c[0] == "clear"]
        assert live.session_id == new_sid and live.running()
        assert live.loop.request_stop(old, StopInfo("user")) is False
    finally:
        _finish(live, q, gate)


def test_commit_without_hud_is_fine(monkeypatch, tmp_path):
    live, gate, q, _ = _start_stuck(monkeypatch, tmp_path)
    try:
        monkeypatch.setattr(hud_state, "_hud", lambda: None)
        session = _session(live)
        assert live.loop.commit(
            session, live_mod._set("扫描", "x"), live_mod._del("矿袋")
        )
    finally:
        _finish(live, q, gate)


def test_output_only_commit_needs_live_session(monkeypatch, tmp_path):
    """只有输出的提交（提示、过期重发）也查会话"""
    live, gate, q, _ = _start_stuck(monkeypatch, tmp_path)
    try:
        session = _session(live)
        assert live.loop.commit(session, live_mod._pub("log", {"task": "live"}))
        assert live.loop.request_stop(session, StopInfo("user"))
        gate.release.set()
        assert live.loop.join(session_id=session.id)
        assert not live.loop.commit(session, live_mod._pub("log", {"task": "live"}))
    finally:
        _finish(live, q, gate)


def test_feedback_context_reads_store():
    """反馈包里的字段和以前一样：读全的带成分，面板被挡的带 cut；信号带 values；发到窗口的消息里没有 values"""
    from astral_toolkit.runtime.results import ResultStore
    from astral_toolkit.tasks.system.feedback import FeedbackContext

    results = ResultStore()
    empty = FeedbackContext.from_results(results)
    assert empty.shown_signal is None and empty.shown_scan is None
    view = {
        "rock": "铜",
        "mass": 1,
        "resistance": 2,
        "instability": 3,
        "minerals": ["m"],
        "at": "t",
        "hud": "不要",
    }
    assert results.accept(MINING_SCAN, view, 1, 0, 1, 0.0, 0.0)
    assert results.accept(
        MINING_SIGNALS, {"view": {"lines": ["l"]}, "values": [7]}, 1, 0, 1, 0.0, 0.0
    )
    c = FeedbackContext.from_results(results)
    assert list(c.shown_scan or ()) == [
        "rock",
        "mass",
        "resistance",
        "instability",
        "minerals",
        "at",
    ]
    assert c.shown_signal == {"lines": ["l"], "values": [7]}
    assert results.accept(MINING_SCAN, view, 1, 0, 2, 0.0, 0.0, quality="partial")
    assert list(FeedbackContext.from_results(results).shown_scan or ()) == [
        "rock",
        "mass",
        "resistance",
        "instability",
        "cut",
        "at",
    ]


def test_stop_waits_for_commit_in_progress(monkeypatch, tmp_path):
    """提交和停止同一把锁：发布到一半时 stop 进不来，发布完才封会话，running=False 排在后面"""
    live, gate, q, _ = _start_stuck(monkeypatch, tmp_path)
    try:
        session = _session(live)
        inside, leave = threading.Event(), threading.Event()
        seq = []
        real = bus.publish
        committer = {"thread": None}
        stopper = {"thread": None}

        def publish(kind, data):
            if threading.current_thread() in (
                committer["thread"],
                stopper["thread"],
            ):  # 别的线程发的不算
                seq.append(kind)
                if kind == "scan":
                    inside.set()
                    assert leave.wait(WAIT)
            real(kind, data)

        monkeypatch.setattr(bus, "publish", publish)
        stamp = live.loop.stamp(session, 1.0)
        assert stamp is not None
        committer["thread"] = threading.Thread(
            target=live.loop.commit,
            args=(session, live_mod._pub("scan", {"rock": "铜"})),
            kwargs={"slot": MINING_SCAN, "value": "铜", "stamp": stamp},
            daemon=True,
        )
        stopper["thread"] = threading.Thread(target=live.stop, daemon=True)
        try:
            committer["thread"].start()
            assert inside.wait(WAIT)
            stopper["thread"].start()
            stopper["thread"].join(0.2)  # 进不来：实现对的话这里一定超时
            assert stopper["thread"].is_alive()
            assert session.alive()
            assert live.results.get(MINING_SCAN) is not None
        finally:
            leave.set()
        committer["thread"].join(WAIT)
        stopper["thread"].join(WAIT)
        assert not committer["thread"].is_alive()
        assert not stopper["thread"].is_alive()
        assert not session.alive()
        assert seq.index("live") > seq.index("scan")
    finally:
        _finish(live, q, gate)


def _cut_rock():
    return Scan(
        rock=None,
        mass=9000.0,
        resistance=20,
        instability=5.0,
        total_scu=None,
        composition=[("Copper", 40.0, None), ("Gold", 60.0, None)],
    )


def test_cut_result_is_partial_and_old_epoch_rejected(monkeypatch, tmp_path):
    """面板被挡走真循环：存的是 partial；算到一半改配装，这份作废，循环不退出，下一帧出新结果"""
    hud, _ = _world(monkeypatch, tmp_path, lambda img: (_cut_rock(), ({}, None, None)))
    monkeypatch.setattr(screen, "LAST_PANEL", {"cut": True})
    live = live_mod._Live()
    calls = []

    def view(*a, **k):
        assert k.get("cut") is True
        calls.append(1)
        if len(calls) == 1:
            live.config_changed()
            return _fake_view("旧配装")
        return _fake_view("新配装")

    monkeypatch.setattr(t_mining, "scan_view", view)
    q = _subscribe()
    try:
        assert live.start() is not None
        got = _wait_kind(q, "scan")
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.quality == "partial"
        assert e.value["rock"] == "新配装"
        assert [m["data"]["rock"] for m in got if m["kind"] == "scan"] == ["新配装"]
        assert ("set", "扫描", "HUD 旧配装") not in hud.calls
    finally:
        _finish(live, q)


def _signal_world(monkeypatch, tmp_path, lines):
    from astral_toolkit.tasks import goals as t_goals

    hud, _ = _world(monkeypatch, tmp_path, lambda img: (Scan(), ({}, None, None)))
    monkeypatch.setattr(signals, "find_signatures", lambda img: [(4285, 1)])
    monkeypatch.setattr(signals, "describe_all", lines)
    monkeypatch.setattr(signals, "match_signature", lambda v: True)
    monkeypatch.setattr(signals, "guesses", lambda *a: [("铝", True)])
    monkeypatch.setattr(t_nav, "_area_now", lambda: None)
    monkeypatch.setattr(t_goals, "_mark_goal_lines", lambda x: x)
    return hud


def test_signal_result_goes_to_store(monkeypatch, tmp_path):
    """信号走真循环：窗口消息里没有 values，store 里有；日志排在悬浮窗之后"""
    hud = _signal_world(monkeypatch, tmp_path, lambda *a: ["信号 4,285 → 铝"])
    live = live_mod._Live()
    q = _subscribe()
    try:
        assert live.start() is not None
        msg = _wait_kind(q, "signals")[-1]["data"]
        assert "values" not in msg and msg["lines"] == ["信号 4,285 → 铝"]
        e = live.results.get(MINING_SIGNALS)
        assert e is not None and e.value["values"] == [4285]
        assert e.value["view"]["lines"] == msg["lines"]
        assert ("set", "信号", "4,285 → 铝") in hud.calls
    finally:
        _finish(live, q)


def test_signal_old_epoch_rejected(monkeypatch, tmp_path):
    live = live_mod._Live()
    calls = []

    def lines(*a):
        calls.append(1)
        if len(calls) == 1:
            live.config_changed()
            return ["旧配装"]
        return ["新配装"]

    hud = _signal_world(monkeypatch, tmp_path, lines)
    q = _subscribe()
    try:
        assert live.start() is not None
        got = _wait_kind(q, "signals")
        assert [m["data"]["lines"] for m in got if m["kind"] == "signals"] == [
            ["新配装"]
        ]
        assert ("set", "信号", "旧配装") not in hud.calls
    finally:
        _finish(live, q)


def test_signal_of_old_session_rejected_after_restart(monkeypatch, tmp_path):
    gate = _Gate()
    hud = _signal_world(monkeypatch, tmp_path, gate.lines)
    live = live_mod._Live()
    live.loop._join_timeout = 0.02
    q = _subscribe()
    try:
        assert live.start() is not None
        assert gate.entered.wait(WAIT)
        old_sid = live.stop()
        assert live.start() is not None
        _wait_kind(q, "signals")
        gate.release.set()
        assert live.loop.join(session_id=old_sid, timeout=WAIT)
        e = live.results.get(MINING_SIGNALS)
        assert e is not None and e.value["view"]["lines"] == ["新"]
        assert ("set", "信号", "旧") not in hud.calls
        assert not [
            m
            for m in _drain(q)
            if m["kind"] == "signals" and m["data"]["lines"] == ["旧"]
        ]
    finally:
        _finish(live, q, gate)


def test_worker_keeps_the_session_it_was_started_with(monkeypatch, tmp_path):
    """会话号和 payload 在 start 的锁里取好交给线程：线程起来得晚，也不会读成后来的新会话"""
    _world(monkeypatch, tmp_path)
    live = live_mod._Live()
    seen = []
    done = threading.Event()

    def setup(session):
        seen.append((session.id, session.payload))

    def tick(session, ctx, now):
        seen.append((session.id, session.payload))
        done.set()
        from astral_toolkit.runtime.session import Tick

        return Tick(0.02, {})

    monkeypatch.setattr(live, "setup", setup)
    monkeypatch.setattr(live, "tick", tick)
    try:
        assert live.start() is not None
        assert done.wait(WAIT)
        assert seen and all(sid == 1 for sid, _ in seen)
        assert all(payload is not None for _, payload in seen)
    finally:
        live.stop()
