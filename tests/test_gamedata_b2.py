"""游戏数据层批 2：星图 / 位置 / 城市与空间站中转 / 地表导航 / 地名对照 改走游戏数据层

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），最小数据复用 test_gamedata_nav 的 _NAV_SOURCES；
不读真实 data/、不碰 userdata/、不联网。"""

import json
from contextlib import contextmanager

from tests.test_gamedata_nav import _NAV_SOURCES, _write_all


def _setup(monkeypatch, tmp_path, **override):
    """tmp_path 当 data/ 根、写最小源（物品 + 导航）；就绪标记、后台线程记录换成新的；星图文件路径指到 tmp_path"""
    import sc_mining.gamedata as G
    from sc_mining.core import paths
    from sc_mining.gamedata import _ready
    from sc_mining.navigation import starmap

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(_ready, "_state", {"done": None, "failed": None})
    monkeypatch.setattr(G, "_state", {"last_error": None, "warm_thread": None})
    monkeypatch.setattr(starmap, "CACHE", tmp_path / "starmap.json")
    _write_all(tmp_path, **override)
    return tmp_path


def _legacy_starmap(tmp_path):
    """以前 starmap.load() 的做法：读 starmap.json、套 starmap_fixes.json、bodies 补 name"""
    from sc_mining.navigation.starmap import fix_points

    data = json.loads((tmp_path / "starmap.json").read_text(encoding="utf-8"))
    fix_points(
        data, json.loads((tmp_path / "starmap_fixes.json").read_text(encoding="utf-8"))
    )
    for name, b in data["bodies"].items():
        b["name"] = name
    return data


# ---------------------------------------------------------------- Task 1：星图


def test_data_dict_shape_matches_legacy(monkeypatch, tmp_path):
    from sc_mining.navigation import starmap

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
    import sc_mining.gamedata as G
    from sc_mining.navigation import starmap

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
    import sc_mining.gamedata as G
    from sc_mining.navigation import starmap

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


def test_starmap_load_downloads_when_no_file(monkeypatch, tmp_path):
    """还没有 starmap.json：和以前一样先下载一次再读"""
    from sc_mining.navigation import starmap

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
    from sc_mining.navigation import position

    _setup(monkeypatch, tmp_path)
    p = position.find_point(internal="dup_x")
    assert p == dict(n="Dup A", i="DUP_X", sys="Pyro", t="Outpost", x=1.0, y=1.0, z=1.0)
    assert position.find_point(internal="Hur_L1")["x"] == 9.0  # 坐标改正后的
    assert position.find_point(internal="nope") is None


def test_find_point_name_norm(monkeypatch, tmp_path):
    from sc_mining.navigation import position

    _setup(monkeypatch, tmp_path)
    assert position.find_point(name="hurston-L1")["i"] == "HUR_L1"
    assert position.find_point(name="Dup B")["n"] == "Dup B"
    assert (
        position.find_point(internal="nope", name="Stanton Star")["n"] == "Stanton Star"
    )
    assert position.find_point(name="Nowhere") is None


def test_find_point_pyro_roman(monkeypatch, tmp_path):
    from sc_mining.navigation import position

    _setup(monkeypatch, tmp_path, **_more_points())
    assert position.find_point(name="Pyro III")["n"] == "Bloom"


def test_from_code_lagrange(monkeypatch, tmp_path):
    from sc_mining.navigation import position

    _setup(monkeypatch, tmp_path, **_more_points())
    assert position.from_code("RR_P1_L1")["n"] == "PYR1 L1"
    assert (
        position.from_code("RR_HUR_L1") is None
    )  # 斯坦顿按 Stanton1_L1 找，最小数据里没有


# ---------------------------------------------------------------- Task 3：地名对照


def _no_ini(monkeypatch):
    """汉化包当作没有（不读真实 data/loc），地点代号只剩 place_codes_zh；place_name 的缓存前后都清掉"""
    from sc_mining.navigation import position

    monkeypatch.setattr(position, "_ini_cache", {"ini": {}})
    position.place_name.cache_clear()


def test_poi_zh_extra_overrides(monkeypatch, tmp_path):
    from sc_mining.navigation import names

    _setup(monkeypatch, tmp_path)
    assert names.poi_zh("Lorville") == "洛维尔（新）"  # places_extra_zh 盖过 places_zh
    assert names.poi_zh("Everus Harbor") == "艾维拉斯港"


def test_poi_zh_strips_bracket_notes(monkeypatch, tmp_path):
    from sc_mining.navigation import names

    _setup(monkeypatch, tmp_path)
    assert names.poi_zh("Everus Harbor [F]") == "艾维拉斯港"
    assert names.poi_zh("Everus Harbor (missing)") == "艾维拉斯港"
    assert names.poi_zh("Nowhere") == ""


def test_place_name_prefix_shortest_then_first(monkeypatch, tmp_path):
    """斯坦顿拉格朗日站汉化包没有时，按 places_zh 里以「arcl1」开头的最短键；同样长取源里靠前的。只看 places_zh"""
    from sc_mining.navigation import position

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
        position.place_name.cache_clear()


def test_place_name_code_table_then_ini(monkeypatch, tmp_path):
    """地点代号：汉化包有就用汉化包的，没有再用随包的代号表（以前两份合成一张表、汉化包盖过代号表）"""
    from sc_mining.navigation import position

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
        position.place_name.cache_clear()


def test_zh_name_station_suffix_fallback(monkeypatch, tmp_path):
    from sc_mining.navigation import position

    _setup(monkeypatch, tmp_path, **{"places_zh.json": {"checkmate": "死局空间站"}})
    assert position._zh_name("Checkmate Station") == "死局空间站"
    assert position._zh_name("Unknown Station") == "Unknown Station"
