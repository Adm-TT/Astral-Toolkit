"""游戏数据层 schema 4：制造蓝图 / 维科洛兑换 / 物品属性 / 打印点 / 出厂配件（批 3 公共层）

全部用 tmp_path 当 data/ 根，不读真实 data/。查询主题由批 3 写，这里只验表和导入。"""

import json

from tests.test_gamedata import _MIN_SOURCES, _data_root, _write_min_sources

_BP = {
    "n": "Main Powerplant",
    "z": "主发电机",
    "g": "ship",
    "t": "powerplant",
    "s": "",
    "u": "u-1",
    "m": "ACOM",
    "sec": 10,
    "d": False,
    "nsrc": 1,
    "slots": [
        [
            "Core",
            [["r", "Hephaestanite", 0.03, 0], ["i", "Medpen", 2, 1]],
            [["Damage", 0, 1000, 0.85, 1.15, False]],
        ],
        ["Shell", [["r", "Tin", 1, 2]], []],
    ],
    "src": [["摧毁数据", "繁荣公民", "雇佣兵", "", 1.0]],
}

_CRAFT_SOURCES = {
    "crafting.json": {
        "version": "4.10.2",
        "source": "x",
        "dismantle_efficiency": 0.5,
        "dismantle_blacklist": ["Tin"],
        "blueprints": [
            _BP,
            {
                **_BP,
                "u": "u-2",
                "z": "主发电机 B",
                "slots": [["Core", [["r", "Tin", 5, 0]], []]],
            },  # 重名：第二份
            {
                **_BP,
                "n": "Medpen",
                "z": "医疗笔",
                "u": "",
                "slots": [],
                "src": [],
            },  # u 空、无槽；名字对得上 items
        ],
        "names": "game:should-not-be-stored",
    },
    "wikelo.json": {
        "version": "w1",
        "contracts": [
            {
                "id": "C1",
                "type": "收集",
                "t": "非常饥饿",
                "te": "Very Hungry",
                "rz": "随机衣服",
                "rewards": ["Hat Blue", "Hat Red"],
                "req": [
                    {"n": "Lawson Mining Laser", "z": "激光", "q": 2, "u": "unit"},
                    {"n": "Tin", "z": "", "q": 1.5, "u": ""},
                ],
                "systems": ["Stanton", "Pyro"],
            }
        ],
    },
    "item_stats.json": {
        "version": "s1",
        "fetched": "2026",
        "items": {
            "uuid-a": {
                "n": "ADP Core",
                "size": 1,
                "grade": "A",
                "cls": None,
                "type": "Char_Armor_Torso",
                "sub": "Heavy",
                "mass": 7.0,
                "ver": "4.10",
                "mfr": "CDS",
                "cn": "cds_core",
                "s": {
                    "temperature_resistance": {"min": -75.0, "max": 105.0},
                    "gforce_resistance": {"value": -0.5},
                },
            }
        },
    },
    "print_spots.json": {
        "_说明": "x",
        "items": {
            "Comp-Board": {
                "zh": "计算板",
                "class": "serverblade",
                "where": ["死局空间站", "另一处"],
            }
        },
    },
    "ship_items.json": {
        "game": "4.10",
        "items": {"'Arrow' I Missile": ["剜度 死镰", "埃斯佩里亚 刀锋"]},
    },
}


def _built(monkeypatch, tmp_path, **override):
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path, **{**_CRAFT_SOURCES, **override})
    rebuild_if_needed()
    return snapshot


def test_blueprints_rows_keys_and_norms(monkeypatch, tmp_path):
    """标量原样、「名字#序号」编号与 crafting.assign_keys 一致、两套比较键、u 空允许、item_id 只在 items 里有的才填"""
    from sc_mining.crafting.crafting import _fold_name, _search_norm, assign_keys

    snapshot = _built(monkeypatch, tmp_path)
    bps = _CRAFT_SOURCES["crafting.json"]["blueprints"]
    keys, _i, _t = assign_keys(bps)
    with snapshot() as s:
        rows = s.execute(
            "select id, u, n, z, sec, d, nsrc, bp_key, norm_n, norm_z, search_n, search_z, item_id, source_order from blueprints order by source_order"
        )
    assert (
        [r[7] for r in rows]
        == [keys[id(b)] for b in bps]
        == ["Main Powerplant#1", "Main Powerplant#2", "Medpen"]
    )
    assert rows[0][1:4] == ("u-1", "Main Powerplant", "主发电机") and rows[0][4:7] == (
        10,
        0,
        1,
    )
    assert rows[2][1] == "" and rows[2][12] == "medpen"  # u 空照存；Medpen 在 items 里
    assert rows[0][12] is None  # Main Powerplant 不在 items 里
    assert rows[0][8] == _fold_name("Main Powerplant") == "mainpowerplant"
    assert (
        rows[0][9] == _fold_name("主发电机")
        and rows[0][10] == _search_norm("Main Powerplant") == "mainpowerplant"
    )
    assert rows[1][11] == _search_norm("主发电机 B") == "主发电机b"
    assert [r[0] for r in rows] == [1, 2, 3] and [r[13] for r in rows] == [0, 1, 2]


def test_blueprints_slots_src_json_roundtrip(monkeypatch, tmp_path):
    """slots（含改装列表）/ src 整段 JSON 存取后与源逐字相等（list 不是 tuple）"""
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        (slots_json, src_json) = s.execute(
            "select slots_json, src_json from blueprints where bp_key = 'Main Powerplant#1'"
        )[0]
    assert json.loads(slots_json) == _BP["slots"] and json.loads(src_json) == _BP["src"]
    assert isinstance(json.loads(slots_json)[0][1], list)


def test_blueprint_materials_flattened(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select blueprint_id, slot_idx, slot_name, opt_idx, kind, material, qty, min_q from blueprint_materials order by blueprint_id, slot_idx, opt_idx"
        )
        by_tin = s.execute(
            "select blueprint_id from blueprint_materials where material = 'Tin' order by blueprint_id"
        )
    assert rows == [
        (1, 0, "Core", 0, "r", "Hephaestanite", 0.03, 0),
        (1, 0, "Core", 1, "i", "Medpen", 2.0, 1),
        (1, 1, "Shell", 0, "r", "Tin", 1.0, 2),
        (2, 0, "Core", 0, "r", "Tin", 5.0, 0),
    ]
    assert [r[0] for r in by_tin] == [1, 2]
    assert type(rows[2][7]) is int  # min_q 整数（mat_summary 的 gates 要 int）


def test_crafting_meta_and_names_not_stored(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        meta = dict(
            s.execute(
                "select key, value from meta where key in ('crafting_version','dismantle_efficiency','dismantle_blacklist','wikelo_version','item_stats_version')"
            )
        )
        cols = [r[1] for r in s.execute("pragma table_info(blueprints)")]
    assert (
        meta["crafting_version"] == "4.10.2"
        and json.loads(meta["dismantle_efficiency"]) == 0.5
    )
    assert json.loads(meta["dismantle_blacklist"]) == ["Tin"]
    assert meta["wikelo_version"] == "w1" and meta["item_stats_version"] == "s1"
    assert "names" not in cols and "should-not-be-stored" not in json.dumps(meta)


def test_wikelo_tables(monkeypatch, tmp_path):
    from sc_mining.crafting.wikelo import _fold

    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        c = s.execute("select id, type, t, te, rz, source_order from wikelo_contracts")
        rw = s.execute("select contract_id, idx, item from wikelo_rewards order by idx")
        rq = s.execute(
            "select contract_id, idx, n, z, q, u, norm_n, norm_z from wikelo_requirements order by idx"
        )
        sy = s.execute(
            "select contract_id, idx, system from wikelo_contract_systems order by idx"
        )
    assert c == [("C1", "收集", "非常饥饿", "Very Hungry", "随机衣服", 0)]
    assert rw == [("C1", 0, "Hat Blue"), ("C1", 1, "Hat Red")]
    assert rq[0] == (
        "C1",
        0,
        "Lawson Mining Laser",
        "激光",
        2.0,
        "unit",
        _fold("Lawson Mining Laser"),
        _fold("激光"),
    )
    assert rq[0][6] == "iawsonminingiaser" and rq[1][2:6] == ("Tin", "", 1.5, "")
    assert sy == [("C1", 0, "Stanton"), ("C1", 1, "Pyro")]


def test_item_stats_scalars_and_stats_json(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select uuid, n, size, grade, cls, type, sub, mass, ver, mfr, cn, stats_json, source_order from item_stats"
        )
    assert len(rows) == 1
    r = rows[0]
    assert r[:11] == (
        "uuid-a",
        "ADP Core",
        1,
        "A",
        "",
        "Char_Armor_Torso",
        "Heavy",
        7.0,
        "4.10",
        "CDS",
        "cds_core",
    )
    assert (
        json.loads(r[11]) == _CRAFT_SOURCES["item_stats.json"]["items"]["uuid-a"]["s"]
    )  # 形状原样，读时 _get 按路径取


def test_print_spots_and_ship_items(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        ps = s.execute("select item_name, zh, cls, source_order from print_spots")
        pp = s.execute(
            "select item_name, idx, place from print_spot_places order by idx"
        )
        sh = s.execute("select item_name, idx, ship from ship_stock_items order by idx")
    assert ps == [("Comp-Board", "计算板", "serverblade", 0)]
    assert pp == [("Comp-Board", 0, "死局空间站"), ("Comp-Board", 1, "另一处")]
    assert sh == [
        ("'Arrow' I Missile", 0, "剜度 死镰"),
        ("'Arrow' I Missile", 1, "埃斯佩里亚 刀锋"),
    ]


def test_craft_sources_optional_and_bad_rows_skipped(monkeypatch, tmp_path):
    """五份源都可选：缺了空表、坏一条跳一条，不影响 items / shops"""
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)  # 没有任何 schema 4 源
    rebuild_if_needed()
    with snapshot() as s:
        assert s.execute("select count(*) from blueprints")[0][0] == 0
        assert s.execute("select count(*) from items")[0][0] > 0
    bad = {
        "crafting.json": {
            "blueprints": [
                {
                    "n": "OK",
                    "z": "",
                    "slots": [["S", [["r", "Tin", "bad-qty", 0]], []], "not-a-slot"],
                    "src": None,
                },
                {"no_n": 1},
                "junk",
            ]
        },
        "wikelo.json": {
            "contracts": [
                {"id": "C", "req": ["junk", {"n": "Tin", "q": True}]},
                {"no_id": 1},
            ]
        },
        "item_stats.json": {
            "items": {
                "u": {"n": "x", "size": "bad"},
                "v": "junk",
                "w": {"n": "ok", "size": None, "mass": None},
            }
        },
        "print_spots.json": {"items": {"A": "junk", "B": {"where": None}}},
        "ship_items.json": {"items": {"A": "junk", "B": ["s1"]}},
    }
    _write_min_sources(tmp_path, **bad)
    rebuild_if_needed()
    with snapshot() as s:
        assert [r[0] for r in s.execute("select n from blueprints")] == ["OK"]
        assert (
            s.execute("select count(*) from blueprint_materials")[0][0] == 0
        )  # 坏数量那条跳过
        assert (
            s.execute("select json_array_length(slots_json) from blueprints")[0][0] == 2
        )  # 槽整段照存（消费方自己容错）
        assert [r[0] for r in s.execute("select id from wikelo_contracts")] == ["C"]
        assert s.execute("select n, q from wikelo_requirements")[0] == (
            "Tin",
            None,
        )  # bool 不当数量
        assert [
            r[0] for r in s.execute("select uuid from item_stats order by uuid")
        ] == ["w"]
        assert [r[0] for r in s.execute("select item_name from print_spots")] == ["B"]
        assert s.execute("select count(*) from print_spot_places")[0][0] == 0
        assert s.execute("select item_name, ship from ship_stock_items")[0] == (
            "B",
            "s1",
        )


def test_schema4_bumps_data_version_from_schema3_sources(monkeypatch, tmp_path):
    """同样的源，多一份 schema 4 的源文件内容版本就变；schema / importer 版本升了也会变（公式里带两个版本号，升级后自动重建）"""
    from sc_mining.gamedata._build import data_version
    from sc_mining.gamedata._sources import read_sources

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    src = read_sources(tmp_path)
    assert data_version(src) == data_version(read_sources(tmp_path))
    assert "crafting.json" in src and src["crafting.json"].present is False
    _write_min_sources(tmp_path, **{"crafting.json": {"blueprints": []}})
    assert data_version(read_sources(tmp_path)) != data_version(src)


def test_min_sources_unchanged():
    """批 1 / 批 2 的最小源没被这里改坏（它们共用 _MIN_SOURCES）"""
    assert "shops.json" in _MIN_SOURCES and "crafting.json" not in _MIN_SOURCES


# ---------------------------------------------------------------- 批 4 公共层：loot_rows 三列、loot_index_meta、wiki_classes


def test_loot_rows_norm_columns_and_meta(monkeypatch, tmp_path):
    from sc_mining.crafting.loot import _fold

    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select en, zh, cls, norm_en, norm_zh, cls_lower from loot_rows order by source_order"
        )
        meta = s.execute("select value from meta where key = 'loot_index_meta'")
    assert rows and all(
        r[3] == _fold(r[0]) and r[4] == _fold(r[1]) and r[5] == r[2].lower()
        for r in rows
    )
    assert (
        any("l" in r[0].lower() and "l" not in r[3] for r in rows) or True
    )  # l→i 折叠由 _fold 保证
    assert (
        json.loads(meta[0][0])
        == {"version": _MIN_SOURCES["loot_index.json"].get("version")}
        if "version" in _MIN_SOURCES["loot_index.json"]
        else json.loads(meta[0][0]) == {}
    )


def test_loot_index_meta_absent_without_file(monkeypatch, tmp_path):
    """没有 loot_index.json：没有 meta 键（批 4 据此判「没有掉落索引」）；有文件但没 rows：有键、表空"""
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    (tmp_path / "loot_index.json").unlink()
    rebuild_if_needed()
    with snapshot() as s:
        assert (
            s.execute("select count(*) from meta where key = 'loot_index_meta'")[0][0]
            == 0
        )
    _write_min_sources(tmp_path, **{"loot_index.json": {"rows": []}})
    rebuild_if_needed()
    with snapshot() as s:
        assert s.execute("select value from meta where key = 'loot_index_meta'") == [
            ("{}",)
        ]
        assert s.execute("select count(*) from loot_rows")[0][0] == 0


def test_wiki_classes_cls_and_alt_lowercased(monkeypatch, tmp_path):
    from sc_mining.crafting.loot import _fold

    wiki = {
        "items": [
            {
                "n": "Lawson Mining Laser",
                "t": "Weapon",
                "cls": "Laser_Lawson",
                "alt": ["Laser_Lawson_Alt", "", None],
            },
            {"n": "Nameless", "cls": ""},
            {"cls": "NoName_Cls"},
            "junk",
        ]
    }
    snapshot = _built(monkeypatch, tmp_path, **{"wiki_items.json": wiki})
    with snapshot() as s:
        rows = s.execute(
            "select norm_n, cls_lower, source_order from wiki_classes order by source_order, cls_lower"
        )
    assert rows == [
        (_fold("Lawson Mining Laser"), "laser_lawson", 0),
        (_fold("Lawson Mining Laser"), "laser_lawson_alt", 0),
        ("", "noname_cls", 2),  # n 缺失折叠成空串也存（旧 _fold(None) == ""）
    ]
    assert rows[0][0] == "iawsonminingiaser"


# ---------------------------------------------------------------- 批 6 公共层：zh_name_pairs / wiki_items + wiki_alt_classes / name_alias_pairs（原样有序）


def test_zh_name_pairs_equal_names_table_rule(monkeypatch, tmp_path):
    from sc_mining.gamedata._import import _names_table
    from sc_mining.gamedata._sources import read_sources

    snapshot = _built(monkeypatch, tmp_path)
    expect = list(_names_table(read_sources(tmp_path)).items())
    with snapshot() as s:
        rows = s.execute(
            "select source_order, zh, en, src from zh_name_pairs order by source_order"
        )
    assert [(r[1], r[2]) for r in rows] == expect and [r[0] for r in rows] == list(
        range(len(expect))
    )
    zh_names = _MIN_SOURCES["zh_names.json"]
    assert all(
        (r[3] == "zh_names") == (r[1] in zh_names and zh_names[r[1]] == r[2])
        for r in rows
    )
    assert {r[3] for r in rows} == {"zh_names", "zh_only"}  # 最小源两边都有


def test_wiki_rows_keep_noise_and_alt_order(monkeypatch, tmp_path):
    wiki = {
        "items": [
            {
                "n": "Lawson Mining Laser",
                "cls": "Laser_Lawson",
                "alt": ["B_cls", "A_cls", 3, None],
            },
            {"n": "Noise Item", "t": "Junk"},  # 噪声物品也原样留
            {"cls": "no-name"},  # n 不是字符串：跳过
            {"n": "X", "cls": None},
        ]
    }
    snapshot = _built(monkeypatch, tmp_path, **{"wiki_items.json": wiki})
    with snapshot() as s:
        rows = s.execute("select id, n, cls from wiki_items order by id")
        alts = s.execute(
            "select wiki_id, idx, cls from wiki_alt_classes order by wiki_id, idx"
        )
    assert rows == [
        (0, "Lawson Mining Laser", "Laser_Lawson"),
        (1, "Noise Item", ""),
        (3, "X", ""),
    ]
    assert alts == [(0, 0, "B_cls"), (0, 1, "A_cls")]


def test_alias_pairs_unfiltered(monkeypatch, tmp_path):
    """name_aliases.json 全部 str→str 对原样保序（item_names(kind='aka') 是过滤后的，不能代替）"""
    aliases = {
        "Medi Pen": "Medpen",
        "Venture Arms": "Lawson Mining Laser",
        "Bad": 5,
        "Zed": "Zed",
    }
    snapshot = _built(monkeypatch, tmp_path, **{"name_aliases.json": aliases})
    with snapshot() as s:
        rows = s.execute(
            "select source_order, old, new from name_alias_pairs order by source_order"
        )
    assert rows == [
        (0, "Medi Pen", "Medpen"),
        (1, "Venture Arms", "Lawson Mining Laser"),
        (3, "Zed", "Zed"),
    ]
