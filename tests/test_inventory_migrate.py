"""库存库 schema 原地升级通道（方案 A：发版 SCHEMA_VERSION 仍为 2，夹具注入 2→3）。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from tests.minipytest import raises

from astral_toolkit.trade.migrate import MigrationStep, upgrade_if_needed
from astral_toolkit.trade.storage import APP_ID, SCHEMA_VERSION, Database


def _version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as c:
        return int(c.execute("PRAGMA user_version").fetchone()[0])


def _step_2_to_3_ok() -> MigrationStep:
    def upgrade(c: sqlite3.Connection) -> None:
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_migration_demo ("
            "id INTEGER PRIMARY KEY, note TEXT NOT NULL DEFAULT '')"
        )

    return MigrationStep(2, 3, "测试：示范旁路表", upgrade)


def _step_2_to_3_fail() -> MigrationStep:
    def upgrade(c: sqlite3.Connection) -> None:
        raise RuntimeError("注入失败")

    return MigrationStep(2, 3, "测试：故意失败", upgrade)


def test_new_db_is_schema_version_2(tmp_path):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)
    assert SCHEMA_VERSION == 2
    assert _version(path) == 2


def test_current_open_noop_no_backup(tmp_path):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)
    before = list(tmp_path.glob("inventory_升级前备份_*.db"))
    Database(path)  # 再打开
    after = list(tmp_path.glob("inventory_升级前备份_*.db"))
    assert before == after == []


def test_upgrade_2_to_3_with_injected_steps(tmp_path):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)
    bak = upgrade_if_needed(
        path,
        target_version=3,
        steps=[_step_2_to_3_ok()],
        backup_dir=tmp_path,
    )
    assert bak is not None and bak.is_file()
    assert _version(path) == 3
    with closing(sqlite3.connect(path)) as c:
        c.execute("INSERT INTO items(id,name) VALUES ('a','x')")
        c.commit()
        assert c.execute("SELECT id FROM items").fetchone()[0] == "a"
        assert c.execute(
            "SELECT name FROM sqlite_master WHERE name='schema_migration_demo'"
        ).fetchone()


def test_upgrade_step_failure_keeps_version_and_backup(tmp_path):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)
    with raises(ValueError, match="版本未抬升"):
        upgrade_if_needed(
            path,
            target_version=3,
            steps=[_step_2_to_3_fail()],
            backup_dir=tmp_path,
        )
    assert _version(path) == 2
    assert list(tmp_path.glob("inventory_升级前备份_*.db"))
    # 修复步骤后可重试
    upgrade_if_needed(
        path,
        target_version=3,
        steps=[_step_2_to_3_ok()],
        backup_dir=tmp_path,
    )
    assert _version(path) == 3


def test_step_that_commits_on_its_own_is_reported(tmp_path):
    """步骤里用 executescript 会把事务提交掉：出错时前面的改动回滚不了。跑完一步要查出来并报错，版本不抬（审查 2026-11-23）"""
    path = tmp_path / "dubhe_inventory.db"
    Database(path)

    def upgrade(c: sqlite3.Connection) -> None:
        c.executescript(
            "CREATE TABLE IF NOT EXISTS schema_migration_demo (id INTEGER);"
        )

    with raises(ValueError, match="版本未抬升"):
        upgrade_if_needed(
            path,
            target_version=3,
            steps=[MigrationStep(2, 3, "测试：自己提交", upgrade)],
            backup_dir=tmp_path,
        )
    assert _version(path) == 2


def test_plain_ddl_rolls_back_with_the_step(tmp_path):
    """一步里先建表、后出错：表不留下（建表语句和这一步同一个事务）"""
    path = tmp_path / "dubhe_inventory.db"
    Database(path)

    def upgrade(c: sqlite3.Connection) -> None:
        c.execute("CREATE TABLE schema_migration_demo (id INTEGER)")
        raise RuntimeError("注入失败")

    with raises(ValueError, match="版本未抬升"):
        upgrade_if_needed(
            path,
            target_version=3,
            steps=[MigrationStep(2, 3, "测试：建表后失败", upgrade)],
            backup_dir=tmp_path,
        )
    with closing(sqlite3.connect(path)) as c:
        assert not c.execute(
            "SELECT 1 FROM sqlite_master WHERE name='schema_migration_demo'"
        ).fetchone()


def test_backups_in_the_same_second_do_not_overwrite(tmp_path):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)
    for _ in range(2):
        with raises(ValueError, match="版本未抬升"):
            upgrade_if_needed(
                path,
                target_version=3,
                steps=[_step_2_to_3_fail()],
                backup_dir=tmp_path,
            )
    assert len(list(tmp_path.glob("inventory_升级前备份_*.db"))) == 2


def test_database_refuses_newer_than_program(tmp_path):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)
    with closing(sqlite3.connect(path)) as c:
        c.execute("PRAGMA user_version=99")
        c.commit()
    with raises(ValueError, match="比本程序新"):
        Database(path)


def test_backup_failure_does_not_change_db(tmp_path, monkeypatch):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)

    def boom(src, dest):
        raise OSError("磁盘满")

    monkeypatch.setattr("astral_toolkit.trade.migrate._backup_file", boom)
    with raises(ValueError, match="备份失败"):
        upgrade_if_needed(
            path,
            target_version=3,
            steps=[_step_2_to_3_ok()],
            backup_dir=tmp_path,
        )
    assert _version(path) == 2


def test_missing_steps_does_not_change_db(tmp_path):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)
    with raises(ValueError, match="没有从版本"):
        upgrade_if_needed(path, target_version=3, steps=[], backup_dir=tmp_path)
    assert _version(path) == 2
    assert list(tmp_path.glob("inventory_升级前备份_*.db")) == []


def test_upgrade_if_needed_noop_when_current(tmp_path):
    path = tmp_path / "dubhe_inventory.db"
    Database(path)
    assert upgrade_if_needed(path, target_version=2, steps=[]) is None
    assert list(tmp_path.glob("inventory_升级前备份_*.db")) == []


def test_app_id_constant():
    assert APP_ID == 0x53435443
