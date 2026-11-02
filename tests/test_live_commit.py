"""采矿助手的提交边界（架构稿 §7.5、§11.2）：停止、重开、改配装时，迟到的结果不能发布、不能进 ResultStore

用线程开关卡准时机，不靠 sleep；画面是假的，不读屏。
"""

import threading
import time
from typing import Any

from PIL import Image

from sc_mining.app import bus, hud_state
from sc_mining.app.engines import live as live_mod
from sc_mining.core import paths
from sc_mining.mining import screen, signals
from sc_mining.mining.parse import Scan
from sc_mining.runtime.results import MINING_SCAN, MINING_SIGNALS
from sc_mining.tasks import mining as t_mining
from sc_mining.tasks import navigation as t_nav

WAIT = 30  # 等线程的上限：正常都是瞬间到，超时就是测试失败


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


def _track(live):
    """记下这个 live 起过的所有工作线程"""
    started = []
    start = live.start

    def tracked():
        start()
        started.append(live.thread)

    live.start = tracked
    return started


def _finish(live, started, q, gate=None):
    """断言失败也要收掉工作线程：补丁还原后它会去读真屏幕"""
    if gate:
        gate.release.set()
    live.stop_ev.set()
    for th in started:
        th.join(WAIT)
    bus.unsubscribe(q)


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


def _stop_with_worker_stuck(live) -> Any:
    """工作线程还卡着时停止，且 stop 不等它（等于 join 超时）：之后旧线程才迟到"""
    worker, live.thread = live.thread, None
    live.stop()
    return worker


def _start_stuck(monkeypatch, tmp_path):
    hud, _ = _world(monkeypatch, tmp_path)
    gate = _Gate()
    monkeypatch.setattr(t_mining, "scan_view", gate.view)
    live = live_mod._Live()
    started = _track(live)
    q = _subscribe()
    live.start()
    assert gate.entered.wait(WAIT)
    return live, gate, q, hud, started


def test_stop_between_analyze_and_commit_publishes_nothing(monkeypatch, tmp_path):
    """① 停止恰好落在算完和提交之间：什么都不发布，ResultStore 不变"""
    live, gate, q, hud, started = _start_stuck(monkeypatch, tmp_path)
    try:
        worker = _stop_with_worker_stuck(live)
        gate.release.set()
        worker.join(WAIT)
        assert not worker.is_alive()
        msgs = _drain(q)
        assert not [m for m in msgs if m["kind"] == "scan"]
        assert not [c for c in hud.calls if c[0] == "set"]
        assert live.results.get(MINING_SCAN) is None
        monkeypatch.setattr(t_nav._M, "results", live.results)
        monkeypatch.setattr(t_nav, "_note_hud", lambda *a, **k: None)
        assert "暂无扫描结果" in t_nav.ore_record()["error"]
    finally:
        _finish(live, started, q, gate)


def test_restart_rejects_late_result_of_old_session(monkeypatch, tmp_path):
    """② 停了马上重开：旧线程迟到的结果不能盖新会话，也不能重新点亮悬浮窗"""
    live, gate, q, hud, started = _start_stuck(monkeypatch, tmp_path)
    first = live.session_id
    try:
        old = _stop_with_worker_stuck(live)
        live.start()
        assert live.session_id > first
        _wait_kind(q, "scan")
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.value["rock"] == "新"
        before = (e.session_id, e.sequence)
        hud_before = len(hud.calls)
        gate.release.set()
        old.join(WAIT)
        assert not old.is_alive()
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.value["rock"] == "新"
        assert (e.session_id, e.sequence) >= before
        assert not [c for c in hud.calls[hud_before:] if "旧" in str(c)]
        live.stop()
        assert not [
            m for m in _drain(q) if m["kind"] == "scan" and m["data"]["rock"] == "旧"
        ]
    finally:
        _finish(live, started, q, gate)


def _manual_run(live, monkeypatch, tmp_path):
    _world(monkeypatch, tmp_path)
    live.session_id = 1
    return live_mod._Run(threading.Event(), 1)


def test_older_frame_arriving_late_is_rejected(monkeypatch, tmp_path):
    """③ 同一会话里旧帧晚到"""
    live = live_mod._Live()
    run = _manual_run(live, monkeypatch, tmp_path)
    older, newer = live._stamp(run, 1.0), live._stamp(run, 2.0)
    q = _subscribe()
    try:
        kw = {"slot": MINING_SCAN, "quality": "complete"}
        assert live._commit(
            run, live_mod._pub("scan", {"rock": "新"}), value="新", stamp=newer, **kw
        )
        assert not live._commit(
            run, live_mod._pub("scan", {"rock": "旧"}), value="旧", stamp=older, **kw
        )
        assert [m["data"]["rock"] for m in _drain(q) if m["kind"] == "scan"] == ["新"]
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.value == "新" and e.sequence == newer.seq
    finally:
        bus.unsubscribe(q)


def test_old_epoch_rejected_after_config_change(monkeypatch, tmp_path):
    """④ 配装变了：旧 epoch 的结果作废，下一帧按新配装算出来再发布，采矿助手不退出"""
    hud, _ = _world(monkeypatch, tmp_path)
    live = live_mod._Live()
    calls = []

    def view(*a, **k):
        calls.append(live.epoch)
        if len(calls) == 1:
            live.config_changed()  # 算到一半改了配装
            return _fake_view("旧配装")
        return _fake_view("新配装")

    monkeypatch.setattr(t_mining, "scan_view", view)
    started = _track(live)
    q = _subscribe()
    try:
        live.start()
        _wait_kind(q, "scan")
        live.stop()
        scans = [m for m in _drain(q) if m["kind"] == "scan"]
        assert not [m for m in scans if m["data"]["rock"] == "旧配装"]
        assert len(calls) >= 2 and calls[1] == calls[0] + 1
        assert ("set", "扫描", "HUD 旧配装") not in hud.calls
        assert ("set", "扫描", "HUD 新配装") in hud.calls
    finally:
        _finish(live, started, q)


def test_old_epoch_commit_changes_nothing(monkeypatch, tmp_path):
    live = live_mod._Live()
    run = _manual_run(live, monkeypatch, tmp_path)
    old = live._stamp(run, 1.0)
    live.config_changed()
    q = _subscribe()
    try:
        assert not live._commit(
            run,
            live_mod._pub("scan", {"rock": "旧"}),
            slot=MINING_SCAN,
            value="旧",
            stamp=old,
        )
        assert not [m for m in _drain(q) if m["kind"] == "scan"]
        assert live.results.get(MINING_SCAN) is None
    finally:
        bus.unsubscribe(q)


def test_stale_republish_does_not_touch_store(monkeypatch, tmp_path):
    """⑤ 过期重发：内容从 ResultStore 取、带 stale，存着的那条不变（不重新 accept）。时钟是假的"""
    clock = {"t": 1000.0}
    frames = {"n": 0}

    def analyse(img):
        frames["n"] += 1
        return (_rock() if frames["n"] <= 3 else Scan(), ({}, None, None))

    _world(monkeypatch, tmp_path, analyse)
    real_grab = screen.grab

    def grab():
        clock["t"] += 5.0
        if frames["n"] > 100:
            ev.set()  # 兜底：等不到过期也别卡住
        return real_grab()

    monkeypatch.setattr(screen, "grab", grab)
    monkeypatch.setattr(time, "time", lambda: clock["t"])
    monkeypatch.setattr(t_mining, "scan_view", lambda *a, **k: _fake_view())
    live = live_mod._Live()
    ev = live.stop_ev
    seen = {}
    real_publish = bus.publish

    def publish(kind, data):
        if kind == "scan":
            if data.get("stale"):
                seen["stale"] = data
                seen["after"] = live.results.get(MINING_SCAN)
                ev.set()
            else:
                seen["fresh"] = data
                seen["before"] = live.results.get(MINING_SCAN)
        real_publish(kind, data)

    monkeypatch.setattr(bus, "publish", publish)
    live._run(ev)
    assert seen.get("stale"), "没有过期重发"
    assert seen["stale"] == {**seen["fresh"], "stale": seen["stale"]["stale"]}
    assert seen["before"] == seen["after"]
    assert "stale" not in seen["after"].value


def test_live_false_comes_after_last_scan(monkeypatch, tmp_path):
    """⑥ running=False 排在最后一条 scan 之后，旧线程迟到也不例外"""
    live, gate, q, _, started = _start_stuck(monkeypatch, tmp_path)
    try:
        worker = _stop_with_worker_stuck(live)
        gate.release.set()
        worker.join(WAIT)
        msgs = _drain(q)
        kinds = [m["kind"] for m in msgs if m["kind"] in ("scan", "live")]
        assert kinds[-1] == "live" and msgs[-1]["data"] == {"running": False}
        assert "scan" not in kinds
    finally:
        _finish(live, started, q, gate)


def test_live_false_after_published_scan(monkeypatch, tmp_path):
    _world(monkeypatch, tmp_path)
    monkeypatch.setattr(t_mining, "scan_view", lambda *a, **k: _fake_view())
    live = live_mod._Live()
    started = _track(live)
    q = _subscribe()
    try:
        live.start()
        got = _wait_kind(q, "scan")
        live.stop()
        msgs = got + _drain(q)
        kinds = [m["kind"] for m in msgs if m["kind"] in ("scan", "live")]
        # start 先起线程再发 running=True，所以开头的 live 可能排在 scan 后面；只看收尾
        assert "scan" in kinds and kinds[-1] == "live"
        assert msgs[-1]["data"] == {"running": False}
    finally:
        _finish(live, started, q)


def _with_results(live, monkeypatch, tmp_path):
    run = _manual_run(live, monkeypatch, tmp_path)
    for slot, value in ((MINING_SCAN, "扫描"), (MINING_SIGNALS, {"view": {}})):
        assert live._commit(run, slot=slot, value=value, stamp=live._stamp(run, 1.0))
    return run


def test_every_way_of_stopping_clears_results(monkeypatch, tmp_path):
    from sc_mining.core import settings

    monkeypatch.setattr(settings, "update", lambda **kw: None)
    monkeypatch.setattr(hud_state, "_note_hud", lambda *a, **k: None)
    log = open(tmp_path / "x.log", "w", encoding="utf-8")

    stops = {
        "stop": lambda live, run: live.stop(),
        "auto_off": lambda live, run: live._auto_off(run.ev, log),
        "fail_off": lambda live, run: live._fail_off(run.ev, "坏了"),
    }
    try:
        for name, stop in stops.items():
            live = live_mod._Live()
            run = _with_results(live, monkeypatch, tmp_path)
            if name == "stop":
                live.stop_ev = run.ev
            epoch = live.epoch
            stop(live, run)
            assert live.results.get(MINING_SCAN) is None, name
            assert live.results.get(MINING_SIGNALS) is None, name
            assert live.epoch == epoch + 1, name
            assert not live._commit(
                run,
                slot=MINING_SCAN,
                value="迟到",
                stamp=live._stamp(run, 2.0),
            ), name
    finally:
        log.close()


def test_output_only_commit_needs_live_session(monkeypatch, tmp_path):
    """只有输出的提交（提示、过期重发）也查会话"""
    live = live_mod._Live()
    run = _manual_run(live, monkeypatch, tmp_path)
    assert live._commit(run)
    live.session_id = 2
    assert not live._commit(run)
    live.session_id = 1
    run.ev.set()
    assert not live._commit(run)


def test_feedback_context_reads_store():
    """反馈包里的字段和以前一样：读全的带成分，面板被挡的带 cut；信号带 values；发到窗口的消息里没有 values"""
    from sc_mining.runtime.results import ResultStore
    from sc_mining.tasks.system.feedback import FeedbackContext

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
    """提交和停止同一把锁：发布到一半时 stop 进不来，发布完才作废、清空，running=False 排在后面"""
    live = live_mod._Live()
    run = _manual_run(live, monkeypatch, tmp_path)
    live.stop_ev = run.ev
    inside, leave = threading.Event(), threading.Event()
    seq = []
    real = bus.publish

    def publish(kind, data):
        seq.append(kind)
        if kind == "scan":
            inside.set()
            assert leave.wait(WAIT)
        real(kind, data)

    monkeypatch.setattr(bus, "publish", publish)
    stamp = live._stamp(run, 1.0)
    committer = threading.Thread(
        target=live._commit,
        args=(run, live_mod._pub("scan", {"rock": "铜"})),
        kwargs={"slot": MINING_SCAN, "value": "铜", "stamp": stamp},
        daemon=True,
    )
    stopper = threading.Thread(target=live.stop, daemon=True)
    try:
        committer.start()
        assert inside.wait(WAIT)
        stopper.start()
        stopper.join(0.2)  # 只用来等「进不来」：实现对的话这里一定超时，不会偶发失败
        assert stopper.is_alive()
        assert not run.ev.is_set()
        assert live.results.get(MINING_SCAN) is not None
    finally:
        leave.set()
    committer.join(WAIT)
    stopper.join(WAIT)
    assert not committer.is_alive()
    assert not stopper.is_alive()
    assert run.ev.is_set()
    assert live.results.get(MINING_SCAN) is None
    assert seq.index("live") > seq.index("scan")


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
    started = _track(live)
    q = _subscribe()
    try:
        live.start()
        got = _wait_kind(q, "scan")
        e = live.results.get(MINING_SCAN)
        assert e is not None and e.quality == "partial"
        assert e.value["rock"] == "新配装"
        assert [m["data"]["rock"] for m in got if m["kind"] == "scan"] == ["新配装"]
        assert ("set", "扫描", "HUD 旧配装") not in hud.calls
    finally:
        _finish(live, started, q)


def _signal_world(monkeypatch, tmp_path, lines):
    from sc_mining.tasks import goals as t_goals

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
    started = _track(live)
    q = _subscribe()
    try:
        live.start()
        msg = _wait_kind(q, "signals")[-1]["data"]
        assert "values" not in msg and msg["lines"] == ["信号 4,285 → 铝"]
        e = live.results.get(MINING_SIGNALS)
        assert e is not None and e.value["values"] == [4285]
        assert e.value["view"]["lines"] == msg["lines"]
        assert ("set", "信号", "4,285 → 铝") in hud.calls
    finally:
        _finish(live, started, q)


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
    started = _track(live)
    q = _subscribe()
    try:
        live.start()
        got = _wait_kind(q, "signals")
        assert [m["data"]["lines"] for m in got if m["kind"] == "signals"] == [
            ["新配装"]
        ]
        assert ("set", "信号", "旧配装") not in hud.calls
    finally:
        _finish(live, started, q)


def test_signal_of_old_session_rejected_after_restart(monkeypatch, tmp_path):
    gate = _Gate()
    hud = _signal_world(monkeypatch, tmp_path, gate.lines)
    live = live_mod._Live()
    started = _track(live)
    q = _subscribe()
    try:
        live.start()
        assert gate.entered.wait(WAIT)
        old = _stop_with_worker_stuck(live)
        live.start()
        _wait_kind(q, "signals")
        gate.release.set()
        old.join(WAIT)
        assert not old.is_alive()
        e = live.results.get(MINING_SIGNALS)
        assert e is not None and e.value["view"]["lines"] == ["新"]
        assert ("set", "信号", "旧") not in hud.calls
        assert not [
            m
            for m in _drain(q)
            if m["kind"] == "signals" and m["data"]["lines"] == ["旧"]
        ]
    finally:
        _finish(live, started, q, gate)


def test_worker_keeps_the_session_it_was_started_with(monkeypatch, tmp_path):
    """会话号在 start 的锁里取好传给线程：线程起来得晚，也不会读成后来的新会话"""
    _world(monkeypatch, tmp_path)
    live = live_mod._Live()
    seen = []
    monkeypatch.setattr(
        live, "_run", lambda ev, session=None: seen.append(session), raising=False
    )
    started = _track(live)
    live.start()
    live.session_id += 5  # 线程读到的如果是这个就错了
    started[0].join(WAIT)
    assert seen == [1]
