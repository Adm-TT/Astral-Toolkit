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
