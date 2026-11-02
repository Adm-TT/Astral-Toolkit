"""游戏数据层 schema 2：星图 / 城市地点 / 设施 / 空间站电梯 / 地名对照 / 挖矿点 的建表与导入（批 2 公共层先行）

用最小源在 tmp_path 建库；变换规则复用 transit._city_rows / transit._lift_rows / starmap.fix_points。
2026-11-02 审查后补：qt 为空原样存、设施 ref 六种键、地名两份都存、挖矿点不去重、导航源坏了不拖垮物品表。"""

import json

from tests.test_gamedata import _MIN_SOURCES, _data_root

_NAV_SOURCES = {
    "starmap.json": {
        "fetched": "2026-10-28",
        "bodies": {
            "Hurston": {
                "sys": "Stanton",
                "x": 1.0,
                "y": 0.0,
                "z": 0.0,
                "rot": 2.48,
                "adj": 117.5,
                "r": 1e6,
                "om": 1.4e6,
                "grid": 2e6,
            },
        },
        "pois": [
            {
                "b": "Hurston",
                "n": "Mining Base #365-YNZ",
                "t": "AsteroidBelt",
                "x": 1.0,
                "y": 2.0,
                "z": 0.0,
                "qt": 0,
            },
            {
                "b": "Hurston",
                "n": "Lorville",
                "t": "City",
                "x": 3.0,
                "y": 4.0,
                "z": 0.0,
                "qt": 1,
            },
            {
                "b": "Hurston",
                "n": "No Marker",
                "t": "Outpost",
                "x": 6.0,
                "y": 6.0,
                "z": 0.0,
                "qt": None,
            },  # 信标未确认
        ],
        "points": [
            {
                "n": "Stanton Star",
                "i": "OOC_Stanton",
                "sys": "Stanton",
                "t": "Star",
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
            },
            {
                "n": "Hurston L1",
                "i": "HUR_L1",
                "sys": "Stanton",
                "t": "Lagrange",
                "x": 5.0,
                "y": 5.0,
                "z": 5.0,
            },
            {
                "n": "Dup A",
                "i": "DUP_X",
                "sys": "Pyro",
                "t": "Outpost",
                "x": 1.0,
                "y": 1.0,
                "z": 1.0,
            },
            {
                "n": "Dup B",
                "i": "DUP_X",
                "sys": "Pyro",
                "t": "Outpost",
                "x": 2.0,
                "y": 2.0,
                "z": 2.0,
            },  # 同内部名：首个胜出
        ],
    },
    "starmap_fixes.json": {"Hurston L1": [9.0, 9.0, 9.0]},  # 覆盖坐标
    "city_places.json": [
        {
            "city": "Lorville",
            "body": "Hurston",
            "cat": "公寓",
            "en": "Hab Lobby",
            "src": "lor_hab",
            "zh": "公寓大堂",
            "area": "A",
            "x": 1.0,
            "y": 2.0,
            "z": 3.0,
            "kinds": ["住宿"],
            "site_en": "Lorville",
            "site_zh": "洛维尔",
        },
        {
            "city": "Lorville",
            "body": "Hurston",
            "cat": "公寓",
            "en": "Hab Lobby 2",
            "src": "lor_hab2",
            "zh": "公寓大堂",
            "area": "A",
            "x": 1.5,
            "y": 2.0,
            "z": 3.0,
            "kinds": [],
            "site_en": "Lorville",
            "site_zh": "洛维尔",
        },  # 同名 → 加序号 2
        {
            "city": "Lorville",
            "body": "Hurston",
            "cat": "坏",
            "en": "Bad",
            "src": "bad",
            "zh": "坏",
            "x": "nan",
            "y": 0,
            "z": 0,
        },  # 坐标非法 → 丢
        {
            "city": "Lorville",
            "body": "Hurston",
            "cat": "公寓",
            "en": "Hab Dup",
            "src": "lor_hab",
            "zh": "",
            "x": 1.0,
            "y": 1.0,
            "z": 1.0,
            "up": [0, 0, 1],
        },  # 重复 src → 加 +
        {
            "city": "",
            "body": "",
            "space": True,
            "sys": "Stanton",
            "cat": "站",
            "en": "Orbit Shop",
            "src": "orb",
            "zh": "轨道店",
            "x": 9.0,
            "y": 9.0,
            "z": 9.0,
        },  # 空间点 → b=@Stanton
    ],
    "place_amenities.json": [
        {
            "en": "Rustville",
            "zh": "锈迹镇",
            "kinds": ["空港", "商店"],
            "rec": "pyro1_outpost",
            "ref": {"poi": "Rustville"},
        },
        {
            "en": "Everus Harbor",
            "zh": "艾维拉斯港",
            "kinds": ["医疗"],
            "rec": "",
            "ref": {
                "poi": "Everus Harbor",
                "body": "Hurston",
                "local": [-507.7, -903.4, 496.4],
            },
        },
        {
            "en": "HUR-L1 Shop",
            "zh": "赫 L1 店",
            "kinds": ["商店"],
            "rec": "",
            "ref": {"point_id": "HUR_L1", "point": "Hurston L1"},
        },
        {
            "en": "Lorville Clinic",
            "zh": "洛维尔诊所",
            "kinds": ["医疗"],
            "rec": "lorville",
            "ref": {"city": "Lorville"},
        },
        {
            "en": "Pyro Body Only",
            "zh": "",
            "kinds": ["医疗"],
            "rec": "",
            "ref": {"body": "Hurston"},
        },
    ],
    "station_lifts.json": {
        "version": 1,
        "hangar_lift_local": {},
        "stations": {
            "rr_hur_l1": {
                "station": "Everus Harbor",
                "ok": True,
                "worst_m": 3,
                "sys": "Stanton",
                "space": True,
                "areas": {
                    "ObjectContainer_Commercial": {
                        "en": "Galleria",
                        "zh": "购物中心",
                        "zone": True,
                    }
                },
                "places": {"galleria": "ObjectContainer_Commercial"},
                "lifts": [
                    {
                        "en": "Main Lift",
                        "zh": "主电梯",
                        "stops": [
                            {
                                "en": "Galleria",
                                "zh": "购物中心",
                                "gates": [[1.0, 2.0, 3.0]],
                                "area": "ObjectContainer_Commercial",
                            }
                        ],
                    }
                ],
                "hangars": [
                    {
                        "size": "Small",
                        "door": [0.0, 0.0, 0.0],
                        "lift": [1.0, 1.0, 1.0],
                        "spawn": [2.0, 2.0, 2.0],
                    }
                ],
            },
            "rr_bad": {"station": "Broken", "ok": False},
        },
    },
    "places_zh.json": {
        "lorville": "洛维尔",
        "everusharbor": "艾维拉斯港",
        "target": "可选：脏数据",
        "empty": "",
        "num": 5,
    },  # 空值 / 非字符串不收
    "places_extra_zh.json": {"lorville": "洛维尔（新）"},  # 覆盖
    "place_codes_zh.json": {"stanton1_lorville": "洛维尔"},
    "mining_spots.json": [
        {
            "id": "ab_mine_pyro_001",
            "sys": "Pyro",
            "zh": "远矿站-DARI",
            "en": "RMB-DARI",
            "kind": "mining_base",
            "area": "Deep Space",
            "x": -13521.0,
            "y": 12915.0,
            "z": -149.0,
        },
    ],
}


def _write_all(tmp_path, **override):
    for name, obj in {**_MIN_SOURCES, **_NAV_SOURCES, **override}.items():
        (tmp_path / name).write_text(
            json.dumps(obj, ensure_ascii=False), encoding="utf-8"
        )


def _built(monkeypatch, tmp_path, **override):
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_all(tmp_path, **override)
    rebuild_if_needed()
    return snapshot


def test_schema2_tables_exist(monkeypatch, tmp_path):
    from sc_mining.gamedata._schema import SCHEMA_VERSION

    assert SCHEMA_VERSION >= 2
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        names = {
            r[0] for r in s.execute("select name from sqlite_master where type='table'")
        }
    for t in (
        "bodies",
        "pois",
        "points",
        "city_places",
        "city_place_kinds",
        "amenities",
        "amenity_kinds",
        "station_lifts",
        "place_names",
        "place_codes",
        "mining_spots",
    ):
        assert t in names, t


def test_starmap_import_applies_fixes_and_norms(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        assert s.execute("select sys, rot, grid from bodies where name='Hurston'") == [
            ("Stanton", 2.48, 2e6)
        ]
        assert s.execute("select x, y, z from points where i='HUR_L1'") == [
            (9.0, 9.0, 9.0)
        ]  # fixes 覆盖
        assert s.execute("select n from points where i_lower='hur_l1'") == [
            ("Hurston L1",)
        ]
        assert s.execute("select n from points where norm_n='stantonstar'") == [
            ("Stanton Star",)
        ]
        assert s.execute("select n, qt from pois where norm_n='lorville'") == [
            ("Lorville", 1)
        ]
        assert s.execute("select qt from pois where norm_n='nomarker'") == [
            (None,)
        ]  # 不能压成 0：显示要是「信标未确认」
        # 同内部名两条都在，按 source_order 首个是 Dup A（find_point 语义）
        assert s.execute(
            "select n from points where i_lower='dup_x' order by source_order limit 1"
        ) == [("Dup A",)]
        assert s.execute("select count(*) from points where i_lower='dup_x'") == [(2,)]
        assert s.execute("select value from meta where key='starmap_fetched'") == [
            ("2026-10-28",)
        ]


def test_starmap_without_fixes_file(monkeypatch, tmp_path):
    """有 starmap.json、没有 starmap_fixes.json：坐标原样"""
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_all(tmp_path)
    (tmp_path / "starmap_fixes.json").unlink()
    rebuild_if_needed()
    with snapshot() as s:
        assert s.execute("select x from points where i='HUR_L1'") == [(5.0,)]


def test_city_places_import_matches_transit_rules(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select id, b, n, zh, city, city_zh, x from city_places order by source_order"
        )
        assert (
            rows
            == [
                (
                    "lor_hab",
                    "Hurston",
                    "Hab Lobby",
                    "公寓大堂",
                    "Lorville",
                    "洛维尔",
                    1.0,
                ),
                (
                    "lor_hab2",
                    "Hurston",
                    "Hab Lobby 2",
                    "公寓大堂 2",
                    "Lorville",
                    "洛维尔",
                    1.5,
                ),
                (
                    "lor_hab+",
                    "Hurston",
                    "Hab Dup",
                    "",
                    "Lorville",
                    "罗威尔",  # 没有 site_zh 时 city_zh 来自 transit.CITY_ZH（和汉化包的「洛维尔」不一样，现状如此）
                    1.0,
                ),  # 重复 src 加 +
                ("orb", "@Stanton", "Orbit Shop", "轨道店", "", "", 9.0),  # 空间点
            ]
        )  # 坏坐标那条被丢；同名第二条加序号
        assert s.execute(
            "select kind from city_place_kinds where place_id='lor_hab'"
        ) == [("住宿",)]
        assert s.execute("select space, sys from city_places where id='orb'") == [
            (1, "Stanton")
        ]
        assert s.execute(
            "select up_x, up_y, up_z from city_places where id='lor_hab+'"
        ) == [(0.0, 0.0, 1.0)]
        assert s.execute("select up_x from city_places where id='lor_hab'") == [(None,)]


def test_amenities_import_splits_kinds_and_refs(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        assert s.execute(
            "select a.en, a.rec_lower, a.ref_poi from amenities a join amenity_kinds k on k.amenity_id=a.id where k.kind='商店' order by a.source_order"
        ) == [("Rustville", "pyro1_outpost", "Rustville"), ("HUR-L1 Shop", "", "")]
        # transit.amenity_targets 实际读的 6 种 ref 键都要原样存：poi / body / local / point / point_id / city
        assert s.execute(
            "select ref_poi, ref_body, ref_local_x, ref_local_y, ref_local_z from amenities where en='Everus Harbor'"
        ) == [("Everus Harbor", "Hurston", -507.7, -903.4, 496.4)]
        assert s.execute(
            "select ref_point, ref_point_id from amenities where en='HUR-L1 Shop'"
        ) == [("Hurston L1", "HUR_L1")]
        assert s.execute(
            "select ref_city from amenities where en='Lorville Clinic'"
        ) == [("Lorville",)]
        assert s.execute(
            "select ref_body, ref_poi, ref_local_x from amenities where en='Pyro Body Only'"
        ) == [("Hurston", "", None)]


def test_station_lifts_import_keeps_valid_station_payload(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select station_key, station, sys, space, worst_m, payload_json from station_lifts"
        )
    assert len(rows) == 1 and rows[0][:5] == (
        "rr_hur_l1",
        "Everus Harbor",
        "Stanton",
        1,
        3,
    )
    payload = json.loads(rows[0][5])
    assert payload["lifts"][0]["stops"][0]["gates"] == [
        [1.0, 2.0, 3.0]
    ]  # 和 transit._lift_rows 校验后的原样一致


def test_place_names_keep_both_sources_and_codes(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        # 两份都存（主键 norm_key+src）：poi_zh 取 extra 优先，position 那一路只看 zh
        assert s.execute(
            "select src, zh from place_names where norm_key='lorville' order by src"
        ) == [("extra", "洛维尔（新）"), ("zh", "洛维尔")]
        assert s.execute(
            "select zh from place_names where norm_key='everusharbor'"
        ) == [("艾维拉斯港",)]
        assert s.execute(
            "select count(*) from place_names where norm_key='target'"
        ) == [(1,)]  # 脏键不过滤，保持行为
        assert s.execute(
            "select count(*) from place_names where norm_key in ('empty', 'num')"
        ) == [(0,)]  # 空值 / 非字符串不收
        assert s.execute(
            "select zh from place_codes where code='stanton1_lorville'"
        ) == [("洛维尔",)]


def test_mining_spots_import_keeps_raw_meters(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        assert s.execute(
            "select sys, en, x from mining_spots where spot_id='ab_mine_pyro_001'"
        ) == [("Pyro", "RMB-DARI", -13521.0)]


def test_mining_spots_keep_rows_without_or_duplicate_id(monkeypatch, tmp_path):
    """navigate.mining_spots 每行都处理、不去重：库里也一行不少"""
    spots = _NAV_SOURCES["mining_spots.json"] + [
        {
            "sys": "Pyro",
            "zh": "无 id",
            "en": "NOID",
            "kind": "mining_base",
            "area": "",
            "x": 1.0,
            "y": 2.0,
            "z": 3.0,
        },
        {
            "id": "ab_mine_pyro_001",
            "sys": "Pyro",
            "zh": "重复",
            "en": "DUP",
            "kind": "mining_base",
            "area": "",
            "x": 4.0,
            "y": 5.0,
            "z": 6.0,
        },
    ]
    snapshot = _built(monkeypatch, tmp_path, **{"mining_spots.json": spots})
    with snapshot() as s:
        assert s.execute("select en from mining_spots order by source_order") == [
            ("RMB-DARI",),
            ("NOID",),
            ("DUP",),
        ]


def test_bad_nav_source_does_not_break_items(monkeypatch, tmp_path):
    """导航是可选源：某个文件坏了只影响它自己的表，物品 / 商店照建（审查 2026-11-02 第 3 条）"""
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_all(tmp_path)
    (tmp_path / "places_extra_zh.json").write_text("{", encoding="utf-8")  # 坏 JSON
    (tmp_path / "mining_spots.json").write_text(
        json.dumps(
            [
                {"id": "x", "x": "nan", "y": 0, "z": 0},
                {"id": "ok", "x": 1, "y": 2, "z": 3},
            ]
        ),
        encoding="utf-8",
    )  # 一条坏坐标
    rebuild_if_needed()
    with snapshot() as s:
        assert s.execute("select count(*) from items")[0][0] > 0
        assert s.execute("select zh from place_names where norm_key='lorville'") == [
            ("洛维尔",)
        ]  # extra 坏了：只剩 zh 那份
        assert s.execute("select spot_id from mining_spots") == [
            ("ok",)
        ]  # 坏行跳过，好行保留


def test_nav_sources_optional(monkeypatch, tmp_path):
    """批 1 的最小源不带任何导航文件时也能建库（表存在但为空）"""
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed
    from tests.test_gamedata import _write_min_sources

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    rebuild_if_needed()
    with snapshot() as s:
        assert s.execute("select count(*) from points") == [(0,)]
        assert s.execute("select count(*) from station_lifts") == [(0,)]


def test_bad_poi_or_point_only_drops_that_row(monkeypatch, tmp_path):
    """starmap.space 来的一条坏数据（NaN 坐标、不是 dict、缺 n）只丢那一条，别的 poi / point 照进库（GD-B2 审查第 1 条）"""
    import json
    import math

    sm = json.loads(json.dumps(_NAV_SOURCES["starmap.json"]))
    good_pois, good_points = len(sm["pois"]), len(sm["points"])
    sm["pois"] += [
        {"b": "Hurston", "n": "NaN Poi", "x": float("nan"), "y": 0, "z": 0},
        "junk",
        {"b": None, "n": "No Body", "x": 1, "y": 1, "z": 1},
        {"b": "Hurston", "n": "Null Z", "x": 1, "y": 1, "z": None},
    ]
    sm["points"] += [
        {"n": "Inf Point", "i": "X", "sys": "Stanton", "x": math.inf, "y": 0, "z": 0},
        {"i": "no-name"},
        5,
    ]
    snapshot = _built(monkeypatch, tmp_path, **{"starmap.json": sm})
    with snapshot() as s:
        assert s.execute("select count(*) from pois")[0][0] == good_pois
        assert s.execute("select count(*) from points")[0][0] == good_points
        assert s.execute("select count(*) from items")[0][0] > 0
