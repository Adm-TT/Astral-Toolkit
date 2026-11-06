"""采矿助手：实时扫描、投票、扫描面板、雷达信号、矿记录（从 test_tools.py 拆出，CL-C3）"""

import pytest


def _live_run(
    monkeypatch,
    tmp_path,
    frames,
    seconds=0.8,
    stale=None,
    static=False,
    ev=None,
    sig=None,
    front=None,
    grabs=None,
    until=None,
):
    """跑一小段实时读屏：frames = 每次 analyse 依次返回的 Scan（None = 画面里没有面板），返回推送的消息和悬浮窗操作。
    front：游戏在不在最前面（默认判断不了 = 照常认，不看真电脑的前台窗口）；grabs：记下每次截图的时间"""
    import threading, time as _t  # noqa: E401
    from PIL import Image
    from astral_toolkit.mining import screen, signals
    from astral_toolkit.core import paths
    from astral_toolkit.mining.parse import Scan
    from astral_toolkit.tasks import mining as t_mining
    import astral_toolkit.app.engines.live as live_mod
    from astral_toolkit.app import bus

    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(paths, "shots", lambda name: tmp_path)
    n = {"i": 0}
    imgs = [
        Image.new("RGB", (320, 180), (20 + 40 * (k % 5), 20, 20)) for k in range(60)
    ]  # 每帧画面都明显不同：不省电跳过

    def grab():
        if grabs is not None:
            grabs.append(_t.time())
        return imgs[0] if static else imgs[n["i"] % len(imgs)]

    def analyse(_):
        s = frames[min(n["i"], len(frames) - 1)]
        n["i"] += 1
        return (s or Scan(), ({}, None, None))

    hud = []
    from astral_toolkit.tasks import navigation as t_nav, system as t_sys
    from astral_toolkit.app import hud_state

    _v = lambda: type(  # noqa: E731
        "H",
        (),
        {
            "set": lambda self, k, v, *rich: hud.append(("set", k)),  # noqa: E731
            "clear": lambda self, k: hud.append(("clear", k)),
        },
    )()
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    monkeypatch.setattr(screen, "grab", grab)
    monkeypatch.setattr(screen, "analyse", analyse)
    monkeypatch.setattr(screen, "INTERVAL", 0.01)
    monkeypatch.setattr(signals, "find_signatures", sig or (lambda im: []))
    monkeypatch.setattr(t_mining, "_game_front", front or (lambda: None))
    from tests.bootstrap_helpers import app_for_test

    # RT-B7：tasks.* 先绑定（认出信号后会问现在在哪个产矿区）；这里照旧另建一个 _Live 跑
    with app_for_test():
        live = live_mod._Live()
        if stale is not None:
            monkeypatch.setattr(live, "stale_after", {"panel": stale, "signals": stale})
        q = bus.subscribe()
        # 总线会补发之前保存的最后一条结果：先丢掉，只看这次跑出来的
        while not q.empty():
            q.get_nowait()
        if ev is not None:
            # 外部开关接上这个会话的停止开关：模拟「算到一半用户点了停止」
            def bridge():
                ev.wait()
                live.stop_ev.set()

            threading.Thread(target=bridge, daemon=True, name="test-live-stop").start()
        try:
            sid = live.start()
            assert sid is not None
            if until is not None:  # 等条件到了就停，不靠固定秒数
                deadline = _t.monotonic() + 5
                while not until() and _t.monotonic() < deadline:
                    _t.sleep(0.005)
            else:
                _t.sleep(seconds)
            live.stop_ev.set()
            live.loop.join(session_id=sid, timeout=2)
            msgs = []
            while not q.empty():
                msgs.append(q.get_nowait())
            return msgs, hud
        finally:
            from astral_toolkit.runtime.session import RunState

            if live.loop.state().state not in (RunState.STOPPED, RunState.FAILED):
                live.stop()  # 还有活会话才补收尾，别给已经停掉的会话再来一次确认
            bus.unsubscribe(q)


def _rock(mass, res, instab, scu, comp):
    from astral_toolkit.mining.parse import Scan

    return Scan(
        rock=None,
        mass=mass,
        resistance=res,
        instability=instab,
        total_scu=scu,
        composition=comp,
    )


def test_app_scan_view_and_manual():
    from astral_toolkit.mining.parse import parse_scan
    from astral_toolkit.tasks import mining as t_mining

    s = parse_scan(
        [
            "扫描结果",
            "钨矿石",
            "质量： 44336",
            "抗性： 4% ",
            "不稳定性： 17.32",
            "组成 23.68 SCU",
            "6.55% 兰石原矿 510",
            "12.95% 钨矿石 662",
            "49.41% 钨矿石 363",
            "31.07% 情性物质 。",
        ]
    )
    v = t_mining.scan_view(s, ({"Inert Materials": 0.3}, 0.3, 96.0))
    assert v["rock"] and v["plans"] and v["refine"] and v["bag"]["cap"] == 96.0
    assert "kg" in v["hud"] and v["plans"][0]["heads"]
    mats = {m["en"]: m for m in v["craft_mats"]}  # 「可制造 N 份蓝图」按钮的数据
    if mats:
        assert (
            mats["Tungsten"]["q"] == 662 and mats["Tungsten"]["count"] > 0
        )  # 同种矿取最高品质
        assert all(m["count"] > 0 and m["ok"] is not None for m in mats.values())
        assert [m["en"] for m in v["minerals"]] and all(
            "en" in m for m in v["minerals"]
        )
    assert t_mining.manual_scan(mass=20000, resistance=10, instability=5)


def test_live_scan_updates_when_read_gets_more_complete(monkeypatch, tmp_path):
    """画面不动时：第一次读到的成分不全，后面读全了也要更新（不能停在不完整的结果上）"""
    import time as _t  # noqa: E401
    from PIL import Image
    from astral_toolkit.mining import screen, signals
    from astral_toolkit.core import paths

    monkeypatch.setattr(
        paths, "log", lambda name: tmp_path / name
    )  # 别往电脑上真实的扫描记录里写
    monkeypatch.setattr(paths, "shots", lambda name: tmp_path)
    from astral_toolkit.mining.parse import Scan
    from astral_toolkit.tasks import mining as t_mining
    import astral_toolkit.app.engines.live as live_mod
    from astral_toolkit.app import bus

    img = Image.new("RGB", (320, 180), (20, 20, 20))
    part = Scan(
        rock="Tungsten",
        mass=44336,
        resistance=4,
        instability=17.32,
        total_scu=23.68,
        composition=[
            ("Tungsten", 12.95, 662),
            ("Tungsten", 49.41, 363),
            ("Inert Materials", 37.64, 0),
        ],
    )
    full = Scan(
        rock="Tungsten",
        mass=44336,
        resistance=4,
        instability=17.32,
        total_scu=23.68,
        composition=[
            ("Laranite", 6.55, 510),
            ("Tungsten", 12.95, 662),
            ("Tungsten", 49.41, 363),
            ("Inert Materials", 31.07, 0),
        ],
    )
    seq = [part, part, full, full, full, full, full, full]
    calls = []

    def analyse(_):
        calls.append(1)
        return (seq[min(len(calls) - 1, len(seq) - 1)], ({}, None, None))

    monkeypatch.setattr(screen, "grab", lambda: img)
    monkeypatch.setattr(screen, "analyse", analyse)
    monkeypatch.setattr(screen, "INTERVAL", 0.01)
    monkeypatch.setattr(signals, "find_signatures", lambda im: [])
    monkeypatch.setattr(
        t_mining, "_game_front", lambda: None
    )  # 不看真电脑上哪个窗口在最前面
    from astral_toolkit.tasks import navigation as t_nav, system as t_sys
    from astral_toolkit.app import hud_state

    _v = lambda: type(  # noqa: E731
        "H", (), {"set": lambda *a: None, "clear": lambda *a: None}
    )()  # 不弹真悬浮窗  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    q = bus.subscribe()
    live = live_mod._Live()
    try:
        sid = live.start()
        assert sid is not None
        deadline = _t.monotonic() + 5
        while (
            len(calls) < 8 and _t.monotonic() < deadline
        ):  # 等这几帧都认过，不固定睡眠
            _t.sleep(0.005)
        live.stop_ev.set()
        live.loop.join(session_id=sid, timeout=2)
        scans = []
        while not q.empty():
            m = q.get_nowait()
            if m["kind"] == "scan":
                scans.append(m["data"])
        assert scans, "没有出结果"
        assert len(scans[-1]["minerals"]) == 2, scans[-1][
            "minerals"
        ]  # 最后显示的是读全的（钨 + 兰石）
        assert len(calls) < 40  # 画面不动、结果已完整：不再一直识别
    finally:
        live.stop()
        bus.unsubscribe(q)


def test_ship_signature_match():
    """截面对得上：短剑正对时的截面应该把短剑排第一；离谱的数对不上任何船"""
    from astral_toolkit.core.paths import DATA
    from astral_toolkit.mining import shipsig

    if not (DATA / "ship_signatures.json").exists():
        pytest.skip("没有舰船截面数据")
    rows = shipsig.match(1956)
    assert rows and "Gladius" in rows[0]["name"]
    assert shipsig.match(10) == []
    # 电磁远超上限的排除掉
    assert all(
        r["em_max"] * shipsig.SLACK >= 10**6 for r in shipsig.match(1956, em=10**6)
    )


def test_live_scan_resumes_after_restart(monkeypatch, tmp_path):
    """原矿扫描开着时 AT 重启 / 升级：重启后自动接着扫（以前重启后就关了，信号识别也跟着没了）"""
    from astral_toolkit import bootstrap
    from astral_toolkit import gamedata
    from astral_toolkit import ocr as OCR
    from astral_toolkit.app.engines import hover as hover_engine
    from astral_toolkit.app.engines import live as live_engine
    from astral_toolkit.app.engines import nav as nav_engine
    from astral_toolkit.app.engines import pos as pos_engine
    from astral_toolkit.core import settings
    from astral_toolkit.core.perfmon import monitor
    from astral_toolkit.tasks.catalog_queries import search as itemsearch
    from astral_toolkit.runtime.session import StopAttempt
    from astral_toolkit.tasks import mining as t_mining, system as t_sys
    from tests.bootstrap_helpers import app_for_test

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    settings.update(agreed=True)
    started = []
    # RT-B7：服务在装配时登记，记下的是各对象当时的 start，所以要在 app_for_test() 之前按类换掉；
    # 这样走的是真的 lifecycle.start_all 和采矿助手的 gate，只是不起真热键、读屏、读 Game.log、perfmon
    monkeypatch.setattr(live_engine._Live, "start", lambda self: started.append(1))
    monkeypatch.setattr(
        live_engine._Live, "stop", lambda self: StopAttempt(None, False, False)
    )
    for cls in (
        hover_engine._Hover,
        pos_engine._Pos,
        pos_engine._LogWatch,
        nav_engine._GameEvents,
    ):
        monkeypatch.setattr(cls, "start", lambda self: None)
    monkeypatch.setattr(monitor, "start", lambda: None)  # 不起 perfmon 常驻线程
    monkeypatch.setattr(OCR, "warmup", lambda: None)  # 不预热 OCR
    monkeypatch.setattr(
        itemsearch, "build_index", lambda: None
    )  # 预热线程照起，但不建搜索索引
    monkeypatch.setattr(gamedata, "warm_up", lambda: None)  # 不建游戏数据库
    monkeypatch.setattr(t_sys, "_online_loop", lambda *a: None)  # 测试里不联网检查更新
    # 新的一份（装配时登记的更新服务也用这份，所以在装配前换）：不永久置 loop；不补发真实反馈
    monkeypatch.setattr(t_sys, "_online", {"info": None, "told": "", "fb_retry": True})
    # live_on 只由会话循环写（RT-B4 起命令层不再写）：这里直接摆开关，测 start_background 的门控
    settings.update(live_on=True)
    with app_for_test() as app:
        t_mining.live_start(app.live)  # 命令层只负责开会话（这里被换成记录调用）
        started.clear()
        bootstrap.start(app)  # 模拟重启：live_on 开着 → 接着扫
        assert started == [1]
    settings.update(live_on=False)
    with app_for_test() as app:  # 关着的时候重启：不自动开
        t_mining.live_stop(app.live)
        started.clear()
        bootstrap.start(app)
        assert not started and not settings.load()["live_on"]


def test_vote_needs_stable_composition_and_same_rock_checks_resistance():
    """成分没读稳（两帧百分比对不上）不算稳定；质量差不多但抗性不同的是两块石头（审查建议 2026-10-23）"""
    from astral_toolkit.mining import screen

    a = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    )
    b = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 45.0, 500), ("Inert Materials", 55.0, 0)]
    )
    assert screen.vote([a, a])[1] and not screen.vote([a, b])[1]
    c = _rock(10000, 20, 5.0, 11.0, a.composition)  # 总 SCU 也要读稳
    assert not screen.vote([a, c])[1]
    assert screen._same_rock(a, a) and not screen._same_rock(
        a, _rock(10050, 45, 5.0, 10.0, a.composition)
    )


def test_live_rebuilds_queue_and_expires_old_result(monkeypatch, tmp_path):
    """目标丢了（连续几帧没面板）投票队列重建，不把下一块石头混进来；面板消失太久，悬浮窗清掉、窗口标过期
    （画面静止、省电跳过识别时也要过期）"""
    a = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    )
    msgs, hud = _live_run(
        monkeypatch, tmp_path, [a, a, a] + [None] * 200, seconds=0.8, stale=0.2
    )
    scans = [m["data"] for m in msgs if m["kind"] == "scan"]
    assert (
        scans and not scans[0].get("stale") and scans[-1].get("stale")
    )  # 先出结果，后来同一条结果带「已过期」再发
    assert ("clear", "扫描") in hud and ("clear", "矿袋") in hud
    from astral_toolkit.app import bus

    q = bus.subscribe()  # 窗口刷新/重连：补发的也是过期的那条
    try:
        replay = [
            m["data"]
            for m in iter(lambda: q.get_nowait() if not q.empty() else None, None)
            if m["kind"] == "scan"
        ]
        assert replay and replay[-1].get("stale")
    finally:
        bus.unsubscribe(q)


def test_live_republishes_corrected_total_scu(monkeypatch, tmp_path):
    """同一块石头，总 SCU 一开始读错、后来读对：要重新发布（以前只看质量/抗性/不稳定性，修正后的数推不出去）"""
    comp = [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    wrong, right = _rock(10000, 20, 5.0, 16.0, comp), _rock(10000, 20, 5.0, 10.0, comp)
    msgs, _ = _live_run(
        monkeypatch, tmp_path, [wrong, wrong] + [right] * 50, seconds=0.6
    )
    scans = [m["data"] for m in msgs if m["kind"] == "scan"]
    assert (
        len(scans) >= 2
        and abs(sum(x["scu"] for x in scans[-1]["minerals"]) - 4.0) < 0.01
    )


def test_live_session_isolation(monkeypatch, tmp_path):
    """快速停了又开（旧线程还卡在识别里、join 已超时）：新会话是全新的；旧会话的结果写不进来"""
    import threading
    from dataclasses import replace

    import astral_toolkit.app.engines.live as live_mod
    from astral_toolkit.core import paths
    from astral_toolkit.mining import screen, signals
    from astral_toolkit.mining.parse import Scan
    from astral_toolkit.runtime.results import MINING_SCAN
    from astral_toolkit.runtime.session import RunFlag
    from astral_toolkit.tasks import mining as t_mining
    from tests.runtime_fakes import RecordingOutput

    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(paths, "shots", lambda name: tmp_path)
    frame = __import__("PIL.Image", fromlist=["Image"]).new(
        "RGB", (320, 180), (30, 20, 20)
    )
    monkeypatch.setattr(screen, "grab", lambda: frame)
    monkeypatch.setattr(
        live_mod,
        "setting_run_flag",
        lambda key: RunFlag(key, lambda k, v: None),
    )
    old_rock = "旧石头"
    old_scan = replace(
        _rock(
            10000.0,
            20,
            5.0,
            12.0,
            [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)],
        ),
        rock=old_rock,
    )
    empty_scan = Scan()
    gate = threading.Event()
    entered = threading.Event()
    calls = {"n": 0}

    def analyse(img):
        calls["n"] += 1
        if calls["n"] == 1:
            return old_scan, ({}, None, None)  # A 先认出一帧
        if calls["n"] == 2:
            entered.set()
            gate.wait(30)  # A 第二帧卡在识别里；放行后两帧投票成立、真去提交（应被拒）
            return old_scan, ({}, None, None)
        return empty_scan, ({}, None, None)

    monkeypatch.setattr(screen, "analyse", analyse)
    monkeypatch.setattr(signals, "find_signatures", lambda img: [])
    monkeypatch.setattr(screen, "INTERVAL", 0.01)
    monkeypatch.setattr(screen, "LAST_RAW", {})
    monkeypatch.setattr(screen, "LAST_PANEL", {})
    monkeypatch.setattr(t_mining, "_game_front", lambda: None)
    out = RecordingOutput()
    live = live_mod._Live(output=out, foreground=lambda: True)
    live.loop._join_timeout = 0.05
    try:
        assert live.start() is not None
        first = live.session_id
        old = live.loop._current.session  # type: ignore[union-attr]
        assert entered.wait(30)
        attempt = live.stop()
        assert attempt.timed_out and not old.alive(), "旧会话的开关已经按下、线程还卡着"
        assert live.start() is not None and live.session_id > first
        second = live.session_id
        new = live.loop._current.session  # type: ignore[union-attr]
        assert new is not old and new.alive() and live.running()
        out.clear()
        gate.set()  # 放行旧线程
        assert live.loop.join(session_id=first, timeout=30)
        entry = live.results.get(MINING_SCAN)
        assert entry is None or old_rock not in repr(entry.value)
        assert not any(old_rock in repr(r.op) for r in out.ops)
        assert live.loop.state().session_id == second
        assert live.running(), "旧会话退出不影响新会话"
        assert live.loop.stamp(old, 1.0) is None  # 旧会话再来取表被拒
    finally:
        gate.set()
        live.stop()
        live.loop.join_all(timeout=30)


def test_live_stop_during_compute_publishes_nothing(monkeypatch, tmp_path):
    """算破碎方案的时候用户按了停止：算完不能再把旧结果推到窗口和悬浮窗（复审 2026-10-23）"""
    import threading
    from astral_toolkit.tasks import mining as t_mining

    real = t_mining.scan_view
    ev = threading.Event()

    def slow_view(scan, bag):
        ev.set()  # 模拟：算到一半用户点了停止
        return real(scan, bag)

    monkeypatch.setattr(t_mining, "scan_view", slow_view)
    a = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    )
    msgs, hud = _live_run(monkeypatch, tmp_path, [a] * 50, seconds=0.5, ev=ev)
    assert not [m for m in msgs if m["kind"] == "scan"] and ("set", "扫描") not in hud


def test_live_saves_frames_when_panel_unreadable(monkeypatch, tmp_path):
    """看得到扫描面板却一直读不全 / 读不稳：自动留一张图、日志记一行 MISS（2026-10-23 用户说「部分矿物扫描失败」，当时没有图可查）"""
    import time as _t

    half = _rock(
        None, None, None, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    )  # 上半截（质量那几行）没读到
    msgs, _ = _live_run(monkeypatch, tmp_path, [half] * 200, seconds=0.6)
    _t.sleep(0.3)  # 存图在后台线程
    log = (tmp_path / "live_log.txt").read_text(encoding="utf-8")
    assert "MISS 读不全" in log and list(tmp_path.glob("*.png"))
    assert log.count("MISS") == 1  # 30 秒内只留一张
    assert not [m for m in msgs if m["kind"] == "scan"]


def test_live_saves_frame_when_votes_never_agree(monkeypatch, tmp_path):
    import time as _t

    a = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    )
    b = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 45.0, 500), ("Inert Materials", 55.0, 0)]
    )
    c = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 30.0, 500), ("Inert Materials", 70.0, 0)]
    )
    d = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 35.0, 500), ("Inert Materials", 65.0, 0)]
    )
    e = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 25.0, 500), ("Inert Materials", 75.0, 0)]
    )
    msgs, _ = _live_run(
        monkeypatch,
        tmp_path,
        [a, b, c, d, e, a, b, c, d, e] + [None] * 200,
        seconds=0.6,
    )
    _t.sleep(0.3)
    log = (tmp_path / "live_log.txt").read_text(encoding="utf-8")
    assert "MISS 读不稳" in log, log
    assert not [m for m in msgs if m["kind"] == "scan"], msgs  # 读不稳：不出结果


def test_live_pauses_when_game_not_in_front(monkeypatch, tmp_path):
    """游戏不在最前面（切到聊天、浏览器）：不截图、不认面板和信号，窗口显示已暂停；回到游戏马上接着认，
    暂停的这段不算面板消失（结果不过期、悬浮窗不清）（2026-10-23 用户同意：聊天窗口里的字被当成面板、数字被当成信号）"""
    import time as _t

    a = _rock(
        10000, 20, 5.0, 10.0, [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    )
    st = {"t0": None}

    def front():
        now = _t.time()
        st["t0"] = st["t0"] or now
        return not (0.4 <= now - st["t0"] < 1.4)  # 0.4~1.4 秒切到了别的窗口

    grabs = []
    msgs, hud = _live_run(
        monkeypatch,
        tmp_path,
        [a] * 5000,
        seconds=2.0,
        stale=0.3,
        front=front,
        grabs=grabs,
    )
    t0 = st["t0"]
    assert grabs and not [
        g for g in grabs if 0.55 < g - t0 < 1.3
    ]  # 暂停时一张都不截、不认
    assert [g for g in grabs if g - t0 > 1.45]  # 回到游戏接着认
    live = [m["data"] for m in msgs if m["kind"] == "live"]
    assert {"running": True, "paused": True} in live
    assert [e for e in live if "paused" in e][-1] == {
        "running": True,
        "paused": False,
    }, live
    scans = [m["data"] for m in msgs if m["kind"] == "scan"]
    assert (
        scans
        and not any(x.get("stale") for x in scans)
        and hud.count(("clear", "扫描")) <= 1
    )  # 暂停那段没让结果过期 / 没多清悬浮窗（1 次是收尾那次）
    log = (tmp_path / "live_log.txt").read_text(encoding="utf-8")
    assert "PAUSE 游戏不在最前面" in log and "RESUME 回到游戏" in log


def test_game_front_unknown_does_not_pause(monkeypatch):
    """判断不了游戏在不在最前面（不是 Windows、这一刻没有前台窗口、出错）返回 None：采矿助手照常认，不能因此停掉"""
    from astral_toolkit.system import showloc

    if not showloc.WIN:
        assert showloc.game_front() is None
        return
    fake = type("U32", (), {})()
    fake.GetForegroundWindow = lambda: 0
    monkeypatch.setattr(showloc, "_u32", fake)
    monkeypatch.setattr(showloc, "_fg_cache", {"hwnd": None, "ok": False})
    assert showloc.game_front() is None and showloc.game_foreground() is False
    fake.GetForegroundWindow = lambda: 1234
    monkeypatch.setattr(showloc, "_is_game_window", lambda h: False)
    monkeypatch.setattr(showloc, "_exe_of", lambda h: "claude.exe")
    assert showloc.game_front() is False
    monkeypatch.setattr(showloc, "_fg_cache", {"hwnd": None, "ok": False})
    monkeypatch.setattr(showloc, "_exe_of", lambda h: "starcitizen.exe")
    assert showloc.game_front() is True

    def boom(h):
        raise OSError("读不到")

    monkeypatch.setattr(showloc, "_fg_cache", {"hwnd": None, "ok": False})
    monkeypatch.setattr(showloc, "_is_game_window", boom)
    assert showloc.game_front() is None


def test_vote_name_and_percent_voted_together():
    """矿名和百分比要一起投票：Copper 40,40 / Copper 60 / Gold 60,60 不能拼出只出现过一次的「Copper 60%」"""
    from astral_toolkit.mining import screen

    rows = [
        ("Copper", 40.0),
        ("Copper", 40.0),
        ("Copper", 60.0),
        ("Gold", 60.0),
        ("Gold", 60.0),
    ]
    frames = [
        _rock(10000, 20, 5.0, 10.0, [(n, p, 500), ("Inert Materials", 100 - p, 0)])
        for n, p in rows
    ]
    best, stable = screen.vote(frames)
    assert best.composition[0][:2] in (
        ("Copper", 40.0),
        ("Gold", 60.0),
    ) and best.composition[0][:2] != ("Copper", 60.0)


def test_vote_tolerates_last_digit_jitter_with_real_readings():
    """末位抖动（质量 12431 / 12437、抗性 20 / 21、百分比 45.22 / 45.27）也要投出结果（2026-10-24 外部补丁）；
    结果只用实际读到过的数，不取平均——抗性 20.5%、百分比 45.245 面板上没有（1.6.43）"""
    from astral_toolkit.mining import screen

    def comp(p):
        return [("Copper", p, 600), ("Inert Materials", round(100 - p, 2), 0)]

    frames = [
        _rock(12431, 20, 5.0, 7.84, comp(45.22)),
        _rock(12437, 21, 5.0, 7.84, comp(45.27)),
    ]
    best, stable = screen.vote(frames)
    assert stable and best.mass in (12431, 12437) and best.resistance in (20, 21), best
    assert best.composition[0][1] in (45.22, 45.27) and best.composition[1][1] in (
        54.78,
        54.73,
    ), best
    best, stable = screen.vote(frames + [_rock(12434, 20, 5.0, 7.84, comp(45.24))])
    assert (
        stable
        and best.resistance == 20
        and best.mass == 12434
        and best.composition[0][1] == 45.24
    ), best
    best, stable = screen.vote_partial(frames)
    assert stable and best.mass in (12431, 12437) and best.resistance in (20, 21), best


def test_enqueue_rock_keeps_votes_on_one_bad_frame():
    """投票队列（2026-10-24 外部补丁）：读稳以后中间认错一帧（质量少认一位）不清空，那一帧不进队列；
    真换了石头要连续两帧一致才清空重计（新石头因此晚出 1 帧）"""
    import collections
    from astral_toolkit.mining import screen

    screen._reject.clear()
    comp = [("Copper", 40.0, 500), ("Inert Materials", 60.0, 0)]
    A, X, B = (
        _rock(10000, 20, 5.0, 10.0, comp),
        _rock(1000, 20, 5.0, 10.0, comp),
        _rock(20850, 35, 5.0, 10.0, comp),
    )
    q = collections.deque(maxlen=screen.VOTE_FRAMES)
    assert [screen.enqueue_rock(q, s) for s in (A, A, A)] == [False] * 3
    assert (
        screen.enqueue_rock(q, X) is False and len(q) == 3
    )  # 认错的一帧先记下，不进队列
    assert screen.enqueue_rock(q, A) is False and len(q) == 4  # 下一帧又是 A：照常累积
    assert screen.vote([x[0] for x in q])[1]
    assert screen.enqueue_rock(q, B) is False and len(q) == 4  # 新石头第一帧：先观察
    assert screen.enqueue_rock(q, B) is True and [x[0] for x in q] == [
        B
    ]  # 连续两帧一致：换石头
    screen._reject.clear()


def test_live_signals_pause_while_scan_panel_open(monkeypatch, tmp_path):
    """对着石头看扫描面板时不认信号（面板上的质量 13,586 会被当成信号，2026-10-23 用户反馈）；
    面板一出现悬浮窗的信号就收起，面板关了再继续认"""
    from astral_toolkit.mining.parse import Scan

    a = Scan(
        rock="Iron",
        mass=13586.0,
        resistance=0.0,
        instability=10.23,
        total_scu=17.46,
        composition=[("Iron", 10.98, 710), ("Inert Materials", 89.02, None)],
    )
    calls = []

    def sig(img):
        calls.append(1)
        return [(13586, False, "13,586", (0, 0, 10, 10))]

    from astral_toolkit.tasks import goals as t_goals, navigation as t_nav

    monkeypatch.setattr(
        t_nav, "_where_now", lambda: None
    )  # 不去读真屏幕右上角（Windows 上会很慢）
    monkeypatch.setattr(
        t_goals, "goal_short", lambda force=False: {}
    )  # 不读真的目标 / 库存
    frames = [None] * 6 + [a] * 60
    msgs, hud = _live_run(monkeypatch, tmp_path, frames, seconds=1.0, sig=sig)
    assert len(calls) <= 6  # 面板出现后不再调用信号识别
    assert ("set", "信号") in hud and ("clear", "信号") in hud
    assert hud.index(("clear", "信号")) > hud.index(("set", "信号"))


def test_scan_view_lots_by_quality(monkeypatch):
    """成分表（1.6.42）：石头里每一份（矿 × 品质、惰性物质）一行；同一种矿两种品质标高 / 低；品质写第几档；
    精炼按份算（精炼保留品质，不同品质精炼完还是分开的）；目标按每一份判断品质门槛；悬浮窗写惰性占比和高品质那份"""
    from astral_toolkit.mining.parse import parse_scan
    from astral_toolkit.tasks import (
        count as t_count,
        goals as t_goals,
        mining as t_mining,
        stock as t_stock,
        trade as t_trade,
    )
    from astral_toolkit.crafting import goals as G

    tung = {
        "en": "Tungsten",
        "zh": "钨",
        "short": 0.5,
        "unit": "SCU",
        "minq": 600,
        "goals": ["某蓝图"],
        "item": None,
    }
    monkeypatch.setattr(G, "load", lambda: [{"id": "x"}])
    monkeypatch.setattr(
        G, "plan", lambda t=None, goals=None: {"goals": [], "shortfall": [tung]}
    )
    _v = lambda: None  # noqa: E731
    for _m in (t_count, t_goals, t_stock, t_trade):
        monkeypatch.setattr(_m, "trade", _v)
    t_goals._SHORT["t"] = 0.0
    s = parse_scan(
        [
            "扫描结果",
            "钨矿石",
            "质量： 44336",
            "抗性： 4% ",
            "不稳定性： 17.32",
            "组成 23.68 SCU",
            "6.55% 兰石原矿 510",
            "12.95% 钨矿石 662",
            "49.41% 钨矿石 363",
            "31.07% 情性物质 。",
        ]
    )
    v = t_mining.scan_view(s, ({}, None, None))
    lots = v["lots"]
    assert [(r["zh"], r["q"], r["rank"]) for r in lots] == [
        ("砬兰石", 510, ""),
        ("钨", 662, "高品质"),
        ("钨", 363, "低品质"),
        ("惰性物质", None, ""),
    ]
    assert [r["tier"] for r in lots] == ["E 档", "D 档", "F 档（最低）", ""]
    assert (
        abs(lots[1]["scu"] - 23.68 * 0.1295) < 1e-3
        and abs(lots[3]["scu"] - 23.68 * 0.3107) < 1e-3
    )
    assert lots[3]["inert"] and lots[3]["refined_text"] == "无精炼产出，仅占用矿袋"
    # 每份精炼后的量加起来 = 第一种精炼方式的总量
    assert abs(sum(r["refined"] or 0 for r in lots) - v["refine"][0]["scu"]) < 1e-6
    assert [(x["zh"], x["q"]) for x in v["refine"][0]["lots"]] == [
        ("砬兰石", 510),
        ("钨", 662),
        ("钨", 363),
    ]
    assert v["lots_plan"] and v["total_scu"] == 23.68 and not v["cut"]
    assert "惰性 31%｜钨 品质 662：3.07 SCU" in v["hud"]
    g = v["goal"][0]
    assert (
        g["ok"]
        and "品质 662：已达标（精炼后 1.50 SCU），品质 363：未达标" in g["text"]
        and "品质 ≥600" in g["text"]
    )
    # 只有一种品质时照旧：「当前 650 不够」
    assert "当前 650 未达标" in t_goals._goal_text(dict(tung, minq=800), 650)
    t_goals._SHORT["t"] = 0.0


def test_scan_view_when_panel_cut_off():
    """面板被屏幕右边挡住（16:10 屏幕上鼹鼠炮塔，2026-10-23 用户反馈）：只有质量、抗性、不稳定性和成分占比，
    照样给破碎方案，写明品质和总 SCU 看不到、调大 FOV视野"""
    from astral_toolkit.mining.parse import Scan
    from astral_toolkit.tasks import mining as t_mining

    c = Scan(
        rock="Ouratite",
        mass=745,
        resistance=20,
        instability=8.2,
        total_scu=None,
        difficulty="简单",
        composition=[
            ("Ouratite", 2.79, None),
            ("Ouratite", 5.04, None),
            ("Agricium", 14.52, None),
            ("Inert Materials", 77.64, None),
        ],
    )
    v = t_mining.scan_view(c, ({}, None, None), cut=True)
    assert (
        v["cut"]
        and "FOV视野" in v["note"]
        and v["plans"]
        and not v["refine"]
        and not v["minerals"]
    )
    assert "面板被遮挡：仅计算破碎方案" in v["hud"] and "惰性 78%" in v["hud"]
    assert [r["scu"] for r in v["lots"]] == [None] * 4 and [
        r["pct"] for r in v["lots"]
    ] == [2.79, 5.04, 14.52, 77.64]


def test_live_cut_panel_gives_breaking_plan(monkeypatch, tmp_path):
    """面板顶着屏幕右边、品质和总 SCU 读不到：两帧一致就出「只有破碎方案」的结果，不当成读不全（不留图）"""
    import time as _t
    from astral_toolkit.mining import screen
    from astral_toolkit.mining.parse import Scan

    c = Scan(
        rock="Ouratite",
        mass=745,
        resistance=20,
        instability=8.2,
        total_scu=None,
        composition=[
            ("Ouratite", 2.79, None),
            ("Agricium", 14.52, None),
            ("Inert Materials", 82.69, None),
        ],
    )
    monkeypatch.setattr(
        screen, "LAST_PANEL", {"cut": True, "box": (2200, 600, 2560, 1000), "h": 14}
    )
    msgs, hud = _live_run(monkeypatch, tmp_path, [c] * 40, seconds=0.5)
    scans = [m["data"] for m in msgs if m["kind"] == "scan"]
    assert (
        scans and scans[-1]["cut"] and scans[-1]["mass"] == 745 and scans[-1]["plans"]
    )
    assert ("set", "扫描") in hud
    _t.sleep(0.2)
    log = (tmp_path / "live_log.txt").read_text(encoding="utf-8")
    assert "PART" in log and "MISS" not in log and not list(tmp_path.glob("*.png"))
    # 没顶着屏幕边的面板读不全：不出这种结果
    monkeypatch.setattr(
        screen, "LAST_PANEL", {"cut": False, "box": (1500, 600, 1800, 1000), "h": 8}
    )
    msgs, _ = _live_run(monkeypatch, tmp_path, [c] * 40, seconds=0.4)
    assert not [m for m in msgs if m["kind"] == "scan"]


def test_live_miss_hint_reason(monkeypatch, tmp_path):
    """读不全时告诉玩家原因：面板被屏幕右边挡住 → 调大 FOV视野；面板不见了提示收起"""
    from astral_toolkit.mining import screen
    from astral_toolkit.mining.parse import Scan

    half = Scan(
        rock="Ouratite",
        mass=None,
        resistance=None,
        instability=None,
        total_scu=None,
        composition=[("Ouratite", 2.79, None), ("Inert Materials", 97.21, None)],
    )
    monkeypatch.setattr(
        screen, "LAST_PANEL", {"cut": True, "box": (2200, 600, 2560, 1000), "h": 14}
    )
    msgs, hud = _live_run(
        monkeypatch, tmp_path, [half] * 30 + [None] * 200, seconds=1.0, stale=0.3
    )
    hints = [m["data"] for m in msgs if m["kind"] == "scan_hint"]
    assert hints and hints[0]["why"] == "cut" and "FOV视野" in hints[0]["text"]
    assert hints[-1]["text"] == "" and ("clear", "扫描") in hud  # 面板不见了：收起
    assert "HINT cut" in (tmp_path / "live_log.txt").read_text(encoding="utf-8")


def test_ore_log_record_and_hotkeys(monkeypatch, tmp_path):
    """1.6.70 原矿记录：记最近一块矿（窗口里点的不带坐标）、删除能撤销；所有热键都能改，原矿记录键能清掉"""
    from astral_toolkit import bootstrap
    from astral_toolkit.mining import ore_log
    from astral_toolkit.core import settings
    from astral_toolkit.tasks import navigation as t_nav, system as t_sys
    from astral_toolkit.app import bus
    from astral_toolkit.app import hud_state

    monkeypatch.setattr(ore_log, "FILE", tmp_path / "ore_log.json")
    monkeypatch.setattr(bus, "publish", lambda *a, **k: None)
    _v = lambda *a, **k: None  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_note_hud", _v)
    from astral_toolkit.runtime.results import MINING_SCAN, ResultStore

    results = ResultStore()
    from tests.bootstrap_helpers import app_for_test

    # RT-B7：结果仓库从装配入口注入（以前改 _M.results）
    with app_for_test(results=results) as app:
        sources = bootstrap.status_sources(app)
        assert "error" in t_nav.ore_record(app.nav_deps)
        _view = {
            "rock": "塔兰导电石",
            "mass": 38775,
            "resistance": 55,
            "instability": 323.46,
            "total_scu": 36.9,
            "at": "16:02:06",
            "lots": [
                {
                    "zh": "塔兰导电石",
                    "en": "Taranite",
                    "pct": 11.55,
                    "q": 718,
                    "scu": 4.26,
                    "inert": False,
                },
                {
                    "zh": "惰性物质",
                    "en": "Inert Materials",
                    "pct": 30.92,
                    "q": None,
                    "scu": 11.41,
                    "inert": True,
                },
            ],
            "refine": [
                {
                    "method": "德尼克斯熔解法",
                    "station": "列夫斯基",
                    "value": 344786,
                    "scu": 12.39,
                }
            ],
        }
        assert results.accept(MINING_SCAN, _view, 1, 0, 1, 0.0, 0.0)
        rec = t_nav.ore_record(app.nav_deps)
        assert (
            rec["value"] == 344786
            and rec["lots"][0]["pct"] == 11.55
            and "coords" not in rec
        )
        assert t_nav.ore_list()["rows"][0]["id"] == rec["id"]
        gone = t_nav.ore_delete(id=rec["id"])
        assert t_nav.ore_list()["rows"] == []
        t_nav.ore_restore(rec=gone)
        assert [r["id"] for r in t_nav.ore_list()["rows"]] == [rec["id"]]
        ore_err = t_nav.ore_go(app.nav_deps, id=rec["id"])["error"]
        assert isinstance(ore_err, str) and "没有坐标" in ore_err
        store = dict(settings.DEFAULTS)
        monkeypatch.setattr(settings, "load", lambda: dict(store))
        monkeypatch.setattr(
            settings, "update", lambda **kw: (store.update(kw), dict(store))[1]
        )
        assert t_sys.set_settings(sources, live_key="f4")["live_key"] == "F4"
        assert "盘点" in t_sys.set_settings(sources, ore_key="F6")["error"]
        assert (
            t_sys.set_settings(sources, ore_key="F11")["ore_key"] == "F11"
            and t_sys.set_settings(sources, ore_key="")["ore_key"] == ""
        )
        assert "F1–F12" in t_sys.set_settings(sources, mark_key="Q")["error"]
        w = t_sys.hotkey_conflicts({**store, "mark_key": "F7", "ore_key": "F7"})
        assert len(w) == 1 and "原矿记录" in w[0] and "记录路标" in w[0]


def test_gear_change_marks_live_for_recalc(monkeypatch, tmp_path):
    """改配装后，采矿助手正在显示的石头要按新配装重算：set_mining_gear 给 _live 打记号"""
    from astral_toolkit.core import settings
    from astral_toolkit.tasks import mining as t_mining
    from tests.bootstrap_helpers import app_for_test

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    with app_for_test() as app:
        before = app.live.loop.config_rev
        t_mining.set_mining_gear(
            app.live,
            ship="mole",
            loadout={"heads": [["helix_ii", []]] * 3, "crew": 2},
        )
        assert app.live.loop.config_rev == before + 1


def test_signal_harvestable_2000():
    """地面 2,000 的倍数是可采集物（植物、菌菇等）：2026-10-27 实测 10,000 = 5 个"""
    from astral_toolkit.mining import signals

    lines = signals.describe_all([(10000, False, "10000", None)], where="ground")
    assert lines == ["信号 10,000 → 可采集物 ×5（植物、菌菇等）"]


def test_live_key_hint_says_stopping_when_refused(monkeypatch):
    """3-2：真引擎正在停止时按 F5，提示「正在停止，请稍候」，不说「已开启」"""
    from types import SimpleNamespace

    from PIL import Image

    from astral_toolkit.app.engines import hover as hover_mod
    from astral_toolkit.app.engines import live as live_engine
    from astral_toolkit.mining import screen as mining_screen
    from astral_toolkit.mining import signals
    from astral_toolkit.mining.parse import Scan
    from astral_toolkit.runtime.session import RunFlag, StopInfo
    from astral_toolkit.tasks import navigation as nav_tasks
    from tests.bootstrap_helpers import app_for_test
    from tests.runtime_fakes import FakeClock, Gate, RecordingOutput

    flag_writes = []
    monkeypatch.setattr(
        live_engine,
        "setting_run_flag",
        lambda key: RunFlag(key, lambda k, v: flag_writes.append((k, v))),
    )
    monkeypatch.setattr(
        mining_screen, "analyse", lambda img: (Scan(), ({}, None, None))
    )
    monkeypatch.setattr(signals, "find_signatures", lambda img: [])
    monkeypatch.setattr(nav_tasks, "settings_key", lambda *a, **k: "F5")
    notes = []
    hud = SimpleNamespace(_note_hud=lambda section, text: notes.append(text))
    monkeypatch.setattr(hover_mod, "_H", lambda: hud)

    frame = Image.new("RGB", (320, 180), (30, 20, 20))
    gate = Gate()
    calls = {"n": 0}

    def grab():
        calls["n"] += 1
        if calls["n"] == 1:
            gate.hold()
        return frame

    with app_for_test(
        foreground=lambda: True,
        grab=grab,
        clock=FakeClock(),
        output=RecordingOutput(),
    ) as app:
        try:
            sid = app.live.start()
            assert sid is not None
            assert gate.entered.wait(10)
            app.live.loop.request_stop_current(StopInfo("user"))  # 不 join：停止中
            app.hover._toggle_live()
            assert notes[-1] == "正在停止，请稍候", "被拒时不能说「已开启」"
            assert "已开启" not in notes[-1]
            gate.release.set()
            assert app.live.loop.join(session_id=sid)
            app.hover._toggle_live()
            assert notes[-1] == "采矿助手已开启｜按 F5 关闭"
            app.live.stop()
        finally:
            gate.release.set()
