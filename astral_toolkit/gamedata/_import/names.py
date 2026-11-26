"""schema 1 的名字部分：中英对照表（_names_table）、名字对、wiki 物品行、wiki 类名"""

import sqlite3

from .._sources import SourceBytes
from ._common import _d, _lst, _s


def _known_en(sources: dict[str, SourceBytes]) -> set[str]:
    """迁移前 trade/names._known_names()（107a760 之前）的规则：商店和掉落里所有英文名（折叠过）——从已读的源算，不碰模块缓存"""
    from ...contracts.textkeys import fold_en as _fold_en

    out: set[str] = set()
    for v in (_d(sources, "shops.json", {}).get("items") or {}).values():
        out.add(_fold_en(v[0]))
    for r in _d(sources, "loot_index.json", {}).get("rows") or []:
        out.add(_fold_en(r[1]))
    return out


def _names_table(sources: dict[str, SourceBytes]) -> dict[str, str]:
    """中英对照表的组装规则（唯一一份；迁移前在 trade/names.table()，107a760 之前）：去假英文名；zh_only_names 只补中文 ≥3 字且还没有的。
    用到的 contracts.textkeys.junk_en / norm_zh / fold_en / CODE_NAME 改了要升 gamedata/_schema.IMPORTER_VERSION"""
    from ...contracts.textkeys import junk_en as _junk, norm_zh as _norm_zh

    zh_names = _d(sources, "zh_names.json", None)
    if zh_names is None:
        return {}  # names.table() 读不到 zh_names.json 直接返回空，不补 zh_only_names：这里保持一致（审查 2026-11-02 第 6 条）
    known = _known_en(sources)
    out = {zh: en for zh, en in zh_names.items() if not _junk(en, known)}
    for zh, en in (_d(sources, "zh_only_names.json", {}) or {}).items():
        if not _junk(en, known) and len(_norm_zh(zh)) >= 3:
            out.setdefault(zh, en)
    return out


def import_name_pairs(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    """批 6 公共层：names.table() 的结果原样有序入 zh_name_pairs（src 标明来自哪份）；name_aliases.json 全部 str→str 对入 name_alias_pairs"""
    table = _names_table(sources)
    zh_names = _d(sources, "zh_names.json", None) or {}
    conn.executemany(
        "insert into zh_name_pairs values (?,?,?,?)",
        [
            (
                i,
                zh,
                en,
                "zh_names" if zh in zh_names and zh_names[zh] == en else "zh_only",
            )
            for i, (zh, en) in enumerate(table.items())
        ],
    )
    aliases = _d(sources, "name_aliases.json", {}) or {}
    conn.executemany(
        "insert into name_alias_pairs values (?,?,?)",
        [
            (i, old, new)
            for i, (old, new) in enumerate(
                aliases.items() if isinstance(aliases, dict) else ()
            )
            if isinstance(old, str) and isinstance(new, str)
        ],
    )


def import_wiki_rows(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    """批 6 公共层：wiki_items.json 的 items 原样（含噪声物品，cls 原大小写），alt 只收字符串、保序"""
    items = (_d(sources, "wiki_items.json", {}) or {}).get("items") or []
    rows, alts = [], []
    for i, w in enumerate(items if isinstance(items, list) else []):
        if not isinstance(w, dict) or not isinstance(w.get("n"), str):
            continue
        rows.append((i, w["n"], _s(w.get("cls")), 2 if w.get("g") == 2 else 1))
        alts.extend(
            (i, j, c) for j, c in enumerate(_lst(w.get("alt"))) if isinstance(c, str)
        )
    conn.executemany("insert into wiki_items values (?,?,?,?)", rows)
    conn.executemany("insert into wiki_alt_classes values (?,?,?)", alts)


def import_wiki_classes(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    """loot._wiki_classes 的规则：按 contracts.textkeys.fold_mixed_loose(n) 收 cls 和 alt[] 的小写，空串不存。
    n 缺失折叠成 ''（旧 _fold(None) == ''）；n 不是字符串、alt 不是列表的条目跳过 / 当空（旧代码整个函数吞错返回空集）"""
    from ...contracts.textkeys import fold_mixed_loose as _fold

    items = _lst((_d(sources, "wiki_items.json", {}) or {}).get("items"))
    out = []
    for i, w in enumerate(items):
        if not isinstance(w, dict) or not (
            w.get("n") is None or isinstance(w.get("n"), str)
        ):
            continue
        k = _fold(w.get("n"))
        for c in [w.get("cls"), *_lst(w.get("alt"))]:
            if isinstance(c, str) and c.lower():
                out.append((k, c.lower(), i))
    conn.executemany("insert into wiki_classes values (?,?,?)", out)
