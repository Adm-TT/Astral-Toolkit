"""游戏数据层：本地 SQLite 库 + 统一查询包（设计见 docs/superpowers/specs/2026-11-02-gamedata-design.md）

功能模块只 import 这个包，不碰 data/ 里的文件、不拿 sqlite 连接。
地基阶段只有公共层（类型、锁、清单、建库、快照）；各 topic 的查询函数按批次加。"""

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
    "Place",
    "ShopDistance",
    "ShopRow",
    "Vec3",
]
