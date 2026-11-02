"""游戏数据层：本地 SQLite 库 + 统一查询包（设计见 docs/superpowers/specs/2026-11-02-gamedata-design.md）

功能模块只 import 这个包，不碰 data/ 里的文件、不拿 sqlite 连接。
地基阶段只有公共层（类型、锁、清单、建库、快照、入口）；各 topic 的查询函数按批次加。

对外入口：
  version()      当前内容版本（快照内就是快照的版本），做派生缓存的键
  snapshot()     一次业务操作钉在一个版本上
  rebuild()      按需重建（阻塞，放工作线程）
  ensure_ready() 启动用：按需重建 + 清旧代
  ensure()       查询前用：库没好就等后台 warm_up，再不行就同步建一次（topic 内部调）
  warm_up()      后台线程跑 ensure_ready()，失败只记 last_error()
  refresh()      数据文件换了之后调：关掉本线程连接，下次快照重读清单
  updating()     改源文件的边界：拿写锁，最外层退出时重建一次
"""

import threading
from contextlib import contextmanager
from typing import Iterator

from . import (
    _build,
    _db,
    crafting,
    items,
    itemstats,
    loot,
    mining,
    names,
    places,
    prices,
    shops,
    starmap,
    wikelo,
)
from ._db import current_version as version, snapshot
from ._lock import write_lock
from ._manifest import Manifest
from . import _ready
from ._ready import ensure
from ._types import (
    BuildError,
    GamedataError,
    GamedataUnavailable,
    Item,
    ItemCandidate,
    Place,
    ShopDistance,
    ShopRow,
    Vec3,
)

__all__ = [
    "BuildError",
    "GamedataError",
    "GamedataUnavailable",
    "Item",
    "ItemCandidate",
    "Manifest",
    "Place",
    "ShopDistance",
    "ShopRow",
    "Vec3",
    "crafting",
    "ensure",
    "ensure_ready",
    "items",
    "itemstats",
    "last_error",
    "loot",
    "mining",
    "names",
    "places",
    "prices",
    "rebuild",
    "refresh",
    "shops",
    "snapshot",
    "starmap",
    "updating",
    "version",
    "warm_up",
    "wikelo",
]

_state: dict = {"last_error": None, "warm_thread": None}
_tls = threading.local()


def rebuild(force: bool = False) -> Manifest:
    """源没变就返回当前清单；变了建新代并发布。阻塞几百毫秒到几秒，别在界面线程调"""
    m = _build.rebuild_if_needed(force=force)
    _ready.forget_failure()
    return m


def ensure_ready() -> Manifest:
    """启动用：按需重建，然后把不再引用的旧库清掉（有别的 AT 开着就不清）"""
    m = _build.rebuild_if_needed()
    _build.cleanup_old_generations()
    return m


def last_error() -> str | None:
    """最近一次后台建库 / 更新边界里的失败原因；成功后清空"""
    return _state["last_error"]


def warm_up() -> threading.Thread:
    """窗口打开后在后台把库建好；失败不抛，记到 last_error()"""

    def run():
        try:
            ensure_ready()
            _state["last_error"] = None
        except Exception as e:  # noqa: BLE001 —— 后台线程，任何失败都只记录
            _state["last_error"] = f"游戏数据库没建好：{e}"

    t = threading.Thread(target=run, daemon=True, name="gamedata-warmup")
    _state["warm_thread"] = t  # ensure() 看到它在跑就等它，不自己再建一遍
    t.start()
    return t


def refresh() -> None:
    """数据文件换了：关掉本线程的连接缓存，下次 snapshot() 重读清单。快照进行中不动"""
    _db.close_thread_connections()
    _ready.forget_failure()  # 源可能刚换好：建库失败的退避不再算数


@contextmanager
def updating() -> Iterator[None]:
    """改源文件的边界：拿数据目录写锁；最外层正常退出时重建一次（嵌套只算一次）。
    建库失败不抛（源已经写好了），记到 last_error()，旧库继续用"""
    depth = getattr(_tls, "depth", 0)
    _tls.depth = depth + 1
    try:
        with write_lock():
            yield
            if depth == 0:
                try:
                    _build.rebuild_if_needed()
                    _state["last_error"] = None
                    _ready.forget_failure()
                except Exception as e:  # noqa: BLE001 —— 源已经写好了，建库失败只记录，不让更新流程报失败
                    _state["last_error"] = (
                        f"数据已更新，但游戏数据库重建失败，仍在用旧数据：{e}"
                    )
    finally:
        _tls.depth = depth
