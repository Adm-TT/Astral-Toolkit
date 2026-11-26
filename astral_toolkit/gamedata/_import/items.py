"""schema 1 的物品部分：物品、商店、掉落、价格"""

import sqlite3

from .._sources import SourceBytes
from ._common import _d
from .names import _names_table


def import_items(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    from ...catalog.search import (
        has_cjk as _has_cjk,
        variant as _variant,
        wiki_noise as _wiki_noise,
    )
    from ...contracts.textkeys import en_key, zh_key
    from ...core.i18n import gear_zh_of_item

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
        if (
            k not in e["zks"]
        ):  # 空键也先留着：原代码的 set 里有空键，第一轮过滤会用到，第 7 段才剔（审查 N1）
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
        if not isinstance(w, dict) or not isinstance(w.get("n"), str):
            continue  # 坏一条跳一条，别让整个库建不出来（批 6 矩阵核对时发现这里会 KeyError）
        e = entry(w["n"])
        if e:
            e.setdefault("wiki", True)
            e["wtype"], e["wsize"], e["desc"] = (
                w.get("t") or "",
                w.get("s"),
                w.get("d") or "",
            )
            if isinstance(w.get("cls"), str) and w["cls"]:
                source_ids.append(("class", w["cls"].lower(), e["ek"]))
    # 5. 旧写法（L141-150）：正名存在、旧写法还不是别的物品，才登记
    for old, real in (_d(sources, "name_aliases.json", {}) or {}).items():
        if not (isinstance(old, str) and isinstance(real, str)):
            continue
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
    items = _d(sources, "shops.json", {}).get("items") or {}
    conn.executemany(
        "insert or ignore into shop_items values (?,?,?,?)",
        [
            (int(iid), v[0], (v[1] if len(v) > 1 and v[1] is not None else "") or "", i)
            for i, (iid, v) in enumerate(items.items())
            if isinstance(v, (list, tuple)) and v and isinstance(v[0], str)
        ],
    )
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
    import json

    from ...contracts.textkeys import fold_mixed_loose as _fold

    raw = _d(sources, "loot_index.json", None)
    rows = (raw.get("rows") if isinstance(raw, dict) else None) or []
    conn.executemany(
        "insert or ignore into loot_rows values (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                r[0],
                r[1],
                r[2] or "",
                r[3] or "",
                int(r[4] or 0),
                (r[5] if len(r) > 5 else "") or "",
                _fold(r[1]),
                _fold(r[5] if len(r) > 5 else ""),
                (r[2] or "").lower(),
                i,
            )
            for i, r in enumerate(rows)
        ],
    )
    if isinstance(raw, dict):
        # 有文件才写这个键（批 4 靠「键在不在」区分「没有掉落索引」和「索引是空的」；version 原值类型照存）
        meta = {"version": raw["version"]} if "version" in raw else {}
        conn.execute(
            "insert or replace into meta values ('loot_index_meta', ?)",
            (json.dumps(meta, ensure_ascii=False),),
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
