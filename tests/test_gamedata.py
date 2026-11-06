"""游戏数据层地基（astral_toolkit/gamedata）：路径、类型、写锁、清单、表结构、快照、建库、入口

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），不读真实 data/、不写 userdata/。"""

import dataclasses
from astral_toolkit.gamedata._cache import VersionCache as _VC


def _data_root(monkeypatch, tmp_path):
    from astral_toolkit.core import paths

    monkeypatch.setattr(paths, "DATA", tmp_path)
    return tmp_path


# ---------------------------------------------------------------- Task 1：路径与类型


def test_paths_follow_data_root(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import _paths

    _data_root(monkeypatch, tmp_path)
    assert _paths.gamedata_dir() == tmp_path / "gamedata"
    assert _paths.db_path("abc") == tmp_path / "gamedata" / "gamedata-abc.db"
    assert _paths.manifest_path().name == "current.json"
    assert _paths.tmp_dir() == tmp_path / "gamedata" / "tmp"
    assert _paths.lock_path() == tmp_path / "gamedata" / ".write.lock"


def test_types_are_frozen():
    from astral_toolkit.gamedata import ShopRow, Vec3
    from tests.minipytest import raises

    v = Vec3(1.0, 2.0, 3.0)
    with raises(dataclasses.FrozenInstanceError):
        v.x = 9  # type: ignore[misc]
    assert ShopRow.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_exceptions_hierarchy():
    from astral_toolkit.gamedata import BuildError, GamedataError, GamedataUnavailable

    assert issubclass(GamedataUnavailable, GamedataError)
    assert issubclass(BuildError, GamedataError)


# ---------------------------------------------------------------- Task 2：写锁与清单


def test_write_lock_reentrant_in_process(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import _lock

    _data_root(monkeypatch, tmp_path)
    with _lock.write_lock():
        with _lock.write_lock():  # 同线程可重入
            pass
    assert _lock.lock_path().exists()


def test_write_lock_blocks_other_process(monkeypatch, tmp_path):
    import subprocess
    import sys
    import time

    from astral_toolkit.gamedata import GamedataError, _lock
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    code = (
        "import sys, time; sys.path.insert(0, sys.argv[1]);"
        "from astral_toolkit.core import paths; from pathlib import Path;"
        "paths.DATA = Path(sys.argv[2]);"
        "from astral_toolkit.gamedata import _lock;"
        "l = _lock.write_lock(); l.__enter__(); print('locked', flush=True); time.sleep(3)"
    )
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = subprocess.Popen(
        [sys.executable, "-c", code, root, str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert p.stdout is not None
        assert p.stdout.readline().strip() == "locked"
        t = time.perf_counter()
        with raises(GamedataError):
            with _lock.write_lock(timeout=0.3):
                pass
        assert time.perf_counter() - t < 2.5
    finally:
        p.kill()
        p.wait()


def test_manifest_roundtrip(monkeypatch, tmp_path):
    from astral_toolkit.gamedata._manifest import (
        Manifest,
        read_manifest,
        write_manifest,
    )

    _data_root(monkeypatch, tmp_path)
    m = Manifest("g1", "v1", 1, "gamedata-g1.db")
    write_manifest(m)
    assert read_manifest() == m


def test_manifest_missing_is_none(monkeypatch, tmp_path):
    from astral_toolkit.gamedata._manifest import read_manifest

    _data_root(monkeypatch, tmp_path)
    assert read_manifest() is None


def test_manifest_corrupt_raises(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import GamedataUnavailable
    from astral_toolkit.gamedata._manifest import read_manifest
    from astral_toolkit.gamedata._paths import manifest_path
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    manifest_path().parent.mkdir(parents=True)
    manifest_path().write_text("{", encoding="utf-8")
    with raises(GamedataUnavailable):
        read_manifest()
    manifest_path().write_text('{"generation_id": "g"}', encoding="utf-8")  # 缺字段
    with raises(GamedataUnavailable):
        read_manifest()


# ---------------------------------------------------------------- Task 3：表结构与源清单

_TABLES = {
    "meta",
    "items",
    "item_names",
    "item_source_ids",
    "shop_rows",
    "loot_rows",
    "mineral_prices",
    # schema 2（导航）
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
    # schema 3
    "shop_items",
    # schema 4（制造 / 维科洛 / 物品属性 + 掉落类名，见 test_gamedata_craft）
    "wiki_classes",
    "zh_name_pairs",
    "wiki_items",
    "wiki_alt_classes",
    "name_alias_pairs",
    "blueprints",
    "blueprint_materials",
    "wikelo_contracts",
    "wikelo_rewards",
    "wikelo_requirements",
    "wikelo_contract_systems",
    "item_stats",
    "print_spots",
    "print_spot_places",
    "ship_stock_items",
    # schema 6（采矿，见 test_gamedata_mining）
    "mining_rock_entries",
    "ship_signatures",
    "refinery_yields",
}


def test_ddl_creates_all_tables(tmp_path):
    import sqlite3

    from astral_toolkit.gamedata._schema import DDL, SCHEMA_VERSION

    assert (
        SCHEMA_VERSION == 6
    )  # 2 = 批 2 导航表（见 test_gamedata_nav）；3 = shop_items；4 = 制造 / 维科洛 / 物品属性（见 test_gamedata_craft）；5 = 可空列存 NULL、q 保留类型；6 = 采矿（见 test_gamedata_mining）
    c = sqlite3.connect(tmp_path / "x.db")
    for s in DDL:
        c.execute(s)
    names = {
        r[0] for r in c.execute("select name from sqlite_master where type='table'")
    }
    c.close()
    assert names == _TABLES  # 多一张少一张都不行


def test_read_sources_hash_matches_bytes(tmp_path):
    import hashlib

    from astral_toolkit.gamedata._sources import SOURCES, read_sources

    raw = b'{"items":{},"rows":[]}'
    (tmp_path / "shops.json").write_bytes(raw)
    s = read_sources(tmp_path)
    assert set(s) == {x.name for x in SOURCES}
    assert (
        s["shops.json"].present
        and s["shops.json"].sha256 == hashlib.sha256(raw).hexdigest()
    )
    assert s["shops.json"].data == {"items": {}, "rows": []}
    assert s["loot_index.json"].present is False
    assert s["loot_index.json"].data is None and s["loot_index.json"].sha256 == ""


def test_read_sources_missing_required_raises(tmp_path):
    from astral_toolkit.gamedata import BuildError
    from astral_toolkit.gamedata._sources import read_sources
    from tests.minipytest import raises

    with raises(BuildError):
        read_sources(tmp_path)


def test_read_sources_bad_json_raises(tmp_path):
    from astral_toolkit.gamedata import BuildError
    from astral_toolkit.gamedata._sources import read_sources
    from tests.minipytest import raises

    (tmp_path / "shops.json").write_text('{"items":', encoding="utf-8")
    with raises(BuildError):
        read_sources(tmp_path)


# ---------------------------------------------------------------- Task 4：只读连接与快照


def _make_db(tmp_path, gen, data_version):
    """按 DDL 建一个空库、写 meta、写清单（不走建库流程，单测快照用）"""
    import sqlite3

    from astral_toolkit.gamedata._manifest import Manifest, write_manifest
    from astral_toolkit.gamedata._paths import db_path
    from astral_toolkit.gamedata._schema import DDL, IMPORTER_VERSION, SCHEMA_VERSION

    p = db_path(gen)
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    for s in DDL:
        c.execute(s)
    c.executemany(
        "insert into meta values (?, ?)",
        [
            ("schema_version", str(SCHEMA_VERSION)),
            ("importer_version", str(IMPORTER_VERSION)),
            ("data_version", data_version),
            ("generation_id", gen),
            ("build_time", "2026-11-02T00:00:00"),
        ],
    )
    c.commit()
    c.close()
    m = Manifest(gen, data_version, SCHEMA_VERSION, p.name)
    write_manifest(m)
    return m


def test_snapshot_reads_meta(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import snapshot

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    with snapshot() as s:
        assert s.data_version == "v1"
        assert s.execute("select value from meta where key='generation_id'") == [
            ("g1",)
        ]


def test_snapshot_nested_reuses_outer(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import snapshot

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    with snapshot() as a:
        _make_db(tmp_path, "g2", "v2")  # 中途发布了新代
        with snapshot() as b:
            assert b is a and b.data_version == "v1"
    with snapshot() as c:
        assert c.data_version == "v2"


def test_snapshot_no_manifest_raises(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import GamedataUnavailable, snapshot
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    with raises(GamedataUnavailable):
        with snapshot():
            pass


def test_snapshot_missing_db_file_raises(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import GamedataUnavailable, snapshot
    from astral_toolkit.gamedata._paths import db_path
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    db_path("g1").unlink()
    with raises(GamedataUnavailable):
        with snapshot():
            pass


def test_snapshot_generation_mismatch_raises(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import GamedataUnavailable, snapshot
    from astral_toolkit.gamedata._manifest import Manifest, write_manifest
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    write_manifest(
        Manifest("g9", "v1", 1, "gamedata-g1.db")
    )  # 清单说 g9，库里 meta 是 g1
    with raises(GamedataUnavailable):
        with snapshot():
            pass


def test_version_outside_snapshot_follows_manifest(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import version

    _data_root(monkeypatch, tmp_path)
    assert version() is None
    _make_db(tmp_path, "g1", "v1")
    assert version() == "v1"


def test_snapshot_connection_is_readonly(monkeypatch, tmp_path):
    import sqlite3

    from astral_toolkit.gamedata import GamedataUnavailable, snapshot
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    with snapshot() as s:
        with raises(
            GamedataUnavailable
        ) as got:  # sqlite 错误统一包成 GamedataUnavailable（复审第 10 条）
            s.execute("insert into meta values ('x', 'y')")
    assert got.value is not None and isinstance(
        got.value.__cause__, sqlite3.OperationalError
    )


# ---------------------------------------------------------------- Task 5：导入与建库

_F = ["Stanton", "MicroTech", "MicroTech", "", "", "New Babbage"]
_MIN_SOURCES = {
    "shops.json": {
        "fmt": 2,
        "fetched": 1.0,
        "items": {
            "171": ["Venture Arms", "Arms"],
            "200": ["Lawson Mining Laser", "Mining"],
            "201": ["Lawson Mining Laser", "Mining"],  # 同名第二个 id：商店 id 取第一个
        },
        "rows": [
            [171, "Shop A", "Stanton · X", 586.0, 0.0, "4.10", _F],
            [171, "Shop B", "Stanton · Y", 0.0, 300.0, "4.10", _F],
            [200, "Shop C", "Pyro · Z", 1000.0, 0.0, "4.10", _F],
        ],
    },
    "loot_index.json": {
        "version": "4.10.2LIVE",
        "rows": [
            ["u1", "Medpen", "medpen_01", "common", 3, "医疗笔"],
            ["u2", "夹克 - 名称", "jacket_01", "rare", 1, "DYL Jacket"],  # 中英填反
        ],
    },
    "zh_names.json": {"视差步枪": "HD", "医疗笔": "Medpen"},  # HD 是假英文名
    "zh_only_names.json": {"荣誉勋章": "Medal Of Honor", "章": "Badge"},  # 后者中文太短
    "name_aliases.json": {
        "Medi Pen": "Medpen",
        "Venture Arms": "Lawson Mining Laser",  # 旧写法已经是另一件物品：不能登记
    },
    "wiki_items.json": {
        "items": [
            {"n": "Medpen", "t": "Consumable", "s": 1, "cls": "medpen_01", "d": "急救"},
            {"n": "Some Paint", "t": "Paints", "s": None, "cls": "paint_01", "d": ""},
        ]
    },
    "prices.json": {"prices": {"Aluminum": {"Area18": 3800, "Lorville": 3000}}},
}


def _write_min_sources(tmp_path, **override):
    import json

    for name, obj in {**_MIN_SOURCES, **override}.items():
        (tmp_path / name).write_text(
            json.dumps(obj, ensure_ascii=False), encoding="utf-8"
        )


def test_build_publish_roundtrip(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import snapshot
    from astral_toolkit.gamedata._build import rebuild_if_needed
    from astral_toolkit.gamedata._manifest import read_manifest
    from astral_toolkit.gamedata._paths import db_path, tmp_dir

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    m = rebuild_if_needed()
    assert read_manifest() == m and db_path(m.generation_id).exists()
    assert not list(tmp_dir().glob("*.tmp"))
    with snapshot() as s:
        assert s.data_version == m.data_version
        assert s.execute("select count(*) from shop_rows") == [(3,)]
        assert s.execute("select count(*) from loot_rows") == [(2,)]
        assert s.execute("select price from mineral_prices where city='Lorville'") == [
            (3000.0,)
        ]


def test_rebuild_skips_when_unchanged(monkeypatch, tmp_path):
    from astral_toolkit.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    assert rebuild_if_needed() == rebuild_if_needed()


def test_rebuild_when_source_changes(monkeypatch, tmp_path):
    from astral_toolkit.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    m1 = rebuild_if_needed()
    _write_min_sources(
        tmp_path, **{"prices.json": {"prices": {"Aluminum": {"Area18": 3900}}}}
    )
    m2 = rebuild_if_needed()
    assert m2.generation_id != m1.generation_id
    assert m2.data_version != m1.data_version


def test_rebuild_force_makes_new_generation_same_version(monkeypatch, tmp_path):
    from astral_toolkit.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    m1 = rebuild_if_needed()
    m2 = rebuild_if_needed(force=True)
    assert m2.generation_id != m1.generation_id
    assert m2.data_version == m1.data_version


def test_build_bad_json_keeps_old_manifest(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import BuildError
    from astral_toolkit.gamedata._build import rebuild_if_needed
    from astral_toolkit.gamedata._manifest import read_manifest
    from astral_toolkit.gamedata._paths import tmp_dir
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    m1 = rebuild_if_needed()
    (tmp_path / "shops.json").write_text("{", encoding="utf-8")
    with raises(BuildError):
        rebuild_if_needed()
    assert read_manifest() == m1
    assert not list(tmp_dir().glob("*"))


def test_import_items_follows_itemsearch_rules(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import snapshot
    from astral_toolkit.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    rebuild_if_needed()
    with snapshot() as s:
        ids = {r[0] for r in s.execute("select item_id from items")}
        # 身份键 = itemsearch.en_key（含 l→i 折叠）
        assert ids == {
            "venturearms",
            "iawsonminingiaser",
            "medpen",
            "dyijacket",
            "medaiofhonor",
        }
        # 中英填反的掉落行已纠正
        assert s.execute("select en, zh from items where item_id='dyijacket'") == [
            ("DYL Jacket", "夹克 - 名称")
        ]
        # 三份数据都有的物品：标记齐全，中文名来自汉化包，wiki 字段进来
        row = s.execute(
            "select zh, has_shop, has_loot, loc, wiki, wtype, wsize, desc from items where item_id='medpen'"
        )
        assert row == [("医疗笔", 0, 1, 1, 1, "Consumable", 1, "急救")]
        # 商店 id 取第一个；两个 uex id 都能对到同一件
        assert s.execute(
            "select item_id from item_source_ids where source='uex' and external_id in ('200','201') order by external_id"
        ) == [("iawsonminingiaser",), ("iawsonminingiaser",)]
        assert s.execute(
            "select item_id from item_source_ids where source='loot_uuid' and external_id='u1'"
        ) == [("medpen",)]
        assert s.execute(
            "select item_id from item_source_ids where source='class' and external_id='medpen_01'"
        ) == [("medpen",)]
        # 名字表：英文 + 汉化中文 + 掉落中文 + 旧写法
        kinds = s.execute(
            "select kind, name from item_names where item_id='medpen' order by kind, name"
        )
        assert kinds == [
            ("aka", "Medi Pen"),
            ("en", "Medpen"),
            ("zh_loc", "医疗笔"),
            ("zh_loot", "医疗笔"),
        ]
        # 商店行原样、顺序保留
        assert s.execute(
            "select uex_item_id, shop_name, price_buy, price_sell, f5, source_order from shop_rows order by source_order"
        ) == [
            (171, "Shop A", 586.0, 0.0, "New Babbage", 0),
            (171, "Shop B", 0.0, 300.0, "New Babbage", 1),
            (200, "Shop C", 1000.0, 0.0, "New Babbage", 2),
        ]


def test_import_alias_does_not_override_existing_item(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import snapshot
    from astral_toolkit.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    rebuild_if_needed()
    with snapshot() as s:
        # "Venture Arms" 本身是一件物品，不能变成 Lawson 的旧写法
        assert s.execute(
            "select count(*) from item_names where kind='aka' and name='Venture Arms'"
        ) == [(0,)]
        assert s.execute("select item_id from item_names where norm='venturearms'") == [
            ("venturearms",)
        ]


def test_data_version_depends_on_missing_flag(tmp_path):
    import json

    from astral_toolkit.gamedata._build import data_version
    from astral_toolkit.gamedata._sources import read_sources

    (tmp_path / "shops.json").write_text(
        json.dumps(_MIN_SOURCES["shops.json"]), encoding="utf-8"
    )
    v_missing = data_version(read_sources(tmp_path))
    (tmp_path / "prices.json").write_text("{}", encoding="utf-8")
    v_present = data_version(read_sources(tmp_path))
    assert v_missing != v_present


# ---------------------------------------------------------------- Task 6：对外入口、并发、清理、接入


def test_rebuild_concurrent_same_process(monkeypatch, tmp_path):
    import threading

    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata._paths import gamedata_dir

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    results, errors = [], []

    def go():
        try:
            results.append(G.rebuild())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=go) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors and len(results) == 4
    assert (
        len({m.generation_id for m in results}) == 1
    )  # 只建了一代，其余等锁后发现没变
    assert len(list(gamedata_dir().glob("gamedata-*.db"))) == 1


def test_updating_rebuilds_once_at_outermost(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _build
    from astral_toolkit.gamedata._manifest import Manifest

    _data_root(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        _build,
        "rebuild_if_needed",
        lambda force=False: calls.append(1) or Manifest("g", "v", 1, "gamedata-g.db"),
    )
    with G.updating():
        with G.updating():
            pass
    assert calls == [1]


def test_updating_swallows_build_error_and_records_it(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import BuildError, _build

    _data_root(monkeypatch, tmp_path)

    def boom(force=False):
        raise BuildError("坏了")

    monkeypatch.setattr(_build, "rebuild_if_needed", boom)
    with G.updating():  # 源已写入、建库失败：不抛，记下来
        pass
    assert "坏了" in (G.last_error() or "")


def test_updating_skips_rebuild_when_body_raises(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _build
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        _build, "rebuild_if_needed", lambda force=False: calls.append(1)
    )
    with raises(ValueError):
        with G.updating():
            raise ValueError("写源文件失败")
    assert calls == []


def test_cleanup_skips_when_other_instance_running(monkeypatch, tmp_path):
    from astral_toolkit.gamedata import _build, _lock
    from astral_toolkit.gamedata._paths import gamedata_dir

    _data_root(monkeypatch, tmp_path)
    monkeypatch.setattr(_build, "other_instance_running", lambda: True)
    monkeypatch.setattr(
        _lock, "other_instance_running", lambda: True
    )  # 别碰真实 userdata/instance.lock
    for i, g in enumerate(("g1", "g2", "g3")):  # 三代：keep=1 本来会删一个
        _make_db(tmp_path, g, f"v{i}")
    assert _build.cleanup_old_generations(keep=1) == []
    assert len(list(gamedata_dir().glob("gamedata-*.db"))) == 3


def test_cleanup_keeps_current_and_one_previous(monkeypatch, tmp_path):
    import os
    import time

    from astral_toolkit.gamedata import _build, _lock
    from astral_toolkit.gamedata._paths import db_path, gamedata_dir

    _data_root(monkeypatch, tmp_path)
    monkeypatch.setattr(_lock, "other_instance_running", lambda: False)
    monkeypatch.setattr(_build, "other_instance_running", lambda: False)
    for i, g in enumerate(("g1", "g2", "g3")):
        _make_db(tmp_path, g, f"v{i}")
        t = time.time() - (3 - i) * 10
        os.utime(db_path(g), (t, t))
    removed = _build.cleanup_old_generations(keep=1)
    assert [p.name for p in removed] == ["gamedata-g1.db"]
    assert sorted(p.name for p in gamedata_dir().glob("gamedata-*.db")) == [
        "gamedata-g2.db",
        "gamedata-g3.db",
    ]


def test_warm_up_swallows_errors(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata._manifest import read_manifest

    _data_root(monkeypatch, tmp_path)  # 没有 shops.json：建库必失败
    t = G.warm_up()
    t.join(10)
    assert not t.is_alive()
    assert read_manifest() is None
    assert G.last_error()


def test_refresh_closes_thread_connection(monkeypatch, tmp_path):
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _db

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    with G.snapshot():
        pass
    assert getattr(_db._tls, "conn", None) is not None
    G.refresh()
    assert getattr(_db._tls, "conn", None) is None


def test_data_pack_clear_caches_calls_refresh(monkeypatch):
    import astral_toolkit.gamedata as G
    from astral_toolkit.update import data_pack

    called = []
    monkeypatch.setattr(G, "refresh", lambda: called.append(1))
    monkeypatch.setattr(
        G, "rebuild", lambda: None
    )  # CACHE_HOOKS 里 itemsearch 的钩子会补建库：不碰真实 data/
    data_pack.clear_caches()
    assert called == [1]


# ---------------------------------------------------------------- Task 7：命令行建库工具


def test_cli_build_and_check(monkeypatch, tmp_path):
    import importlib
    import sys
    from pathlib import Path

    from astral_toolkit.gamedata._manifest import read_manifest
    from astral_toolkit.gamedata._paths import db_path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    T = importlib.import_module("build_gamedata")

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    assert T.main(["--data", str(tmp_path)]) == 0
    m = read_manifest()
    assert m is not None
    assert T.main(["--data", str(tmp_path), "--check"]) == 0
    assert T.main(["--data", str(tmp_path)]) == 0  # 没变：不重建
    assert read_manifest() == m
    assert T.main(["--data", str(tmp_path), "--force"]) == 0
    assert read_manifest() != m
    m2 = read_manifest()
    assert m2 is not None
    db_path(m2.generation_id).write_bytes(b"garbage")
    assert T.main(["--data", str(tmp_path), "--check"]) == 2


def test_cli_check_without_db_returns_2(monkeypatch, tmp_path):
    import importlib
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    T = importlib.import_module("build_gamedata")

    _data_root(monkeypatch, tmp_path)
    assert T.main(["--data", str(tmp_path), "--check"]) == 2


# ---------------------------------------------------------------- 审查整改（新上下文审查 2026-11-02）


def test_updating_swallows_any_rebuild_exception(monkeypatch, tmp_path):
    """审查第 2 条：清单被占（PermissionError）或源结构不对（AttributeError）时，源已写好，不能让更新流程报失败"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata import _build

    _data_root(monkeypatch, tmp_path)

    def boom(force=False):
        raise PermissionError("current.json 被占用")

    monkeypatch.setattr(_build, "rebuild_if_needed", boom)
    with G.updating():
        pass
    assert "被占用" in (G.last_error() or "")


def test_build_wraps_unexpected_source_shape_in_build_error(monkeypatch, tmp_path):
    """审查第 2 条：shops.json 是合法 JSON 但结构不对 → BuildError，不是裸 AttributeError"""
    from astral_toolkit.gamedata import BuildError
    from astral_toolkit.gamedata._build import rebuild_if_needed
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path, **{"shops.json": [1, 2, 3]})
    with raises(BuildError):
        rebuild_if_needed()


def test_rebuild_recovers_from_corrupt_manifest(monkeypatch, tmp_path):
    """审查第 3 条：清单坏了要能重建，不是永远报错"""
    from astral_toolkit.gamedata._build import rebuild_if_needed
    from astral_toolkit.gamedata._manifest import read_manifest
    from astral_toolkit.gamedata._paths import manifest_path

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    manifest_path().parent.mkdir(parents=True, exist_ok=True)
    manifest_path().write_text("{", encoding="utf-8")
    m = rebuild_if_needed()
    assert read_manifest() == m


def test_ensure_ready_rebuilds_when_db_file_corrupt(monkeypatch, tmp_path):
    """审查第 4 条：库文件在但是坏的 → 启动要重建新一代，不能跳过"""
    import astral_toolkit.gamedata as G
    from astral_toolkit.gamedata._build import rebuild_if_needed
    from astral_toolkit.gamedata._paths import db_path

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    m1 = rebuild_if_needed()
    db_path(m1.generation_id).write_bytes(b"garbage")
    m2 = G.ensure_ready()
    assert m2.generation_id != m1.generation_id
    with G.snapshot() as s:
        assert s.execute("select count(*) from items")[0][0] > 0


def test_data_version_includes_app_version(monkeypatch, tmp_path):
    """审查第 5 条：导入规则是代码，升级应用后库要重建"""
    from astral_toolkit.core import version as V
    from astral_toolkit.gamedata._build import data_version
    from astral_toolkit.gamedata._sources import read_sources

    _write_min_sources(tmp_path)
    a = data_version(read_sources(tmp_path))
    monkeypatch.setattr(V, "VERSION", "99.99.99")
    b = data_version(read_sources(tmp_path))
    assert a != b


def test_names_table_without_zh_names_is_empty(monkeypatch, tmp_path):
    """审查第 6 条：没有 zh_names.json 时 names.table() 返回空，不补 zh_only_names；导入要一致"""
    from astral_toolkit.gamedata._import import _names_table
    from astral_toolkit.gamedata._sources import read_sources

    _write_min_sources(tmp_path)
    (tmp_path / "zh_names.json").unlink()
    assert _names_table(read_sources(tmp_path)) == {}


def test_import_matches_itemsearch_index_on_sample(monkeypatch, tmp_path):
    """审查第 8 条：在同一份小样本上，建库结果和 itemsearch._build_locked() 逐条一致"""
    from astral_toolkit.crafting import itemsearch, loot, shops
    from astral_toolkit.gamedata import snapshot
    from astral_toolkit.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    monkeypatch.setattr(shops, "CACHE", tmp_path / "shops.json")
    monkeypatch.setattr(loot, "INDEX", tmp_path / "loot_index.json")
    monkeypatch.setattr(loot, "_index", None)
    monkeypatch.setattr(itemsearch, "_cache", _VC())
    index = itemsearch._build_locked()
    assert index is not None
    rows = index["rows"]
    rebuild_if_needed()
    with snapshot() as s:
        db = s.execute(
            "select item_id, en, zh, cat, has_shop, has_loot, loc, wiki, wtype, wsize, desc, variant, zlen, source_order from items order by source_order"
        )
        aka = {}
        for iid, name in s.execute(
            "select item_id, name from item_names where kind='aka'"
        ):
            aka.setdefault(iid, []).append(name)
    exp = [
        (
            e["ek"],
            e["en"],
            e["zh"],
            e["cat"],
            int(e["shop"] is not None),
            int(e["loot"]),
            int(e["loc"]),
            int(bool(e.get("wiki"))),
            e.get("wtype") or "",
            e.get("wsize"),
            e.get("desc") or "",
            int(e["variant"]),
            e["zlen"],
            i,
        )
        for i, e in enumerate(rows)
    ]
    assert db == exp
    assert aka == {e["ek"]: e["aka"] for e in rows if e.get("aka")}
    assert len(rows) >= 4


# ---------------------------------------------------------------- schema 3：shop_items（批 1 要求，2026-11-02）


def test_shop_items_keep_every_uex_entry_verbatim(monkeypatch, tmp_path):
    """shops.json 的 items 原样一行一条：同一折叠名的两种写法（Synergy / Synergy+）都在，英文名不改、顺序照源"""
    from astral_toolkit.gamedata import snapshot
    from astral_toolkit.gamedata._build import rebuild_if_needed
    from astral_toolkit.gamedata._schema import SCHEMA_VERSION

    assert SCHEMA_VERSION >= 3  # shop_items 从 3 起就有
    _data_root(monkeypatch, tmp_path)
    shops = dict(_MIN_SOURCES["shops.json"])
    shops["items"] = {
        **shops["items"],
        "1797": ["Synergy", "Component"],
        "1798": ["Synergy+", None],  # 折叠后同名；类别 None → ''
        "1799": ["Odd\xa0Name", "Misc"],  # 不换 \xa0
    }
    _write_min_sources(tmp_path, **{"shops.json": shops})
    rebuild_if_needed()
    with snapshot() as s:
        rows = s.execute(
            "select uex_item_id, en, cat, source_order from shop_items order by source_order"
        )
    assert rows[:3] == [
        (171, "Venture Arms", "Arms", 0),
        (200, "Lawson Mining Laser", "Mining", 1),
        (201, "Lawson Mining Laser", "Mining", 2),
    ]
    assert rows[3:] == [
        (1797, "Synergy", "Component", 3),
        (1798, "Synergy+", "", 4),
        (1799, "Odd\xa0Name", "Misc", 5),
    ]


# ---------------------------------------------------------------- 读清单的 Windows 共享冲突重试（批 1 实测：边搜边发布，读清单报拒绝访问）


def test_read_manifest_retries_permission_error(monkeypatch, tmp_path):
    from pathlib import Path

    from astral_toolkit.gamedata import _manifest
    from astral_toolkit.gamedata._manifest import (
        Manifest,
        read_manifest,
        write_manifest,
    )

    _data_root(monkeypatch, tmp_path)
    m = Manifest("g1", "v1", 1, "gamedata-g1.db")
    write_manifest(m)
    real = Path.read_text
    calls = {"n": 0}

    def flaky(self, *a, **kw):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise PermissionError(13, "拒绝访问")  # 换名瞬间
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", flaky)
    monkeypatch.setattr(_manifest, "_RETRY_SLEEP", 0.0)
    assert read_manifest() == m
    assert calls["n"] == 4


def test_read_manifest_gives_up_after_retries(monkeypatch, tmp_path):
    from pathlib import Path

    from astral_toolkit.gamedata import GamedataUnavailable, _manifest
    from astral_toolkit.gamedata._manifest import (
        Manifest,
        read_manifest,
        write_manifest,
    )
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    write_manifest(Manifest("g1", "v1", 1, "gamedata-g1.db"))

    def always(self, *a, **kw):
        raise PermissionError(13, "拒绝访问")

    monkeypatch.setattr(Path, "read_text", always)
    monkeypatch.setattr(_manifest, "_RETRY_SLEEP", 0.0)
    with raises(GamedataUnavailable):
        read_manifest()


def test_read_manifest_cached_until_file_changes(monkeypatch, tmp_path):
    """清单文件没变（mtime / 大小 / inode 一样）就不重读：导航每帧读清单好几次（收口 2）；换文件、就地改坏都能察觉"""
    from pathlib import Path

    from astral_toolkit.gamedata import GamedataUnavailable
    from astral_toolkit.gamedata._manifest import (
        Manifest,
        read_manifest,
        write_manifest,
    )
    from astral_toolkit.gamedata._paths import manifest_path
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    write_manifest(Manifest("g1", "v1", 1, "gamedata-g1.db"))
    first = read_manifest()
    real = Path.read_text
    reads = []
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *a, **kw: (reads.append(1), real(self, *a, **kw))[1],
    )
    assert read_manifest() is first and read_manifest() is first and reads == []
    write_manifest(Manifest("g2", "v2", 1, "gamedata-g2.db"))  # os.replace 换文件
    assert read_manifest() == Manifest("g2", "v2", 1, "gamedata-g2.db") and reads == [1]
    manifest_path().write_text("{", encoding="utf-8")  # 就地改坏（大小变了）
    with raises(GamedataUnavailable):
        read_manifest()
    manifest_path().unlink()
    assert read_manifest() is None
