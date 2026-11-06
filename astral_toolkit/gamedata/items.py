"""物品目录 topic：items / item_names / item_source_ids 三张表的查询

顺序一律按导入顺序（items.source_order；同一物品的多个名字按插入顺序），和原来 itemsearch 内存里的列表顺序一致。
传 snap 时用调用方的快照（一次操作钉在一个版本上），不传就自己开一个。"""

from dataclasses import dataclass

from ._cache import VersionCache
from ._ready import use
from ._types import Item, ItemCandidate

_COLS = "item_id, en, zh, cat, has_shop, has_loot, loc, wiki, wtype, wsize, desc, variant, zlen, source_order"


@dataclass(frozen=True)
class ItemRow(Item):
    """items 表一整行：Item 再加两列"""

    zlen: int  # 最短中文比较键的长度（没有中文名是 99），搜索排序用
    source_order: int


def _row(r: tuple) -> ItemRow:
    return ItemRow(
        r[0],
        r[1],
        r[2],
        r[3],
        bool(r[4]),
        bool(r[5]),
        bool(r[6]),
        bool(r[7]),
        r[8],
        r[9],
        r[10],
        bool(r[11]),
        r[12],
        r[13],
    )


def get(item_id: str, snap=None) -> ItemRow | None:
    with use(snap) as s:
        rows = s.execute(f"select {_COLS} from items where item_id = ?", (item_id,))
    return _row(rows[0]) if rows else None


def all(snap=None) -> tuple[ItemRow, ...]:  # noqa: A001 —— 计划定的名字，模块里用不到内置 all
    """全部物品，按导入顺序"""
    with use(snap) as s:
        return tuple(
            _row(r)
            for r in s.execute(f"select {_COLS} from items order by source_order")
        )


_cand: VersionCache[tuple[ItemCandidate, ...]] = VersionCache()


def _load_candidates(s) -> tuple[ItemCandidate, ...]:
    aka: dict[str, list[str]] = {}
    for item_id, name in s.execute(
        "select item_id, name from item_names where kind = 'aka' order by rowid"
    ):
        aka.setdefault(item_id, []).append(name)
    return tuple(
        ItemCandidate(i, en, tuple(aka.get(i, ())), o)
        for i, en, o in s.execute(
            "select item_id, en, source_order from items order by source_order"
        )
    )


def candidates(snap=None) -> tuple[ItemCandidate, ...]:
    """OCR 纠错 / 模糊搜索的轻量候选：(item_id, 英文名, 旧写法们, 顺序)，按导入顺序；按内容版本缓存一份"""
    with use(snap) as s:
        return _cand.get(s, _load_candidates)


def names_of(item_id: str, snap=None) -> tuple[tuple[str, str, str], ...]:
    """这件物品的所有名字：(kind, name, norm)，按导入时的插入顺序"""
    with use(snap) as s:
        return tuple(
            (k, n, m)
            for k, n, m in s.execute(
                "select kind, name, norm from item_names where item_id = ? order by rowid",
                (item_id,),
            )
        )


def zh_keys_of_all(snap=None) -> dict[str, tuple[str, ...]]:
    """item_id → 这件物品所有中文比较键（汉化包、掉落数据两种），顺序 = 导入顺序；物品搜索（tasks/catalog_queries/search）建索引用"""
    out: dict[str, list[str]] = {}
    with use(snap) as s:
        for item_id, norm in s.execute(
            "select item_id, norm from item_names where kind in ('zh_loc', 'zh_loot') order by rowid"
        ):
            ks = out.setdefault(item_id, [])
            if norm not in ks:
                ks.append(norm)
    return {k: tuple(v) for k, v in out.items()}


def by_name(name: str, snap=None) -> ItemRow | None:
    """英文名（折叠后）精确对上物品主键；其次对上旧写法（kind='aka'）"""
    from ..contracts.textkeys import en_key

    k = en_key(name)
    if not k:
        return None
    with use(snap) as s:
        hit = get(k, s)
        if hit is not None:
            return hit
        rows = s.execute(
            "select item_id from item_names where kind = 'aka' and norm = ? order by rowid limit 1",
            (k,),
        )
        return get(rows[0][0], s) if rows else None


def by_source_id(source: str, external_id: str, snap=None) -> ItemRow | None:
    """外部编号 → 物品：source = uex / loot_uuid / class"""
    with use(snap) as s:
        rows = s.execute(
            "select item_id from item_source_ids where source = ? and external_id = ?",
            (source, str(external_id)),
        )
        return get(rows[0][0], s) if rows else None


def _like(fragment: str) -> str:
    """LIKE 的模式：% _ 和转义字符 ! 本身都转义掉，按字面子串找"""
    return "%" + fragment.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def search(fragment: str, limit: int | None = None, snap=None) -> tuple[ItemRow, ...]:
    """英文名或任一名字里含 fragment（ASCII 不分大小写）：按导入顺序；limit 为 None 不截断"""
    if not fragment:
        return ()
    pat = _like(fragment)
    sql = (
        f"select {_COLS} from items where en like ? escape '!' "
        "or item_id in (select item_id from item_names where name like ? escape '!') order by source_order"
    )
    params: tuple = (pat, pat)
    if limit is not None:
        sql += " limit ?"
        params += (int(limit),)
    with use(snap) as s:
        return tuple(_row(r) for r in s.execute(sql, params))


def names_by_kind(
    kinds: tuple[str, ...], snap=None
) -> dict[str, tuple[tuple[str, str, str], ...]]:
    """item_id → 这几种名字 (kind, name, norm)，按导入时的插入顺序；物品搜索（tasks/catalog_queries/search）建索引一次取全"""
    out: dict[str, list[tuple[str, str, str]]] = {}
    marks = ",".join("?" * len(kinds))
    with use(snap) as s:
        for item_id, k, n, m in s.execute(
            f"select item_id, kind, name, norm from item_names where kind in ({marks}) order by rowid",
            tuple(kinds),
        ):
            out.setdefault(item_id, []).append((k, n, m))
    return {k: tuple(v) for k, v in out.items()}


def first_source_ids(source: str, snap=None) -> dict[str, str]:
    """item_id → 这个来源里登记的第一个外部编号（导入顺序）；uex 就是以前索引里的「商店 id」（同名多个 id 取第一个）"""
    out: dict[str, str] = {}
    with use(snap) as s:
        for item_id, x in s.execute(
            "select item_id, external_id from item_source_ids where source = ? order by rowid",
            (source,),
        ):
            out.setdefault(item_id, x)
    return out
