"""游戏数据层批 5：采矿石头表、挖矿点、飞船信号、精炼站加成改走数据层

全部用 tmp_path 当 data/ 根，不读真实 data/、不写 userdata/、不联网。"""

import json

from tests.test_gamedata_b1 import _setup

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
