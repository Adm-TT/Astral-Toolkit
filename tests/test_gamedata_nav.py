"""游戏数据层 schema 2：星图 / 城市地点 / 设施 / 空间站电梯 / 地名对照 / 挖矿点 的建表与导入（批 2 公共层先行）

用最小源在 tmp_path 建库；变换规则复用 transit._city_rows / transit._lift_rows / starmap._apply_fixes。"""

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
            "en": "HUR-L1",
            "zh": "赫 L1",
            "kinds": ["医疗"],
            "rec": "",
            "ref": {"internal": "HUR_L1"},
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
    },
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


def _write_all(tmp_path):
    for name, obj in {**_MIN_SOURCES, **_NAV_SOURCES}.items():
        (tmp_path / name).write_text(
            json.dumps(obj, ensure_ascii=False), encoding="utf-8"
        )


def _built(monkeypatch, tmp_path):
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_all(tmp_path)
    rebuild_if_needed()
    return snapshot


def test_schema2_tables_exist(monkeypatch, tmp_path):
    from sc_mining.gamedata._schema import SCHEMA_VERSION

    assert SCHEMA_VERSION == 2
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
        assert s.execute("select value from meta where key='starmap_fetched'") == [
            ("2026-10-28",)
        ]


def test_city_places_import_matches_transit_rules(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        rows = s.execute(
            "select id, b, n, zh, city, city_zh, x from city_places order by source_order"
        )
    assert rows == [
        ("lor_hab", "Hurston", "Hab Lobby", "公寓大堂", "Lorville", "洛维尔", 1.0),
        ("lor_hab2", "Hurston", "Hab Lobby 2", "公寓大堂 2", "Lorville", "洛维尔", 1.5),
    ]  # 坏坐标那条被丢；同名第二条加序号
    with snapshot() as s:
        assert s.execute(
            "select kind from city_place_kinds where place_id='lor_hab'"
        ) == [("住宿",)]


def test_amenities_import_splits_kinds_and_refs(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        assert s.execute(
            "select a.en, a.rec_lower, a.ref_poi, a.ref_internal from amenities a join amenity_kinds k on k.amenity_id=a.id where k.kind='商店'"
        ) == [("Rustville", "pyro1_outpost", "Rustville", "")]
        assert s.execute(
            "select en from amenities a join amenity_kinds k on k.amenity_id=a.id where k.kind='医疗'"
        ) == [("HUR-L1",)]


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


def test_place_names_extra_overrides_and_codes(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        assert s.execute(
            "select zh, src from place_names where norm_key='lorville'"
        ) == [("洛维尔（新）", "extra")]
        assert s.execute(
            "select zh from place_names where norm_key='everusharbor'"
        ) == [("艾维拉斯港",)]
        assert s.execute(
            "select count(*) from place_names where norm_key='target'"
        ) == [(1,)]  # 脏键不过滤，保持行为
        assert s.execute(
            "select zh from place_codes where code='stanton1_lorville'"
        ) == [("洛维尔",)]


def test_mining_spots_import_keeps_raw_meters(monkeypatch, tmp_path):
    snapshot = _built(monkeypatch, tmp_path)
    with snapshot() as s:
        assert s.execute(
            "select sys, en, x from mining_spots where id='ab_mine_pyro_001'"
        ) == [("Pyro", "RMB-DARI", -13521.0)]


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
