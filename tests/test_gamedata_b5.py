"""游戏数据层批 5：采矿石头表、挖矿点、飞船信号、精炼站加成改走数据层

全部用 tmp_path 当 data/ 根，不读真实 data/、不写 userdata/、不联网。"""

import json

from tests.test_gamedata_b1 import _count_updating, _fake_data_module, _setup
from tests.test_gamedata_mining import _MINING_SOURCES

_ROCKS = {
    "tiers": {"common": {"p_cluster": 100.0, "sizes": [[0.1, 6, 6]]}},
    "ores": {"Iron": {"sig": 4285, "tier": "common", "zh": "铁"}},
    "areas": {"A": {"Iron": 18}, "B": {"Iron": 18.0}, "Empty": {}},
    "contains": {"Iron": ["Iron", "Quartz"]},
    "version": "4.10",
}
_SHIPS = {
    "note": "n",
    "ships": [
        {"name": "A", "cs": [1000, 2000, 3000], "em_max": 100, "ir_max": 0, "x": 1},
        {"name": "B", "cs": [1000, 2000, 3000], "em_max": 0, "ir_max": 50, "zh": "乙"},
        "junk",
        {"name": "C", "cs": [1000.0, 2500.0, 3500.5], "em_max": 0, "ir_max": 0},
        {"name": "D", "cs": [9000, 9500, 9900], "em_max": 0, "ir_max": 0},
    ],
}
_PRICES = {
    "prices": {"Aluminum": {"Area18": 3800}},
    "yields": {
        "ARC-L1": {"Aluminum": 5},
        "CRU-L1": {"Aluminum": 2.5},
        "Empty": {},
        "Bad": ["junk"],
    },
}


def _src(**override):
    return {
        "mining_rocks.json": _ROCKS,
        "ship_signatures.json": _SHIPS,
        "prices.json": _PRICES,
        **override,
    }


def _write(tmp_path, name, obj):
    """改写一份源（obj 是 str 就原样写）"""
    (tmp_path / name).write_text(
        obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8"
    )


# ---------------------------------------------------------------- Task 1：topic


def test_rocks_roundtrip_same_shape(monkeypatch, tmp_path):
    import sc_mining.gamedata as G

    _setup(monkeypatch, tmp_path, **_src())
    assert G.mining.rocks() == _ROCKS


def test_rocks_three_states(monkeypatch, tmp_path):
    import sc_mining.gamedata as G

    _setup(monkeypatch, tmp_path)  # 无文件
    assert G.mining.rocks() == {}
    for bad in ("{坏", []):
        with G.updating():
            _write(tmp_path, "mining_rocks.json", bad)
        assert G.mining.rocks() == {}
    with G.updating():
        _write(tmp_path, "mining_rocks.json", {"areas": {}, "ores": {}})
    assert G.mining.rocks() == {"areas": {}, "ores": {}}  # 没有 contains 段就没有这个键


def test_int_float_types_kept(monkeypatch, tmp_path):
    import sc_mining.gamedata as G

    _setup(monkeypatch, tmp_path, **_src())
    r = G.mining.rocks()["areas"]
    assert type(r["A"]["Iron"]) is int and type(r["B"]["Iron"]) is float
    y = G.prices.refinery_yields()
    assert type(y["ARC-L1"]["Aluminum"]) is int
    assert type(y["CRU-L1"]["Aluminum"]) is float
    s = G.mining.ship_signatures()
    assert type(s[0]["cs"][0]) is int and type(s[2]["cs"][0]) is float


def test_rocks_and_ships_cached_per_version(monkeypatch, tmp_path):
    import sc_mining.gamedata as G

    _setup(monkeypatch, tmp_path, **_src())
    r, s = G.mining.rocks(), G.mining.ship_signatures()
    assert G.mining.rocks() is r and G.mining.ship_signatures() is s
    with G.updating():
        _write(tmp_path, "mining_rocks.json", {"areas": {"N": {}}})
        _write(tmp_path, "ship_signatures.json", {"ships": []})
    assert G.mining.rocks() == {"areas": {"N": {}}}
    assert G.mining.ship_signatures() == ()


def test_ship_signatures_order_and_skip_non_dict(monkeypatch, tmp_path):
    import sc_mining.gamedata as G

    _setup(monkeypatch, tmp_path)
    assert G.mining.ship_signatures() == ()  # 无文件
    with G.updating():
        _write(tmp_path, "ship_signatures.json", _SHIPS)
    assert list(G.mining.ship_signatures()) == [
        s for s in _SHIPS["ships"] if isinstance(s, dict)
    ]


def test_refinery_yields_fresh_dicts_and_skip_non_dict(monkeypatch, tmp_path):
    import sc_mining.gamedata as G

    _setup(monkeypatch, tmp_path, **_src())
    a, b = G.prices.refinery_yields(), G.prices.refinery_yields()
    assert list(a) == ["ARC-L1", "CRU-L1", "Empty"]  # 按源顺序；list 值的站不在
    assert a["Empty"] == {}
    assert a == b and a["ARC-L1"] is not b["ARC-L1"]  # 值会塞进 REFINERIES，不共享


def test_mining_topic_uses_outer_snapshot(monkeypatch, tmp_path):
    """外层快照开着时换代：topic 读到的仍是外层版本"""
    import sc_mining.gamedata as G

    _setup(monkeypatch, tmp_path, **_src())
    G.ensure()
    with G.snapshot():
        with G.updating():
            _write(tmp_path, "mining_rocks.json", {"areas": {"N": {}}})
            _write(tmp_path, "prices.json", {"yields": {"N": {}}})
        assert G.mining.rocks() == _ROCKS
        assert "N" not in G.prices.refinery_yields()
    assert G.mining.rocks() == {"areas": {"N": {}}}
    assert list(G.prices.refinery_yields()) == ["N"]


# ---------------------------------------------------------------- Task 2：mining_area

DEEP = "Deep Space Asteroids"
_AREA_ROCKS = {
    "tiers": {"common": {"p_cluster": 100.0, "sizes": [[0.5, 6, 6]]}},
    "ores": {"Iron": {"sig": 4285, "tier": "common"}},
    "areas": {
        DEEP: {"Iron": 50.0, "Gold": 2},
        "PYR1-L1": {"Iron": 1.5},
        "Keeger Belt": {"Bexalite": 18.0},
        "Empty Area": {},
    },
    "contains": {"Iron": ["Iron", "Quartz"]},
}
_AREA_SPOTS = [
    {
        "id": "c1",
        "sys": "Pyro",
        "zh": "小行星群",
        "en": "C1",
        "kind": "cluster",
        "area": DEEP,
        "x": 1e10,
        "y": 0.0,
        "z": 0.0,
    },
    {
        "id": "m1",
        "sys": "Pyro",
        "zh": "远矿站",
        "en": "M1",
        "kind": "mining_base",
        "area": "PYR1-L1",
        "x": 2e10,
        "y": 0.0,
        "z": 0.0,
    },
    {
        "id": "m2",
        "sys": "Pyro",
        "zh": "和 m1 重合",
        "en": "M2",
        "kind": "mining_base",
        "area": DEEP,
        "x": 2e10,
        "y": 0.0,
        "z": 0.0,
    },
    {
        "id": "empty",
        "sys": "Pyro",
        "zh": "没有地点名",
        "en": "E",
        "kind": "mining_base",
        "area": "",
        "x": 3e10,
        "y": 0.0,
        "z": 0.0,
    },
    {
        "id": "nyx",
        "sys": "Nyx",
        "zh": "别的星系",
        "en": "N",
        "kind": "mining_base",
        "area": DEEP,
        "x": 4e10,
        "y": 0.0,
        "z": 0.0,
    },
    {
        "sys": "Pyro",
        "zh": "无 id、缺表",
        "en": "X",
        "kind": "mining_base",
        "area": "No Table",
        "x": 5e10,
        "y": 0.0,
        "z": 0.0,
    },
]


def _body(sys_, x):
    return {"sys": sys_, "x": x, "y": 0.0, "z": 0.0, "r": 1e6, "om": 1e6, "grid": 2e6}


_AREA_STAR = {
    "fetched": "2026-11-02",
    "bodies": {"Yela": _body("Stanton", 1e11), "Terminus": _body("Pyro", 6e10)},
    "pois": [],
    "points": [
        {
            "n": "P1 L1",
            "i": "P1_L1",
            "sys": "Pyro",
            "t": "Lagrange Point",
            "x": 7e10,
            "y": 0.0,
            "z": 0.0,
        },
        {
            "n": "Belt",
            "i": "belt",
            "sys": "Pyro",
            "t": "AsteroidBelt",
            "x": 8e10,
            "y": 0.0,
            "z": 0.0,
        },
        {
            "n": "ARC L1",
            "i": "ARC_L1",
            "sys": "Stanton",
            "t": "Lagrange Point",
            "x": 9e10,
            "y": 0.0,
            "z": 0.0,
        },
    ],
}


def _area_setup(monkeypatch, tmp_path, **override):
    """最小库 + 采矿源；星图的 CACHE 指到 tmp（否则没有真实 data/ 的机器上 load() 会去下载）"""
    from sc_mining.navigation import starmap

    _setup(
        monkeypatch,
        tmp_path,
        **{
            "mining_rocks.json": _AREA_ROCKS,
            "mining_spots.json": _AREA_SPOTS,
            "starmap.json": _AREA_STAR,
            **override,
        },
    )
    monkeypatch.setattr(starmap, "CACHE", tmp_path / "starmap.json")
    return tmp_path


def _legacy_rocks_table(data_dir):
    """迁移前的读法（只在测试里存在）"""
    try:
        t = json.loads((data_dir / "mining_rocks.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return t if isinstance(t, dict) else {}


def _legacy_spots_raw(data_dir):
    try:
        return json.loads((data_dir / "mining_spots.json").read_text(encoding="utf-8"))
    except Exception:
        return []


_AREA_INPUTS = [
    ((1e10, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((1e10 + 4.9e7, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((1e10 + 5.1e7, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((2e10, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((2e10 + 1.9e7, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((2e10 + 2.1e7, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((3e10, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((4e10, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((5e10, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((6e10 + 1e9, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((7e10 + 1e6, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((8e10 + 1e6, 0.0, 0.0), "Pyro", None, None, "", ""),
    ((1e12, 0.0, 0.0), "Pyro", None, None, "", ""),
    (None, "Pyro", None, None, "", ""),
    ((1.0, 2.0, 3.0), "Pyro", None, None, "Akiro", ""),
    ((1.0, 2.0, 3.0), "Pyro", None, None, "AsteroidCluster_Pyro_1", ""),
    ((1.0, 2.0, 3.0), "Pyro", "Fairo", True, "", ""),
    ((1.0, 2.0, 3.0), "Nyx", None, None, "Keeger", ""),
    ((48.0e9, 0.0, 0.0), "Nyx", None, None, "", ""),
    ((30e9, 0.0, 0.0), "Nyx", None, None, "", ""),
    ((1e11 + 6e8, 0.0, 0.0), "Stanton", None, None, "", ""),
    ((9e10 + 1e6, 0.0, 0.0), "Stanton", None, None, "", ""),
    ((1e13, 1e13, 0.0), "Stanton", None, None, "", ""),
    ((1.0, 2.0, 3.0), "Stanton", "Hurston", True, "", ""),
]


def test_area_equals_legacy_on_sample(monkeypatch, tmp_path):
    from sc_mining.mining import mining_area as M

    _area_setup(monkeypatch, tmp_path)
    new = [M.area(*a) for a in _AREA_INPUTS]
    assert any(r and r.get("rocks") for r in new)
    monkeypatch.setattr(M, "rocks_table", lambda: _legacy_rocks_table(tmp_path))
    monkeypatch.setattr(M, "_spots_raw", lambda: _legacy_spots_raw(tmp_path))
    assert new == [M.area(*a) for a in _AREA_INPUTS]


def _forbid_json_reads(monkeypatch, *names):
    """读到这几个文件就炸（证明查询路径不再读 JSON）"""
    import pathlib

    real = pathlib.Path.read_text

    def guard(self, *a, **k):
        assert self.name not in names, f"不该读 {self.name}"
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", guard)


def test_area_reads_no_json_and_pins_one_snapshot(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.core import paths
    from sc_mining.gamedata import _db
    from sc_mining.mining import mining_area as M
    from tests.minipytest import raises

    _area_setup(monkeypatch, tmp_path)
    G.ensure()
    _forbid_json_reads(monkeypatch, "mining_spots.json", "mining_rocks.json")
    real_cached = paths.cached_json

    def cached(p, *a, **k):
        assert p.name != "mining_rocks.json"
        return real_cached(p, *a, **k)

    monkeypatch.setattr(paths, "cached_json", cached)
    # 只有最外层 snapshot() 进入时读清单：读清单次数 = 开了几个最外层快照
    calls = []
    real_read = _db.read_manifest

    def counted():
        calls.append(1)
        return real_read()

    monkeypatch.setattr(_db, "read_manifest", counted)
    assert M.area((1e12, 0.0, 0.0), "Pyro")["zh"] == M.NO_ORE  # 走完派罗整个分支
    assert len(calls) == 1
    monkeypatch.setattr(_db, "read_manifest", real_read)

    # 函数体里的异常照常往外抛（钉快照那层不吞）
    def boom(g):
        raise RuntimeError("函数体的错")

    real_spot = M._pyro_spot
    monkeypatch.setattr(M, "_pyro_spot", boom)
    with raises(RuntimeError):
        M.area((1e12, 0.0, 0.0), "Pyro")
    monkeypatch.setattr(M, "_pyro_spot", real_spot)

    # 进不了快照：不抛，当作没有数据
    def no_snap():
        raise G.GamedataUnavailable("库坏了")

    monkeypatch.setattr(G, "snapshot", no_snap)
    monkeypatch.setattr(_db, "snapshot", no_snap)
    assert M.area((1e12, 0.0, 0.0), "Pyro") is None
    assert M.area((1e13, 1e13, 0.0), "Stanton") is None


def test_pyro_spot_raw_meters_same_system_only(monkeypatch, tmp_path):
    from sc_mining.mining import mining_area as M

    _area_setup(monkeypatch, tmp_path)
    assert M.area((2e10 + 19_999_000, 0.0, 0.0), "Pyro")["name"] == "PYR1-L1"  # 2 万 km
    assert M.area((2e10 + 20_001_000, 0.0, 0.0), "Pyro")["zh"] == M.NO_ORE
    assert M.area((1e10 + 49_999_000, 0.0, 0.0), "Pyro")["name"] == DEEP  # 星团 5 万 km
    assert M.area((1e10 + 50_001_000, 0.0, 0.0), "Pyro")["zh"] == M.NO_ORE
    assert M.area((4e10, 0.0, 0.0), "Pyro")["zh"] == M.NO_ORE  # sys=Nyx 的重合点不算
    assert M.area((2e10, 0.0, 0.0), "Pyro")["name"] == "PYR1-L1"  # 都中取源顺序第一个
    assert M.area((3e10, 0.0, 0.0), "Pyro")["zh"] == M.NO_ORE  # 没有地点名的点不算
    assert M.area((5e10, 0.0, 0.0), "Pyro") is None  # 在点上但缺表：不能说不刷
    assert M.area((1e7, 0.0, 0.0), "Pyro")["zh"] == M.NO_ORE  # 按千米传对不上：单位没变


def test_rocks_refresh_after_rebuild_and_stamp_follows_version(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.mining import mining_area as M

    _area_setup(monkeypatch, tmp_path)
    assert "New" not in M.rocks_table()["areas"]
    before = M.rocks_stamp()
    assert before == G.version() and before is not None
    with G.updating():
        _write(tmp_path, "mining_rocks.json", {"areas": {"New": {"Iron": 1}}})
    assert M.rocks_table()["areas"] == {"New": {"Iron": 1}}  # 不调 clear_caches 也换了
    assert M.rocks_stamp() == G.version() != before


def test_mining_area_empty_when_db_unavailable(monkeypatch, tmp_path):
    from sc_mining.core import paths
    from sc_mining.mining import mining_area as M

    _area_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")  # 没有 shops.json：建不出库
    assert M.rocks_table() == {} and M._spots_raw() == ()
    assert M.rocks_stamp() is None
    assert (
        M.area((2e10, 0.0, 0.0), "Pyro") is None
    )  # 没数据：不知道星团在哪，不说「不刷」
    assert M.area((1e13, 1e13, 0.0), "Stanton") is None  # 斯坦顿分支也不抛
    assert M.area((48.0e9, 0.0, 0.0), "Nyx")["name"] == "Keeger Belt"  # 内置表不受影响
    assert "rocks" not in M.area((48.0e9, 0.0, 0.0), "Nyx")


def test_area_for_spot_returns_empty_dict_not_none(monkeypatch, tmp_path):
    from sc_mining.mining import mining_area as M

    _area_setup(monkeypatch, tmp_path)
    assert M.area_for_spot({"area": "Empty Area"}, None) == {}
    assert M.area_for_spot({"area": "Nope"}, None) is None
    assert M.area_for_spot({"lagrange": "P1_L1"}, None) == {"Iron": 1.5}


# ---------------------------------------------------------------- Task 3：shipsig


def _legacy_ships(data_dir):
    """迁移前的读法（只在测试里存在；match / describe 没改，换掉 ships 就是旧行为）"""
    return json.loads((data_dir / "ship_signatures.json").read_text(encoding="utf-8"))[
        "ships"
    ]


_MATCH_SHIPS = {
    "note": "n",
    "ships": [
        {"id": "b", "name": "Beta", "cs": [1000, 2000, 3000], "em_max": 100, "ir_max": 0},
        {"id": "a", "name": "Alpha", "cs": [1000, 2000, 3000], "em_max": 0, "ir_max": 50},
        {"id": "a2", "name": "Alpha", "cs": [1000, 2000, 3000], "em_max": 0, "ir_max": 0, "zh": "阿尔法二"},
        {"id": "f", "name": "Float", "cs": [1000.0, 2000.5, 3000.25], "em_max": 0, "ir_max": 0, "role": "x"},
        {"id": "s", "name": "Same", "cs": [1000.0, 2000.0, 3000.0], "em_max": 0, "ir_max": 0},
        {"id": "d", "name": "Far", "cs": [9000, 9500, 9900], "em_max": 10, "ir_max": 10, "zh": "远"},
    ],
}  # fmt: skip
_MATCH_INPUTS = [
    (1000, None, None, 6),
    (2000, None, None, 6),
    (3000, None, None, 6),
    (880, None, None, 6),
    (3360, None, None, 6),
    (879, None, None, 6),
    (3361, None, None, 6),
    (1000, 160, None, 6),
    (1000, 161, None, 6),
    (1000, None, 80, 6),
    (1000, None, 81, 6),
    (2000.5, 5000, 5000, 6),
    (9500, 16, 16, 6),
    (9500, 17, 17, 6),
    (0, None, None, 6),
    (1000, None, None, 1),
    (5000, None, None, 6),
]


def test_ship_match_equals_legacy_on_sample(monkeypatch, tmp_path):
    from sc_mining.mining import shipsig

    _setup(monkeypatch, tmp_path, **{"ship_signatures.json": _MATCH_SHIPS})
    new_m = [shipsig.match(c, e, i, n) for c, e, i, n in _MATCH_INPUTS]
    new_d = [shipsig.describe(c, e, i) for c, e, i, _ in _MATCH_INPUTS if c]
    assert new_m[0] and new_m[0][0]["variants"]  # 样例真的走到了变体合并
    monkeypatch.setattr(shipsig, "ships", lambda: _legacy_ships(tmp_path))
    assert new_m == [shipsig.match(c, e, i, n) for c, e, i, n in _MATCH_INPUTS]
    assert new_d == [shipsig.describe(c, e, i) for c, e, i, _ in _MATCH_INPUTS if c]


def test_ships_refresh_after_rebuild_without_clear_caches(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.mining import shipsig

    _setup(monkeypatch, tmp_path, **{"ship_signatures.json": _MATCH_SHIPS})
    assert len(shipsig.ships()) == 6
    with G.updating():
        _write(tmp_path, "ship_signatures.json", {"ships": _MATCH_SHIPS["ships"][:1]})
    assert [s["id"] for s in shipsig.ships()] == ["b"]


def test_ships_empty_when_missing_or_db_unavailable(monkeypatch, tmp_path):
    from sc_mining.core import paths
    from sc_mining.mining import shipsig

    _setup(monkeypatch, tmp_path)  # 没有 ship_signatures.json
    assert shipsig.ships() == [] and shipsig.match(1000) == []
    assert shipsig.describe(1000) == ["截面 1,000：没有对得上的船"]
    monkeypatch.setattr(paths, "DATA", tmp_path / "empty")  # 建不出库
    assert shipsig.ships() == []


def test_ships_does_not_read_json(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.mining import shipsig

    _setup(monkeypatch, tmp_path, **{"ship_signatures.json": _MATCH_SHIPS})
    G.ensure()
    _forbid_json_reads(monkeypatch, "ship_signatures.json")
    assert shipsig.match(1000)


def test_clear_caches_still_safe_for_shipsig(monkeypatch, tmp_path):
    from sc_mining.mining import shipsig
    from sc_mining.update import data_pack, uex

    _setup(monkeypatch, tmp_path, **{"ship_signatures.json": _MATCH_SHIPS})
    monkeypatch.setattr(uex, "apply_live", lambda m: False)
    data_pack.clear_caches()
    assert shipsig.match(1000)


# ---------------------------------------------------------------- Task 4：精炼站加成


def _stations(m):
    m.REFINERIES["CRU-L1"] = ("十字 L1", {"Aluminum": 9})
    m.REFINERIES["Empty"] = ("空站", {"Aluminum": 9})
    return m


def test_apply_live_yields_from_db_no_json_fallback(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.update import uex

    _setup(monkeypatch, tmp_path, **{"prices.json": _PRICES})
    G.ensure()
    _write(tmp_path, "prices.json", {"yields": {"ARC-L1": {"Aluminum": 999}}})  # 不重建
    m = _stations(_fake_data_module())
    refs = m.REFINERIES
    assert uex.apply_live(m) is True
    assert m.REFINERIES is refs  # refinery.py 绑定了这个 dict：只换值
    assert refs["ARC-L1"] == ("弧 L1", {"Aluminum": 5})  # 库里的，不是改过的 JSON
    assert type(refs["CRU-L1"][1]["Aluminum"]) is float
    assert refs["Empty"] == ("空站", {})  # {} 把加成清空
    assert "Bad" not in refs  # 不认识的站不加
    assert m.CITY_PRICES["Aluminum"] == {"Area18": 3800, "Lorville": 2}


def test_apply_live_db_unavailable_keeps_builtin(monkeypatch, tmp_path):
    from sc_mining.update import uex

    _setup(monkeypatch, tmp_path, **{"prices.json": _PRICES})
    _write(tmp_path, "shops.json", "{坏")  # 必需源坏了：建不出库
    _forbid_json_reads(monkeypatch, "prices.json")
    m = _stations(_fake_data_module())
    refs, prices = m.REFINERIES, m.CITY_PRICES
    before = (dict(refs), json.dumps(prices, sort_keys=True))
    assert uex.apply_live(m) is False
    assert m.REFINERIES is refs and m.CITY_PRICES is prices
    assert (dict(refs), json.dumps(prices, sort_keys=True)) == before


def test_apply_live_prices_and_yields_same_snapshot(monkeypatch, tmp_path):
    """矿价和加成在一个快照里读：最外层只开一次（只有最外层进入时读清单）"""
    import sc_mining.gamedata as G
    from sc_mining.gamedata import _db
    from sc_mining.update import uex

    _setup(monkeypatch, tmp_path, **{"prices.json": _PRICES})
    G.ensure()
    calls = []
    real = _db.read_manifest

    def counted():
        calls.append(1)
        return real()

    monkeypatch.setattr(_db, "read_manifest", counted)
    assert uex.apply_live(_fake_data_module()) is True
    assert len(calls) == 1


def test_apply_live_false_when_prices_json_bad_or_empty(monkeypatch, tmp_path):
    """坏文件、里面没有矿价也没有加成：什么也不覆盖，返回 False，不靠外层吞错"""
    from sc_mining.update import uex

    for i, bad in enumerate(("{坏", [], {"prices": {}, "yields": {}})):
        _setup(monkeypatch, tmp_path / str(i), **{"prices.json": _PRICES})
        _write(tmp_path / str(i), "prices.json", bad)
        m = _fake_data_module()
        assert uex.apply_live(m) is False
        assert m.CITY_PRICES["Aluminum"] == {"Area18": 1, "Lorville": 2}
        assert m.REFINERIES["ARC-L1"] == ("弧 L1", {})


# ---------------------------------------------------------------- Task 5：回归


def test_signals_and_parse_unchanged_via_rocks_table(monkeypatch, tmp_path):
    from sc_mining.mining import mining_area as M
    from sc_mining.mining import parse, signals

    _setup(monkeypatch, tmp_path, **_MINING_SOURCES)
    ores = ["Aluminum", "Quantainium", "NoSuchOre"]
    rocks = ["Agricium", "NoSuchRock"]

    def sample():
        return (
            [signals.cluster_weight(m, n) for m in ores for n in range(1, 8)],
            [parse._rock_contains(r) for r in rocks],
        )

    new = sample()
    assert parse._rock_contains("Agricium")
    monkeypatch.setattr(M, "rocks_table", lambda: _legacy_rocks_table(tmp_path))
    assert new == sample()


def test_refresh_still_inside_updating(monkeypatch, tmp_path):
    from sc_mining.update import uex

    _setup(monkeypatch, tmp_path)
    state = _count_updating(monkeypatch)
    monkeypatch.setattr(uex, "_get", lambda endpoint: [])
    monkeypatch.setattr(uex, "OUT", tmp_path / "prices.json")
    uex.refresh()
    assert state["n"] == 1 and state["writes"][0][1]


def test_mining_modules_do_not_read_data_dir():
    """代码里没有 DATA，也没有这几份文件名的字符串（注释和文档字符串里提到不算）"""
    import ast
    import inspect

    from sc_mining.mining import laser, locations, mining_area, parse, refinery
    from sc_mining.mining import shipsig, signals

    files = (
        "mining_rocks.json",
        "mining_spots.json",
        "ship_signatures.json",
        "prices.json",
    )
    for mod in (mining_area, shipsig, signals, parse, refinery, laser, locations):
        tree = ast.parse(inspect.getsource(mod))
        docs = {
            id(n.value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
        }
        for n in ast.walk(tree):
            assert not (isinstance(n, ast.Name) and n.id == "DATA"), mod.__name__
            assert not (isinstance(n, ast.alias) and n.name == "DATA"), mod.__name__
            if isinstance(n, ast.Constant) and id(n) not in docs:
                assert not any(f in str(n.value) for f in files), mod.__name__


def test_area_when_manifest_corrupt_enter_fails(monkeypatch, tmp_path):
    """线上 snapshot() 是生成器，清单坏了要到 __enter__ 才抛：接住、不残留快照，当作没有数据"""
    import sc_mining.gamedata as G
    from sc_mining.gamedata import _db
    from sc_mining.gamedata._paths import gamedata_dir
    from sc_mining.mining import mining_area as M

    _area_setup(monkeypatch, tmp_path)
    G.ensure()
    (gamedata_dir() / "current.json").write_text("{坏", encoding="utf-8")
    assert M.area((2e10, 0.0, 0.0), "Pyro") is None
    assert M.area((48.0e9, 0.0, 0.0), "Nyx")["name"] == "Keeger Belt"
    assert getattr(_db._tls, "snap", None) is None
