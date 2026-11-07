"""游戏数据层批 2：星图 / 位置 / 城市与空间站中转 / 地表导航 / 地名对照 改走游戏数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），最小数据复用 test_gamedata_nav 的 _NAV_SOURCES；
不读真实 data/、不碰 userdata/、不联网。"""

import json
from contextlib import contextmanager

from tests.test_gamedata_nav import _NAV_SOURCES, _write_all


def _setup(monkeypatch, tmp_path, **override):
    """tmp_path 当 data/ 根、写最小源（物品 + 导航）；就绪标记、后台线程记录换成新的；星图文件路径指到 tmp_path"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths
    from astral_toolkit.gamedata import _ready
    from astral_toolkit.navigation import starmap

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(_ready, "_state", {"done": None, "failed": None})
    monkeypatch.setattr(G, "_state", {"last_error": None, "warm_thread": None})
    monkeypatch.setattr(starmap, "CACHE", tmp_path / "starmap.json")
    _write_all(tmp_path, **override)
    return tmp_path


def _legacy_starmap(tmp_path):
    """以前 starmap.load() 的做法：读 starmap.json、套 starmap_fixes.json、bodies 补 name"""
    from astral_toolkit.navigation.starmap import fix_points

    data = json.loads((tmp_path / "starmap.json").read_text(encoding="utf-8"))
    fix_points(
        data, json.loads((tmp_path / "starmap_fixes.json").read_text(encoding="utf-8"))
    )
    for name, b in data["bodies"].items():
        b["name"] = name
    return data


# ---------------------------------------------------------------- Task 1：星图


def test_data_dict_shape_matches_legacy(monkeypatch, tmp_path):
    from astral_toolkit.navigation import starmap

    _setup(monkeypatch, tmp_path)
    d = starmap.load()
    assert set(d) == {"bodies", "pois", "points", "fetched"}
    assert d == _legacy_starmap(tmp_path)
    assert [p["n"] for p in d["points"]] == [
        "Stanton Star",
        "Hurston L1",
        "Dup A",
        "Dup B",
    ]  # 源顺序，同内部名两条都在
    assert d["points"][1]["x"] == 9.0  # 坐标改正套上了
    assert [q["qt"] for q in d["pois"]] == [0, 1, None]  # 没信标的 qt 原样是 None
    assert set(d["bodies"]["Hurston"]) == {
        "sys",
        "x",
        "y",
        "z",
        "rot",
        "adj",
        "r",
        "om",
        "grid",
        "name",
    }
    assert starmap.load() is d  # 同一版本同一个对象


def test_starmap_load_refreshes_after_rebuild(monkeypatch, tmp_path):
    """更新数据后导航立刻用新星图：换代后 load() 返回新内容"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.navigation import starmap

    _setup(monkeypatch, tmp_path)
    old = starmap.load()
    new_src = json.loads(json.dumps(_NAV_SOURCES["starmap.json"]))
    new_src["bodies"]["Hurston"]["x"] = 42.0
    new_src["fetched"] = "2026-11-02"
    with G.updating():
        (tmp_path / "starmap.json").write_text(json.dumps(new_src), encoding="utf-8")
    d = starmap.load()
    assert d is not old
    assert d["bodies"]["Hurston"]["x"] == 42.0 and d["fetched"] == "2026-11-02"


def test_starmap_update_runs_inside_updating(monkeypatch, tmp_path):
    """starmap.update() 写 starmap.json 在 gamedata.updating() 里（退出时重建库），联网不在里面"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.navigation import starmap

    _setup(monkeypatch, tmp_path)
    (tmp_path / "starmap.json").unlink()
    log = []
    fake = dict(
        source="starmap.space",
        fetched="2026-11-02",
        bodies={f"B{i}": {} for i in range(10)},
        pois=[{"qt": 1}] * 300,
        points=[],
    )
    monkeypatch.setattr(starmap, "_fetch", lambda path: log.append("fetch") or [])
    monkeypatch.setattr(starmap, "compact", lambda oc, pois: fake)

    @contextmanager
    def updating():
        log.append(("enter", starmap.CACHE.exists()))
        yield
        log.append(("exit", starmap.CACHE.exists()))

    monkeypatch.setattr(G, "updating", updating)
    starmap.update()
    assert log == ["fetch", "fetch", ("enter", False), ("exit", True)]


def test_starmap_update_reports_rebuild_failure(monkeypatch, tmp_path):
    """星图下载写好了、但出口重建库失败：不能再说「已更新」，要说还在用旧星图（整改第 1 批第 2 条）"""
    import builtins

    from astral_toolkit.gamedata import _build
    from astral_toolkit.navigation import starmap

    _setup(monkeypatch, tmp_path)
    fake = dict(
        source="starmap.space",
        fetched="2026-11-02",
        bodies={f"B{i}": {} for i in range(10)},
        pois=[{"qt": 1}] * 300,
        points=[],
    )
    monkeypatch.setattr(starmap, "_fetch", lambda path: [])
    monkeypatch.setattr(starmap, "compact", lambda oc, pois: fake)

    def boom():
        raise RuntimeError("建库炸了")

    monkeypatch.setattr(_build, "rebuild_if_needed", boom)
    said = []
    monkeypatch.setattr(
        builtins, "print", lambda *a, **k: said.append(" ".join(map(str, a)))
    )
    starmap.update()
    last = said[-1]
    assert (
        "已更新" not in last.split("：")[0] and "旧星图" in last and "建库炸了" in last
    )


def test_starmap_load_downloads_when_no_file(monkeypatch, tmp_path):
    """还没有 starmap.json：和以前一样先下载一次再读"""
    from astral_toolkit.navigation import starmap

    _setup(monkeypatch, tmp_path)
    src = (tmp_path / "starmap.json").read_text(encoding="utf-8")
    (tmp_path / "starmap.json").unlink()
    called = []

    def fake_update():
        called.append(1)
        (tmp_path / "starmap.json").write_text(src, encoding="utf-8")

    monkeypatch.setattr(starmap, "update", fake_update)
    d = starmap.load()
    assert called == [1] and "Hurston" in d["bodies"]


# ---------------------------------------------------------------- Task 2：按内部名 / 名字找点


def _more_points():
    """最小星图再加派罗的行星和拉格朗日点（Pyro3 → Bloom、P1_L1），给罗马数字和地点代码用"""
    sm = json.loads(json.dumps(_NAV_SOURCES["starmap.json"]))
    sm["points"] += [
        dict(n="Bloom", i="pyro3", sys="Pyro", t="Planet", x=7.0, y=7.0, z=0.0),
        dict(
            n="PYR1 L1", i="P1_L1", sys="Pyro", t="Lagrange Point", x=8.0, y=8.0, z=0.0
        ),
    ]
    return {"starmap.json": sm}


def test_find_point_internal_case_insensitive_first_match(monkeypatch, tmp_path):
    """内部名不分大小写；同一内部名两个点取源里第一个（商店「最近买点」靠它定位）"""
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path)
    p = position.find_point(internal="dup_x")
    assert p == dict(n="Dup A", i="DUP_X", sys="Pyro", t="Outpost", x=1.0, y=1.0, z=1.0)
    assert (position.find_point(internal="Hur_L1") or {})["x"] == 9.0  # 坐标改正后的
    assert position.find_point(internal="nope") is None


def test_find_point_name_norm(monkeypatch, tmp_path):
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path)
    assert (position.find_point(name="hurston-L1") or {})["i"] == "HUR_L1"
    assert (position.find_point(name="Dup B") or {})["n"] == "Dup B"
    p = position.find_point(internal="nope", name="Stanton Star")
    assert (p or {})["n"] == "Stanton Star"
    assert position.find_point(name="Nowhere") is None


def test_find_point_pyro_roman(monkeypatch, tmp_path):
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path, **_more_points())
    assert (position.find_point(name="Pyro III") or {})["n"] == "Bloom"


def test_from_code_lagrange(monkeypatch, tmp_path):
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path, **_more_points())
    assert (position.from_code("RR_P1_L1") or {})["n"] == "PYR1 L1"
    assert (
        position.from_code("RR_HUR_L1") is None
    )  # 斯坦顿按 Stanton1_L1、OOC_Stanton1_L1 找，最小数据里都没有


def _ooc_points():
    """星图现在的斯坦顿叫法（OOC_ 开头）：微科星和它的卫星卡利俄珀、HUR L1 拉格朗日点、弧星和它的 L4；
    最后一个和微科星同编号、排在后面（认源里第一个，不认它）"""
    sm = json.loads(json.dumps(_NAV_SOURCES["starmap.json"]))
    sm["points"] += [
        dict(
            n="Microtech",
            i="OOC_Stanton_4_Microtech",
            sys="Stanton",
            t="Planet",
            x=40.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="Calliope",
            i="OOC_Stanton_4a_Calliope",
            sys="Stanton",
            t="Planet",
            x=41.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="HUR L1",
            i="OOC_Stanton1_L1",
            sys="Stanton",
            t="Lagrange Point",
            x=12.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="ArcCorp",
            i="OOC_Stanton_3_ArcCorp",
            sys="Stanton",
            t="Planet",
            x=30.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="ARC L4",
            i="OOC_Stanton3_L4",
            sys="Stanton",
            t="Lagrange Point",
            x=33.0,
            y=3.0,
            z=0.0,
        ),
        dict(
            n="Microtech Dup",
            i="OOC_Stanton_4_MicrotechDup",
            sys="Stanton",
            t="Planet",
            x=99.0,
            y=0.0,
            z=0.0,
        ),
    ]
    return {"starmap.json": sm}


def test_from_code_stanton_ooc_names(monkeypatch, tmp_path):
    """星图里斯坦顿改叫 OOC_Stanton_4_Microtech、OOC_Stanton1_L1 以后，日志里的旧代码照样对得上（2026-11-07 老大在
    新巴贝奇发现物品查询不按远近排）：城市按星球 / 卫星的编号找（卫星不会认成星球），拉格朗日站按 OOC_ 加旧名找；
    星图里没有的照旧 None；给出去的点是一份新的，调用方改了不碰缓存"""
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path, **_ooc_points())
    position._ooc_bodies.cache_clear()
    p = position.from_code("Stanton4_NewBabbage")
    assert p is not None and p["i"] == "OOC_Stanton_4_Microtech" and p["x"] == 40.0
    p["x"] = -1.0
    assert (position.from_code("Stanton4_NewBabbage") or {}).get("x") == 40.0
    assert (position.from_code("Stanton4a_SomeOutpost") or {}).get(
        "i"
    ) == "OOC_Stanton_4a_Calliope"
    assert (position.from_code("RR_HUR_L1") or {}).get("i") == "OOC_Stanton1_L1"
    assert position.from_code("Stanton2_Orison") is None
    assert position.from_code("RR_CRU_L1") is None
    assert position._ooc_bodies.cache_info().currsize == 1
    position.reset_names()  # 汉化包 / 数据更新后清地名缓存时，星图编号表一起清
    assert position._ooc_bodies.cache_info().currsize == 0


def test_from_log_and_shop_point_stanton_ooc_names(monkeypatch, tmp_path):
    """在新巴贝奇开过库存（日志 Location[Stanton4_NewBabbage]）：现在的星图下照样知道你在微科星；
    弧星 L4 站上的商店换算到 L4 那个点、不是星球中心；只写了星球的商店照旧是星球"""
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path, **_ooc_points())
    position._ooc_bodies.cache_clear()
    log = tmp_path / "Game.log"
    log.write_text(
        "<2026-11-07T12:00:00.000Z> [Notice] <RequestLocationInventory> Player[X] "
        "requested inventory for Location[Stanton4_NewBabbage] [Team]\n",
        encoding="utf-8",
    )
    hit = position.from_log(log)
    assert hit is not None and hit[2]["i"] == "OOC_Stanton_4_Microtech"
    arc = position.shop_point(
        [
            "Stanton",
            "ArcCorp",
            "ArcCorp Lagrange Point 4",
            "",
            "ARC-L4 Faint Glen Station",
            "",
        ]
    )
    assert (arc or {}).get("i") == "OOC_Stanton3_L4"
    city = position.shop_point(["Stanton", "ArcCorp", "", "", "", "Area18"])
    assert (city or {}).get("i") == "OOC_Stanton_3_ArcCorp"


# ---------------------------------------------------------------- Task 3：地名对照


def _no_ini(monkeypatch):
    """汉化包当作没有（不读真实 data/loc），地点代号只剩 place_codes_zh；place_name 的缓存前后都清掉"""
    from astral_toolkit.navigation import position

    monkeypatch.setattr(position, "_ini_cache", {"ini": {}})
    position._place_name.cache_clear()


def test_poi_zh_extra_overrides(monkeypatch, tmp_path):
    from astral_toolkit.navigation import names

    _setup(monkeypatch, tmp_path)
    assert names.poi_zh("Lorville") == "洛维尔（新）"  # places_extra_zh 盖过 places_zh
    assert names.poi_zh("Everus Harbor") == "艾维拉斯港"


def test_poi_zh_strips_bracket_notes(monkeypatch, tmp_path):
    from astral_toolkit.navigation import names

    _setup(monkeypatch, tmp_path)
    assert names.poi_zh("Everus Harbor [F]") == "艾维拉斯港"
    assert names.poi_zh("Everus Harbor (missing)") == "艾维拉斯港"
    assert names.poi_zh("Nowhere") == ""


def test_place_name_prefix_shortest_then_first(monkeypatch, tmp_path):
    """斯坦顿拉格朗日站汉化包没有时，按 places_zh 里以「arcl1」开头的最短键；同样长取源里靠前的。只看 places_zh"""
    from astral_toolkit.navigation import position

    _setup(
        monkeypatch,
        tmp_path,
        **{
            "places_zh.json": {"arcl1zzz": "长", "arcl1b": "乙", "arcl1a": "甲"},
            "places_extra_zh.json": {"arcl1": "extra 不算", "newbabbage": "extra 不算"},
            "place_codes_zh.json": {},
        },
    )
    _no_ini(monkeypatch)
    try:
        assert position.place_name("RR_ARC_L1") == "乙"
        assert position.place_name("RR_HUR_L1") == "HUR-L1"
        assert position.place_name("Stanton4_NewBabbage") == "New Babbage"
    finally:
        position._place_name.cache_clear()


def test_place_name_code_table_then_ini(monkeypatch, tmp_path):
    """地点代号：汉化包有就用汉化包的，没有再用随包的代号表（以前两份合成一张表、汉化包盖过代号表）"""
    from astral_toolkit.navigation import position

    _setup(
        monkeypatch,
        tmp_path,
        **{"place_codes_zh.json": {"rr_p3": "代号表名 (Orbituary)", "rr_p6": "废墟"}},
    )
    _no_ini(monkeypatch)
    try:
        assert position.ini_name("RR_P3") == "代号表名"
        monkeypatch.setattr(position, "_ini_cache", {"ini": {"rr_p3": "汉化包名"}})
        assert position.ini_name("RR_P3") == "汉化包名"
        assert position.ini_name("RR_P6") == "废墟"
        assert position.ini_name("RR_P9") == ""
    finally:
        position._place_name.cache_clear()


def test_place_name_follows_data_version(monkeypatch, tmp_path):
    """汉化包更新时 reset_names 在 updating() 里、库还没换代；别的线程这时查到旧名记进缓存，
    换代以后 place_name 也要用上新库里的地名，不能一直显示旧的"""
    from astral_toolkit import gamedata
    from astral_toolkit.navigation import position

    _setup(
        monkeypatch,
        tmp_path,
        **{"places_zh.json": {"arcl1a": "旧名"}, "place_codes_zh.json": {}},
    )
    _no_ini(monkeypatch)
    try:
        assert position.place_name("RR_ARC_L1") == "旧名"
        with gamedata.updating():
            (tmp_path / "places_zh.json").write_text(
                json.dumps({"arcl1a": "新名"}, ensure_ascii=False), encoding="utf-8"
            )
            position._place_name.cache_clear()
            # 库还没换代，查到的还是旧库
            assert position.place_name("RR_ARC_L1") == "旧名"
        assert position.place_name("RR_ARC_L1") == "新名"
    finally:
        position._place_name.cache_clear()


def test_zh_name_station_suffix_fallback(monkeypatch, tmp_path):
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path, **{"places_zh.json": {"checkmate": "死局空间站"}})
    assert position._zh_name("Checkmate Station") == "死局空间站"
    assert position._zh_name("Unknown Station") == "Unknown Station"


# ---------------------------------------------------------------- Task 4：城市地点、设施、空间站电梯


def test_city_places_equal_to_legacy_transform(monkeypatch, tmp_path):
    """建库时变换好的城市地点读出来，和以前 _city_rows(city_places.json) 逐条相等（同名加序号、重复 id 加 +、@sys 空间点、up）"""
    from astral_toolkit.navigation import transit

    _setup(monkeypatch, tmp_path)
    got = transit.city_places()
    legacy = transit._city_rows(_NAV_SOURCES["city_places.json"])
    assert got == legacy
    assert [q["zh"] for q in got] == ["公寓大堂", "公寓大堂 2", "", "轨道店"]
    assert [q["id"] for q in got] == ["lor_hab", "lor_hab2", "lor_hab+", "orb"]
    assert got[2]["up"] == (0.0, 0.0, 1.0) and got[3]["b"] == "@Stanton"
    assert got[0]["t"] == "City" and got[0]["qt"] == 0 and got[0]["kinds"] == ["住宿"]
    assert transit.city_places() is got  # 同一版本同一个列表


def test_station_lifts_equal_to_legacy(monkeypatch, tmp_path):
    from astral_toolkit.navigation import transit

    _setup(monkeypatch, tmp_path)
    got = transit.station_lifts()
    assert got == transit._lift_rows(_NAV_SOURCES["station_lifts.json"])
    assert list(got) == ["rr_hur_l1"]  # ok=False 的整站丢


def test_amenity_targets_resolves_three_ref_kinds(monkeypatch, tmp_path):
    """设施的 poi / point(_id) / body 三种引用按当前星图回查；星图单独更新后，设施跟着用新坐标"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.navigation import transit

    amen = _NAV_SOURCES["place_amenities.json"] + [
        {
            "en": "Lorville",
            "zh": "",
            "kinds": ["医疗"],
            "rec": "",
            "ref": {"poi": "Lorville"},
        }
    ]
    _setup(monkeypatch, tmp_path, **{"place_amenities.json": amen})
    assert transit.amenity_targets("医疗") == [
        dict(
            b="Hurston",
            n="Everus Harbor",
            zh="艾维拉斯港",
            t="Orbital Station",
            qt=1,
            x=-507.7,
            y=-903.4,
            z=496.4,
        ),  # poi 找不到：用 body + local 造轨道站
        dict(
            b="@Stanton",
            sys="Stanton",
            space=True,
            n="Pyro Body Only",
            zh="",
            t="Orbital Station",
            qt=1,
            x=0.001,
            y=0.0,
            z=0.0,
        ),  # 只有 body：天体坐标 /1000
        dict(b="Hurston", n="Lorville", t="City", x=3.0, y=4.0, z=0.0, qt=1),  # poi
    ]  # Lorville Clinic 只有 city 引用：没有坐标，不列
    shop = transit.amenity_targets("商店")
    assert [(q["n"], q["x"]) for q in shop] == [("HUR-L1 Shop", 0.009)]  # point_id
    with G.updating():
        (tmp_path / "starmap_fixes.json").write_text(
            json.dumps({"Hurston L1": [12.0, 12.0, 12.0]}), encoding="utf-8"
        )
    assert transit.amenity_targets("商店")[0]["x"] == 0.012


def test_transit_does_not_read_json(monkeypatch, tmp_path):
    """数据目录里只有游戏数据库、没有那几份 JSON：城市地点、电梯、设施照样能用"""
    import shutil

    from astral_toolkit.core import paths
    from astral_toolkit.gamedata import _ready
    from astral_toolkit.navigation import starmap, transit

    a = _setup(monkeypatch, tmp_path / "a")
    want = (
        transit.city_places(),
        transit.station_lifts(),
        transit.amenity_targets("商店"),
    )
    b = tmp_path / "b"
    shutil.copytree(a / "gamedata", b / "gamedata")
    monkeypatch.setattr(paths, "DATA", b)
    monkeypatch.setattr(_ready, "_state", {"done": str(b / "gamedata"), "failed": None})
    monkeypatch.setattr(
        starmap, "CACHE", a / "starmap.json"
    )  # 只给 load() 判断「下载过没有」
    got = (
        transit.city_places(),
        transit.station_lifts(),
        transit.amenity_targets("商店"),
    )
    assert got == want and len(got[0]) == 4 and got[1] and got[2]


# ---------------------------------------------------------------- Task 5：挖矿点、死导入


def test_mining_spots_divides_by_1000_and_merges(monkeypatch, tmp_path):
    """挖矿点从库读：坐标米 → 千米（保留 3 位），没有英文名用 id；挖矿点更新后跟着变"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.navigation import navigate

    spots = _NAV_SOURCES["mining_spots.json"] + [
        dict(
            id="x2",
            sys="Pyro",
            zh="",
            en="",
            kind="cluster",
            area="",
            x=1000.0,
            y=0.0,
            z=0.0,
        )
    ]
    _setup(monkeypatch, tmp_path, **{"mining_spots.json": spots})
    got = navigate.mining_spots()
    assert got == [
        dict(
            b="@Pyro",
            sys="Pyro",
            space=True,
            n="RMB-DARI",
            zh="远矿站-DARI",
            t="Mining Spot",
            x=-13.521,
            y=12.915,
            z=-0.149,
            qt=1,
            rocks=None,
        ),
        dict(
            b="@Pyro",
            sys="Pyro",
            space=True,
            n="x2",
            zh="",
            t="Mining Spot",
            x=1.0,
            y=0.0,
            z=0.0,
            qt=1,
            rocks=None,
        ),
    ]  # 最小星图里没有拉格朗日点：只有这两条
    assert navigate.mining_spots() is got
    with G.updating():
        (tmp_path / "mining_spots.json").write_text(
            json.dumps(spots[:1]), encoding="utf-8"
        )
    assert [q["n"] for q in navigate.mining_spots()] == ["RMB-DARI"]


def test_mining_spots_skips_row_without_name(monkeypatch, tmp_path):
    """挖矿点英文名和 id 都空：跳过这一条，搜索不崩（以前 r["id"] 抛 KeyError 被吞，也是丢这一条）"""
    from astral_toolkit.navigation import navigate

    nameless = dict(
        sys="Pyro", zh="", en="", kind="cluster", area="", x=1000.0, y=0.0, z=0.0
    )
    _setup(
        monkeypatch,
        tmp_path,
        **{"mining_spots.json": _NAV_SOURCES["mining_spots.json"] + [nameless]},
    )
    assert [q["n"] for q in navigate.mining_spots()] == ["RMB-DARI"]
    hits, total = navigate.search("远矿站")
    assert [q["n"] for q in hits] == ["RMB-DARI"] and total == 1


def test_search_without_db_still_searches(monkeypatch, tmp_path):
    """调用方自己传星图、游戏数据库建不出来：照常搜（地名退化成空），不抛（整改第 1 批第 1 条）"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.core import paths
    from astral_toolkit.gamedata import _ready
    from astral_toolkit.navigation import navigate

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(paths, "DATA", empty)  # 没有任何源：建不出库
    monkeypatch.setattr(_ready, "_state", {"done": None, "failed": None})
    monkeypatch.setattr(G, "_state", {"last_error": None, "warm_thread": None})
    monkeypatch.setattr(navigate, "waypoints", lambda: [])
    data = {
        "bodies": {"ArcCorp": {"r": 800000.0}},
        "pois": [dict(b="ArcCorp", n="Area18", t="City", x=0.0, y=0.0, z=0.0, qt=1)],
        "points": [],
    }
    hits, total = navigate.search("area18", data)
    assert [q["n"] for q in hits] == ["Area18"] and total == 1


def test_navigate_has_no_starmap_private_imports():
    """星图、地名、城市地点以前的读文件缓存（_data / _data_stamp / _places_zh / _city / _amen …）都删干净了"""
    from astral_toolkit.navigation import names, navigate, starmap, transit

    for mod, gone in (
        (
            navigate,
            (
                "_data",
                "_data_stamp",
                "_files_stamp",
                "_apply_fixes",
                "_places_zh",
                "_city",
                "_amen",
            ),
        ),
        (starmap, ("_data", "_data_stamp", "_files_stamp", "_apply_fixes")),
        (names, ("_places_zh",)),
        (transit, ("_city", "_amen")),
    ):
        for name in gone:
            assert not hasattr(mod, name), f"{mod.__name__}.{name}"


def test_amenity_targets_pins_one_snapshot(monkeypatch, tmp_path):
    """设施表和城里的点钉在同一个快照里：星图取好之后整个过程只读一次清单（收口 2，待做 ⑰）"""
    from astral_toolkit.gamedata import _db
    from astral_toolkit.navigation import transit
    from astral_toolkit.navigation import starmap as sm

    _setup(monkeypatch, tmp_path)
    data = sm.load()
    real = _db.read_manifest
    n = []
    monkeypatch.setattr(
        _db, "read_manifest", lambda: (n.append(1), real())[1]
    )  # 快照 / version() 都经 _db 读清单
    transit.amenity_targets("医疗", data)
    assert n == [1]
