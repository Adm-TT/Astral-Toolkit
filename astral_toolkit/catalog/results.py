"""物品查询用例交给展示层的结果（IQ-B5）：不可变，只放值，不取数据、不排版。

用例在 tasks/catalog.py，排版在 app/presenters/catalog.py。facts 是过渡期的旧字典：crafting.acquire.info 原样的结果
（取数据和组合规则还写在一起，IQ 不拆它）。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ItemInfo:
    """一件物品的详情。facts：acquire.info 原样的字典；zh：查好的中文名；goal：目标提示文字（不在目标里是 ""）"""

    facts: dict[str, Any]
    zh: str
    goal: str


@dataclass(frozen=True)
class LootLookup:
    """掉落那一块。loot：crafting.loot.info 原样的结果（None、pending、error 字典都原样）；取的时候抛了异常：error 是那个异常"""

    loot: Any = None
    error: Exception | None = None
