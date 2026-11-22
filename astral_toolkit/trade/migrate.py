"""库存库 schema 原地升级（PRAGMA user_version）。

发版 STEPS 为空、SCHEMA_VERSION 仍为 2：通道与测试就绪，下一刀真实 DDL 再登记步骤并抬版本。
新结构性对象必须走 N→N+1 迁移并抬 user_version，不要只靠 CREATE IF NOT EXISTS 偷加。
每一步在一个事务里跑，建表、加列这类语句和数据改写一起提交、出错一起回滚（实测能回滚）。
步骤里不许自己提交：不要用 executescript（它会先把当前事务提交掉）、不要自己 COMMIT——
那样出错时前面的改动已经落盘、版本却没抬，库就成了半截升级的。跑完一步会查这件事，查到就报错（审查 2026-11-23）。
不做 down-migrate。详见 docs/superpowers/specs/2026-11-17-inventory-schema-migrations.md。
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .storage import APP_ID, SCHEMA_VERSION


@dataclass(frozen=True)
class MigrationStep:
    """一步：from_version → to_version。upgrade 在已打开的写连接上改库，须幂等。"""

    from_version: int
    to_version: int
    note: str
    upgrade: Callable[[sqlite3.Connection], None]


# 发版迁移链；无真实 DDL 前保持空。测试可传入自定义 steps。
STEPS: tuple[MigrationStep, ...] = ()


def _read_version(path: Path) -> int:
    uri = path.absolute().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=15)) as c:
        if c.execute("PRAGMA application_id").fetchone()[0] != APP_ID:
            raise ValueError("不是交易助手数据库")
        return int(c.execute("PRAGMA user_version").fetchone()[0])


def _backup_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(src, timeout=15)) as s,
        closing(sqlite3.connect(dest)) as d,
    ):
        s.backup(d)


def _chain(
    from_version: int, target_version: int, steps: Sequence[MigrationStep]
) -> list[MigrationStep]:
    by_from = {s.from_version: s for s in steps}
    out: list[MigrationStep] = []
    cur = from_version
    while cur < target_version:
        step = by_from.get(cur)
        if step is None or step.to_version <= cur:
            raise ValueError(
                f"没有从版本 {cur} 升到 {target_version} 的迁移步骤，未改库"
            )
        out.append(step)
        cur = step.to_version
    if cur != target_version:
        raise ValueError(f"迁移链终点是 {cur}，目标是 {target_version}，未改库")
    return out


def upgrade_if_needed(
    path: Path | str,
    *,
    target_version: int = SCHEMA_VERSION,
    steps: Sequence[MigrationStep] | None = None,
    backup_dir: Path | str | None = None,
) -> Path | None:
    """若 user_version < target_version：先备份，再按序执行步骤并抬版本。
    已是最新 → 返回 None（不备份）。
    成功升级 → 返回备份路径。
    备份失败或任一步失败 → 抛 ValueError，不抬版本（能回滚的已回滚；DDL 靠步骤幂等）。"""
    path = Path(path)
    if not path.exists():
        raise ValueError("库存库文件不存在，无法升级")
    use_steps = STEPS if steps is None else steps
    backup_root = Path(backup_dir) if backup_dir is not None else path.parent

    current = _read_version(path)
    if current > target_version:
        raise ValueError("库存库比本程序新，请升级 AT")
    if current == target_version:
        return None

    chain = _chain(current, target_version, use_steps)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = backup_root / f"inventory_升级前备份_{stamp}.db"
    n = 2
    while backup_path.exists():  # 同一秒里又升一次：别盖掉上一份备份
        backup_path = backup_root / f"inventory_升级前备份_{stamp}_{n}.db"
        n += 1
    try:
        _backup_file(path, backup_path)
    except (OSError, sqlite3.Error) as e:
        raise ValueError(f"库存升级前备份失败，未改库：{e}") from e
    if not backup_path.is_file():
        raise ValueError("库存升级前备份失败，未改库：备份文件未生成")

    for step in chain:
        try:
            with closing(sqlite3.connect(path, timeout=15, isolation_level=None)) as c:
                c.execute("PRAGMA foreign_keys=ON")
                c.execute("BEGIN IMMEDIATE")
                try:
                    step.upgrade(c)
                    if (
                        not c.in_transaction
                    ):  # 这一步自己把事务提交了：改动已经落盘，没法回滚
                        raise RuntimeError(
                            "这一步自己提交了事务（用了 executescript 或 COMMIT），"
                            "库可能只升了一半，要从备份恢复"
                        )
                    c.execute(f"PRAGMA user_version={int(step.to_version)}")
                    c.execute("COMMIT")
                except BaseException:
                    try:
                        c.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                    raise
        except Exception as e:
            raise ValueError(
                f"库存库从 {step.from_version} 升到 {step.to_version} 失败"
                f"（{step.note}），版本未抬升。备份：{backup_path}"
            ) from e

    final = _read_version(path)
    if final != target_version:
        raise ValueError(
            f"库存升级后版本是 {final}，期望 {target_version}。备份：{backup_path}"
        )
    return backup_path
