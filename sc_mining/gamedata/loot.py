"""掉落 topic：loot_index.json 的 rows（loot_rows 表，6 列原样 + 导入时算好的折叠键）、wiki_items.json 的游戏类名
（wiki_classes 表）、掉落索引的版本（meta 键 loot_index_meta）

挑选、排序、变体过滤这些业务逻辑留在 crafting/loot.py，这里只管查。顺序一律按导入顺序（source_order）。
掉落明细（loot_details.zip、data/loot/*.json）不入库，crafting/loot.py 照旧按需读文件。"""

import json
from dataclasses import dataclass

from ._cache import VersionCache
from ._ready import use


@dataclass(frozen=True)
class LootRow:
    """loot_index.json 的一行：uuid / en / zh / rarity / n 原样（库里 None 存成 '' / 0）；
    norm_en / norm_zh = crafting.loot._fold(en / zh)，cls_lower = 类名小写"""

    uuid: str
    en: str
    zh: str
    rarity: str
    norm_en: str
    norm_zh: str
    cls_lower: str
    n: int
    source_order: int


_COLS = "uuid, en, zh, rarity, norm_en, norm_zh, cls_lower, n, source_order"


def _rows(s, where: str = "", params: tuple = ()) -> tuple[LootRow, ...]:
    return tuple(
        LootRow(*r)
        for r in s.execute(
            f"select {_COLS} from loot_rows {where} order by source_order", params
        )
    )


_all: VersionCache[tuple[LootRow, ...]] = VersionCache()


def rows(snap=None) -> tuple[LootRow, ...]:
    """全部掉落物品，按源顺序；按内容版本缓存一份（部分匹配要整表扫）"""
    with use(snap) as s:
        return _all.get(s, _rows)


def exact(norm_en: str, norm_zh: str, snap=None) -> tuple[LootRow, ...]:
    """折叠后英文名或中文名完全相等的行，按源顺序；空键不参与（两个都空返回空）"""
    if not norm_en and not norm_zh:
        return ()
    with use(snap) as s:
        return _rows(
            s,
            "where (? <> '' and norm_en = ?) or (? <> '' and norm_zh = ?)",
            (norm_en, norm_en, norm_zh, norm_zh),
        )


def by_cls_prefix(prefix: str, snap=None) -> tuple[LootRow, ...]:
    """类名（小写）以 prefix 开头的行，按源顺序；按字面比（类名里的 _ 不能当 LIKE 通配符）"""
    with use(snap) as s:
        return _rows(s, "where substr(cls_lower, 1, ?) = ?", (len(prefix), prefix))


def wiki_classes(norm_n: str, snap=None) -> frozenset[str]:
    """物品查询（wiki）里折叠后名字是 norm_n 的全部游戏类名（cls 和 alt，小写，不含空串）"""
    with use(snap) as s:
        return frozenset(
            c
            for (c,) in s.execute(
                "select cls_lower from wiki_classes where norm_n = ?", (norm_n,)
            )
        )


def index_meta(snap=None) -> dict | None:
    """掉落索引的版本信息 {"version": …}（源里没有 version 键是 {}）；没有 loot_index.json（或坏了）返回 None"""
    with use(snap) as s:
        got = s.execute("select value from meta where key = 'loot_index_meta'")
    return json.loads(got[0][0]) if got else None
