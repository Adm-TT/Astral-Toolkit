"""建库与发布：源 JSON → 临时库 → 校验 → 落成 gamedata-<代号>.db → 原子切换清单

内容版本 data_version 由源文件（名字、在不在、字节哈希）+ schema 版本 + 导入规则版本算出；没变就不重建。
建库失败只抛 BuildError，旧库和旧清单一个字节不动。"""

import hashlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from . import _import
from ._lock import other_instance_running, write_lock
from ._manifest import Manifest, read_manifest, write_manifest
from ._paths import db_path, gamedata_dir, tmp_dir
from ._schema import DDL, IMPORTER_VERSION, SCHEMA_VERSION
from ._sources import SourceBytes, read_sources
from ._types import BuildError, GamedataUnavailable

_REQUIRED_NONEMPTY = ("items", "shop_rows")  # 源不空时这两张表不能空


def data_version(sources: dict[str, SourceBytes]) -> str:
    """源文件清单（名字、在不在、sha256）+ schema + 导入规则 → 稳定的内容版本"""
    from ..core import version as _v

    payload = {
        "schema": SCHEMA_VERSION,
        "importer": IMPORTER_VERSION,
        "app": _v.VERSION,  # 导入规则复用 itemsearch / names / i18n 的代码，升级应用就得重建（审查 2026-11-02）
        "files": sorted((s.name, s.present, s.sha256) for s in sources.values()),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:32]


def new_generation_id() -> str:
    return time.strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)


def build(sources: dict[str, SourceBytes], generation_id: str, dv: str) -> Path:
    """建到 tmp/ 下的临时库，校验通过后挪到正式位置。失败抛 BuildError 并删掉临时文件"""
    tmp_dir().mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir() / f"gamedata-{generation_id}.db.tmp"
    dst = db_path(generation_id)
    conn = None
    try:
        conn = sqlite3.connect(tmp)
        conn.execute("PRAGMA journal_mode=DELETE")
        with conn:
            for s in DDL:
                conn.execute(s)
            _import.import_items(conn, sources)
            _import.import_shops(conn, sources)
            _import.import_loot(conn, sources)
            _import.import_wiki_classes(conn, sources)
            _import.import_name_pairs(conn, sources)
            _import.import_wiki_rows(conn, sources)
            _import.import_prices(conn, sources)
            _import.import_starmap(conn, sources)
            _import.import_city_places(conn, sources)
            _import.import_amenities(conn, sources)
            _import.import_station_lifts(conn, sources)
            _import.import_place_names(conn, sources)
            _import.import_mining_spots(conn, sources)
            _import.import_crafting(conn, sources)
            _import.import_wikelo(conn, sources)
            _import.import_item_stats(conn, sources)
            _import.import_print_spots(conn, sources)
            _import.import_ship_items(conn, sources)
            meta = [
                ("schema_version", str(SCHEMA_VERSION)),
                ("importer_version", str(IMPORTER_VERSION)),
                ("data_version", dv),
                ("generation_id", generation_id),
                ("build_time", time.strftime("%Y-%m-%dT%H:%M:%S")),
            ] + [(f"src:{s.name}", s.sha256) for s in sources.values()]
            conn.executemany("insert into meta values (?, ?)", meta)
        _verify(conn, sources)
        conn.close()
        conn = None
        os.replace(tmp, dst)
        return dst
    except BuildError:
        raise
    except Exception as e:  # noqa: BLE001 —— 源结构不对会抛各种异常，统一成 BuildError，旧库不受影响
        raise BuildError(f"建游戏数据库失败：{e}") from e
    finally:
        if conn is not None:
            conn.close()
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _verify(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    ok = conn.execute("PRAGMA quick_check").fetchone()
    if not ok or ok[0] != "ok":
        raise BuildError(f"游戏数据库完整性检查不过：{ok}")
    have = {
        r[0] for r in conn.execute("select name from sqlite_master where type='table'")
    }
    need = {
        "meta",
        "items",
        "item_names",
        "item_source_ids",
        "shop_items",
        "shop_rows",
        "loot_rows",
        "mineral_prices",
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
        # schema 4
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
    }
    if not need <= have:
        raise BuildError(f"游戏数据库缺表：{sorted(need - have)}")
    shops = sources.get("shops.json")
    if shops and shops.data and (shops.data.get("items") or shops.data.get("rows")):
        for t in _REQUIRED_NONEMPTY:
            n = conn.execute(f"select count(*) from {t}").fetchone()[0]
            if n == 0:
                raise BuildError(f"游戏数据库的 {t} 表是空的，源数据有问题")


def _db_usable(m: Manifest) -> bool:
    """清单指的库真的能打开、代号对得上（库文件坏了或对不上就重建；审查 2026-11-02 第 4 条）"""
    from ._db import _open_readonly

    try:
        _open_readonly(m).close()
        return True
    except GamedataUnavailable:
        return False


def publish(generation_id: str, dv: str) -> Manifest:
    m = Manifest(generation_id, dv, SCHEMA_VERSION, db_path(generation_id).name)
    try:
        write_manifest(m)
    except OSError as e:  # Windows 清单被占住：新库留着，清单不动，下次再试
        raise BuildError(f"发布游戏数据库清单失败：{e}") from e
    return m


def rebuild_if_needed(force: bool = False) -> Manifest:
    """内容版本没变、库还在、schema 一致 → 直接返回当前清单；否则建新代并发布。阻塞，调用方放工作线程"""
    from ..core import paths

    with write_lock():
        sources = read_sources(paths.DATA)
        dv = data_version(sources)
        try:
            m = read_manifest()
        except GamedataUnavailable:
            m = None  # 清单坏了：当成没有，重建（审查 2026-11-02 第 3 条）
        if (
            not force
            and m is not None
            and m.data_version == dv
            and m.schema_version == SCHEMA_VERSION
            and _db_usable(m)
        ):
            return m
        gen = new_generation_id()
        build(sources, gen, dv)
        return publish(gen, dv)


def cleanup_old_generations(keep: int = 1) -> list[Path]:
    """删掉不再被清单引用的旧库，保留最近 keep 个；有别的 AT 开着就不动。返回删掉的文件"""
    if other_instance_running():
        return []
    removed: list[Path] = []
    with write_lock():
        m = read_manifest()
        current = m.file if m else None
        olds = sorted(
            (p for p in gamedata_dir().glob("gamedata-*.db") if p.name != current),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in olds[keep:]:
            try:
                p.unlink()
                removed.append(p)
            except OSError:
                pass  # 被占用：下次再说
    return removed
