"""游戏数据层批 2：星图 / 位置 / 城市与空间站中转 / 地表导航 / 地名对照 改走游戏数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），最小数据复用 test_gamedata_nav 的 _NAV_SOURCES；
不读真实 data/、不碰 userdata/、不联网。"""

import json

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


def test_starmap_load_without_file_waits_for_pack(monkeypatch, tmp_path):
    """还没有 starmap.json：不下载（2026-11-13 起星图只跟数据包来），明说等数据包"""
    from astral_toolkit.core import net
    from astral_toolkit.navigation import starmap
    from tests.minipytest import raises

    _setup(monkeypatch, tmp_path)
    (tmp_path / "starmap.json").unlink()
    sent = []
    monkeypatch.setattr(net, "read", lambda *a, **k: sent.append(a) or b"{}")
    with raises(RuntimeError) as e:
        starmap.load()
    assert "数据包" in str(e.value) and sent == []


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


def test_stanton_old_and_new_names_mixed(monkeypatch, tmp_path):
    """星球是老叫法（Stanton3）、拉格朗日点是新叫法（OOC_Stanton3_L4），或者反过来：拉格朗日站商店照样找得到；
    新旧两种都有时先认老叫法（和以前一样，from_code 也是）"""
    from astral_toolkit.navigation import position

    sm = json.loads(json.dumps(_NAV_SOURCES["starmap.json"]))
    sm["points"] += [
        dict(
            n="ArcCorp", i="Stanton3", sys="Stanton", t="Planet", x=30.0, y=0.0, z=0.0
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
            n="Crusader",
            i="OOC_Stanton_2_Crusader",
            sys="Stanton",
            t="Planet",
            x=20.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="CRU L1",
            i="Stanton2_L1",
            sys="Stanton",
            t="Lagrange Point",
            x=21.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="CRU L1 New",
            i="OOC_Stanton2_L1",
            sys="Stanton",
            t="Lagrange Point",
            x=22.0,
            y=0.0,
            z=0.0,
        ),
    ]
    _setup(monkeypatch, tmp_path, **{"starmap.json": sm})
    position._ooc_bodies.cache_clear()
    arc = position.shop_point(
        ["Stanton", "ArcCorp", "ArcCorp Lagrange Point 4", "", "", ""]
    )
    assert (arc or {}).get("i") == "OOC_Stanton3_L4"
    cru = position.shop_point(
        ["Stanton", "Crusader", "Crusader Lagrange Point 1", "", "", ""]
    )
    assert (cru or {}).get("i") == "Stanton2_L1"
    assert (position.from_code("RR_CRU_L1") or {}).get("i") == "Stanton2_L1"


def _more_place_points():
    """老大日志里出现过、以前认不出的几种地点用到的星图点（内部名照真实星图）；加一个内部名就叫 Nyx 的点，
    看 Nyx_Levski 是不是先认列夫斯基；派罗的 Bloom（pyro3）给派罗近轨道站用"""
    sm = json.loads(json.dumps(_NAV_SOURCES["starmap.json"]))
    sm["points"] += [
        dict(
            n="Hurston",
            i="OOC_Stanton_1_Hurston",
            sys="Stanton",
            t="Planet",
            x=10.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="Jumppoint Magnus",
            i="OOC_JumpPoint_stanton_magnus",
            sys="Stanton",
            t="Jumppoint",
            x=50.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="Jumppoint Pyro",
            i="OOC_JumpPoint_stanton_pyro",
            sys="Stanton",
            t="Jumppoint",
            x=51.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="Pyro - Nyx Jump Point",
            i="Pyro_Gate_Nyx",
            sys="Pyro",
            t="Jumppoint",
            x=55.0,
            y=0.0,
            z=0.0,
        ),
        dict(
            n="Nyx - Castra Jump Point",
            i="jumppoint_nyx_castra",
            sys="Nyx",
            t="Jumppoint",
            x=60.0,
            y=0.0,
            z=0.0,
        ),
        dict(n="Nyx Star", i="Nyx", sys="Nyx", t="Star", x=65.0, y=0.0, z=0.0),
        dict(
            n="Delamar",
            i="glaciemring_segment_levski",
            sys="Nyx",
            t="Planet",
            x=70.0,
            y=0.0,
            z=0.0,
        ),
        dict(n="Bloom", i="pyro3", sys="Pyro", t="Planet", x=80.0, y=0.0, z=0.0),
    ]
    return {"starmap.json": sm}


def test_from_code_leo_jump_points_and_levski(monkeypatch, tmp_path):
    """老大日志里以前认不出的：行星近轨道站 RR_HUR_LEO、派罗的 RR_P3_LEO 算星球；JUMP 表里有的照旧按名字找，表里没有、或按名字找不到的
    按两个星系名找；Nyx_Levski 先认列夫斯基（星图里有内部名叫 Nyx 的点也不认成它）；对不上的照旧 None"""
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path, **_more_place_points())
    position._ooc_bodies.cache_clear()
    assert (position.from_code("RR_HUR_LEO") or {}).get("i") == "OOC_Stanton_1_Hurston"
    assert position.from_code("RR_CRU_LEO") is None  # 十字军不在这份星图里
    assert (position.from_code("RR_P3_LEO") or {}).get("i") == "pyro3"
    assert position.from_code("RR_P6_LEO") is None  # Terminus 不在这份星图里
    assert (position.from_code("RR_JP_StantonMagnus") or {}).get(
        "i"
    ) == "OOC_JumpPoint_stanton_magnus"
    assert (position.from_code("RR_JP_NyxCastra") or {}).get(
        "i"
    ) == "jumppoint_nyx_castra"
    assert (position.from_code("RR_JP_PyroNyx") or {}).get("i") == "Pyro_Gate_Nyx"
    assert (position.from_code("RR_JP_StantonPyro") or {}).get(
        "i"
    ) == "OOC_JumpPoint_stanton_pyro"
    assert position.from_code("RR_JP_Weird") is None
    assert position.from_code("RR_JP_StantonMagnusX") is None
    assert (position.from_code("Nyx_Levski") or {}).get(
        "i"
    ) == "glaciemring_segment_levski"


def test_from_log_this_session_unknown_does_not_use_last_session(monkeypatch, tmp_path):
    """这次游戏有位置信号、但认不出：当不知道，不退回上一局（上一局在新巴贝奇，人在别处按 F6 不能拿新巴贝奇对账）；
    这次游戏一条位置信号都没有：照旧用上一局的"""
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path, **_ooc_points())
    position._ooc_bodies.cache_clear()
    monkeypatch.setattr(position, "_save_ids", lambda: None)
    backups = tmp_path / "logbackups"
    backups.mkdir()
    line = (
        "<2026-11-07T12:00:00.000Z> [Notice] <RequestLocationInventory> Player[X] "
        "requested inventory for Location[{}] [Team]\n"
    )
    (backups / "old.log").write_text(
        line.format("Stanton4_NewBabbage"), encoding="utf-8"
    )
    now = tmp_path / "Game.log"
    now.write_text(line.format("RR_ZZ_Unknown"), encoding="utf-8")
    assert position.from_log(now) is None
    quiet = tmp_path / "Game2.log"
    quiet.write_text("<2026-11-07T12:00:00.000Z> [Notice] 别的事\n", encoding="utf-8")
    hit = position.from_log(quiet)
    assert hit is not None and hit[2]["i"] == "OOC_Stanton_4_Microtech"


def test_point_zh_stanton_lagrange_ooc_name(monkeypatch):
    """星图里斯坦顿拉格朗日点现在叫 OOC_Stanton3_L1：导航地名照样拿到汉化包里的站名（以前只认 Stanton3_L1，退回英文）"""
    from astral_toolkit.navigation import names as N
    from astral_toolkit.navigation import position

    fake = {"RR_ARC_L1": "弧 L1 广袤森林站"}
    monkeypatch.setattr(position, "ini_name", lambda k: fake.get(k, ""))
    for i in ("OOC_Stanton3_L1", "Stanton3_L1"):
        p = dict(t="Lagrange Point", i=i, n="ARC L1")
        assert N.point_zh(p) == "弧 L1 广袤森林站"


_STATION_ROWS = [
    dict(city="rr_jp_stantonmagnus", city_zh="尼克斯星门", site_en="Nyx Gateway"),
    dict(city="rr_jp_nyxcastra", city_zh="斯坦顿星门", site_en="Stanton Gateway"),
    dict(city="rr_jp_pyrostanton", city_zh="斯坦顿星门", site_en="Stanton Gateway"),
    dict(city="rr_jp_stantonpyro", city_zh="派罗星门", site_en="Pyro Gateway"),
    dict(city="rr_hur_leo", city_zh="埃弗勒斯空间站", site_en="Everus Harbor"),
    dict(city="rr_p3_leo", city_zh="", site_en="Orbituary"),
]  # 照真实的站内地点表（city_places）：斯坦顿和尼克斯之间的星门建在了原来马格努斯（斯坦顿这头）、卡斯塔（尼克斯这头）跳跃点的位置


def test_place_name_gateway_and_leo_stations(monkeypatch, tmp_path):
    """星门站、行星近轨道站的地点名查游戏数据库的站内地点表（不能按代码里的星系名拼：RR_JP_StantonMagnus 是尼克斯星门、
    RR_JP_NyxCastra 是斯坦顿星门）；没有中文用英文站名；表里没有、游戏数据库不可用照旧"""
    from astral_toolkit.gamedata import GamedataError
    from astral_toolkit.gamedata import places as gd_places
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(gd_places, "city_places", lambda snap=None: _STATION_ROWS)
    position._place_name.cache_clear()
    try:
        assert position.place_name("RR_JP_StantonMagnus") == "尼克斯星门"
        assert position.place_name("RR_JP_NyxCastra") == "斯坦顿星门"
        assert position.place_name("RR_JP_StantonPyro") == "派罗星门"
        assert position.place_name("RR_HUR_LEO") == "埃弗勒斯空间站"
        assert position.place_name("RR_P3_LEO") == "Orbituary"  # 没有中文：英文站名
        assert (
            position.place_name("RR_JP_PyroNyx") == "Pyro - Nyx Jump Point"
        )  # 表里没有：照旧
        assert position.place_name("RR_MIC_LEO") == "MIC LEO"  # 表里没有：照旧

        def down(*a, **k):
            raise GamedataError("游戏数据库不可用")

        monkeypatch.setattr(gd_places, "city_places", down)
        position._place_name.cache_clear()
        assert position.place_name("RR_HUR_LEO") == "HUR LEO"
    finally:
        position._place_name.cache_clear()


def _stock_places(monkeypatch, raw, zh):
    """盘点地点列表换成给定的几个站（中文名按 zh 表），缓存换新的"""
    from astral_toolkit.crafting import stockplaces as SP
    from astral_toolkit.gamedata._cache import VersionCache
    from astral_toolkit.navigation import navigate

    monkeypatch.setattr(navigate, "poi_zh", lambda en: zh.get(en))
    monkeypatch.setattr(SP, "_PLACES", VersionCache())
    monkeypatch.setattr(SP, "_INDEX", VersionCache(identity=True))
    monkeypatch.setattr(SP, "_raw_places", lambda: list(raw))
    return SP


def test_gateway_and_leo_names_match_stock_places(monkeypatch, tmp_path):
    """日志代码 → 地点名 → 盘点地点列表（开始盘点就是这么认地点的）：星门站、近轨道站都对上列表里的站，同名的按星系分"""
    from astral_toolkit.gamedata import places as gd_places
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(gd_places, "city_places", lambda snap=None: _STATION_ROWS)
    SP = _stock_places(
        monkeypatch,
        [
            ("Stanton", "Hurston", "", "Everus Harbor", False),
            ("Stanton", "", "", "Nyx Gateway (Stanton)", False),
            ("Pyro", "", "", "Nyx Gateway (Pyro)", False),
            ("Pyro", "", "", "Stanton Gateway (Pyro)", False),
            ("Nyx", "", "", "Stanton Gateway (Nyx)", False),
        ],
        {
            "Everus Harbor": "埃弗勒斯空间站",
            "Nyx Gateway (Stanton)": "尼克斯星门",
            "Nyx Gateway (Pyro)": "尼克斯星门",
            "Stanton Gateway (Pyro)": "斯坦顿星门",
            "Stanton Gateway (Nyx)": "斯坦顿星门",
        },
    )
    position._place_name.cache_clear()
    try:
        for code, sysname, label in [
            ("RR_JP_StantonMagnus", "Stanton", "尼克斯星门（斯坦顿）"),
            ("RR_JP_NyxCastra", "Nyx", "斯坦顿星门（尼克斯）"),
            ("RR_JP_PyroStanton", "Pyro", "斯坦顿星门（派罗）"),
            ("RR_HUR_LEO", "Stanton", "埃弗勒斯空间站"),
        ]:
            got = SP.match(position.place_name(code), sysname) or {}
            assert got.get("label") == label, code
    finally:
        position._place_name.cache_clear()


def test_old_gateway_names_match_gateway_places(monkeypatch, tmp_path):
    """派罗、尼克斯那几个星门站以前的自动地点名（「斯坦顿 - 派罗 跳跃点」这类，盘点记成了自定义地点）：改叫站名以后，
    旧名字下的库存记录照样归到星门站（库存页、盘点对账都按 match 认地点，不带星系）"""
    _setup(monkeypatch, tmp_path)
    SP = _stock_places(
        monkeypatch,
        [
            ("Stanton", "", "", "Pyro Gateway (Stanton)", False),
            ("Pyro", "", "", "Stanton Gateway (Pyro)", False),
            ("Pyro", "", "", "Nyx Gateway (Pyro)", False),
            ("Nyx", "", "", "Pyro Gateway (Nyx)", False),
        ],
        {},
    )
    for old, en in [
        ("斯坦顿 - 派罗 跳跃点", "Pyro Gateway (Stanton)"),
        ("Stanton-Pyro Jump Point", "Pyro Gateway (Stanton)"),
        ("Pyro-Stanton Jump Point", "Stanton Gateway (Pyro)"),
        ("Pyro - Nyx Jump Point", "Nyx Gateway (Pyro)"),
        ("Jumppoint_Nyx_Pyro", "Pyro Gateway (Nyx)"),
    ]:
        assert (SP.match(old) or {}).get("en") == en, old


def test_ooc_body_without_version_or_database(monkeypatch, tmp_path):
    """拿不到游戏数据库的版本号时现查、不缓存（不然数据换了还用旧表）；游戏数据库不可用时给 None，不往外抛"""
    from astral_toolkit.gamedata import GamedataError
    from astral_toolkit.gamedata import starmap as gd_starmap
    from astral_toolkit.navigation import position

    _setup(monkeypatch, tmp_path, **_ooc_points())
    position._ooc_bodies.cache_clear()
    monkeypatch.setattr(position, "_data_version", lambda: None)
    assert (position._ooc_body("Stanton4") or {}).get("i") == "OOC_Stanton_4_Microtech"
    assert position._ooc_bodies.cache_info().currsize == 0

    def down(*a, **k):
        raise GamedataError("游戏数据库不可用")

    monkeypatch.setattr(gd_starmap, "data_dict", down)
    assert position._ooc_body("Stanton4") is None


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


def test_from_log_reads_each_new_part_once_when_called_together(monkeypatch, tmp_path):
    """窗口每秒查状态、开始盘点、库存页同时调 from_log：同一段新日志只读一次（11-09 加锁前两边可能一起往前读）"""
    import threading
    import time as _time
    from pathlib import Path

    from astral_toolkit.navigation import position

    log = tmp_path / "Game.log"
    log.write_text("x" * 100, encoding="utf-8")
    calls = []

    def slow_read(path, pos, state):
        calls.append(pos)
        _time.sleep(0.2)  # 读得慢：另一个调用这时进来
        return Path(path).stat().st_size

    monkeypatch.setattr(position, "_read_forward", slow_read)
    monkeypatch.setattr(position, "_from_backups", lambda path: None)
    monkeypatch.setattr(position, "_log_cache", {})
    ts = [threading.Thread(target=position.from_log, args=(log,)) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(5)
    assert calls == [0]
