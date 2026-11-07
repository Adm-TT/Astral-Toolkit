"""物品查询用例交给展示层的结果（IQ-B5）：不可变，只放值，不取数据、不排版。

用例在 tasks/catalog.py，排版在 app/presenters/catalog.py。facts：tasks/catalog_queries/acquire.info 给的详情字典
（取数据在那边，大部分组合规则在 catalog/acquire；买点那块还在 tasks/catalog_queries/acquire，见那边说明）。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ItemInfo:
    """一件物品的详情。facts：tasks/catalog_queries/acquire.info 给的详情字典；zh：查好的中文名；goal：目标提示文字（不在目标里是 ""）"""

    facts: dict[str, Any]
    zh: str
    goal: str


@dataclass(frozen=True)
class LootLookup:
    """掉落那一块。loot：tasks/catalog_queries/loot.info 原样的结果（None、pending、error 字典都原样）；取的时候抛了异常：error 是那个异常"""

    loot: Any = None
    error: Exception | None = None
