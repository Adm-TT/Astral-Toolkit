"""名字对照 topic（批 6）：汉化包中英对照、wiki 游戏类名、旧写法、掉落类名 → uuid——全部原样有序行，不做合并 / 过滤

“首个胜出 / 后写覆盖”这类冲突语义由读者（trade/names、trade/gamekey）自己在内存里建索引时决定，这里只保证顺序和源一致。
不能拿 items / item_names 代替：那边是物品目录合并过滤后的结果（矩阵 2026-11-02-gd-b6-callsites.md §6）。"""

from dataclasses import dataclass

from ._cache import VersionCache
from ._ready import use


@dataclass(frozen=True)
class ZhName:
    """trade/names.table() 的一条：中文、英文都是源文件原文；src = 'zh_names' / 'zh_only'"""

    zh: str
    en: str
    src: str
    source_order: int


@dataclass(frozen=True)
class WikiClass:
    """wiki_items.json 的一行：n、cls 原样（cls 原大小写，没有就是 ''），alt 按源顺序"""

    n: str
    cls: str
    alt: tuple[str, ...]
    source_order: int


_zh: VersionCache[tuple[ZhName, ...]] = VersionCache()
_wiki: VersionCache[tuple[WikiClass, ...]] = VersionCache()
_alias: VersionCache[tuple[tuple[str, str], ...]] = VersionCache()
_uuid: VersionCache[tuple[tuple[str, str], ...]] = VersionCache()


def _load_zh(s) -> tuple[ZhName, ...]:
    return tuple(
        ZhName(zh, en, src, o)
        for zh, en, src, o in s.execute(
            "select zh, en, src, source_order from zh_name_pairs order by source_order"
        )
    )


def _load_wiki(s) -> tuple[WikiClass, ...]:
    alts: dict[int, list[str]] = {}
    for wid, cls in s.execute(
        "select wiki_id, cls from wiki_alt_classes order by wiki_id, idx"
    ):
        alts.setdefault(wid, []).append(cls)
    return tuple(
        WikiClass(n, cls, tuple(alts.get(i, ())), i)
        for i, n, cls in s.execute("select id, n, cls from wiki_items order by id")
    )


def _load_alias(s) -> tuple[tuple[str, str], ...]:
    return tuple(
        (old, new)
        for old, new in s.execute(
            "select old, new from name_alias_pairs order by source_order"
        )
    )


def _load_uuid(s) -> tuple[tuple[str, str], ...]:
    return tuple(
        (cls, u)
        for cls, u in s.execute("select cls, uuid from loot_rows order by source_order")
    )


def zh_pairs(snap=None) -> tuple[ZhName, ...]:
    """中文 → 英文对照（已去假英文名，zh_names 在前、zh_only 补的在后），按 names.table() 的顺序"""
    with use(snap) as s:
        return _zh.get(s, _load_zh)


def wiki_classes(snap=None) -> tuple[WikiClass, ...]:
    """wiki_items.json 的全部行（含涂装等噪声物品），按源顺序"""
    with use(snap) as s:
        return _wiki.get(s, _load_wiki)


def alias_pairs(snap=None) -> tuple[tuple[str, str], ...]:
    """name_aliases.json 的全部 (旧写法, 正名)，按源顺序，不过滤"""
    with use(snap) as s:
        return _alias.get(s, _load_alias)


def class_uuids(snap=None) -> tuple[tuple[str, str], ...]:
    """掉落索引的 (类名原样, uuid)，按源顺序"""
    with use(snap) as s:
        return _uuid.get(s, _load_uuid)
