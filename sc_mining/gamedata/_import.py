"""把读好的源 JSON 变成库里的行

import_items 逐段复现 crafting/itemsearch.py:_build_locked() 的合并规则（行号指 main 4facdc5），折叠函数直接 import 复用、不抄。
改了这里的规则要升 _schema.IMPORTER_VERSION。对应关系见 docs/superpowers/specs/2026-11-02-gamedata-callsites.md。"""

import sqlite3
from typing import Any

from ._sources import SourceBytes


def _d(sources: dict[str, SourceBytes], name: str, default: Any) -> Any:
    s = sources.get(name)
    return default if s is None or s.data is None else s.data


def _known_en(sources: dict[str, SourceBytes]) -> set[str]:
    """trade/names._known_names()：商店和掉落里所有英文名（折叠过）——但从已读的源算，不碰模块缓存"""
    from ..trade.names import _fold_en

    out: set[str] = set()
    for v in (_d(sources, "shops.json", {}).get("items") or {}).values():
        out.add(_fold_en(v[0]))
    for r in _d(sources, "loot_index.json", {}).get("rows") or []:
        out.add(_fold_en(r[1]))
    return out


def _names_table(sources: dict[str, SourceBytes]) -> dict[str, str]:
    """trade/names.table() L16-38 的规则：去假英文名；zh_only_names 只补中文 ≥3 字且还没有的"""
    from ..trade.names import _junk, _norm_zh

    known = _known_en(sources)
    out = {
        zh: en
        for zh, en in (_d(sources, "zh_names.json", {}) or {}).items()
        if not _junk(en, known)
    }
    for zh, en in (_d(sources, "zh_only_names.json", {}) or {}).items():
        if not _junk(en, known) and len(_norm_zh(zh)) >= 3:
            out.setdefault(zh, en)
    return out


def import_items(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    from ..core.i18n import gear_zh_of_item
    from ..crafting.itemsearch import _has_cjk, _variant, _wiki_noise, en_key, zh_key

    by_en: dict[str, dict] = {}
    rows: list[dict] = []
    source_ids: list[tuple[str, str, str]] = []

    def entry(en):  # L85-99
        ek = en_key(en)
        if not ek:
            return None
        e = by_en.get(ek)
        if e is None:
            e = by_en[ek] = {
                "en": en.replace("\xa0", " "),
                "ek": ek,
                "zh": "",
                "zh_loot": "",
                "zks": [],  # 有序去重，代替 set：库里要保留顺序
                "shop": None,
                "cat": "",
                "loot": False,
                "loc": False,
                "aka": [],
            }
            rows.append(e)
        return e

    def add_zk(e, k, kind, name):
        if k and k not in e["zks"]:
            e["zks"].append(k)
        e.setdefault("names", []).append((kind, name, k))

    # 1. 商店物品（L100-103）：第一个 id 胜出；所有 id 都登记到外部编号表
    for iid, (en, cat) in (_d(sources, "shops.json", {}).get("items") or {}).items():
        e = entry(en)
        if e:
            if e["shop"] is None:
                e["shop"], e["cat"] = int(iid), cat or ""
            source_ids.append(("uex", str(iid), e["ek"]))
    # 2. 掉落索引（L104-117）
    for r in _d(sources, "loot_index.json", {}).get("rows") or []:
        uuid, en, cls, zh = r[0], r[1], r[2], (r[5] if len(r) > 5 else "") or ""
        if _has_cjk(en) and not _has_cjk(zh):  # 个别中英文填反
            en, zh = zh or en, en
        if not _has_cjk(zh):  # 「PH - xxx」占位名不算中文名
            zh = ""
        e = entry(en)
        if e:
            e["loot"] = True
            source_ids.append(("loot_uuid", uuid, e["ek"]))
            if cls:
                source_ids.append(("class", (cls or "").lower(), e["ek"]))
            if zh:
                e["zh_loot"] = e["zh_loot"] or zh
                add_zk(e, zh_key(zh), "zh_loot", zh)
    # 3. 汉化包（L118-123）
    for zh, en in _names_table(sources).items():
        e = entry(en)
        if e:
            e["loc"] = True
            e["zh"] = e["zh"] or zh
            add_zk(e, zh_key(zh), "zh_loc", zh)
    # 4. wiki 清单（L124-131）：只补别处没有的英文名；类型 / 尺寸 / 描述
    for w in _d(sources, "wiki_items.json", {}).get("items") or []:
        e = entry(w["n"])
        if e:
            e.setdefault("wiki", True)
            e["wtype"], e["wsize"], e["desc"] = (
                w.get("t") or "",
                w.get("s"),
                w.get("d") or "",
            )
            if w.get("cls"):
                source_ids.append(("class", w["cls"].lower(), e["ek"]))
    # 5. 旧写法（L141-150）：正名存在、旧写法还不是别的物品，才登记
    for old, real in (_d(sources, "name_aliases.json", {}) or {}).items():
        e = by_en.get(en_key(real))
        if e and en_key(old) not in by_en:
            e["aka"].append(old)
    # 6. 两轮过滤（L151-160）
    taken = {k for e in rows if e["shop"] is not None or e["loot"] for k in e["zks"]}
    rows = [
        e
        for e in rows
        if e["shop"] is not None or e["loot"] or not (set(e["zks"]) & taken)
    ]
    rows = [
        e
        for e in rows
        if e["shop"] is not None or e["loot"] or e["loc"] or not _wiki_noise(e)
    ]
    kept = {e["ek"] for e in rows}
    # 7. 派生字段（L166-178）
    for i, e in enumerate(rows):
        e["zh"] = e["zh"] or e["zh_loot"]
        gz = gear_zh_of_item(e["en"])
        if gz:
            e["zh"] = gz
            add_zk(e, zh_key(gz), "zh_loc", gz)
        e["zks"] = [k for k in e["zks"] if k]
        e["zlen"] = min((len(k) for k in e["zks"]), default=99)
        e["variant"] = _variant(e["en"], e["zh"])
        e["order"] = i

    conn.executemany(
        "insert into items values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                e["ek"],
                e["en"],
                e["zh"],
                e["cat"],
                int(e["shop"] is not None),
                int(e["loot"]),
                int(e["loc"]),
                int(bool(e.get("wiki"))),
                e.get("wtype") or "",
                e.get("wsize"),
                e.get("desc") or "",
                int(e["variant"]),
                e["zlen"],
                e["order"],
            )
            for e in rows
        ],
    )
    names: list[tuple] = []
    for e in rows:
        names.append((e["ek"], "en", e["en"], "en", e["ek"], e["order"]))
        for kind, name, k in e.get("names") or []:
            if k:
                names.append((e["ek"], "zh", name, kind, k, e["order"]))
        for old in e["aka"]:
            names.append((e["ek"], "en", old, "aka", en_key(old), e["order"]))
    conn.executemany("insert into item_names values (?,?,?,?,?,?)", names)
    conn.executemany(
        "insert or ignore into item_source_ids values (?,?,?)",
        [(s, x, ek) for s, x, ek in source_ids if ek in kept],
    )


def import_shops(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    rows = _d(sources, "shops.json", {}).get("rows") or []
    conn.executemany(
        "insert into shop_rows values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                int(r[0]),
                r[1],
                r[2],
                float(r[3]),
                float(r[4]),
                str(r[5]),
                *[
                    str(x)
                    for x in ((r[6] if len(r) > 6 and r[6] else [""] * 6) + [""] * 6)[
                        :6
                    ]
                ],
                i,
            )
            for i, r in enumerate(rows)
        ],
    )


def import_loot(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    rows = _d(sources, "loot_index.json", {}).get("rows") or []
    conn.executemany(
        "insert or ignore into loot_rows values (?,?,?,?,?,?,?)",
        [
            (
                r[0],
                r[1],
                r[2] or "",
                r[3] or "",
                int(r[4] or 0),
                (r[5] if len(r) > 5 else "") or "",
                i,
            )
            for i, r in enumerate(rows)
        ],
    )


def import_prices(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    prices = (_d(sources, "prices.json", {}) or {}).get("prices") or {}
    conn.executemany(
        "insert or replace into mineral_prices values (?,?,?)",
        [
            (mineral, city, float(price))
            for mineral, cities in prices.items()
            for city, price in (cities or {}).items()
            if price is not None
        ],
    )
