"""游戏数据层 schema 6：采矿石头表 / 舰船截面 / 精炼站加成（批 5 公共层）

全部用 tmp_path 当 data/ 根，不读真实 data/。查询主题由批 5 写，这里只验表和导入。"""

import json

from tests.test_gamedata import _data_root, _write_min_sources

_ROCKS = {
    "tiers": {
        "common": {"p_cluster": 100.0, "sizes": [[0.1, 6, 6], [0.3, 5, 5]]},
        "epic": {"p_cluster": 40.0, "sizes": [[0.1, 3, 3]]},
    },
    "ores": {
        "Aluminum": {"sig": 4285, "tier": "common"},
        "Quantainium": {"sig": 2200, "tier": "epic"},
    },
    "areas": {"Hurston": {"Aluminum": 44.0, "Quantainium": 2.0}, "Empty Place": {}},
    "contains": {"Agricium": ["Agricium", "Aslarite", "Titanium"]},
    "version": "4.10",
}
_SHIPS = {
    "source": "x",
    "note": "n",
    "ships": [
        {
            "id": "aegs_avenger_stalker",
            "name": "Avenger Stalker",
            "size": 2,
            "cs": [2231, 6515, 8925],
            "em_max": 28427,
            "ir_max": 15972,
            "em_rest": 344,
            "zh": "复仇者 追猎",
        },
        "junk",
        {
            "id": "no_zh",
            "name": "No Zh",
            "cs": [1, 2, 3],
            "em_max": 1,
            "ir_max": 1,
            "em_rest": 0,
        },
    ],
}
_PRICES = {
    "prices": {"Aluminum": {"Area18": 3800}},
    "yields": {
        "ARC-L1": {"Aluminum": 5, "Gold": -3.5},
        "Empty Station": {},
        "Bad": "junk",
    },
}

_MINING_SOURCES = {
    "mining_rocks.json": _ROCKS,
    "ship_signatures.json": _SHIPS,
    "prices.json": _PRICES,
}


def _built(monkeypatch, tmp_path, **override):
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path, **{**_MINING_SOURCES, **override})
    rebuild_if_needed()
    return snapshot


def test_mining_rock_entries_roundtrip_by_section(monkeypatch, tmp_path):
    """每段每键一行、值 JSON 原样（float / int / 空 dict / 列表都不变）；非 dict 顶层键进 meta.extra，段顺序进 meta.sections"""
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select section, key, value_json, source_order from mining_rock_entries order by section, source_order"
        )
        meta = json.loads(
            s.execute("select value from meta where key = 'mining_rocks_meta'")[0][0]
        )
    got = {}
    for sec, k, vj, i in rows:
        got.setdefault(sec, {})[k] = json.loads(vj)
    assert got == {k: v for k, v in _ROCKS.items() if isinstance(v, dict)}
    assert (
        got["areas"]["Empty Place"] == {}
        and type(got["ores"]["Aluminum"]["sig"]) is int
        and type(got["areas"]["Hurston"]["Aluminum"]) is float
    )
    assert meta == {
        "sections": ["tiers", "ores", "areas", "contains"],
        "extra": {"version": "4.10"},
    }
    assert [r[3] for r in rows if r[0] == "tiers"] == [0, 1]


def test_mining_rocks_absent_means_no_meta_key(monkeypatch, tmp_path):
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(
        tmp_path, **{"ship_signatures.json": _SHIPS, "prices.json": _PRICES}
    )
    rebuild_if_needed()
    with snapshot() as s:
        assert s.execute("select count(*) from mining_rock_entries")[0][0] == 0
        assert (
            s.execute("select count(*) from meta where key = 'mining_rocks_meta'")[0][0]
            == 0
        )
        assert s.execute(
            "select value from meta where key = 'src:mining_rocks.json'"
        ) == [("",)]  # 文件不在 → 空串
    _write_min_sources(tmp_path, **{"mining_rocks.json": {}})
    rebuild_if_needed()
    with snapshot() as s:
        assert json.loads(
            s.execute("select value from meta where key = 'mining_rocks_meta'")[0][0]
        ) == {"sections": [], "extra": {}}
        assert (
            s.execute("select value from meta where key = 'src:mining_rocks.json'")[0][
                0
            ]
            != ""
        )


def test_ship_signatures_whole_row_json_and_skip_junk(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select source_order, ship_json from ship_signatures order by source_order"
        )
    assert [r[0] for r in rows] == [0, 2]  # "junk" 跳过，留空号
    assert (
        json.loads(rows[0][1]) == _SHIPS["ships"][0]
        and json.loads(rows[1][1]) == _SHIPS["ships"][2]
    )
    assert "zh" not in json.loads(rows[1][1])  # 没有的键就是没有，不补


def test_refinery_yields_whole_station_json(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select station, bonus_json, source_order from refinery_yields order by source_order"
        )
        prices = s.execute("select count(*) from mineral_prices")[0][0]
    assert [(r[0], json.loads(r[1]), r[2]) for r in rows] == [
        ("ARC-L1", {"Aluminum": 5, "Gold": -3.5}, 0),
        ("Empty Station", {}, 1),
    ]  # "Bad" 不是 dict 跳过
    got = json.loads(rows[0][1])
    assert type(got["Aluminum"]) is int and type(got["Gold"]) is float
    assert prices == 1  # 同一份 prices.json 的 prices 段照旧进 mineral_prices


def test_mining_sources_optional_and_odd_shapes(monkeypatch, tmp_path):
    """三份都可选、形状不对不拖垮建库"""
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(
        tmp_path,
        **{
            "mining_rocks.json": ["not", "a", "dict"],
            "ship_signatures.json": {"ships": "junk"},
            "prices.json": {"prices": {}, "yields": ["junk"]},
        },
    )
    rebuild_if_needed()
    with snapshot() as s:
        assert s.execute("select count(*) from items")[0][0] > 0
        assert s.execute("select count(*) from mining_rock_entries")[0][0] == 0
        assert (
            s.execute("select count(*) from meta where key = 'mining_rocks_meta'")[0][0]
            == 0
        )  # 不是 dict 当没有
        assert s.execute("select count(*) from ship_signatures")[0][0] == 0
        assert s.execute("select count(*) from refinery_yields")[0][0] == 0
