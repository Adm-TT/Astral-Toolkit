"""导航：右上角调试信息、定位、路标、城内 / 空间站 / 光环带路线、导航记号、游戏日志（从 test_tools.py 拆出，CL-C3）"""

import pytest
from datetime import datetime
from datetime import timezone
from astral_toolkit.ocr import OcrToken
import time
from astral_toolkit.update import shops
from astral_toolkit.navigation import position
from tests.tools_helpers import _shops_db


def _nav_db(monkeypatch, tmp_path):
    """城里导航的用例（批 2 起城市地点 / 城外设施 / 空间站电梯走游戏数据层）：tmp_path 里写好的这几份源，
    加上真实星图（有就带上，以前这些用例也读真实星图），建成临时库；改了源再调一次就重建"""
    from astral_toolkit.core import paths

    real = [paths.DATA / f for f in ("starmap.json", "starmap_fixes.json")]
    mine = [
        tmp_path / f
        for f in ("city_places.json", "place_amenities.json", "station_lifts.json")
    ]
    _shops_db(
        monkeypatch,
        tmp_path,
        {"fmt": shops.FMT, "fetched": 0, "items": {}, "rows": []},
        copy=[p for p in real + mine if p.exists()],
    )


def test_displayinfo_parse():
    """游戏右上角 r_DisplayInfo 的文字（取自你 2026-10-20 新巴贝奇医院的截图）"""
    from astral_toolkit.navigation.displayinfo import parse

    lines = [
        "Zone: ObjectContainer-Ground Lobby Pos: -4.61m 74.93m 11.71m",
        "Zone: OOC_Stanton_4_Microtech Pos: 520.9152km 410.2893km 744.0843km",
        "Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
        "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km",
        "Current player location : Hospital Stanton4 NewBabbage (L2 : Stanton4 NewBabbage)",
        "Planet: OOC_Stanton_4_Microtech (Load Complete)",
    ]
    d = parse(lines)
    assert all(
        abs(a - b) < 0.01
        for a, b in zip(d["global"], (22462326485.3, 37186368633.8, 744084.3))
    )
    assert d["local"] == (520.9152, 410.2893, 744.0843) and "Microtech" in d["zone"]
    assert (
        d["location"].startswith("Hospital Stanton4 NewBabbage")
        and "Microtech" in d["planet"]
    )
    bad = list(lines)
    bad[3] = (
        "Zone: Root Pos: 22462326.4853km 37186868.6338km 744.0843km"  # OCR 认错一位：两行对不上就不用
    )
    assert parse(bad)["global"] is None
    assert parse(["纯音乐，请欣赏"])["global"] is None


def test_displayinfo_feeds_locate(monkeypatch):
    from astral_toolkit.navigation import navigate
    from astral_toolkit.navigation.displayinfo import parse

    if not navigate.CACHE.exists():
        import pytest

        pytest.skip("没有星图数据")
    g = parse(["Zone: SolarSystem_1 Pos: 22462326.4853km 37186368.6338km 744.0843km"])[
        "global"
    ]
    monkeypatch.setattr(navigate, "_remember", lambda *a, **k: None)
    here = navigate.locate(g)
    assert here["body"] == "microTech" or "icro" in here["body"]


def test_displayinfo_local_beats_rotation_math():
    from astral_toolkit.navigation import navigate

    if not navigate.CACHE.exists():
        import pytest

        pytest.skip("没有星图数据")
    assert navigate.zone_body("OOC Stanton 4 Microtech") == "Microtech"
    assert navigate.zone_body("OOC Stanton 2b Daymar") == "Daymar"
    navigate_remember = navigate._remember
    navigate._remember = lambda *a, **k: None
    navigate._offsets.clear()
    g = (22462326485.3, 37186368633.8, 744084.3)
    try:
        ref = navigate.locate(g)
        assert ref["src"] == "推算"
        near = (ref["x"] + 0.1, ref["y"] - 0.1, ref["z"])
        h = navigate.locate(g, local=near, zone="OOC Stanton 4 Microtech")
        assert (h["x"], h["y"]) == near[:2] and h[
            "src"
        ] == "游戏"  # 游戏给的、和推算接近：用游戏的
        h = navigate.locate(
            g, local=(520.9, 310.2, 744.1), zone="OOC Stanton 4 Microtech"
        )
        # OCR 认错一位、差太远：不用；用「推算 + 刚才记下的偏差」，位置和上一次一样，不会跳回推算的
        assert (
            abs(h["x"] - near[0]) < 0.01
            and abs(h["y"] - near[1]) < 0.01
            and h["src"] == "推算+偏差"
        )
        h = navigate.locate(
            g, local=near, zone="OOC Stanton 4 Microtech", local_ok=False
        )  # 和 CamPos 对不上
        assert h["src"] == "推算+偏差"
        assert abs(ref["height_m"] - 396) < 20  # 游戏显示 Altitude 396 m
    finally:
        navigate._remember = navigate_remember
        navigate._offsets.clear()


def test_log_place_is_specific(monkeypatch):
    """顶部「位置」要显示具体地点（新巴贝奇），不是星球（微科星）"""

    zh = {
        "newbabbage": "新巴贝奇",
        "arcl1wideforeststation": "弧 L1 广袤森林站",
        "checkmate": "死局空间站",
    }

    def place_zh(key="", prefix=None):  # 代替查库的 places_zh（批 2 起走游戏数据层）
        if prefix is not None:
            keys = sorted((k for k in zh if k.startswith(prefix)), key=len)
            return zh[keys[0]] if keys else None
        return zh.get(key)

    monkeypatch.setattr(position, "_place_zh", place_zh)
    monkeypatch.setattr(
        position, "_station_at", lambda i: "Checkmate Station" if i == "P2_L4" else ""
    )
    position._place_name.cache_clear()
    assert position.place_name("Stanton4_NewBabbage") == "新巴贝奇"
    assert position.place_name("RR_ARC_L1") == "弧 L1 广袤森林站"
    assert position.place_name("RR_P2_L4") == "死局空间站"
    assert position.place_name("Stanton1_SomeNewPlace") == "Some New Place"
    position._place_name.cache_clear()


def test_displayinfo_real_ocr_lines():
    """你电脑上 RapidOCR 读你截图右上角的真实结果（S 认成 5、O 认成 0）"""
    from astral_toolkit.navigation.displayinfo import parse

    d = parse(
        [
            "Zone:0bjectcontainer-Ground_Lobby Pos:-4.6lm 74.93m 11.71m",
            "Zone: 00c_Stanton_4_Microtech Pos: 520.9152km 419.2893km 744.0843km",
            "Zone: 5olarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
            "Currentplayer location :HospitalStanton4 NewBabbage(LZ:Stanton4 NewBabbage)",
            "Planet:ooc_Stanton_4_Microtech(Load Complete)",
        ]
    )
    assert d["global"] and abs(d["global"][0] - 22462326485.3) < 1
    assert (
        d["local"] == (520.9152, 419.2893, 744.0843) and "NewBabbage" in d["location"]
    )


def test_displayinfo_1080p_root_line_noise():
    """1080p 玩家反馈（2026-10-30，F10 五次）：Root 那行字小常被认岔——Pos 认成 P0s、数字间多个点或减号。
    以前纠错会把 P0s 也当数字改成 P05，两行对不上就当没读到，导航一直提示「读不到位置」"""
    from astral_toolkit.navigation.displayinfo import parse, _fix_numbers

    sysl = (
        "Zone:SolarSystem 876187763260 Pos:-18930550.7051km -2610477.0938km 22.9634km"
    )
    d = parse(
        [sysl, "Zone:Ro0t P0s:-18930550.7051km -2610477.0938km 22.9634km"],
        need_both=True,
    )
    assert (
        d["global"] == (-18930550705.1, -2610477093.8, 22963.4)
        or max(
            abs(a - b)
            for a, b in zip(d["global"], (-18930550705.1, -2610477093.8, 22963.4))
        )
        < 1
    )
    sysl = (
        "Zone: SolarSystem 876187763260 Pos: -18930516.9195km -2610457.4010km 21.7491km"
    )
    d = parse(
        [sysl, "Zone:Ro0t Pos: -18930516.9195km -2610457.4010km.21.7491km"],
        need_both=True,
    )
    assert d["global"] and abs(d["global"][2] - 21749.1) < 0.5
    sysl = "Zone: SolarSystem_876187763260 Pos: -18930529.1194km -2610454.7742km -23.2650km"
    d = parse(
        [sysl, "Zone:Ro0tP0s:-18930529.1194km-2610454.7742km--23.2650km"],
        need_both=True,
    )
    assert d["global"] and abs(d["global"][2] + 23265.0) < 0.5
    d = parse(
        [sysl, "Zone:Ro0tP0s:-18930529.1194km-2610454.7742km.--23.2650km"],
        need_both=True,
    )  # 点号和双减号一起
    assert d["global"] and abs(d["global"][2] + 23265.0) < 0.5
    assert _fix_numbers("Zone:Ro0t P0s:-1.5km 2.0km 3.0km").startswith(
        "Zone:Ro0t P0s:"
    )  # 区域名和 Pos 不当数字改
    # 认错的那行和另一行对不上，照旧不收（保险不放松）
    d = parse(
        [
            "Zone:SolarSystem 1 Pos:-18930550.7051km -2610477.0938km 22.9634km",
            "Zone:Ro0t P0s:-18930550.7051km -2610477.0938km 23.9634km",
        ],
        need_both=True,
    )
    assert d["global"] is None


def test_reader_backoff_capped_while_navigating(monkeypatch):
    """导航开着时读不到，最多隔 max_gap 秒再试（以前最长一分钟，玩家看到的位置隔 40–90 秒才动一下）"""
    from astral_toolkit.navigation import displayinfo as D

    monkeypatch.setattr(
        D, "read", lambda allow_yield=True, diag=False: {**D.parse([]), "fast": False}
    )
    from astral_toolkit.system import showloc

    monkeypatch.setattr(showloc, "game_foreground", lambda: True)
    r = D.Reader(every=1.0)
    r.max_gap = 5.0
    for _ in range(30):
        r.next_at = 0
        r.poll(force=True)

    assert r.next_at - time.time() <= 5.0 + 0.5
    r2 = D.Reader(every=1.0)
    for _ in range(30):
        r2.next_at = 0
        r2.poll(force=True)
    assert r2.next_at - time.time() > 20  # 不导航时照旧慢慢退


def test_nav_tip_texts():
    """窗口状态和悬浮窗提示说法一致（审查 2026-10-30）：读得到不提示；8–30 秒前读到过有上次结果标暂停；
    刚开始没结果只说等待；更久 / 从没读到才教开调试信息"""
    from astral_toolkit.app.presenters.nav import nav_tip

    st, tip = nav_tip(True, 100.0, 101.0, True, "H")
    assert tip == "" and "实时" in st
    st, tip = nav_tip(False, 100.0, 110.0, True, "H")
    assert "r_DisplayInfo" not in st + tip and "暂停更新" in tip
    st, tip = nav_tip(False, 100.0, 110.0, False, "H")
    assert "上次结果" not in st + tip
    for last in (60.0, 0.0):
        st, tip = nav_tip(False, last, 100.0, True, "H")
        assert "r_DisplayInfo 2" in tip and st.startswith("H")


def test_display_label_lagrange_station():
    from astral_toolkit.navigation.position import display_label as d

    assert d("RR P2 L4 CLINIC(LZ:R P24)") == "死局空间站"
    assert d("RR P2 L4(LZ:RR P24)") == "死局空间站"
    assert d("RR_HUR_L2") == "赫 L2 坚贞梦想站"
    assert d("Hospital Stanton4 NewBabbage (L2 : Stanton4 NewBabbage)") == "新巴贝奇"


def test_status_keeps_displayinfo_place_when_reader_goes_stale():
    """切屏后右上角暂时读不到，位置还显示死局空间站，不跳回别的；游戏日志里有更新的地点才换。
    2026-10-26 起不导航也一直读右上角（实时位置）：右上角读到的比日志新就用右上角的"""
    from astral_toolkit import bootstrap
    from astral_toolkit.tasks import system as t_sys
    from tests.bootstrap_helpers import app_for_test

    with app_for_test() as app:
        import astral_toolkit.navigation.position as P

        sources = bootstrap.status_sources(app)
        old = P.current, P.from_log, app.pos.label, app.nav.target
        try:
            app.nav.target = {"n": "测试目标"}
            app.pos.reader.ok_at = 0  # 读取器已经不算「开着」
            app.pos.label = (time.time() - 20, "死局空间站")
            P.current = lambda *a, **k: {
                "label": "玛格达 附近",
                "age": 1.0,
                "sys": "Pyro",
            }
            P.from_log = lambda *a, **k: (time.time() - 3600, "死局空间站", {})
            assert t_sys.status(sources)["position"]["label"] == "死局空间站"
            P.current = lambda *a, **k: {
                "label": "鼠巢空间站",
                "age": 2.0,
                "sys": "Pyro",
            }  # 后来在别处开了库存
            P.from_log = lambda *a, **k: (time.time() - 2, "鼠巢空间站", {})
            assert t_sys.status(sources)["position"]["label"] == "鼠巢空间站"
            app.nav.target = None  # 不导航也一样：右上角刚读到的比日志新，用右上角的
            app.pos.label = (time.time(), "死局空间站")
            assert t_sys.status(sources)["position"]["label"] == "死局空间站"
        finally:
            P.current, P.from_log, app.pos.label, app.nav.target = old


def test_displayinfo_reads_only_needed_lines_after_first_time(monkeypatch):
    """右上角：第一次整块认、记下要用的几行在哪；之后只认这几行；认出来对不上就重新整块认"""
    from PIL import Image
    from astral_toolkit.navigation import displayinfo as D

    D._layout.update(at=0.0, boxes=None)
    T = lambda text, x, y: OcrToken(text, 90, (x, y, len(text) * 9, 20))  # noqa: E731
    lines = [
        "Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
        "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km",
        "Current player location : Hospital Stanton4 NewBabbage (LZ: Stanton4 NewBabbage)",
    ]
    full_calls, line_calls = [], []
    toks = [T("纯音乐，请欣赏", 10, 60)] + [
        T(t, 1740 - len(t) * 9, 20 + 40 * i) for i, t in enumerate(lines)
    ]
    monkeypatch.setattr(
        "astral_toolkit.ocr.recognize",
        lambda img, **k: full_calls.append(img.size) or toks,
    )
    answers = iter(lines + lines + ["乱码"] * 3)
    monkeypatch.setattr(
        "astral_toolkit.ocr.read_line",
        lambda img: line_calls.append(img.size) or (next(answers), 0.9),
    )
    img = Image.new("RGB", (2560, 1440))
    assert D.read(img)["global"] and len(full_calls) == 1 and not line_calls
    assert len(D._layout["boxes"]) == 3
    # 和 Root 同一行左边的「纯音乐」不算进 Root 那行
    assert all(b[0] > 100 for b in D._layout["boxes"])
    for _ in range(2):
        info = D.read(img)
        assert info["global"] and "NewBabbage" in info["location"]
    assert len(full_calls) == 1 and len(line_calls) == 6  # 后两次只认了那 3 行
    D.read(img)  # 认出来对不上：马上重新整块认
    assert len(full_calls) == 2
    D._layout.update(at=0.0, boxes=None)


def test_displayinfo_local_cross_checked_with_campos():
    """星球局部坐标和 CamPos Planet Zone（同一个位置，单位米）两行对得上才算可靠"""
    from astral_toolkit.navigation.displayinfo import parse

    base = [
        "Zone: OOC_Stanton_4_Microtech Pos: 520.9152km 419.2893km 744.0843km",
        "Zone: SolarSystem_862949775749 Pos: 22462326.4853km 37186368.6338km 744.0843km",
        "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km",
    ]
    ok = parse(base + ["CamP0s P1anet Zone: 520915.218755 419289.333861 744084.256923"])
    assert ok["local_ok"] is True and ok["campos"][0] == 520915.218755
    bad = parse(
        base + ["CamPos Planet Zone: 520915.218755 449289.333861 744084.256923"]
    )  # 认错一位
    assert bad["local_ok"] is False
    assert parse(base)["local_ok"] is None
    # 实测：快速读取时 5 被认成 s（52091s），数字里的 s/o/l 换回来
    fixed = parse(
        base + [" CamP06 Planet Zone: 52091s.218755 419289.333861 744084.256923"]
    )
    assert fixed["local_ok"] is True


def test_nav_bearing_is_steady_when_standing_still(monkeypatch, tmp_path):
    """站着不动：右上角那行有时认不出，位置也不在「游戏给的」和「推算的」之间来回跳，显示的方位不变"""
    from astral_toolkit.navigation import navigate as n
    import astral_toolkit.runtime.workers.navigation as nav_mod
    from astral_toolkit.app.presenters import nav as present_nav

    if not n.CACHE.exists():
        import pytest

        pytest.skip("没有星图数据")
    import copy

    monkeypatch.setattr(
        n, "CALIB", tmp_path / "rotation_calib.json"
    )  # locate(local_ok=True) 会校准自转相位：写临时文件
    calib0 = copy.deepcopy(n._calib)
    n._remember_orig, n._remember = n._remember, (lambda *a, **k: None)
    n._offsets.clear()
    try:
        g = (22462326485.3, 37186368633.8, 744084.3)
        ref = n.locate(g, when=1792500000.0)
        game = (ref["x"] + 0.8, ref["y"] - 0.6, ref["z"])  # 推算和游戏差将近 1 km
        target = {
            "b": ref["body"],
            "x": game[0] + 2.0,
            "y": game[1] + 1.2,
            "z": game[2],
            "n": "目标",
        }
        steady = nav_mod._Steady()
        shown = set()
        for i in range(12):
            local = None if i % 3 == 2 else game  # 每 3 次有 1 次没认出那一行
            h = n.locate(
                g,
                when=1792500000.0,
                local=local,
                zone="OOC Stanton 4 Microtech",
                local_ok=True if local else None,
            )
            shown.add(
                n.deg_text(
                    present_nav.ground_view_of(h, target, n.load(), steady)["bearing"]
                )
            )
        assert len(shown) == 1
    finally:
        n._remember = n._remember_orig
        n._offsets.clear()
        n._calib.clear()
        n._calib.update(calib0)  # 校准待定的读数不留给后面的测试


def test_bearing_text_and_deadband():
    from astral_toolkit.navigation import navigate as n
    import astral_toolkit.runtime.workers.navigation as nav_mod

    assert n.deg_text(359.6) == "000" and n.deg_text(5.2) == "005"
    st = nav_mod._Steady()
    assert (
        st(10.0) == 10.0
        and st(11.5) == 10.0
        and st(358.9) == 358.9
        and st(0.5) == 358.9
        and st(1.2) == 1.2
    )


def test_nav_uses_display_info_waypoints_use_showlocation():
    """导航实时方位只读右上角调试信息（不往游戏里打字）；自定义路标只用 /showlocation（2026-10-23 用户要求）"""
    import inspect
    from astral_toolkit.tasks import navigation as t_nav
    import astral_toolkit.runtime.workers.navigation as nav_mod

    run = "\n".join(
        inspect.getsource(fn)
        for fn in (
            nav_mod._NavWorker._first_tick,
            nav_mod._NavWorker._ground_tick,
            nav_mod._NavWorker._space_tick,
        )
    )
    assert (
        "showlocation(" not in run and "showloc import" not in run
    )  # 实时导航：读右上角，不往游戏里打字（读不到时只接玩家自己输的 /showlocation）
    src = inspect.getsource(t_nav.mark_here) + inspect.getsource(t_nav._save_here)
    assert (
        "showlocation" in src and "_pos.reader" not in src and "use_offset=False" in src
    )


def test_space_waypoint(monkeypatch, tmp_path):
    """太空里用当前位置新建路标：记星系坐标；导航给直线距离、先跳到哪、对准哪个标记"""
    import math  # noqa: E401, F401
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.tasks import (
        navigation as t_nav,
        system as t_sys,
    )
    from astral_toolkit.app import hud_state

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(n, "WAYPOINTS", tmp_path / "wp.json")
    # 尼克斯星系里一个拉格朗日点旁边 20 km 的太空（不在任何星球附近）
    lp = next(
        p
        for p in data["points"]
        if p["sys"] == "Nyx" and p["t"] in ("Lagrange Point", "Jumppoint")
    )
    g = (lp["x"] + 20_000, lp["y"], lp["z"])  # 米
    assert n.system_of(g, data) == "Nyx"
    # 窗口里点「用当前位置新建」：只认 /showlocation 的坐标——等剪贴板出现新坐标，不在星球上 → 太空路标
    clip = {"t": "随便什么"}
    monkeypatch.setattr(n, "read_clipboard", lambda: clip["t"])
    _v = lambda: type("H", (), {"set": lambda *a: None, "clear": lambda *a: None})()  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    import threading

    monkeypatch.setattr(
        threading,
        "Timer",
        lambda *a, **k: type("T", (), {"start": lambda self: None})(),
    )  # 悬浮窗短提示 6 秒后自己收起：别在补丁还原后建真悬浮窗
    monkeypatch.setattr(
        __import__("astral_toolkit.core.paths", fromlist=["log"]),
        "log",
        lambda name: tmp_path / name,
    )  # 真的写记录（写到临时目录），以前把记录函数换掉，没发现它和导航记录重名、一调用就报错
    from tests.bootstrap_helpers import app_for_test

    # RT-B7：tasks.* 要先绑定（存太空路标会问现在在哪个星系）
    with app_for_test() as app:
        r = t_nav.waypoint_add(app.nav_deps, name="气体云矿点", here=True)
        assert r["pending"] and "/showlocation" in r["message"]
        time.sleep(0.3)
        clip["t"] = f"Coordinates: x:{g[0]} y:{g[1]} z:{g[2]}"
        for _ in range(40):
            if any(w["n"] == "气体云矿点" for w in n.waypoints()):
                break
            time.sleep(0.1)
        rows = t_nav.waypoints()
        w = next(r for r in rows if r["name"] == "气体云矿点")
        assert w["space"] and w["system"] == "Nyx"
        # 搜得到，路线给最近的参照点
        hits, _ = n.search("气体云矿点")
        p = hits[0]
        assert n.is_space(p)
        plan = t_nav.nav_plan(t_nav._place_row(p)["key"])
        assert plan["space"] and plan["routes"][0]["direct"] < 25
        # 就在原地：到了
        assert n.space_guide(g, p, data)["arrived"]
        # 从参照点另一侧 300 km 飞过来：直线距离对、对准参照点（目标就在它旁边）夹角很小
        far = (lp["x"] - 300_000, lp["y"], lp["z"])
        s = n.space_guide(far, p, data)
        assert abs(s["direct"] - 320) < 0.5 and s["aim"]["angle"] < 5
        # 在别的星系：提示先跳过去
        other = next(b for b in data["bodies"].values() if b["sys"] != "Nyx")
        assert not n.space_guide((other["x"], other["y"], other["z"]), p, data)[
            "same_system"
        ]
        t_nav._HERE["name"] = None


def test_camdir_steering():
    """右上角 CamDir（俯仰 横滚 偏航）→ 机头要怎么转。用 2026-10-23 微科星轨道的真实截图核对过约定：
    CamDir 23 9 -142、Root Pos (22461632.7352, 37186362.6645, 799.5096) km，画面里地平线在中心略下方"""
    import math
    from astral_toolkit.navigation.displayinfo import parse
    from astral_toolkit.navigation import navigate as n

    assert parse(["CamDir: 23 9 -142 FOV: 70 Focal: 3.00"])["camdir"] == (23, 9, -142)
    assert parse(["CamD1r 12 -1 72 F0V: 60"])["camdir"] == (
        12,
        -1,
        72,
    )  # OCR 认错的字母也行
    assert (
        parse(["CamDir: 23 9 -1420 FOV: 70"])["camdir"] is None
    )  # 超出范围 = 认错数字
    # 基本方向：镜头不转时朝 +y
    assert n.steer_text(n.steer((0, 0, 0), (0, 0, 0), (0, 1000, 0))).startswith("✅")
    s = n.steer((0, 0, 0), (0, 0, 0), (1000, 1000, 0))
    assert (
        round(s["turn"]) == 45 and abs(s["pitch"]) < 1 and "右转 45°" in n.steer_text(s)
    )
    s = n.steer((0, 0, 0), (0, 0, 0), (0, 1000, -1000))
    assert round(s["pitch"]) == -45 and "低头 45°" in n.steer_text(s)
    assert "掉头" in n.steer_text(n.steer((0, 0, 0), (0, 0, 0), (-10, -1000, 0)))
    # 真实截图：微科星的地平线应该在机头下方约 3°（画面中心略下方）
    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    data = n.load()
    if "Microtech" not in data.get("bodies", {}):
        pytest.skip("没有星图数据")
    b = data["bodies"]["Microtech"]
    g = (22461632.7352e3, 37186362.6645e3, 799.5096e3)
    s = n.steer(g, (23, 9, -142), (b["x"], b["y"], b["z"]))
    limb = math.degrees(math.asin(b["r"] / math.dist(g, (b["x"], b["y"], b["z"]))))
    assert -8 < s["pitch"] + limb < 2


def test_mark_here_hotkey(monkeypatch, tmp_path):
    """游戏里按 F7：等玩家自己在聊天框输入 /showlocation（AT 不替你打字），用剪贴板里的坐标记路标（太空里记星系坐标）；不读右上角"""
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.system import showloc
    from astral_toolkit.tasks import (
        navigation as t_nav,
        system as t_sys,
    )
    from tests.bootstrap_helpers import app_for_test

    from astral_toolkit.app import hud_state
    import threading

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(n, "WAYPOINTS", tmp_path / "wp.json")
    lp = next(
        p
        for p in data["points"]
        if p["sys"] == "Stanton" and p["t"] == "Lagrange Point"
    )
    g = (lp["x"] + 5_000, lp["y"], lp["z"])
    monkeypatch.setattr(
        showloc, "showlocation", lambda log=None: (g, "Coordinates: ...")
    )
    monkeypatch.setattr(
        __import__("astral_toolkit.core.paths", fromlist=["log"]),
        "log",
        lambda name: tmp_path / name,
    )  # 真的写记录（写到临时目录），以前把记录函数换掉，没发现它和导航记录重名、一调用就报错
    shown = {}

    class H:
        def set(self, k, v, *rich):
            shown[k] = v

        def clear(self, k):
            shown.pop(k, None)

    _v = lambda: H()  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    monkeypatch.setattr(
        threading,
        "Timer",
        lambda *a, **k: type("T", (), {"start": lambda self: None})(),
    )
    with app_for_test() as app:
        monkeypatch.setattr(
            app.pos.reader,
            "poll",
            lambda force=False: (_ for _ in ()).throw(AssertionError("不该读右上角")),
        )
        out = t_nav.mark_here(app.nav_deps)
        assert (
            "error" not in out
            and "斯坦顿星系" in out["where"]
            and "已保存" in shown["路标"]
        )
        assert "已记下" in (tmp_path / "nav_log.txt").read_text(
            encoding="utf-8"
        )  # 记录真的写进去了
        wp = n.waypoints()[-1]
        assert n.is_space(wp) and wp["n"] == out["name"]
        # 点过「用当前位置新建」再按 F7：用那里填的名字
        t_nav._HERE.update(name="我的矿点", until=__import__("time").time() + 30)
        assert (
            t_nav.mark_here(app.nav_deps)["name"] == "我的矿点"
            and t_nav._HERE["name"] is None
        )
        # 60 秒内没等到玩家输入 /showlocation：悬浮窗说原因，不记
        monkeypatch.setattr(
            showloc,
            "showlocation",
            lambda log=None: (None, "60 秒内没等到 /showlocation"),
        )
        assert "error" in t_nav.mark_here(app.nav_deps) and "没等到" in shown["路标"]


def test_parse_showlocation_clip():
    from astral_toolkit.navigation.navigate import parse_clip

    assert parse_clip("Coordinates: x:-18930539540.1 y:-2610158765.2 z:295000.3") == (
        -18930539540.1,
        -2610158765.2,
        295000.3,
    )
    assert parse_clip("hello") is None and parse_clip("") is None


def test_camdir_sign_filter():
    """CamDir 漏了负号（-142 认成 142）：这次不用；转过 ±180° 是真的转了，照用"""
    from astral_toolkit.runtime.workers.navigation import _CamFilter

    f = _CamFilter()
    assert f.check((23, 9, -142)) == (23, 9, -142)
    assert f.check((23, 9, 142)) is None
    assert f.check((24, 9, -140)) == (24, 9, -140)
    f = _CamFilter()
    assert f.check((0, 0, 178)) and f.check((0, 0, -178)) == (0, 0, -178)


def test_where_now_ground_or_space(monkeypatch):
    """信号表外的值要知道玩家在地面还是太空：小行星带 → 太空；贴着星球 → 地面；高空 → 太空"""
    from astral_toolkit.tasks import navigation as t_nav
    from tests.bootstrap_helpers import app_for_test

    with app_for_test() as app:
        from astral_toolkit.navigation import navigate

        monkeypatch.setattr(t_nav, "_WHERE", {"t": 0.0, "v": None, "tried": 0.0})
        monkeypatch.setattr(
            app.pos,
            "latest",
            (
                time.time(),
                (1.0, 2.0, 3.0),
                {"location": "AsteroidCluster MiningBase Stanton2"},
            ),
        )
        assert t_nav._where_now(app.nav_deps) == "space"
        monkeypatch.setattr(t_nav, "_WHERE", {"t": 0.0, "v": None, "tried": 0.0})
        monkeypatch.setattr(
            app.pos,
            "latest",
            (time.time(), (1.0, 2.0, 3.0), {"location": "Planet Clio"}),
        )
        monkeypatch.setattr(
            navigate, "locate", lambda *a, **k: {"inside": True, "height_m": 2700}
        )
        assert t_nav._where_now(app.nav_deps) == "ground"
        monkeypatch.setattr(t_nav, "_WHERE", {"t": 0.0, "v": None, "tried": 0.0})
        monkeypatch.setattr(
            navigate, "locate", lambda *a, **k: {"inside": True, "height_m": 400_000}
        )
        assert t_nav._where_now(app.nav_deps) == "space"


def test_space_fix_navigation(monkeypatch, tmp_path):
    """太空路标一键定位：两次 /showlocation 之间直线飞 → 距离、近了多少、偏离角、多久到；不读右上角（2026-10-23 用户定的方案）"""
    import time as _t
    from astral_toolkit.core import paths
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.tasks import navigation as t_nav
    from tests.bootstrap_helpers import app_for_test

    from astral_toolkit.app import bus

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    from astral_toolkit.core import settings

    monkeypatch.setattr(
        settings,
        "load",
        lambda: {**settings.DEFAULTS, "nav_mode": "space", "fix_key": "F9"},
    )  # 玩家自己选了「手动定位」、绑了 F9
    lp = next(
        p
        for p in data["points"]
        if p["sys"] == "Stanton" and p["t"] == "Lagrange Point"
    )
    target = {
        "n": "太空矿点",
        "b": "@Stanton",
        "t": "Waypoint",
        "sys": "Stanton",
        "space": True,
        "qt": 0,
        "x": lp["x"] / 1000 + 50,
        "y": lp["y"] / 1000,
        "z": lp["z"] / 1000,
    }
    g0 = (lp["x"] + 10_000, lp["y"] + 5_000, lp["z"])
    g1 = (lp["x"] + 20_000, lp["y"] + 5_000, lp["z"])
    f = n.fix_guide([(0, g0), (10, g1)], target, data)
    assert (
        abs(f["direct"] - 30.41) < 0.05
        and f["delta"] < -9
        and f["deviation"] < 10
        and 25 < f["eta"] < 35
    )
    text = n.fix_text(f, "F9")
    assert "近了" in text and "✅ 偏离" in text and "秒到" in text
    assert "再按 F9" in n.fix_text(
        n.fix_guide([(0, g1)], target, data), "F9"
    )  # 只有一次：提示再飞一段
    back = n.fix_text(n.fix_guide([(0, g1), (5, g0)], target, data), "F9")
    assert "远了" in back and "❌" in back and "反方向" in back
    with app_for_test() as app:
        # 导航中：剪贴板出现新的 /showlocation 坐标就更新（自己在聊天框输也行），悬浮窗显示结果
        clip = {"t": "旧东西"}
        monkeypatch.setattr(n, "read_clipboard", lambda: clip["t"])
        hud = {}
        from astral_toolkit.tasks import system as t_sys
        from astral_toolkit.app import hud_state

        _v = lambda: type(  # noqa: E731
            "H",
            (),
            {
                "set": lambda self, k, v, *rich: hud.__setitem__(k, v),  # noqa: E731
                "clear": lambda self, k: hud.pop(k, None),
            },
        )()
        for _m in (t_nav, t_sys, hud_state):
            monkeypatch.setattr(_m, "_hud", _v)
        q = bus.subscribe()
        try:
            app.nav.start(target)
            _t.sleep(0.5)
            assert "F9" in hud.get("导航", "")
            clip["t"] = f"Coordinates: x:{g0[0]} y:{g0[1]} z:{g0[2]}"
            _t.sleep(0.8)
            clip["t"] = f"Coordinates: x:{g1[0]} y:{g1[1]} z:{g1[2]}"
            _t.sleep(0.8)
            assert (
                "偏离" in hud["导航"]
                and "近了" in hud["导航"]
                and len(app.nav.fixes) == 2
            )
        finally:
            app.nav.stop()
            bus.unsubscribe(q)
        # 没在导航太空路标时按 F9：提示，不打字
        import threading

        monkeypatch.setattr(
            threading,
            "Timer",
            lambda *a, **k: type("T", (), {"start": lambda self: None})(),
        )  # 「仅用于手动定位」5 秒后清提示：别在补丁还原后建真悬浮窗
        assert "error" in t_nav.fix_here(app.nav_deps)


def test_space_fix_dedupe_and_session(monkeypatch, tmp_path):
    """审查 1.6.23：剪贴板监听和 F9 拿到同一份坐标只算一次；导航结束 / 换目标后，旧的定位结果不再发出来"""
    import time as _t
    from astral_toolkit.core import paths, settings
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.tasks import (
        navigation as t_nav,
        system as t_sys,
    )
    from tests.bootstrap_helpers import app_for_test

    from astral_toolkit.app import bus
    from astral_toolkit.app import hud_state

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    data = n.load()
    if not data.get("points"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(
        settings, "load", lambda: {**settings.DEFAULTS, "nav_mode": "space"}
    )  # 手动定位
    monkeypatch.setattr(n, "read_clipboard", lambda: "")
    _v = lambda: type("H", (), {"set": lambda *a: None, "clear": lambda *a: None})()  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    lp = next(
        p
        for p in data["points"]
        if p["sys"] == "Stanton" and p["t"] == "Lagrange Point"
    )
    target = {
        "n": "太空矿点",
        "b": "@Stanton",
        "t": "Waypoint",
        "sys": "Stanton",
        "space": True,
        "qt": 0,
        "x": lp["x"] / 1000 + 50,
        "y": lp["y"] / 1000,
        "z": lp["z"] / 1000,
    }
    g0 = (lp["x"] + 10_000, lp["y"] + 5_000, lp["z"])
    g1 = (lp["x"] + 20_000, lp["y"] + 5_000, lp["z"])
    c0 = f"Coordinates: x:{g0[0]} y:{g0[1]} z:{g0[2]}"
    c1 = f"Coordinates: x:{g1[0]} y:{g1[1]} z:{g1[2]}"
    with app_for_test() as app:
        q = bus.subscribe()
        try:
            app.nav.start(target)
            sess = app.nav.session
            app.nav.add_fix(g0, c0, session=sess)
            _t.sleep(
                0.05
            )  # 两次定位要隔开时间才算得出多久到（Windows 时钟粒度粗，连着调用可能同一时刻）
            v = app.nav.add_fix(g1, c1, session=sess)  # 剪贴板监听先收到
            assert v["deviation"] is not None and v["eta"]
            again = app.nav.add_fix(g1, c1, session=sess)  # F9 返回同一份坐标
            assert (
                len(app.nav.fixes) == 2
                and again["deviation"] == v["deviation"]
                and again["eta"] == v["eta"]
            )
            assert (
                app.nav.add_fix(g1, None, session=sess)["delta"] == v["delta"]
            )  # 坐标一样也不重复记
            app.nav.start(target)  # 换导航：旧会话的结果作废
            assert (
                app.nav.add_fix(g0, "别的" + c0, session=sess) is None
                and app.nav.fixes == []
            )
            sess2 = app.nav.session
            app.nav.stop()
            while True:  # 清掉之前的消息
                try:
                    q.get_nowait()
                except Exception:
                    break
            assert app.nav.add_fix(g1, "再别的" + c1, session=sess2) is None
            assert app.nav.add_fix(g1, "再别的" + c1) is None  # 没在导航
            left = []
            while True:
                try:
                    left.append(q.get_nowait())
                except Exception:
                    break
            assert not any(
                isinstance(m, dict) and (m.get("data") or {}).get("active")
                for m in left
            )
        finally:
            app.nav.stop()
            bus.unsubscribe(q)


def test_nav_mode_switch(monkeypatch, tmp_path):
    """导航页的开关：星球上的路标可以切到太空导航（一键定位），太空路标只能用太空导航；正在导航就按新方式重新开始"""
    import json, time as _t  # noqa: E401, F401, F811
    from astral_toolkit.core import settings, paths
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.tasks import (
        navigation as t_nav,
        system as t_sys,
    )
    from tests.bootstrap_helpers import app_for_test

    from astral_toolkit.app import hud_state

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    data = n.load()
    if not data.get("bodies"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(n, "read_clipboard", lambda: "")
    store = {}
    monkeypatch.setattr(
        settings,
        "load",
        lambda: (
            {**settings.DEFAULTS, **store}
            if hasattr(settings, "DEFAULTS")
            else dict(store)
        ),
    )
    monkeypatch.setattr(settings, "update", lambda **kw: store.update(kw))
    _v = lambda: type("H", (), {"set": lambda *a: None, "clear": lambda *a: None})()  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    ground = {
        "n": "地面点",
        "b": "Daymar",
        "t": "Waypoint",
        "sys": "Stanton",
        "qt": 0,
        "x": 100.0,
        "y": 50.0,
        "z": 0.0,
    }
    space = {
        "n": "太空点",
        "b": "@Stanton",
        "t": "Waypoint",
        "sys": "Stanton",
        "space": True,
        "qt": 0,
        "x": 1.0,
        "y": 2.0,
        "z": 3.0,
    }
    with app_for_test() as app:
        try:
            assert (
                app.nav.use_space(ground) is False and app.nav.use_space(space) is False
            )  # 2026-10-27：太空路标默认也实时读右上角
            app.nav.start(ground)
            assert app.nav.space_mode is False
            r = t_nav.nav_mode(app.nav_deps, "space")
            assert (
                r["space"] is True and app.nav.space_mode and app.nav.target is ground
            )
            t_nav.nav_mode(app.nav_deps, "ground")
            assert app.nav.space_mode is False
            app.nav.start(space)
            t_nav.nav_mode(app.nav_deps, "ground")
            assert app.nav.space_mode is False  # 太空路标也能用实时定位
            assert "error" in t_nav.nav_mode(app.nav_deps, "别的")
        finally:
            app.nav.stop()
    # 星球上的路标用一键定位：在星球自转坐标里算（目标跟着星球转，不能当成星系里的固定点）
    b = data["bodies"]["Daymar"]  # noqa: F841
    t0 = 1_800_000_000.0
    tgt_g = n.target_global(ground, data, t0 + 10)
    near = tuple(v + 1000 for v in tgt_g)  # 离目标约 1.7 km
    f = n.fix_guide([(t0 + 10, near)], ground, data)
    assert f["same_system"] and 1.5 < f["direct"] < 2.0


def test_halo_routes_match_scminer():
    """小行星带导航：对照 SCMiner 的 Aaron Halo Flight Computer（ARC-L1 出发，第 5 带）
    SCMiner：CRU-L3 12.7 Gm/389 Mm、CRU-L4 14.3/345、Hurston 13.5/192、Crusader 33.2/177、CRU-L5 39.5/151"""
    import math

    from astral_toolkit.navigation import halo
    from astral_toolkit.navigation import navigate as n

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    pts = halo.points()
    if "ARC-L1" not in pts:
        pytest.skip("没有星图数据")
    want = {
        "CRU-L3": (12.7, 389),
        "CRU-L4": (14.3, 345),
        "Hurston": (13.5, 192),
        "Crusader": (33.2, 177),
        "CRU-L5": (39.5, 151),
    }
    rows = {r["to"]: r for r in halo.routes("ARC-L1", 5, 103, pts)}
    for to, (gm, mm) in want.items():
        r = rows[to]
        assert abs(r["dropout"] - gm) < 0.06, (to, r["dropout"])
        assert abs(r["margin"] - mm) / mm < 0.05, (to, r["margin"])
        assert r["late"] < r["dropout"] < r["early"]
    assert abs(rows["CRU-L4"]["window"] - 3.3) < 0.2  # 345 Mm ÷ 103 Mm/s
    assert rows["CRU-L4"]["wide"] and not rows["Hurston"]["wide"]
    assert (
        rows["CRU-L5"]["blocked"] and not rows["CRU-L4"]["blocked"]
    )  # 穿过恒星的标出来
    ms = [r["margin"] for r in halo.routes("ARC-L1", 5, 103, pts)]
    assert ms == sorted(ms, reverse=True)
    assert "microTech" in pts and halo.route("ARC-L1", "ARC-L1", 5, 103, pts) is None
    t = halo.plan_text(rows["CRU-L4"])
    assert (
        "14.3 Gm" in t and "按 U" in t and "14.5–14.1 Gm" in t and "秒" not in t
    )  # 挖矿用：0.1 Gm、不讲反应秒数
    try:
        halo.band(11)
        assert False
    except ValueError:
        pass
    # 断开后核对：离恒星多远、在不在带里、往哪飞
    assert halo.where((20.3e9, 0, 0))["band"] == 5
    assert halo.where_text(halo.where((20.3e9, 0, 0)), 5).startswith("✅")
    t = halo.where_text(halo.where((20.0e9, 0, 0)), 5)
    assert "第3带" in t and "往外" in t and "230" in t
    assert "往里" in halo.where_text(halo.where((21.6e9, 0, 0)), 5)
    assert halo.where_text(halo.where((10e9, 0, 0)), 5).startswith("❌")
    # 量子速度用游戏数据（以前抄 SCMiner 的慢了两三倍）；老写法「Voyage (S2)」尺寸改过了，按名字认
    assert halo.qd_speed("Atlas (S1)") == 259 and halo.qd_speed("odyssey") == 238
    assert halo.qd_speed("Voyage (S2)") == 208 and halo.qd_speed("Goliath (S1)") == 219
    assert "19.60–21.39 Gm" in halo.where_text(halo.where((10e9, 0, 0)), 5)
    # 断开后核对：比方案的断开点多飞 / 少飞多少（老大实飞量滑多远）
    p = rows["CRU-L4"]
    B = pts["CRU-L4"]
    A = pts["ARC-L1"]
    L = math.dist(A, B)
    stop = [(B[i] + (A[i] - B[i]) * (p["dropout"] - 0.17) / L) * 1e9 for i in range(3)]
    o = halo.overshoot(p, stop, pts)
    assert o and abs(o["over"] - 170) <= 1 and "多飞了 170 Mm" in o["text"]
    stop = [(B[i] + (A[i] - B[i]) * (p["dropout"] + 0.05) / L) * 1e9 for i in range(3)]
    assert "少飞了 50 Mm" in halo.overshoot(p, stop, pts)["text"]
    assert (
        halo.overshoot({"text": "方案", "band": 5}, stop, pts) is None
    )  # 方案里没有目标


def test_halo_services(monkeypatch, tmp_path):
    """小行星带页的接口：选项、路线、挂到悬浮窗；挂着方案时按 F9 或自己输 /showlocation 核对在不在带里（复审 1.6.24 补的情形）"""
    import time as _t
    from astral_toolkit.core import paths, settings
    from astral_toolkit.navigation import halo
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.system import showloc
    from astral_toolkit.tasks import navigation as t_nav
    from tests.bootstrap_helpers import app_for_test

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    if "ARC-L1" not in halo.points():
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    store = dict(settings.DEFAULTS)
    monkeypatch.setattr(settings, "load", lambda: dict(store))
    monkeypatch.setattr(
        settings, "update", lambda **kw: (store.update(kw), dict(store))[1]
    )
    clip = {
        "t": "Coordinates: x:20300000000 y:0 z:0"
    }  # 挂上之前就在剪贴板里的旧坐标：不算
    monkeypatch.setattr(n, "read_clipboard", lambda: clip["t"])
    hud = {}
    from astral_toolkit.tasks import system as t_sys
    from astral_toolkit.app import hud_state

    _v = lambda: type(  # noqa: E731
        "H",
        (),
        {
            "set": lambda self, k, v, *rich: hud.__setitem__(k, v),  # noqa: E731
            "clear": lambda self, k: hud.pop(k, None),
        },
    )()
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    with app_for_test() as app:
        o = t_nav.halo_options()
        assert (
            len(o["bands"]) == 10
            and o["bands"][4]["ores"][0] == "量子矿物"
            and o["qd"] == "Atlas (S1)"
        )
        assert any(p["key"] == "ARC-L1" for p in o["points"])
        r = t_nav.halo_routes(frm="ARC-L1", band=5, qd="Odyssey (S3)")
        # 存着老写法「Odyssey (S3)」：尺寸改过了，按名字认出游戏数据的速度
        assert store["halo_qd"] == "Odyssey (S3)" and r["speed"] == 238 and r["rows"]
        assert "error" in t_nav.halo_routes(
            frm="ARC-L1", band=0
        ) and "error" in t_nav.halo_routes(frm="没有", band=5)
        assert "error" in t_nav.halo_pin(
            app.nav_deps, frm="ARC-L1", to="ARC-L1", band=5
        )
        app.nav.target = None
        try:
            p = t_nav.halo_pin(app.nav_deps, frm="ARC-L1", to="CRU-L4", band=5)
            assert (
                "14.3 Gm" in hud["小行星带"]
                and "自动核对" in hud["小行星带"]
                and t_nav._HALO["plan"] is p
            )
            _t.sleep(0.5)
            assert "✅" not in hud["小行星带"]  # 旧坐标没被当成新定位
            # 自己在聊天框输 /showlocation：剪贴板出现新坐标就核对
            clip["t"] = "Coordinates: x:20000000000 y:0 z:0"
            _t.sleep(0.8)
            assert "第3带" in hud["小行星带"] and "往外" in hud["小行星带"]
            assert "比方案的断开点" in hud["小行星带"]  # 核对时说出多飞 / 少飞多少
            # F9：拿到的还是这一份坐标（监听已经处理过）→ 不重复算，结果一样
            monkeypatch.setattr(
                showloc,
                "showlocation",
                lambda log=None: ((20.0e9, 0.0, 0.0), clip["t"]),
            )
            assert t_nav.fix_here(app.nav_deps)["band"] == 3
            monkeypatch.setattr(
                showloc,
                "showlocation",
                lambda log=None: (
                    (20.3e9, 0.0, 0.0),
                    "Coordinates: x:20300000001 y:0 z:0",
                ),
            )
            assert t_nav.fix_here(app.nav_deps)["band"] == 5 and "✅" in hud["小行星带"]
            monkeypatch.setattr(
                showloc, "showlocation", lambda log=None: (None, "游戏没在前台")
            )
            assert (
                "error" in t_nav.fix_here(app.nav_deps)
                and "定位失败" in hud["小行星带"]
            )

            # F9 等坐标期间方案被取下：结果作废，不报错
            def slow(log=None):
                t_nav.halo_unpin()
                return None, "超时"

            monkeypatch.setattr(showloc, "showlocation", slow)
            assert t_nav.fix_here(app.nav_deps) == {"error": "超时"}
            t_nav.halo_pin(app.nav_deps, frm="ARC-L1", to="CRU-L4", band=5)

            def swap(log=None):
                t_nav.halo_pin(app.nav_deps, frm="ARC-L1", to="CRU-L3", band=5)
                return (20.3e9, 0.0, 0.0), "Coordinates: x:20300000002 y:0 z:0"

            monkeypatch.setattr(showloc, "showlocation", swap)
            assert "error" in t_nav.fix_here(app.nav_deps)  # 换了方案：旧的这次不算
        finally:
            t_nav.halo_unpin()
        assert "小行星带" not in hud and t_nav._HALO["plan"] is None
        logged = (tmp_path / "nav_log.txt").read_text(encoding="utf-8").splitlines()
        assert any(
            "比方案的断开点" in x for x in logged
        )  # 核对多出来的那一行记进导航日志
        assert all(x[:4].isdigit() for x in logged)  # 而且不拆成两行：每行都以日期开头
        clip["t"] = "Coordinates: x:20100000000 y:0 z:0"
        _t.sleep(0.5)
        assert "小行星带" not in hud  # 取下后监听停了
        import threading

        monkeypatch.setattr(
            threading,
            "Timer",
            lambda *a, **k: type("T", (), {"start": lambda self: None})(),
        )  # 「仅用于手动定位」5 秒后清提示：别在补丁还原后建真悬浮窗
        assert "error" in t_nav.fix_here(app.nav_deps)  # 什么都没挂：只提示，不打字


def test_halo_where_edges():
    """判带用没四舍五入的半径：离内边界还差 400 km 不能说已经在带里"""
    from astral_toolkit.navigation import halo

    w = halo.where((20.2296e9, 0, 0))
    assert (
        w["band"] is None
        and halo.where_text(w, 5).startswith("⚠️")
        and "km" in halo.where_text(w, 5)
    )
    w = halo.where((20.4104e9, 0, 0))
    assert (
        w["band"] == 6
        and halo.where_text(w, 5).startswith("⚠️")
        and "往里" in halo.where_text(w, 5)
    )
    assert halo.where_text(halo.where((20.2300001e9, 0, 0)), 5).startswith("✅")


def test_waypoint_from_pasted_showlocation(monkeypatch, tmp_path):
    """路标页粘贴 /showlocation 的输出：先预览认出星球 / 经纬度，再起名保存（2026-10-23 用户要求，取代填经纬度）"""
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.core import paths
    from astral_toolkit.tasks import (
        navigation as t_nav,
        system as t_sys,
    )
    from astral_toolkit.app import hud_state

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    data = n.load()
    if not data.get("bodies"):
        pytest.skip("没有星图数据")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(n, "WAYPOINTS", tmp_path / "wp.json", raising=False)
    saved = []
    monkeypatch.setattr(
        n,
        "add_waypoint",
        lambda name, body, local: saved.append(("ground", name, body)),
    )
    monkeypatch.setattr(
        n,
        "add_space_waypoint",
        lambda name, system, g: saved.append(("space", name, system)),
    )
    monkeypatch.setattr(t_nav, "waypoints", lambda: [])
    _v = lambda: type("H", (), {"set": lambda *a: None, "clear": lambda *a: None})()  # noqa: E731
    for _m in (t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    b = data["bodies"]["Daymar"]  # noqa: F841
    g = (
        n.target_global(
            {"b": "Daymar", "x": 10.0, "y": 20.0, "z": 0.5, "t": "Waypoint"},
            data,
            1_800_000_000.0,
        )
        if hasattr(n, "target_global")
        else None
    )
    from tests.bootstrap_helpers import app_for_test

    # RT-B7：tasks.navigation 要先绑定（预览会看现在的位置线索）
    with app_for_test() as app:
        assert "error" in t_nav.waypoint_preview(app.nav_deps, text="随便一句话")
        assert "error" in t_nav.waypoint_from_text(
            app.nav_deps, name="x", text="没有坐标"
        )
        assert "error" in t_nav.waypoint_from_text(
            app.nav_deps, name="", text="Coordinates: x:1 y:2 z:3"
        )
        lp = next(
            p
            for p in data["points"]
            if p["sys"] == "Stanton" and p["t"] == "Lagrange Point"
        )
        txt = f"Coordinates: x:{lp['x'] + 5000} y:{lp['y']} z:{lp['z']}"
        pv = t_nav.waypoint_preview(app.nav_deps, text=txt)
        assert pv["ok"] and pv["space"] and "Stanton" in pv["body"]
        r = t_nav.waypoint_from_text(app.nav_deps, name="太空点", text=txt)
        assert saved[-1] == ("space", "太空点", "Stanton") and "太空" in r["desc"]
        if g:
            txt = f"Coordinates: x:{g[0]} y:{g[1]} z:{g[2]}"
            pv = t_nav.waypoint_preview(app.nav_deps, text=txt)
            assert (
                pv["ok"]
                and not pv["space"]
                and pv["body"] == "Daymar"
                and "戴玛尔" in pv["desc"]
            )
            t_nav.waypoint_from_text(app.nav_deps, name="地面点", text=txt)
            assert saved[-1] == ("ground", "地面点", "Daymar")


def test_pyro_place_names_from_localization():
    """2026-10-27 用户反馈：派罗很多空间站、星球显示成 PYR4-L1 这种代号。汉化包里都有正式名：
    有站的点用站名（RR_P1_L2 → 焰联-远程站-1-2），空点用点本身的叫法（派1 PYR1 L1）；星球、跳跃点也一样"""
    from astral_toolkit.navigation import position as P, navigate as n

    if not P.ini_name("RR_P2_L4"):
        pytest.skip("没有汉化包")
    assert P.place_name("RR_P2_L4") == "死局空间站"
    assert P.place_name("RR_P1_L2") == "焰联-远程站-1-2"
    assert (
        P.place_name("RR_P3") == "轨道讣闻站" and P.place_name("RR_P6") == "废墟空间站"
    )
    assert P.place_name("RR_P1_L1") == "派1 PYR1 L1"
    assert P.display_label("RR_P3_Clinic") == "轨道讣闻站"
    data = (
        n.load() if n.CACHE.exists() else {}
    )  # 没有星图：只测上面汉化包的部分，不联网下载
    if data.get("points"):
        labels = [
            n.label(p)
            for p in data["points"]
            if p["sys"] in ("Pyro", "Stanton") and p["t"] != "AsteroidBelt"
        ]
        assert all("（" in x for x in labels), [x for x in labels if "（" not in x]
        assert P.display_label("Pyro5d") == "法伊罗"


def test_poi_rule_names():
    """洞穴、前哨这类社区起的名字（汉化包里没有）按规则翻，编号原样保留"""
    from astral_toolkit.navigation.navigate import rule_zh

    assert rule_zh("Rock Cave #12, Fauna") == "岩石洞穴 #12（有动物）"
    assert (
        rule_zh("Sand Cave #015 / Derelict Outpost #023")
        == "沙地洞穴 #015 / 废弃前哨站 #023"
    )
    assert rule_zh("RL_Pyro3_col_m_drlct_otpst_occ_001") == "废弃前哨站（有人）001"
    assert rule_zh("Caterpillar Derelict 03 S1") == "毛虫残骸 03 S1"
    assert rule_zh("HDRSO-Bersch") == ""


def test_showlocation_keys_freed(monkeypatch, tmp_path):
    """2026-10-27 用户定：/showlocation 只在必要时用，「记录路标」「一键定位」默认不绑；老玩家存着的也清一次（之后自己绑的不再动）"""
    import json  # noqa: F811
    from astral_toolkit.core import settings
    from astral_toolkit.tasks import navigation as t_nav, system as t_sys

    f = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "FILE", f)
    assert settings.DEFAULTS["mark_key"] == "" and settings.DEFAULTS["fix_key"] == ""
    f.write_text(
        json.dumps(
            {
                "agreed": True,
                "mark_key": "F7",
                "fix_key": "F9",
                "nav_mode": "space",
            }
        ),
        encoding="utf-8",
    )
    cfg = settings.load()
    assert (
        cfg["mark_key"] == ""
        and cfg["fix_key"] == ""
        and cfg["nav_mode"] == "auto"
        and cfg["keys_v5"]
    )
    settings.update(fix_key="F11")
    assert settings.load()["fix_key"] == "F11"  # 清过一次，后来自己绑的不动
    vals = {n: k for k, _, n in t_sys._hotkey_values({**settings.DEFAULTS})}
    assert (
        vals["mark_key"] == ""
        and vals["fix_key"] == ""
        and vals["trade_capture_key"] == "F8"
    )
    monkeypatch.setattr(settings, "load", lambda: dict(settings.DEFAULTS))
    assert t_nav.fix_key_hint() == ("", "在聊天框输入 /showlocation 定位")


def test_fix_key_hint_uses_shared_hotkey_table(monkeypatch):
    """一键定位的撞键提示和设置页用同一张热键表。"""
    from astral_toolkit.core import settings
    from astral_toolkit.tasks import navigation as t_nav
    from astral_toolkit.tasks.system import settings as t_set

    assert t_nav.hotkey_conflicts is t_set.hotkey_conflicts
    assert not hasattr(t_nav, "HOTKEYS")
    assert not hasattr(t_nav, "_hotkey_values")

    monkeypatch.setattr(
        settings, "load", lambda: {**settings.DEFAULTS, "fix_key": "F8"}
    )
    assert t_nav.fix_key_hint() == (
        "F8",
        (
            "F8 同时用于「物品识别」和「一键定位」，按下只执行「物品识别」："
            "需在设置页更换「一键定位」的按键，或在聊天框输入 /showlocation"
        ),
    )


def test_nav_marker_projection():
    """导航记号（2026-10-27）：目标投到屏幕上的位置；画面外贴边画箭头；不盖右上角调试信息；记号和瞄准环能画出来"""
    import math
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.app import overlay as o
    from astral_toolkit.navigation.displayinfo import parse, REGION

    assert parse(["CamDir: 23 9 -142 FOV: 78 Focal: 0.10"])["fov"] == 78
    assert parse(["CamDir: 23 9 -142 FOV: 999"])["fov"] is None
    W, H, cam = 2560, 1440, (0, 0, 0)  # 镜头不转：朝 +y、头顶 +z
    p = n.project((0, 0, 0), cam, 78, (0, 1000, 0), W, H)
    assert (
        p["on"]
        and abs(p["x"] - W / 2) < 0.5
        and abs(p["y"] - H / 2) < 0.5
        and p["off"] < 0.01
    )
    p = n.project((0, 0, 0), cam, 78, (100, 1000, 0), W, H)
    assert p["on"] and p["x"] > W / 2 and abs(p["y"] - H / 2) < 0.5  # 右边
    up = math.tan(math.radians(39)) * 1000  # 正好在上边缘（上下视角 78°）
    p = n.project((0, 0, 0), cam, 78, (0, 1000, up * 0.999), W, H)
    assert p["on"] and p["y"] < 2
    p = n.project((0, 0, 0), cam, 78, (1000, 10, 0), W, H)
    assert (
        not p["on"] and not p["behind"] and abs(p["angle"]) < 1
    )  # 画面右边外面：箭头朝右
    x, y = o.edge_point(p["angle"], W, H, 70)
    assert abs(x - (W - 70)) < 1 and abs(y - H / 2) < 1
    p = n.project((0, 0, 0), cam, 78, (0, -1000, 0), W, H)
    assert p["behind"] and not p["on"] and abs(p["off"] - 180) < 0.1
    assert (
        n.dist_text(512) == "512 m"
        and n.dist_text(12_345) == "12.3 km"
        and n.dist_text(3.2e9) == "3.2 Gm"
    )
    # 不盖右上角那块
    x, y = o.avoid_box(W * 0.8, 10, 100, 60, W, H, REGION)
    assert y >= REGION[3] * H
    img, (ax, ay) = o.marker_image({"on": True, "label": "12.3 km"})
    assert img.width > 40 and 0 < ax < img.width
    img, _ = o.marker_image({"on": False, "angle": 135, "label": "1,234 km"})
    assert img.getbbox()
    assert (
        o.ring_image({"off": 30, "angle": 45}).getbbox()
        and o.ring_image({"off": 170, "angle": -90, "behind": True}).getbbox()
    )


def test_game_events_from_log(tmp_path):
    """游戏日志事件（2026-10-27，按 4.10.2 的真实日志行）：选量子目标、量子到达、管辖区、禁火区、监管区域、重生；
    只读打开以后新写的部分；游戏重开（日志变小）从头读"""
    from astral_toolkit.system.gamelog import GameEvents, EventTail

    L = [
        "<2026-10-24T10:46:36.173Z> [Notice] <Player Selected Quantum Target - Local> [ItemNavigation][CL][40004] | NOT AUTH | "
        "CRUS_Spirit_A1_899163362014[899163362014]|CSCItemNavigation::OnPlayerSelectedQuantumTarget|Player has selected point "
        "ab_collector_gas_Stanton4 as their destination, routing locally [Team_CGP4][QuantumTravel]",
        "<2026-10-24T10:47:40.133Z> [Notice] <Quantum Drive Arrived - Arrived at Final Destination> [ItemNavigation][CL][40004] | "
        "NOT AUTH | CRUS_Spirit_A1_899163362014[899163362014]|CSCItemNavigation::OnQuantumDriveArrived|Quantum Drive has arrived "
        "at final destination [Team_CGP4][QuantumTravel]",
        '<2026-10-26T14:53:31.492Z> [Notice] <SHUDEvent_OnNotification> Added notification "正在进入禁火区 - 禁止一切战斗行为: " [1] to queue.',
        '<2026-10-26T14:53:32.492Z> [Notice] <SHUDEvent_OnNotification> Added notification "已进入 微科公司 管辖区: " [1] to queue.',
        '<2026-10-26T14:53:33.492Z> [Notice] <SHUDEvent_OnNotification> Added notification "已离开监管区域: " [1] to queue.',
        '<2026-10-26T14:53:34.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "合约共享：RSI 探索月" [1] to queue.',
        "<2026-10-26T14:55:00.000Z> [CSessionManager::OnClientSpawned] Spawned!",
    ]
    g = GameEvents()
    kinds = [e[1:] for line in L for e in g.feed(line)]
    assert kinds == [
        ("qt_target", "ab_collector_gas_Stanton4"),
        ("qt_arrived", True),
        ("armistice", True),
        ("jurisdiction", "微科公司"),
        ("monitored", False),
        ("spawn", True),
    ]
    assert g.last["jurisdiction"][1] == "微科公司"
    log = tmp_path / "Game.log"
    log.write_text(L[0] + "\n", encoding="utf-8")
    tail = EventTail(log)
    assert tail.poll() == []  # 打开前的旧事件不算
    with open(log, "a", encoding="utf-8") as f:
        f.write(L[1] + "\n" + L[3][:40])  # 半行：等写完
    assert [e[1] for e in tail.poll()] == ["qt_arrived"]
    with open(log, "a", encoding="utf-8") as f:
        f.write(L[3][40:] + "\n")
    assert [e[1] for e in tail.poll()] == ["jurisdiction"]
    log.write_text(L[1] + "\n", encoding="utf-8")  # 游戏重开：新日志更短
    assert [e[1] for e in tail.poll()] == ["qt_arrived"]


def test_city_nav(monkeypatch, tmp_path):
    """城内导航：读 city_places.json（坏行跳过、改了文件重读），按米显示、8 米内到达、上下楼层提示"""
    import json  # noqa: F811
    from astral_toolkit.app.presenters import nav as present_nav
    from astral_toolkit.navigation import navigate as n

    rows = [
        {
            "city": "NewBabbage",
            "body": "Microtech",
            "cat": "交易",
            "en": "TDD",
            "zh": "交易中心",
            "area": "广场",
            "x": 520.900,
            "y": 419.200,
            "z": 744.100,
        },
        {
            "city": "NewBabbage",
            "body": "Microtech",
            "en": "坏的",
            "x": "abc",
            "y": 0,
            "z": 0,
        },
        {"en": "缺字段"},
    ]
    f = tmp_path / "city_places.json"
    f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    _nav_db(monkeypatch, tmp_path)
    ps = n.city_places()
    assert (
        len(ps) == 1
        and n.is_city(ps[0])
        and ps[0]["city_zh"] == "新巴贝奇"
        and ps[0]["b"] == "Microtech"
    )
    assert not n.is_city({"t": "Outpost"}) and not n.is_city(None)
    rows[0]["zh"] = "改过"
    f.write_text(json.dumps(rows[:1], ensure_ascii=False), encoding="utf-8")
    _nav_db(monkeypatch, tmp_path)  # 数据更新时会重建库
    assert n.city_places()[0]["zh"] == "改过"

    t = ps[0]
    r = math_r = (t["x"] ** 2 + t["y"] ** 2 + t["z"] ** 2) ** 0.5
    k = 1 - 0.012 / r  # 同一方向往下 12 米
    h = (t["x"] ** 2 + t["y"] ** 2) ** 0.5
    tx, ty = t["y"] / h, -t["x"] / h  # 水平方向（和地心方向垂直）
    here = dict(
        body="Microtech",
        inside=True,
        x=t["x"] * k + 0.05 * tx,
        y=t["y"] * k + 0.05 * ty,
        z=t["z"] * k,
        lat=0.0,
        lon=0.0,
        height_m=0.0,
        radius_km=math_r,
    )
    d, up = n.city_metrics(here, t)
    assert 45 < d < 60 and 10 < up < 14
    txt = n.city_text(here, t)
    assert " m" in txt and "上方" in txt and "km" not in txt
    assert n._short(here, t).startswith("朝 ")
    near = dict(here, x=t["x"] + 0.003 * tx, y=t["y"] + 0.003 * ty, z=t["z"])
    assert n.city_text(near, t).startswith("✅ 到了")
    flat = dict(here, x=t["x"] + 0.03 * tx, y=t["y"] + 0.03 * ty, z=t["z"])
    assert "楼" not in n.city_text(flat, t)
    assert n._short(dict(here, body="Hurston"), t).startswith("先量子跳到")

    monkeypatch.setattr(n, "here_text", lambda h, data: "")
    v = present_nav.ground_view_of(here, t, {})
    assert (
        v["city"] and not v["arrived"] and 45 < v["direct_m"] < 60 and v["updown"] > 10
    )
    assert present_nav.ground_view_of(near, t, {})["arrived"]


def test_city_nav_review(monkeypatch, tmp_path):
    """二审城内导航的 5 个问题：同名地点串号、记号没校准、手动定位到达标准、坏数据、详情页叫人量子跳"""
    import json  # noqa: F811
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.tasks import navigation as t_nav

    base = {
        "city": "NewBabbage",
        "body": "Microtech",
        "cat": "空港",
        "en": "ASOP",
        "zh": "ASOP 终端",
        "area": "空港",
    }
    rows = [
        dict(base, src="a", x=520.9, y=419.2, z=744.1),
        dict(base, src="b", x=520.95, y=419.2, z=744.1),
        dict(base, src="c", en=None, x=1, y=1, z=1),
        dict(base, src="d", cat=None, x=1, y=1, z=1),
        dict(base, src="e", x="NaN", y=1, z=1),
        "坏",
        None,
    ]
    (tmp_path / "city_places.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    _nav_db(monkeypatch, tmp_path)
    ps = n.city_places()
    assert [p["id"] for p in ps] == ["a", "b", "d"] and ps[2]["cat"] == ""
    assert ps[0]["zh"] == "ASOP 终端" and ps[1]["zh"] == "ASOP 终端 2"
    k0, k1 = t_nav._place_row(ps[0])["key"], t_nav._place_row(ps[1])["key"]
    assert k0 != k1 and t_nav._places[k1] is ps[1]

    t = ps[0]  # 手动定位：100 米不算到，按米显示
    b = {"r": 1_000_000.0, "sys": "Stanton"}
    monkeypatch.setattr(n, "system_of", lambda g, data: "Stanton")
    monkeypatch.setattr(n, "to_local", lambda body, g, when: tuple(v / 1000 for v in g))
    data = {"bodies": {"Microtech": b}}
    g = (t["x"] * 1000 + 100.0, t["y"] * 1000, t["z"] * 1000)
    f = n.fix_guide([(1.0, g)], t, data)
    assert f["city"] and not f["arrived"] and 99 < f["direct"] * 1000 < 101
    txt = n.fix_text(f)
    assert "100 m" in txt and "km" not in txt
    g2 = (t["x"] * 1000 + 3.0, t["y"] * 1000, t["z"] * 1000)
    assert n.fix_guide([(1.0, g2)], t, data)["arrived"]

    monkeypatch.setattr(
        n, "to_global", lambda body, p, when: tuple(v * 1000 for v in p)
    )
    here = dict(
        body="Microtech", x=t["x"] + 0.010, y=t["y"], z=t["z"]
    )  # 游戏局部坐标：离目标 10 米
    g_game = (
        here["x"] * 1000 + 500.0,
        here["y"] * 1000,
        here["z"] * 1000,
    )  # 星系坐标和推算差 500 米
    tg = n.target_global(t, data, 1.0, (g_game, here, 1.0))
    import math

    assert abs(math.dist(g_game, tg) - 10.0) < 0.01
    assert abs(math.dist(g_game, n.target_global(t, data, 1.0)) - 510.0) < 0.01

    monkeypatch.setattr(n, "load", lambda: data)
    monkeypatch.setattr(n, "latlon", lambda p: (0.0, 0.0, 1000.0))
    plan = t_nav.nav_plan(k1)
    assert plan["city"] and plan["routes"] == [] and plan["area"] == "空港"


def test_city_arrive_hysteresis_and_near():
    """2026-10-27 实测：到了在 7–9 米来回跳 → 进 8 米算到、出 15 米才算离开；15 米内不给转向角度"""
    from astral_toolkit.navigation import navigate as n

    assert n.city_arrived(7.5) and not n.city_arrived(9)
    assert n.city_arrived(12, before=True) and not n.city_arrived(16, before=True)
    t = {"b": "Microtech", "t": "City", "x": 520.9, "y": 419.2, "z": 744.1}
    h = (t["x"] ** 2 + t["y"] ** 2) ** 0.5
    tx, ty = t["y"] / h, -t["x"] / h
    here = dict(
        body="Microtech",
        inside=True,
        x=t["x"] + 0.012 * tx,
        y=t["y"] + 0.012 * ty,
        z=t["z"],
    )
    assert n.city_text(here, t).startswith("就在附近 12 m")
    assert n.city_text(here, t, arrived=True).startswith("✅ 到了")
    far = dict(here, x=t["x"] + 0.05 * tx, y=t["y"] + 0.05 * ty)
    assert n.city_text(far, t).startswith("朝 ")


def test_displayinfo_yields_to_mining(monkeypatch):
    """采矿助手看着面板时，读位置字模认不出也不退回识别引擎（2026-10-27 录制：抢引擎让悬浮窗晚 10–18 秒）；
    强制读（判断地面/太空）照常用识别引擎"""
    from astral_toolkit.navigation import displayinfo as D, gridtext

    calls = []
    monkeypatch.setattr(gridtext, "ready", lambda h: True)
    monkeypatch.setattr(D, "_grid_read", lambda piece, h: None)
    monkeypatch.setattr(
        D,
        "_full_read",
        lambda piece, h: calls.append(1) or {**D.parse([]), "global": (1e7, 1e7, 1e7)},
    )
    import astral_toolkit.core.capture as Cap
    from PIL import Image

    monkeypatch.setattr(Cap, "grab_region", lambda r: Image.new("RGB", (400, 300)))
    monkeypatch.setattr(Cap, "game_area", lambda: {"height": 1440})
    monkeypatch.setattr(D, "_YIELD", {"until": 0.0})
    D.yield_ocr(6)
    info = D.read()
    assert info.get("yielded") and not info["global"] and not calls
    r = D.Reader(every=1.0)
    monkeypatch.setattr("astral_toolkit.system.showloc.game_foreground", lambda: True)
    assert r.poll() is None and not calls and r.misses == 0  # 让路不算没读到
    r.poll(force=True)
    assert calls == [1] and r.info and r.info["global"]  # 强制读不让
    monkeypatch.setattr(D, "_YIELD", {"until": 0.0})
    assert not D.read().get("yielded")


def test_nav_nearest(monkeypatch, tmp_path):
    """导航「医院 / 空港 / 买船」找最近的（2026-10-27）：城里只找本城（取船终端 / 登记处优先），城外按星图里的站算距离；
    位置不知道只列出来；汉化名自带的英文不重复"""
    import json  # noqa: F811
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.tasks import navigation as t_nav

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    data = n.load()
    city = [
        {
            "city": "NewBabbage",
            "body": "Microtech",
            "cat": "医院",
            "en": "Hospital Check-In",
            "zh": "登记处",
            "src": "nb/checkin",
            "x": 520.900,
            "y": 419.200,
            "z": 744.100,
        },
        {
            "city": "NewBabbage",
            "body": "Microtech",
            "cat": "医院",
            "en": "Pharmacy",
            "zh": "药店",
            "src": "nb/pharm",
            "x": 520.950,
            "y": 419.250,
            "z": 744.000,
        },
        {
            "city": "Lorville",
            "body": "Hurston",
            "cat": "医院",
            "en": "Hospital Check-In",
            "zh": "登记处",
            "src": "lv/checkin",
            "x": -328.989,
            "y": -752.435,
            "z": 572.12,
        },
    ]
    arc0 = next(p for p in data["points"] if p["n"] == "ARC L1")
    city.append(
        {
            "city": "rr_arc_l1",
            "sys": "Stanton",
            "space": True,
            "cat": "交易",
            "kinds": ["交易"],
            "en": "Commodity Terminal",
            "src": "arc/commodity",
            "x": arc0["x"] / 1000 + 50,
            "y": arc0["y"] / 1000,
            "z": arc0["z"] / 1000,
        }
    )
    # 站里只解出交易终端：设施表里这个站的医院 / 空港照样要列（审查 2026-10-30，派罗死局等站没解出取船终端）
    amen = [
        {
            "en": "ARC-L1 Wide Forest Station",
            "zh": "弧 L1 广袤森林站",
            "kinds": ["医院", "空港"],
            "ref": {"point": "ARC L1"},
            "rec": "rr_arc_l1",
        },
        {"en": "Nowhere", "kinds": ["医院"], "ref": {"point": "不存在的点"}},
        "坏行",
    ]
    (tmp_path / "city_places.json").write_text(
        json.dumps(city, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "place_amenities.json").write_text(
        json.dumps(amen, ensure_ascii=False), encoding="utf-8"
    )
    _nav_db(monkeypatch, tmp_path)
    now = time.time()
    arc = next(p for p in data["points"] if p["n"] == "ARC L1")
    g = (arc["x"] + 5000, arc["y"], arc["z"])
    hits = n.nearest("医院", g, "Stanton", now, data)
    assert hits[0][1]["n"] == "ARC-L1 Wide Forest Station" and 4000 < hits[0][0] < 6000
    assert n.label(hits[0][1]) == "弧 L1 广袤森林站（ARC-L1 Wide Forest Station）"
    assert {q["n"] for _, q in hits} == {
        "ARC-L1 Wide Forest Station",
        "Hospital Check-In",
    }  # 城里只要登记处，药店不列
    nb = next(
        q
        for q in n.city_places()
        if q["city"] == "NewBabbage"
        and q["cat"] == "医院"
        and q["n"] == "Hospital Check-In"
    )
    g2 = n.target_global(nb, data, now)
    here = n.locate(g2, when=now)
    hits = n.nearest("医院", g2, "Stanton", now, data, here)
    assert [q["city"] for _, q in hits] == ["NewBabbage"] and hits[0][
        0
    ] < 50  # 在城里：只找本城
    assert all(
        d is None for d, _ in n.nearest("医院", None, "", None, data)
    )  # 不知道位置：只列出来
    assert (
        n.label(
            {"n": "Checkmate", "zh": "死局空间站 (Checkmate)", "t": "Orbital Station"}
        )
        == "死局空间站（Checkmate）"
    )
    from tests.bootstrap_helpers import nav_deps

    assert "error" in t_nav.nav_near(nav_deps(), "加油")


def test_city_route(monkeypatch, tmp_path):
    """城里分段路线（2026-10-27）：远了走到站台 → 坐地铁（同线直达 / 在共同的站换乘一次）→ 出站；近了直接走；
    只有一个站的线不算；当前步骤标 →"""
    import json  # noqa: F811
    from astral_toolkit.navigation import navigate as n

    def pt(x, y, z):
        return {"x": x, "y": y, "z": z}

    city = [
        dict(
            city="Lorville",
            body="Hurston",
            cat="地铁",
            en="A gate1",
            zh="地铁站台 · 城市大门 01（外环 A 线）",
            line="perim_line_a",
            stop="gate1",
            src="a1",
            **pt(-317.0, -756.5, 573.5),
        ),
        dict(
            city="Lorville",
            body="Hurston",
            cat="地铁",
            en="A mc",
            zh="地铁站台 · 地铁中心（外环 A 线）",
            line="perim_line_a",
            stop="mc",
            src="amc",
            **pt(-328.9, -758.8, 564.0),
        ),
        dict(
            city="Lorville",
            body="Hurston",
            cat="地铁",
            en="SP mc",
            zh="地铁站台 · 地铁中心（空港线）",
            line="sp_line",
            stop="mc",
            src="smc",
            **pt(-328.9, -758.85, 564.03),
        ),
        dict(
            city="Lorville",
            body="Hurston",
            cat="地铁",
            en="SP sp",
            zh="地铁站台 · 蒂莎空港（空港线）",
            line="sp_line",
            stop="sp",
            src="ssp",
            **pt(-326.9, -758.6, 565.6),
        ),
        dict(
            city="Lorville",
            body="Hurston",
            cat="地铁",
            en="CEN only",
            zh="地铁站台 · 列维斯登站（中央线）",
            line="cen_line",
            stop="lvsdn",
            src="c1",
            **pt(-329.0, -758.6, 564.2),
        ),
        dict(
            city="Lorville",
            body="Hurston",
            cat="买船",
            en="New Deal",
            zh="全新交易",
            src="nd",
            **pt(-326.95, -758.65, 565.55),
        ),
        dict(
            city="Lorville",
            body="Hurston",
            cat="空港",
            en="Gate1 ASOP",
            zh="1 号门取船",
            src="g1",
            **pt(-317.02, -756.52, 573.52),
        ),
    ]
    (tmp_path / "city_places.json").write_text(
        json.dumps(city, ensure_ascii=False), encoding="utf-8"
    )
    _nav_db(monkeypatch, tmp_path)
    ps = {q["n"]: q for q in n.city_places()}
    assert set(n._metro_lines("Lorville")) == {
        "perim_line_a",
        "sp_line",
    }  # 中央线只有一个站：不算

    def here_at(q, dx=0.0):
        return dict(
            body="Hurston",
            inside=True,
            x=q["x"] + dx,
            y=q["y"],
            z=q["z"],
            radius_km=1000.0,
            lat=0,
            lon=0,
            height_m=0,
        )

    route = n.city_route(here_at(ps["Gate1 ASOP"]), ps["New Deal"])
    assert [a for a, *_ in route] == ["walk", "ride", "transfer", "ride"]
    assert (
        route[1][1]["stop"] == "mc"
        and route[2][2] == "sp_line"
        and route[3][1]["stop"] == "sp"
    )
    goal, steps = n.city_leg(
        here_at(ps["A gate1"]), ps["New Deal"]
    )  # 站在站台上：当前步骤是上车，指向下一站
    assert (
        goal is ps["A mc"]
        and steps[1].startswith("→ 2. 坐 外环 A 线（Perimeter Line A） 到 地铁中心")
        and "换乘 空港线（Spaceport Line）" in steps[2]
    )
    plan = {}  # 导航时：路线定下来按段走（二审 2026-10-27）
    far0 = here_at(ps["Gate1 ASOP"], dx=0.05)
    assert n.city_leg(far0, ps["New Deal"], plan)[0] is ps["A gate1"] and plan["i"] == 0
    route0 = plan["route"]
    assert (
        n.city_leg(here_at(ps["A gate1"]), ps["New Deal"], plan)[0] is ps["A mc"]
        and plan["i"] == 1
    )
    goal, steps = n.city_leg(
        here_at(ps["A gate1"], dx=0.01), ps["New Deal"], plan
    )  # 车开出去一点：还在这一段，不跳回第一步
    assert plan["route"] is route0 and plan["i"] == 1 and steps[1].startswith("→ 2.")
    assert (
        n.city_leg(here_at(ps["A mc"]), ps["New Deal"], plan)[0] is ps["SP mc"]
        and plan["i"] == 2
    )  # 到地铁中心：换乘
    assert (
        n.city_leg(here_at(ps["SP mc"]), ps["New Deal"], plan)[0] is ps["SP sp"]
        and plan["i"] == 3
    )  # 上了空港线
    goal, steps = n.city_leg(
        here_at(ps["SP sp"]), ps["New Deal"], plan
    )  # 坐到终点站：出站步行
    assert goal is ps["New Deal"] and steps[-1].startswith("→ 5. 出站步行到")
    assert "5. 出站步行到 全新交易" in steps[-1]
    far = here_at(ps["Gate1 ASOP"], dx=0.05)  # 离站台 50 米：当前步骤是走到站台
    assert n.city_leg(far, ps["New Deal"])[1][0].startswith("→ 1. 步行到")
    assert (
        n.city_route(here_at(ps["SP sp"]), ps["New Deal"]) is None
    )  # 就在旁边：直接走
    assert n.city_leg(here_at(ps["SP sp"]), ps["New Deal"]) == (ps["New Deal"], [])


def test_site_menu(monkeypatch, tmp_path):
    """主城 / 空间站里的分类菜单（2026-10-27）：拉格朗日点的站用星系坐标；离站 6 km 内算在站里，只列这个站的；
    按站自己的「上」分楼层；同一个站里重名才加编号；名字双语"""
    import json  # noqa: F811
    from astral_toolkit.navigation import navigate as n

    base = dict(
        city="rr_hur_l1",
        site_en="HUR-L1 Green Glade Station",
        site_zh="赫 L1 绿色林地站",
        body="",
        sys="Stanton",
        space=True,
        up=[0, 0, 1],
        area="",
    )
    rows = [
        dict(
            base,
            cat="取船",
            kinds=["取船"],
            en="Fleet Manager Terminal",
            zh="舰队管理器终端",
            src="a",
            x=1000.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            base,
            cat="商店",
            kinds=["吃喝"],
            en="Bar",
            zh="酒吧",
            src="b",
            x=1000.05,
            y=0.0,
            z=0.02,
        ),
        dict(
            base,
            cat="商店",
            kinds=["吃喝"],
            en="Bar",
            zh="酒吧",
            src="c",
            x=1000.2,
            y=0.0,
            z=0.0,
        ),
        dict(
            base,
            city="rr_hur_l2",
            cat="商店",
            kinds=["吃喝"],
            en="Bar",
            zh="酒吧",
            src="d",
            x=5000.0,
            y=0.0,
            z=0.0,
        ),
    ]
    (tmp_path / "city_places.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    _nav_db(monkeypatch, tmp_path)
    data = {"bodies": {}, "pois": [], "points": []}
    ps = n.city_places()
    assert [q["zh"] for q in ps] == [
        "舰队管理器终端",
        "酒吧",
        "酒吧 2",
        "酒吧",
    ]  # 别的站的同名不加编号
    assert (
        ps[0]["b"] == "@Stanton" and ps[0]["space"] and n.label(ps[1]) == "酒吧（Bar）"
    )
    g = (1000_000.0, 0.0, 0.0)
    s = n.site_at(g, None, None, data)
    assert s["site"] == "rr_hur_l1" and s["kinds"] == ["取船", "吃喝"]
    assert (
        n.site_at((1010_000.0, 0.0, 0.0), None, None, data) is None
    )  # 离站 10 km：不在站里
    near = n.site_nearest("rr_hur_l1", "吃喝", g, None, data)
    assert [q["id"] for _, q in near] == ["b", "c"] and round(near[0][0]) == 54
    assert "上方 20 米" in n.station_text(g, near[0][1], data)
    assert n.station_text(g, ps[0], data).startswith("✅ 到了")


def test_train_data(monkeypatch, tmp_path):
    """帮助改进识别（2026-10-27）：被汉化包纠正的名字那一行存成「小截图 + 正确答案」；认对的只抽一部分；
    开关关了不存；每天有上限；跑测试时不发"""
    import json  # noqa: F811
    from PIL import Image
    from astral_toolkit.system import train_data as T
    from astral_toolkit.core import settings, paths

    monkeypatch.setattr(paths, "USER", tmp_path)
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    monkeypatch.setattr(T, "maybe_send", lambda force=False: None)
    img = Image.new("RGB", (400, 200), "black")
    toks = [
        OcrToken("塔维因战争服役微记（完好）", 90.0, (20, 30, 240, 22)),
        OcrToken("体积：173uSCU", 90.0, (20, 56, 100, 18)),
    ]
    T.from_tooltip(
        img,
        toks,
        ("塔维因战争服役微记（完好）", ""),
        ("塔维因战争服役徽记（完好）", "Tevarin War Service Marker (Pristine)"),
    )
    js = sorted((tmp_path / "train").glob("*.json"))
    assert len(js) == 1
    rec = json.loads(js[0].read_text(encoding="utf-8"))
    assert (
        rec["truth"] == "塔维因战争服役徽记（完好）"
        and rec["ocr"] == "塔维因战争服役微记（完好）"
    )
    with Image.open(tmp_path / "train" / rec["img"]) as im:
        assert im.size == (248, 30)  # 那一行四周各多 4 像素
    monkeypatch.setattr(T.random, "random", lambda: 0.99)  # 认对的：抽不中就不存
    assert not T.add_line(img, (20, 56, 100, 18), "体积", "体积")
    assert not T.add_line(img, (20, 56, 100, 400), "很高", "很髙")  # 不像一行字
    settings.update(train_upload=False)
    assert not T.add_line(img, (20, 56, 100, 18), "关了", "关子")
    settings.update(train_upload=True)
    monkeypatch.setattr(T, "DAY_MAX", 1)
    assert not T.add_line(img, (20, 56, 100, 18), "今天满了", "今天满子")
    # 一包不超过服务器的 60 个文件；服务器拒收（4xx）当天不再发（二审 2026-10-27）
    import io as _io
    import zipfile
    import urllib.error

    monkeypatch.setattr(T, "DAY_MAX", 1000)
    for k in range(T.BATCH + 5):
        assert T.add_line(img, (20, 56, 100, 18), f"第{k}条", f"弟{k}条")
    monkeypatch.setattr(T, "enabled", lambda: True)
    got = {}

    def fake_open(req, timeout=None):
        got["body"] = req.data
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    T._send_batch()
    with zipfile.ZipFile(_io.BytesIO(got["body"])) as z:
        names = z.namelist()
    assert 0 < len(names) <= 60 and all(
        n.startswith("train/") and n.count("/") == 1 for n in names
    )
    assert T._refused_today()
    T.clear()  # 关掉开关：本地攒着的删掉
    assert not list((tmp_path / "train").glob("*.png")) and not list(
        (tmp_path / "train").glob("*.json")
    )


def test_rotation_phase_calibration(tmp_path, monkeypatch):
    """右上角同时给了星系坐标和星球坐标 → 反推自转相位：算回来和原值一样；连续两次一致才写文件；写了以后 rotation_deg 用校准值"""
    import math
    from astral_toolkit.navigation import navigate as n

    if not n.CACHE.exists():
        pytest.skip("没有星图数据")
    monkeypatch.setattr(n, "CALIB", tmp_path / "rotation_calib.json")
    n._calib.update(stamp=None, data={}, pending={})
    n._offsets.clear()
    d = n.load()
    b, name = d["bodies"]["Microtech"], "Microtech"
    when = datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc)
    p = (68.364, 64.276, -996.49)  # 新巴贝奇附近（星球坐标，千米）
    a = (360 - n.rotation_deg(b, when)) / n.R2D
    c, s = math.cos(-a), math.sin(-a)
    lx, ly = p[0] * 1000, p[1] * 1000
    g = (b["x"] + lx * c - ly * s, b["y"] + lx * s + ly * c, b["z"] + p[2] * 1000)
    assert abs(n.phase_from(b, g, p, when) - b["adj"]) < 1e-6
    assert n.phase_from(b, g, (p[0], p[1], p[2] + 5), when) is None  # 高度对不上：不信
    # 假装游戏里的相位比表里多 1°：第一次只记着，第二次一致才采用
    shifted = (360 - (n.rotation_deg(b, when) + 1.0)) / n.R2D
    c2, s2 = math.cos(-shifted), math.sin(-shifted)
    g2 = (b["x"] + lx * c2 - ly * s2, b["y"] + lx * s2 + ly * c2, b["z"] + p[2] * 1000)
    assert (
        not n._calibrate(name, b, g2, p, when) and not n.CALIB.exists()
    )  # 第一次只记着
    assert n._calibrate(name, b, g2, p, when) is True and n.CALIB.exists()
    assert (
        abs(
            n._ang_diff(
                n.rotation_deg(b, when),
                (n.rotation_deg({**b, "name": ""}, when) + 1.0) % 360,
            )
        )
        < 1e-4
    )  # 文件里存 5 位小数
    assert (
        math.dist(n.to_local(b, g2, when), p) < 0.01
    )  # 校准后推算的位置和游戏给的一致
    n._calib.update(stamp=None, data={}, pending={})


def test_nav_hud_missing_does_not_break_halo_and_fix(monkeypatch, tmp_path):
    """悬浮窗建不起来（_hud() 是 None）：小行星带核对、取下方案、一键定位照常返回，不抛 AttributeError
    （以前 tasks/navigation 里 7 处直接 _hud().set / .clear；待做原第 342 行）"""
    import threading
    import types
    from pathlib import Path

    from astral_toolkit.app import hud_state
    from astral_toolkit.core import paths
    from astral_toolkit.navigation import halo
    from astral_toolkit.tasks import navigation as t_nav

    src = Path(t_nav.__file__).read_text(encoding="utf-8")
    assert "_hud().set(" not in src and "_hud().clear(" not in src
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    monkeypatch.setattr(t_nav, "_hud", lambda: None)
    monkeypatch.setattr(hud_state, "_hud", lambda: None)
    monkeypatch.setattr(halo, "where", lambda g: {"band": 3})
    monkeypatch.setattr(halo, "where_text", lambda w, band: "在第3带")
    published = []
    monkeypatch.setattr(t_nav.bus, "publish", lambda kind, data: published.append(kind))
    ran = []
    monkeypatch.setattr(
        threading,
        "Timer",
        lambda secs, fn: types.SimpleNamespace(start=lambda: ran.append(fn())),
    )  # 「仅用于手动定位」那条 5 秒后清提示：马上跑，看清提示那一步也不抛
    t_nav._HALO.update(plan={"text": "方案", "band": 5}, last=None, seen=None)
    try:
        w = t_nav.halo_check(
            (1.0, 2.0, 3.0), "Coordinates: x:1 y:2 z:3", t_nav._HALO["sess"]
        )
        assert w and w["text"] == "在第3带" and published == ["halo"]
    finally:
        assert t_nav.halo_unpin() == {"ok": True}
    deps = types.SimpleNamespace(
        nav=types.SimpleNamespace(target=None, space_mode=False)
    )
    got = t_nav.fix_here(deps)  # type: ignore[arg-type]  # 只用到 deps.nav，给个假的
    assert got == {"error": "当前未导航到太空路标"} and ran == [None]
