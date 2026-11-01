"""游戏数据层地基（sc_mining/gamedata）：路径、类型、写锁、清单、表结构、快照、建库、入口

全部用 tmp_path 当 data/ 根（monkeypatch paths.DATA），不读真实 data/、不写 userdata/。"""

import dataclasses


def _data_root(monkeypatch, tmp_path):
    from sc_mining.core import paths

    monkeypatch.setattr(paths, "DATA", tmp_path)
    return tmp_path


# ---------------------------------------------------------------- Task 1：路径与类型


def test_paths_follow_data_root(monkeypatch, tmp_path):
    from sc_mining.gamedata import _paths

    _data_root(monkeypatch, tmp_path)
    assert _paths.gamedata_dir() == tmp_path / "gamedata"
    assert _paths.db_path("abc") == tmp_path / "gamedata" / "gamedata-abc.db"
    assert _paths.manifest_path().name == "current.json"
    assert _paths.tmp_dir() == tmp_path / "gamedata" / "tmp"
    assert _paths.lock_path() == tmp_path / "gamedata" / ".write.lock"


def test_types_are_frozen():
    from sc_mining.gamedata import ShopRow, Vec3
    from tests.minipytest import raises

    v = Vec3(1.0, 2.0, 3.0)
    with raises(dataclasses.FrozenInstanceError):
        v.x = 9  # type: ignore[misc]
    assert ShopRow.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_exceptions_hierarchy():
    from sc_mining.gamedata import BuildError, GamedataError, GamedataUnavailable

    assert issubclass(GamedataUnavailable, GamedataError)
    assert issubclass(BuildError, GamedataError)


# ---------------------------------------------------------------- Task 2：写锁与清单


def test_write_lock_reentrant_in_process(monkeypatch, tmp_path):
    from sc_mining.gamedata import _lock

    _data_root(monkeypatch, tmp_path)
    with _lock.write_lock():
        with _lock.write_lock():  # 同线程可重入
            pass
    assert _lock.lock_path().exists()


def test_write_lock_blocks_other_process(monkeypatch, tmp_path):
    import subprocess
    import sys
    import time

    from sc_mining.gamedata import GamedataError, _lock
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    code = (
        "import sys, time; sys.path.insert(0, sys.argv[1]);"
        "from sc_mining.core import paths; from pathlib import Path;"
        "paths.DATA = Path(sys.argv[2]);"
        "from sc_mining.gamedata import _lock;"
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
    from sc_mining.gamedata._manifest import Manifest, read_manifest, write_manifest

    _data_root(monkeypatch, tmp_path)
    m = Manifest("g1", "v1", 1, "gamedata-g1.db")
    write_manifest(m)
    assert read_manifest() == m


def test_manifest_missing_is_none(monkeypatch, tmp_path):
    from sc_mining.gamedata._manifest import read_manifest

    _data_root(monkeypatch, tmp_path)
    assert read_manifest() is None


def test_manifest_corrupt_raises(monkeypatch, tmp_path):
    from sc_mining.gamedata import GamedataUnavailable
    from sc_mining.gamedata._manifest import read_manifest
    from sc_mining.gamedata._paths import manifest_path
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
}


def test_ddl_creates_all_tables(tmp_path):
    import sqlite3

    from sc_mining.gamedata._schema import DDL, SCHEMA_VERSION

    assert SCHEMA_VERSION == 1
    c = sqlite3.connect(tmp_path / "x.db")
    for s in DDL:
        c.execute(s)
    names = {
        r[0] for r in c.execute("select name from sqlite_master where type='table'")
    }
    c.close()
    assert names == _TABLES


def test_read_sources_hash_matches_bytes(tmp_path):
    import hashlib

    from sc_mining.gamedata._sources import SOURCES, read_sources

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
    from sc_mining.gamedata import BuildError
    from sc_mining.gamedata._sources import read_sources
    from tests.minipytest import raises

    with raises(BuildError):
        read_sources(tmp_path)


def test_read_sources_bad_json_raises(tmp_path):
    from sc_mining.gamedata import BuildError
    from sc_mining.gamedata._sources import read_sources
    from tests.minipytest import raises

    (tmp_path / "shops.json").write_text('{"items":', encoding="utf-8")
    with raises(BuildError):
        read_sources(tmp_path)


# ---------------------------------------------------------------- Task 4：只读连接与快照


def _make_db(tmp_path, gen, data_version):
    """按 DDL 建一个空库、写 meta、写清单（不走建库流程，单测快照用）"""
    import sqlite3

    from sc_mining.gamedata._manifest import Manifest, write_manifest
    from sc_mining.gamedata._paths import db_path
    from sc_mining.gamedata._schema import DDL, IMPORTER_VERSION, SCHEMA_VERSION

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
    from sc_mining.gamedata import snapshot

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    with snapshot() as s:
        assert s.data_version == "v1"
        assert s.execute("select value from meta where key='generation_id'") == [
            ("g1",)
        ]


def test_snapshot_nested_reuses_outer(monkeypatch, tmp_path):
    from sc_mining.gamedata import snapshot

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    with snapshot() as a:
        _make_db(tmp_path, "g2", "v2")  # 中途发布了新代
        with snapshot() as b:
            assert b is a and b.data_version == "v1"
    with snapshot() as c:
        assert c.data_version == "v2"


def test_snapshot_no_manifest_raises(monkeypatch, tmp_path):
    from sc_mining.gamedata import GamedataUnavailable, snapshot
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    with raises(GamedataUnavailable):
        with snapshot():
            pass


def test_snapshot_missing_db_file_raises(monkeypatch, tmp_path):
    from sc_mining.gamedata import GamedataUnavailable, snapshot
    from sc_mining.gamedata._paths import db_path
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    db_path("g1").unlink()
    with raises(GamedataUnavailable):
        with snapshot():
            pass


def test_snapshot_generation_mismatch_raises(monkeypatch, tmp_path):
    from sc_mining.gamedata import GamedataUnavailable, snapshot
    from sc_mining.gamedata._manifest import Manifest, write_manifest
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
    from sc_mining.gamedata import version

    _data_root(monkeypatch, tmp_path)
    assert version() is None
    _make_db(tmp_path, "g1", "v1")
    assert version() == "v1"


def test_snapshot_connection_is_readonly(monkeypatch, tmp_path):
    import sqlite3

    from sc_mining.gamedata import snapshot
    from tests.minipytest import raises

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    with snapshot() as s:
        with raises(sqlite3.OperationalError):
            s.execute("insert into meta values ('x', 'y')")


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
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed
    from sc_mining.gamedata._manifest import read_manifest
    from sc_mining.gamedata._paths import db_path, tmp_dir

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
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    assert rebuild_if_needed() == rebuild_if_needed()


def test_rebuild_when_source_changes(monkeypatch, tmp_path):
    from sc_mining.gamedata._build import rebuild_if_needed

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
    from sc_mining.gamedata._build import rebuild_if_needed

    _data_root(monkeypatch, tmp_path)
    _write_min_sources(tmp_path)
    m1 = rebuild_if_needed()
    m2 = rebuild_if_needed(force=True)
    assert m2.generation_id != m1.generation_id
    assert m2.data_version == m1.data_version


def test_build_bad_json_keeps_old_manifest(monkeypatch, tmp_path):
    from sc_mining.gamedata import BuildError
    from sc_mining.gamedata._build import rebuild_if_needed
    from sc_mining.gamedata._manifest import read_manifest
    from sc_mining.gamedata._paths import tmp_dir
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
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

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
    from sc_mining.gamedata import snapshot
    from sc_mining.gamedata._build import rebuild_if_needed

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

    from sc_mining.gamedata._build import data_version
    from sc_mining.gamedata._sources import read_sources

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

    import sc_mining.gamedata as G
    from sc_mining.gamedata._paths import gamedata_dir

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
    import sc_mining.gamedata as G
    from sc_mining.gamedata import _build
    from sc_mining.gamedata._manifest import Manifest

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
    import sc_mining.gamedata as G
    from sc_mining.gamedata import BuildError, _build

    _data_root(monkeypatch, tmp_path)

    def boom(force=False):
        raise BuildError("坏了")

    monkeypatch.setattr(_build, "rebuild_if_needed", boom)
    with G.updating():  # 源已写入、建库失败：不抛，记下来
        pass
    assert "坏了" in (G.last_error() or "")


def test_updating_skips_rebuild_when_body_raises(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata import _build
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
    from sc_mining.gamedata import _lock
    from sc_mining.gamedata._build import cleanup_old_generations
    from sc_mining.gamedata._paths import gamedata_dir

    _data_root(monkeypatch, tmp_path)
    monkeypatch.setattr(_lock, "other_instance_running", lambda: True)
    _make_db(tmp_path, "g1", "v1")
    _make_db(tmp_path, "g2", "v2")
    assert cleanup_old_generations() == []
    assert len(list(gamedata_dir().glob("gamedata-*.db"))) == 2


def test_cleanup_keeps_current_and_one_previous(monkeypatch, tmp_path):
    import os
    import time

    from sc_mining.gamedata import _build, _lock
    from sc_mining.gamedata._paths import db_path, gamedata_dir

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
    import sc_mining.gamedata as G
    from sc_mining.gamedata._manifest import read_manifest

    _data_root(monkeypatch, tmp_path)  # 没有 shops.json：建库必失败
    t = G.warm_up()
    t.join(10)
    assert not t.is_alive()
    assert read_manifest() is None
    assert G.last_error()


def test_refresh_closes_thread_connection(monkeypatch, tmp_path):
    import sc_mining.gamedata as G
    from sc_mining.gamedata import _db

    _data_root(monkeypatch, tmp_path)
    _make_db(tmp_path, "g1", "v1")
    with G.snapshot():
        pass
    assert getattr(_db._tls, "conn", None) is not None
    G.refresh()
    assert getattr(_db._tls, "conn", None) is None


def test_data_pack_clear_caches_calls_refresh(monkeypatch):
    import sc_mining.gamedata as G
    from sc_mining.update import data_pack

    called = []
    monkeypatch.setattr(G, "refresh", lambda: called.append(1))
    data_pack.clear_caches()
    assert called == [1]
