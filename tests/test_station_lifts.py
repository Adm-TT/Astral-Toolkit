"""空间站站内导航（2026-10-28）：右上角最里层 Zone 名、按区域坐电梯分段。用假数据，不读 data\\ 里的大文件"""

import json

import pytest


def test_parse_inner_zone():
    """最里层 Zone 行三个数都是 m：只记名字（inner_zone），星系坐标照旧用 SolarSystem / Root 那两行"""
    from sc_mining.navigation import displayinfo as di

    lines = [
        "Zone: Hangar_SmallFront_RestStop_906008046493 Pos: 16.86m -88.26m 5.97m",
        "Zone: OOC_Stanton4_L1 Pos: 2894.81m 3565.84m -269.96m",
        "Zone: SolarSystem_863177739492 Pos: 20215827.1330km 33467068.5735km -269.96m",
        "Zone: Root Pos: 20215827.1330km 33467068.5735km -269.96m",
        "Current player location : RR MIC L1 (LZ : RR MIC L1)",
    ]
    r = di.parse(lines, need_both=True)
    assert r["inner_zone"] == "Hangar SmallFront RestStop 906008046493"
    assert r["global"] == (20215827133.0, 33467068573.5, -269.96) or all(
        abs(a - b) < 1e-3
        for a, b in zip(r["global"], (20215827133.0, 33467068573.5, -269.96))
    )
    assert (
        r["local"] is None and r["zone"] == "" and r["location"].startswith("RR MIC L1")
    )
    city = di.parse(
        [
            "Zone: OOC_Stanton_4_Microtech Pos: 520.9152km 410.2893km 744.0843km",
            "Zone: Root Pos: 22462326.4853km 37186368.6338km 744.0843km",
        ]
    )
    assert (
        city["inner_zone"] == "OOC Stanton 4 Microtech"
        and city["zone"] == "OOC Stanton 4 Microtech"
    )
    assert di.parse([])["inner_zone"] == ""


def _station(tmp_path, monkeypatch):
    from sc_mining.navigation import navigate as n

    areas = {
        "ObjectContainer_Entry": {"en": "Lobby", "zh": "大厅", "zone": True},
        "ObjectContainer_Commercial": {
            "en": "Galleria",
            "zh": "购物中心",
            "zone": True,
        },
        "ObjectContainer_habs": {"en": "Habs", "zh": "居住区", "zone": True},
        "hangar": {"en": "Hangar", "zh": "机库"},
    }
    lifts = [
        {
            "id": "TransitManager_Internal",
            "en": "Station Lift",
            "zh": "站内电梯",
            "stops": [
                {
                    "key": "@ui_dest_commercial",
                    "en": "Galleria",
                    "zh": "购物中心",
                    "area": "ObjectContainer_Commercial",
                    "gates": [[0.0, 0.0, 0.0]],
                },
                {
                    "key": "@ui_dest_entry_exit",
                    "en": "Hangars & Habs",
                    "zh": "机库 & 居住区",
                    "area": "ObjectContainer_Entry",
                    "gates": [[0.1, 0.0, 0.0], [0.1, 0.006, 0.0]],
                },
            ],
        },
        {
            "id": "TransitManager_Spaceport-to-Hangars",
            "en": "Hangar Lift",
            "zh": "机库电梯",
            "stops": [
                {
                    "key": "@ui_interactor_lobby",
                    "en": "Lobby",
                    "zh": "大厅",
                    "area": "ObjectContainer_Entry",
                    "gates": [[0.12, 0.0, 0.0]],
                },
                {
                    "key": "hangar",
                    "en": "Hangar",
                    "zh": "机库",
                    "area": "hangar",
                    "gates": [],
                },
            ],
        },
        {
            "id": "TransitManager_Habs",
            "en": "Habs Lift",
            "zh": "居住区电梯",
            "stops": [
                {
                    "key": "@ui_interactor_floor_01",
                    "en": "Floor 01",
                    "zh": "01 楼",
                    "area": "ObjectContainer_habs",
                    "gates": [[0.2, 0.0, 0.0]],
                },
                {
                    "key": "@ui_interactor_floor_02",
                    "en": "Floor 02",
                    "zh": "02 楼",
                    "area": "ObjectContainer_habs",
                    "gates": [[0.2, 0.0, 0.016]],
                },
                {
                    "key": "@ui_interactor_lobby",
                    "en": "Lobby",
                    "zh": "大厅",
                    "area": "ObjectContainer_Entry",
                    "gates": [[0.13, 0.0, 0.0]],
                },
            ],
        },
    ]
    hangars = [
        {
            "id": "H1",
            "size": "Small",
            "door": [0.5, 0.0, 0.0],
            "lift": [0.6, 0.0, 0.0],
            "spawn": [0.6, 0.003, 0.0],
        },
        {
            "id": "H2",
            "size": "Large",
            "door": [0.5, 0.3, 0.0],
            "lift": [0.6, 0.3, 0.0],
            "spawn": [0.6, 0.303, 0.0],
        },
    ]
    st = {
        "areas": areas,
        "lifts": lifts,
        "hangars": hangars,
        "places": {"comm/term": "ObjectContainer_Commercial"},
    }
    (tmp_path / "station_lifts.json").write_text(
        json.dumps(
            {
                "version": 1,
                "stations": {
                    "rr_x": dict(st, space=True, sys="Stanton"),
                    "rr_y": dict(
                        st,
                        body="ArcCorp",
                        places={"comm/term+": "ObjectContainer_Commercial"},
                    ),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    row = {
        "site_en": "X",
        "site_zh": "X 站",
        "cat": "交易",
        "kinds": ["交易"],
        "en": "Commodity Terminal",
        "zh": "商品交易终端",
        "src": "comm/term",
        "x": -0.03,
        "y": 0.0,
        "z": 0.0,
    }
    places = [
        dict(row, city="rr_x", body="", sys="Stanton", space=True),
        dict(row, city="rr_y", body="ArcCorp"),
    ]
    (tmp_path / "city_places.json").write_text(
        json.dumps(places, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(n, "DATA", tmp_path)
    return n, {q["city"]: q for q in n.city_places()}


def test_zone_kind(monkeypatch, tmp_path):
    n, _ = _station(tmp_path, monkeypatch)
    st = n.station_lifts()["rr_x"]
    assert n.zone_kind("TransitCarriage elev util 904902949100", st) == "lift"
    assert n.zone_kind("Hangar SmallFront RestStop 906008046493", st) == "hangar"
    assert n.zone_kind("ObjectContainer Commercial", st) == "ObjectContainer_Commercial"
    assert (
        n.zone_kind("ObjectC0ntainer Entry", st) == "ObjectContainer_Entry"
    )  # 字模认错一个字母
    assert n.zone_kind("OOC Stanton4 L1", st) is None and n.zone_kind("", st) is None


def test_station_leg_hangar_to_shop(monkeypatch, tmp_path):
    """机库 → 机库电梯 → 大厅换站内电梯 → 购物中心；在电梯里提示选哪站；区域名对不上就重新规划；离站远了不分段"""
    n, ps = _station(tmp_path, monkeypatch)
    tgt = ps["rr_x"]
    plan = {}
    goal, steps = n.station_leg(
        (0.6, 0.002, 0.0), tgt, plan, "Hangar SmallFront RestStop 9060"
    )
    assert (
        n.pos(goal) == (0.6, 0.0, 0.0) and len(steps) == 4
    )  # 机库：先去自己这个机库（小）的电梯
    assert (
        steps[0] == "→ 1. 去机库电梯（Hangar Lift）"
        and steps[1] == "   2. 坐机库电梯（Hangar Lift）到「大厅（Lobby）」"
    )
    assert steps[
        2
    ] == "   3. 换站内电梯（Station Lift）到「购物中心（Galleria）」" and steps[
        3
    ].startswith("   4. 出电梯到 商品交易终端")
    goal, steps = n.station_leg(
        (0.6, 0.0005, 0.0), tgt, plan, "Hangar SmallFront RestStop 9060"
    )  # 走到电梯门口：还没进电梯
    assert plan["i"] == 0 and n.pos(goal) == (0.6, 0.0, 0.0)
    goal, steps = n.station_leg(
        (0.6, 0.0, 0.001), tgt, plan, "TransitCarriage elev util 1"
    )  # 进了电梯
    assert (
        n.pos(goal) == (0.12, 0.0, 0.0)
        and steps[1].startswith("→ 2.")
        and steps[2] == "   在电梯里选「大厅（Lobby）」"
    )
    goal, steps = n.station_leg(
        (0.6, 0.0005, 0.0), tgt, plan, "Hangar SmallFront RestStop 9060"
    )  # 又出来了：指回电梯门
    assert (
        plan["i"] == 1
        and n.pos(goal) == (0.6, 0.0, 0.0)
        and "在电梯里选" not in "".join(steps)
    )
    goal, steps = n.station_leg(
        (0.6, 0.0, 0.001), tgt, plan, "TransitCarriage elev util 1"
    )
    assert n.pos(goal) == (0.12, 0.0, 0.0)
    goal, steps = n.station_leg(
        (0.121, 0.0, 0.0), tgt, plan, "TransitCarriage elev util 2"
    )  # 到大厅，还在机库电梯里
    assert (
        plan["i"] == 2
        and n.pos(goal) == (0.1, 0.0, 0.0)
        and steps[2].startswith("→ 3.")
        and len(steps) == 4
    )
    goal, steps = n.station_leg(
        (0.1, 0.0, 0.0), tgt, plan, "ObjectContainer Entry"
    )  # 出电梯走到站内电梯门口：门口也还是这一步
    assert plan["i"] == 2 and n.pos(goal) == (0.1, 0.0, 0.0)
    goal, steps = n.station_leg(
        (0.1, 0.0, 0.0), tgt, plan, "TransitCarriage elev util 3"
    )  # 进了站内电梯
    assert (
        plan["i"] == 3
        and n.pos(goal) == (0.0, 0.0, 0.0)
        and "在电梯里选「购物中心（Galleria）」" in steps[3]
    )
    goal, steps = n.station_leg(
        (-0.01, 0.0, 0.0), tgt, plan, "ObjectContainer Commercial"
    )  # 到购物中心：最后一步
    assert goal is tgt and steps[-1].startswith("→ 4. 出电梯到")
    # 区域名对不上路线：重新规划（在购物中心里就直接走）
    plan = {}
    n.station_leg((0.6, 0.002, 0.0), tgt, plan, "Hangar SmallFront RestStop 9060")
    assert n.station_leg(
        (-0.02, 0.0, 0.0), tgt, plan, "ObjectContainer Commercial"
    ) == (tgt, [])
    # 读不到区域名：按坐标就近认（大厅的门旁边）→ 一段站内电梯；离门 4 米内才算进了电梯
    plan = {}
    goal, steps = n.station_leg((0.11, 0.0, 0.0), tgt, plan, "")
    assert (
        n.pos(goal) == (0.1, 0.0, 0.0)
        and steps[0] == "→ 1. 去站内电梯（Station Lift）"
        and steps[1] == "   2. 坐站内电梯（Station Lift）到「购物中心（Galleria）」"
    )
    assert (
        n.pos(n.station_leg((0.106, 0.0, 0.0), tgt, plan, "")[0]) == (0.1, 0.0, 0.0)
        and plan["i"] == 0
    )
    assert (
        n.pos(n.station_leg((0.1035, 0.0, 0.0), tgt, plan, "")[0]) == (0.0, 0.0, 0.0)
        and plan["i"] == 1
    )
    plan = {"x": 1}
    assert (
        n.station_leg((50.0, 0.0, 0.0), tgt, plan, "ObjectContainer Entry") == (tgt, [])
        and plan == {}
    )  # 不在站里
    assert n.station_leg((0.6, 0.002, 0.0), dict(tgt, id="nope"), {}, "") == (
        dict(tgt, id="nope"),
        [],
    )  # 点没标区域


def test_station_leg_no_zone_name_any_gate(monkeypatch, tmp_path):
    """全程读不到区域名：走另一扇门也算进了电梯；直接到了下一段的下车门附近，两段一起算完成（复审 2026-10-28）"""
    n, ps = _station(tmp_path, monkeypatch)
    tgt = ps["rr_x"]
    plan = {}
    assert n.pos(n.station_leg((0.11, 0.0, 0.0), tgt, plan, "")[0]) == (0.1, 0.0, 0.0)
    goal, steps = n.station_leg(
        (0.1, 0.0065, 0.0), tgt, plan, ""
    )  # 走的是另一扇门（隔 6 米）
    assert plan["i"] == 1 and n.pos(goal) == (0.0, 0.0, 0.0)
    goal, steps = n.station_leg(
        (-0.005, 0.0, 0.0), tgt, plan, ""
    )  # 到购物中心的门：出电梯走到目的地
    assert goal is tgt and steps[-1].startswith("→ 3.")
    plan = {}
    n.station_leg((0.11, 0.0, 0.0), tgt, plan, "")
    goal, steps = n.station_leg(
        (0.0, 0.001, 0.0), tgt, plan, ""
    )  # 上车那一帧没读到：直接在下车门附近
    assert goal is tgt and plan["i"] == 2


def test_station_leg_switch_lift_without_lobby_frame(monkeypatch, tmp_path):
    """从机库电梯直接换进站内电梯、一帧大厅都没读到：离站内电梯门近就算换到了；规划时人已在电梯里马上提示选哪站"""
    n, ps = _station(tmp_path, monkeypatch)
    tgt = ps["rr_x"]
    plan = {}
    n.station_leg((0.6, 0.002, 0.0), tgt, plan, "Hangar SmallFront RestStop 9060")
    n.station_leg(
        (0.6, 0.0, 0.001), tgt, plan, "TransitCarriage elev util 904902949036"
    )
    n.station_leg(
        (0.121, 0.0, 0.0), tgt, plan, "TransitCarriage elev util 904902949036"
    )  # 到大厅（还在机库电梯里）
    assert plan["i"] == 2
    n.station_leg(
        (0.1005, 0.0, 0.0), tgt, plan, "TransitCarriage elev util 9049O2949036"
    )  # 离站内电梯门近，但还是同一部轿厢（认错一位）
    assert plan["i"] == 2
    goal, steps = n.station_leg(
        (0.1005, 0.0, 0.0), tgt, plan, "TransitCarriage elev util 904902951177"
    )  # 换进了站内电梯
    assert (
        plan["i"] == 3
        and n.pos(goal) == (0.0, 0.0, 0.0)
        and "在电梯里选「购物中心（Galleria）」" in steps[3]
    )
    goal, steps = n.station_leg(
        (0.6, 0.0, 0.001), tgt, {}, "TransitCarriage elev util 904902949036"
    )  # 在机库电梯里才开始导航
    assert n.pos(goal) == (0.12, 0.0, 0.0) and "   在电梯里选「大厅（Lobby）」" in steps


def test_car_number_changed():
    from sc_mining.navigation import navigate as n

    assert n._car_no("TransitCarriage elev util 904902949100") == "904902949100"
    assert not n._car_changed("904902949036", "9049O2949O36") and n._car_changed(
        "904902949036", "904902949100"
    )
    assert n._car_changed("", "904902949036")


def test_unpack_lifts_rotated_station():
    """转了 90° 的 TransitManager：门要先转它的朝向再加位置；不转的话点离本区域的门几千米，自检能查出来（第 25 轮复审）"""
    import math
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import unpack_lifts as UL

    q90 = (math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4))  # 绕 z 转 90°
    mp, rel = (1000.0, 0.0, 0.0), (2000.0, 0.0, 0.0)
    g = UL.tm_local(mp, q90, rel)
    assert all(abs(a - b) < 1e-6 for a, b in zip(g, (1000.0, 2000.0, 0.0)))
    place = {"id": "shop", "x": 1.03, "y": 2.0, "z": 0.0}  # 点在门旁边 30 米（千米）
    good = [{"stops": [{"area": "A", "gates": [[v / 1000 for v in g]]}]}]
    bad = [
        {"stops": [{"area": "A", "gates": [[v / 1000 for v in UL.add(mp, rel)]]}]}
    ]  # 没套朝向：门跑到 (3000, 0, 0)
    assert UL.worst_place_gate([place], {"shop": "A"}, good) < 50
    assert UL.worst_place_gate([place], {"shop": "A"}, bad) > UL.AREA_GATE_M


def test_zone_kind_numbered_names():
    """区域名的编号是名字的一部分：两边都不去编号；认错一个字母也认；两个只差一位的名字分不清就不认（审查 2026-10-28）"""
    from sc_mining.navigation import navigate as n

    st = {
        "areas": {
            "ObjectContainer-000": {"zone": True},
            "ObjectContainer-001": {"zone": True},
            "rs_refin_occu_001": {"zone": True},
            "rs_habs_010_occu_001": {"zone": True},
        }
    }
    assert n.zone_kind("ObjectContainer-000", st) == "ObjectContainer-000"
    assert n.zone_kind("ObjectContainer 001", st) == "ObjectContainer-001"
    assert (
        n.zone_kind("ObjectContainer 00l", st) is None
    )  # 刚好认错区分的那一位：分不清
    assert n.zone_kind("rs refin 0ccu 001", st) == "rs_refin_occu_001"
    assert n.zone_kind("rs habs 010 occu 00l", st) == "rs_habs_010_occu_001"
    assert (
        n.zone_kind("TransitCarriaqe elev util 904902949100", st) == "lift"
    )  # 前缀认错一个字母
    assert n.zone_kind("Hanqar SmallFront RestStop 906008046493", st) == "hangar"


def test_lift_rows_skip_bad_station(monkeypatch, tmp_path):
    """station_lifts.json 里结构不对的站跳过，别的照常"""
    from sc_mining.navigation import navigate as n

    good = {
        "areas": {},
        "lifts": [{"stops": [{"area": "a", "gates": [[1, 2, 3]]}]}],
        "hangars": [],
        "places": {},
    }
    good = dict(
        good,
        lifts=[
            {
                "en": "L",
                "zh": "梯",
                "stops": [{"area": "a", "en": "A", "zh": "甲", "gates": [[1, 2, 3]]}],
            }
        ],
        hangars=[
            {"size": "Small", "door": [0, 0, 0], "lift": [0, 0, 0], "spawn": [0, 0, 0]}
        ],
    )
    bad = dict(
        good,
        lifts=[
            {
                "en": "L",
                "zh": "梯",
                "stops": [{"area": "a", "en": "A", "zh": "甲", "gates": [[1, 2]]}],
            }
        ],
    )
    no_en = dict(good, lifts=[{"zh": "梯", "stops": []}])
    no_size = dict(
        good, hangars=[{"door": [0, 0, 0], "lift": [0, 0, 0], "spawn": [0, 0, 0]}]
    )
    assert set(
        n._lift_rows(
            {
                "stations": {
                    "g": good,
                    "b": bad,
                    "c": {"areas": {}},
                    "e": no_en,
                    "s": no_size,
                }
            }
        )
    ) == {"g"}
    assert n._lift_rows([]) == {} and n._lift_rows({"stations": None}) == {}


def test_pos_zone_change_counts_as_moved():
    """进电梯站着不动：区域名变成轿厢也算变了（导航要马上提示选哪站）；轿厢的随机编号变了不算"""
    from sc_mining.app.engines import pos

    a = {"inner_zone": "TransitCarriage elev util 904902949036"}
    assert pos._zone_base(a) == pos._zone_base(
        {"inner_zone": "TransitCarriage elev util 904902949100"}
    )
    assert pos._zone_base(a) != pos._zone_base({"inner_zone": "ObjectContainer Entry"})
    assert pos._zone_base(a) == pos._zone_base(
        {"inner_zone": "TransitCarriage elev util 90490294910O"}
    )  # 编号里数字认成字母
    assert (
        pos._zone_base(None) == ""
        and pos._zone_base({"inner_zone": "ObjectContainer Entry"})
        == "ObjectContainer Entry"
    )


def test_nav_engine_station_branch(monkeypatch, tmp_path):
    """导航线程的空间站分支走一遍：机库里指向机库电梯、悬浮窗和窗口都有步骤；进了电梯（坐标不变、区域名变）提示选哪站"""
    import threading
    import time
    import types

    n, ps = _station(tmp_path, monkeypatch)
    from sc_mining.tasks import mining as t_mining, navigation as t_nav, system as t_sys
    from sc_mining.app.engines.manager import EngineManager

    em = EngineManager.get_instance()
    from sc_mining.app import hud_state
    from sc_mining.app import bus
    from sc_mining.app.engines import nav as nav_mod

    tgt = ps["rr_x"]
    monkeypatch.setattr(n, "load", lambda: {"bodies": {}, "pois": [], "points": []})
    monkeypatch.setattr(n, "locate", lambda *a, **k: {"inside": False, "body": None})
    monkeypatch.setattr(n, "system_info", lambda *a, **k: ("Stanton", True))
    monkeypatch.setattr(n, "read_clipboard", lambda: "")
    huds, pubs = [], []

    class Hud:
        def set(self, k, v):
            huds.append(v)

        def clear(self, k):
            pass

    _v = lambda: Hud()  # noqa: E731
    for _m in (t_mining, t_nav, t_sys, hud_state):
        monkeypatch.setattr(_m, "_hud", _v)
    monkeypatch.setattr(t_mining, "_marker_tick", lambda *a, **k: None)
    monkeypatch.setattr(bus, "publish", lambda topic, data: pubs.append((topic, data)))
    now = time.time()
    g = (600.0, 0.5, 0.0)
    fake = types.SimpleNamespace(
        current=(now, g, {"inner_zone": "Hangar SmallFront RestStop 1", "t": now}),
        latest=(0.0, None, None),
        read_at=now,
        reader=types.SimpleNamespace(active=True),
    )
    monkeypatch.setattr(em, "pos", fake)
    nv = nav_mod._Nav()
    nv.target, nv.session = tgt, 1
    ev = threading.Event()
    th = threading.Thread(target=nv._run, args=(ev, 1), daemon=True)
    th.start()

    def wait(pred):
        end = time.time() + 5
        while time.time() < end:
            if any(pred(h) for h in huds):
                return True
            time.sleep(0.05)
        return False

    try:
        assert wait(lambda h: "→ 1. 去机库电梯（Hangar Lift）" in h)
        here = [d["here"] for t, d in pubs if t == "nav" and d.get("here")]
        assert (
            here
            and here[-1]["steps"][0] == "→ 1. 去机库电梯（Hangar Lift）"
            and here[-1]["arrived"] is False
        )
        fake.latest = (
            time.time(),
            g,
            {"inner_zone": "TransitCarriage elev util 2", "t": time.time()},
        )  # 进电梯：坐标没变
        assert wait(lambda h: "在电梯里选「大厅（Lobby）」" in h)
    finally:
        ev.set()
        th.join(3)
    assert not th.is_alive()


def test_station_leg_habs_floor_and_no_zone_fixes(monkeypatch, tmp_path):
    """居住区各层都能下到大厅：挑本层的门（第 26 轮复审）；在电梯里开始导航、不在任何门口：先直指目的地；
    读不到区域名：站在目的地上算到了，连着几帧在路线外的区域就重新规划"""
    n, ps = _station(tmp_path, monkeypatch)
    tgt = ps["rr_x"]
    plan = {}
    goal, steps = n.station_leg(
        (0.2, 0.0, 0.0165), tgt, plan, "ObjectContainer habs"
    )  # 2 楼
    assert (
        n.pos(goal) == (0.2, 0.0, 0.016)
        and steps[0] == "→ 1. 去居住区电梯（Habs Lift）"
    )
    n.station_leg(
        (0.2, 0.0, 0.016), tgt, plan, "TransitCarriage elev util 904902955555"
    )
    assert plan["i"] == 1
    assert n.station_leg(
        (0.3, 0.0, 0.0), tgt, {}, "TransitCarriage elev util 904902955555"
    ) == (tgt, [])  # 电梯半路
    plan = {}
    n.station_leg((0.6, 0.002, 0.0), tgt, plan, "Hangar SmallFront RestStop 9060")
    n.station_leg(
        (0.6, 0.0, 0.001), tgt, plan, "TransitCarriage elev util 904902949036"
    )  # 进机库电梯
    assert plan["i"] == 1
    n.station_leg(
        (-0.03, 0.0, 0.0), tgt, plan, ""
    )  # 坐电梯路过目的地、读空一帧：不跳段
    n.station_leg((0.3, 0.0, 0.0), tgt, plan, "TransitCarriage elev util 904902949036")
    assert plan["i"] == 1
    for k in range(3):  # 读不到区域名、站在目的地上连着 3 帧
        goal, steps = n.station_leg((-0.03, 0.0, 0.0), tgt, plan, "")
        assert (goal is tgt) == (k == 2)
    assert steps[-1].startswith("→ 4.")
    plan = {}
    n.station_leg((0.6, 0.002, 0.0), tgt, plan, "Hangar SmallFront RestStop 9060")
    for k in range(2):  # 跑到居住区 1 楼门口（不在路线上）
        n.station_leg((0.2, 0.0, 0.001), tgt, plan, "")
        assert plan["legs"][0]["frm"] == "hangar"
    goal, steps = n.station_leg((0.2, 0.0, 0.001), tgt, plan, "")  # 第 3 帧：重新规划
    assert plan["legs"][0]["frm"] == "ObjectContainer_habs" and steps[0].endswith(
        "去居住区电梯（Habs Lift）"
    )


def test_city_leg_orbital_station(monkeypatch, tmp_path):
    """绕星球轨道的站走 city_leg：同一颗星球才分段"""
    n, ps = _station(tmp_path, monkeypatch)
    tgt = ps["rr_y"]
    here = dict(body="ArcCorp", inside=True, x=0.11, y=0.0, z=0.0)
    goal, steps = n.city_leg(here, tgt, {}, "ObjectContainer Entry")
    assert (
        n.pos(goal) == (0.1, 0.0, 0.0) and steps[0] == "→ 1. 去站内电梯（Station Lift）"
    )
    assert n.city_leg(dict(here, body="Hurston"), tgt, {}, "ObjectContainer Entry") == (
        tgt,
        [],
    )


def test_showlocation_only_waits_for_player(monkeypatch):
    """AT 不替玩家打字（控制台指令第 4 批）：showlocation 只等剪贴板出现新坐标；同一时间只等一份"""
    import threading
    from sc_mining.navigation import navigate as n
    from sc_mining.system import showloc

    assert not hasattr(showloc, "send_showlocation") and not hasattr(showloc, "_send")
    monkeypatch.setattr(n, "read_clipboard", lambda: "old")
    got, release = [], threading.Event()

    def wait(old, timeout):
        got.append(timeout)
        release.wait(5)
        return (1.0, 2.0, 3.0), "Coordinates: x:1 y:2 z:3"

    monkeypatch.setattr(showloc, "wait_new_coords", wait)
    out = []
    t = threading.Thread(target=lambda: out.append(showloc.showlocation()))
    t.start()
    for _ in range(100):
        if got:
            break
        threading.Event().wait(0.02)
    assert got == [showloc.TYPE_WAIT] == [60]
    g, why = showloc.showlocation()  # 已经在等：第二份直接返回，不重复记
    assert g is None and "已经在等" in why
    release.set()
    t.join(5)
    assert out == [((1.0, 2.0, 3.0), "Coordinates: x:1 y:2 z:3")]
    monkeypatch.setattr(showloc, "wait_new_coords", lambda old, timeout: (None, None))
    g, why = showloc.showlocation()
    assert g is None and "60 秒内没读到新坐标" in why


def test_no_synthetic_input_in_nav_files():
    """导航负责的文件里不能有合成输入（控制台指令第 4 批）"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "sc_mining"
    files = [
        root / "system" / "showloc.py",
        root / "tasks" / "navigation.py",
        root / "app" / "overlay.py",
        root / "app" / "engines" / "nav.py",
        root / "app" / "engines" / "pos.py",
        root / "app" / "hud_state.py",
        root / "app" / "api" / "navigation.py",
    ] + sorted((root / "navigation").glob("*.py"))
    bad = re.compile(
        r"SendInput|keybd_event|mouse_event|KEYEVENTF|_KEYBDINPUT|自动输入 /showlocation|自动跑"
    )
    hits = [
        f"{f.name}:{k}"
        for f in files
        for k, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if bad.search(line)
    ]
    assert hits == []


def test_browser_page_titled_star_citizen_is_not_game(monkeypatch):
    """标题以「Star Citizen」开头的浏览器窗口不是游戏：读得到进程名就以进程名为准（S2 审查 2026-10-31）"""
    from sc_mining.system import showloc

    if not showloc.WIN:
        pytest.skip("只有 Windows")
    monkeypatch.setattr(
        showloc, "_window_text", lambda h, fn: "Star Citizen - YouTube - Google Chrome"
    )
    monkeypatch.setattr(showloc, "_exe_of", lambda h: "chrome.exe")
    assert showloc._is_game_window(1) is False
    monkeypatch.setattr(showloc, "_exe_of", lambda h: "starcitizen.exe")
    assert showloc._is_game_window(1) is True
    monkeypatch.setattr(showloc, "_exe_of", lambda h: "")
    assert showloc._is_game_window(1) is False
    monkeypatch.setattr(showloc, "_window_text", lambda h, fn: "Star Citizen ")
    assert showloc._is_game_window(1) is True


def test_space_guide_uses_top_right_hints(monkeypatch):
    """太空导航定星系带上右上角线索（不再只按最近星球猜）；不给就用位置线程登记的来源（S2 审查 2026-10-31）"""
    from sc_mining.navigation import navigate as n

    seen = []
    monkeypatch.setattr(
        n, "system_of", lambda g, data=None, **kw: seen.append(kw) or "Pyro"
    )
    data = {"bodies": {}, "points": []}
    tgt = {"space": True, "x": 0.0, "y": 0.0, "z": 0.0, "sys": "Nyx"}
    assert (
        n.space_guide((1e9, 0, 0), tgt, data, hints={"solar_id": "862685702877"})[
            "same_system"
        ]
        is False
    )
    assert seen[-1] == {"solar_id": "862685702877"}
    monkeypatch.setattr(n, "HINTS", lambda: {"zone": "keeger"})
    n.fix_guide([(0.0, (1e9, 0, 0))], tgt, data)
    assert seen[-1] == {"zone": "keeger"}
    monkeypatch.setattr(n, "HINTS", lambda: 1 / 0)  # 来源坏了也不影响导航
    n.space_guide((1e9, 0, 0), tgt, data)
    assert seen[-1] == {}


def test_ore_go_name_clash_and_recorded_system(monkeypatch):
    """原矿「去这里」：同一分钟同种矿不撞名；用记录时定下的星系（S2 审查 2026-10-31）"""
    from sc_mining.tasks import navigation as t_nav
    from sc_mining.mining import ore_log

    rec = {
        "id": "abcd1234ef",
        "rock": "铜",
        "at": "2026-10-31 12:00:01",
        "coords": [1.0, 2.0, 3.0],
        "system": "Nyx",
    }
    saved, rows = [], [{"name": "原矿 铜 10-31 12:00", "key": "wp:old"}]
    monkeypatch.setattr(ore_log, "load", lambda: [rec])
    monkeypatch.setattr(ore_log, "update", lambda id, **kw: None)
    monkeypatch.setattr(t_nav, "waypoints", lambda: list(rows))
    monkeypatch.setattr(
        t_nav,
        "_save_here",
        lambda name, g, info=None, system=None: (
            saved.append((name, system)),
            rows.append({"name": name, "key": "wp:new"}),
        ),
    )
    monkeypatch.setattr(t_nav, "nav_start", lambda key: {"key": key})
    r = t_nav.ore_go(id=rec["id"])
    assert r["name"] == "原矿 铜 10-31 12:00 #abcd" and saved == [(r["name"], "Nyx")]


def test_here_hints_only_for_where_you_are(monkeypatch):
    """右上角线索只用在「坐标就是你现在的位置」时：粘贴的远处坐标不套用当前星系（S2 审查 2026-10-31）"""
    from sc_mining.tasks import navigation as t_nav

    pos = type("P", (), {})()
    pos.current = (0.0, (1e9, 0.0, 0.0), {})
    pos.hints = lambda: {"zone": "Pyro"}
    monkeypatch.setattr(t_nav, "_pos", pos)
    assert t_nav._hints_near((1e9 + 5000, 0.0, 0.0)) == {"zone": "Pyro"}
    assert t_nav._hints_near((5e9, 0.0, 0.0)) == {}
    pos.current = (0.0, None, None)
    assert t_nav._hints_near((1e9, 0.0, 0.0)) == {}


def test_here_watch_save_error_is_reported(monkeypatch):
    """「用当前位置新建」存路标出错：悬浮窗提示、写日志，线程不悄悄退出（S2 审查 2026-10-31）"""
    import time as _t
    from sc_mining.tasks import navigation as t_nav
    from sc_mining.navigation import navigate as n
    from sc_mining.system import showloc

    notes, logs = [], []
    monkeypatch.setattr(n, "read_clipboard", lambda: "old")
    monkeypatch.setattr(
        showloc, "wait_new_coords", lambda old, timeout: ((1.0, 2.0, 3.0), "new")
    )
    monkeypatch.setattr(
        t_nav,
        "_save_here",
        lambda name, g: (_ for _ in ()).throw(RuntimeError("路标文件坏了")),
    )
    monkeypatch.setattr(t_nav, "_note_hud", lambda *a: notes.append(a))
    monkeypatch.setattr(t_nav, "_wp_log", logs.append)
    monkeypatch.setattr(
        t_nav, "_HERE", {"name": "矿点", "until": _t.time() + 30, "thread": None}
    )
    t_nav._start_here_watch()
    t_nav._HERE["thread"].join(5)
    assert notes and "未保存" in notes[-1][1] and any("失败" in x for x in logs)


def test_nav_log_has_no_user_folder():
    """nav_log.txt 会进反馈包：用户目录换成 ~（S2 审查 2026-10-31）"""
    from sc_mining.tasks.navigation import _no_home

    s = _no_home(
        "File \"C:\\Users\\张 三\\AppData\\Local\\AT\\current\\x.py\", line 3 | c:/users/bob/a.json | 'D:\\\\Users\\\\x\\\\b'"
    )
    assert "张 三" not in s and "bob" not in s and "\\x\\" not in s
    assert "~\\AppData\\Local\\AT" in s and "~/a.json" in s


def test_last_position_written_at_most_every_30s(monkeypatch, tmp_path):
    """last_position.json 最多 30 秒写一次、原子写（以前 0.2 秒一次，S2 审查 2026-10-31）"""
    from sc_mining.navigation import navigate as n

    monkeypatch.setattr(n, "LAST", tmp_path / "last_position.json")
    monkeypatch.setattr(n, "_last_at", [0.0])
    n._remember((1.0, 2.0, 3.0), "Hurston")
    first = json.loads(n.LAST.read_text(encoding="utf-8"))
    n._remember((9.0, 9.0, 9.0), "Hurston")
    assert json.loads(n.LAST.read_text(encoding="utf-8")) == first and first["x"] == 1.0


def test_read_forward_returns_end_of_last_full_line(monkeypatch, tmp_path):
    """分块读 Game.log：返回最后一个完整行的结尾，下次不重读半行（S2 审查 2026-10-31）"""
    from sc_mining.navigation import position as P

    p = tmp_path / "Game.log"
    data = b"Inventory a\nxx\nInventory b\nhalf"
    p.write_bytes(data)
    fed = []
    st = type("S", (), {"feed": lambda self, line: fed.append(line)})()
    for chunk in (3, 5, 7, 1 << 20):
        fed.clear()
        monkeypatch.setattr(P, "CHUNK", chunk)
        assert P._read_forward(p, 0, st) == data.rfind(b"\n") + 1
        assert fed == ["Inventory a", "Inventory b"]


def test_pos_hints_use_latest_read_even_when_hovering():
    """悬停不动（坐标没变）时线索也要在：按最近一次读到的算，不按坐标最后一次变化算（复审 2026-10-31）"""
    import time as _t
    from sc_mining.app.engines.pos import _Pos

    p = object.__new__(_Pos)
    p.latest = (_t.time() - 60, (1.0, 2.0, 3.0), {"zone": "old"})
    p.current = (
        _t.time(),
        (1.0, 2.0, 3.0),
        {"zone": "keeger", "location": "", "solar_id": "862685702877"},
    )
    assert p.hints() == {"zone": "keeger", "location": "", "solar_id": "862685702877"}
    p.current = (_t.time() - 60, (1.0, 2.0, 3.0), {"zone": "keeger"})
    assert p.hints() == {}


def test_mark_here_prompts_and_no_double_wait(monkeypatch):
    """记路标热键：先在悬浮窗提示输入 /showlocation（挂到等完）；「用当前位置新建」已经在等时不再等第二份（第 4 批审查）"""
    import threading
    import time as _t
    from sc_mining.system import showloc
    from sc_mining.tasks import navigation as t_nav

    notes = []
    monkeypatch.setattr(
        t_nav, "_note_hud", lambda sec, text, secs=None: notes.append((sec, text, secs))
    )
    monkeypatch.setattr(t_nav, "_wp_log", lambda m: None)
    monkeypatch.setattr(showloc, "showlocation", lambda log=None: (None, "没读到"))
    monkeypatch.setattr(t_nav, "_HERE", {"name": None, "until": 0, "thread": None})
    assert t_nav.mark_here() == {"error": "没读到"}
    assert (
        notes[0][0] == "定位"
        and "/showlocation" in notes[0][1]
        and notes[0][2] == showloc.TYPE_WAIT
    )
    notes.clear()
    called = []
    monkeypatch.setattr(
        showloc, "showlocation", lambda log=None: called.append(1) or (None, "x")
    )
    ev = threading.Event()
    th = threading.Thread(target=ev.wait, args=(5,))
    th.start()
    monkeypatch.setattr(
        t_nav, "_HERE", {"name": "矿点", "until": _t.time() + 30, "thread": th}
    )
    try:
        assert t_nav.mark_here() == {"pending": True} and not called
        assert "矿点" in notes[-1][1]
    finally:
        ev.set()
        th.join(5)
