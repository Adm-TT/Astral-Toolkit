"""把读好的源 JSON 变成库里的行

import_items 逐段复现 crafting/itemsearch.py:_build_locked() 的合并规则（行号指 main 4facdc5），折叠函数直接 import 复用、不抄。
改了这里的规则要升 _schema.IMPORTER_VERSION。对应关系见 docs/superpowers/specs/2026-11-02-gamedata-callsites.md。"""

import sqlite3
from typing import Any

from ._sources import SourceBytes


def _d(sources: dict[str, SourceBytes], name: str, default: Any) -> Any:
    s = sources.get(name)
    return default if s is None or s.data is None else s.data


def _txt(v: Any) -> str | None:
    """可空文本列：字符串原样、其它（含 None）存 NULL——读端还原 dict 时 None 和 '' 分得开（批 3 要求）；
    类型不对也只是这一列为 NULL，不让整库建不出来"""
    return v if isinstance(v, str) else None


def _s(v: Any) -> str:
    """要算折叠键 / 不可空的地方：不是字符串当空串"""
    return v if isinstance(v, str) else ""


def _num(v: Any) -> int | float | None:
    """数值列：int / float（不含 bool）原样（int 就存 int，列不声明类型时 SQLite 也保留），其它 None"""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v: Any) -> int | None:
    """整数列：int（不含 bool）或整数值的 float，其它 None"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def _lst(v: Any) -> list:
    return v if isinstance(v, list) else []


def _known_en(sources: dict[str, SourceBytes]) -> set[str]:
    """迁移前 trade/names._known_names()（107a760 之前）的规则：商店和掉落里所有英文名（折叠过）——从已读的源算，不碰模块缓存"""
    from ..contracts.textkeys import fold_en as _fold_en

    out: set[str] = set()
    for v in (_d(sources, "shops.json", {}).get("items") or {}).values():
        out.add(_fold_en(v[0]))
    for r in _d(sources, "loot_index.json", {}).get("rows") or []:
        out.add(_fold_en(r[1]))
    return out


def _names_table(sources: dict[str, SourceBytes]) -> dict[str, str]:
    """中英对照表的组装规则（唯一一份；迁移前在 trade/names.table()，107a760 之前）：去假英文名；zh_only_names 只补中文 ≥3 字且还没有的。
    用到的 trade/names._junk / contracts.textkeys.norm_zh / contracts.textkeys.fold_en / _CODE 改了要升 gamedata/_schema.IMPORTER_VERSION"""
    from ..contracts.textkeys import norm_zh as _norm_zh
    from ..trade.names import _junk

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
        rows.append((i, w["n"], _s(w.get("cls"))))
        alts.extend(
            (i, j, c) for j, c in enumerate(_lst(w.get("alt"))) if isinstance(c, str)
        )
    conn.executemany("insert into wiki_items values (?,?,?)", rows)
    conn.executemany("insert into wiki_alt_classes values (?,?,?)", alts)


def import_items(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    from ..contracts.textkeys import en_key, zh_key
    from ..core.i18n import gear_zh_of_item
    from ..crafting.itemsearch import _has_cjk, _variant, _wiki_noise

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

    from ..contracts.textkeys import fold_mixed_loose as _fold

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


def import_wiki_classes(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    """loot._wiki_classes 的规则：按 contracts.textkeys.fold_mixed_loose(n) 收 cls 和 alt[] 的小写，空串不存。
    n 缺失折叠成 ''（旧 _fold(None) == ''）；n 不是字符串、alt 不是列表的条目跳过 / 当空（旧代码整个函数吞错返回空集）"""
    from ..contracts.textkeys import fold_mixed_loose as _fold

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


# ---------------------------------------------------------------- schema 2：导航（批 2 公共层，2026-11-02）
# 变换规则直接 import 复用 navigation 里的现有函数，不抄：transit._city_rows、transit._lift_rows、starmap.fix_points、names._norm
# 导航源都是可选源：坏一条跳一条、坏一个文件空一张表，不拖垮物品 / 商店（审查 2026-11-02 第 3 条）


def _xyz(r):
    import math

    v = (float(r["x"]), float(r["y"]), float(r["z"]))
    if not all(math.isfinite(x) for x in v):
        raise ValueError("坐标不是有限数")
    return v


def _rows(raw, fn):
    """逐条变换，坏的跳过：返回 [(源下标, 变换结果)]"""
    out = []
    for i, r in enumerate(raw if isinstance(raw, list) else []):
        try:
            out.append((i, fn(r)))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def import_starmap(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    import copy

    from ..navigation.names import _norm
    from ..navigation.starmap import fix_points

    raw = _d(sources, "starmap.json", None)
    if not isinstance(raw, dict):
        return
    data = copy.deepcopy(raw)
    for key in (
        "pois",
        "points",
    ):  # 不是 dict 的条目换成 {}（占位保住源下标），fix_points 和下面的行函数都能过；行函数再把它丢掉
        if isinstance(data.get(key), list):
            data[key] = [x if isinstance(x, dict) else {} for x in data[key]]
    fix_points(data, _d(sources, "starmap_fixes.json", None))
    bodies = []
    for i, (name, b) in enumerate((data.get("bodies") or {}).items()):
        try:
            bodies.append(
                (
                    name,
                    b.get("sys") or "",
                    *_xyz(b),
                    b.get("rot"),
                    b.get("adj"),
                    b.get("r"),
                    b.get("om"),
                    b.get("grid"),
                    i,
                )
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    conn.executemany(
        "insert or ignore into bodies values (?,?,?,?,?,?,?,?,?,?,?)", bodies
    )

    def qt(v):  # 原样：没有 QTMarker 时是 None，显示「信标未确认」，不能压成 0
        return (
            int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        )

    # 坐标 / 字段检查全在 _rows 的 try 里：starmap.space 来的一条坏数据（NaN、null、不是 dict）只丢那一条，
    # 不能让整库建不出来——批 2 起导航全靠这个库（GD-B2 控制台审查 2026-11-02 第 1 条）
    def poi_row(q):
        if not (isinstance(q.get("b"), str) and isinstance(q.get("n"), str)):
            raise ValueError("poi 缺 b / n")
        return (
            q["b"],
            q["n"],
            q.get("t") if isinstance(q.get("t"), str) else "",
            *_xyz(q),
            qt(q.get("qt")),
            _norm(q["n"]),
        )

    def point_row(p):
        if not isinstance(p.get("n"), str):
            raise ValueError("point 缺 n")
        ident = p.get("i") if isinstance(p.get("i"), str) else ""
        return (
            p["n"],
            ident,
            p.get("sys") if isinstance(p.get("sys"), str) else "",
            p.get("t") if isinstance(p.get("t"), str) else "",
            *_xyz(p),
            _norm(p["n"]),
            ident.lower(),
        )

    conn.executemany(
        "insert into pois (b, n, t, x, y, z, qt, norm_n, source_order) values (?,?,?,?,?,?,?,?,?)",
        [(*row, i) for i, row in _rows(data.get("pois"), poi_row)],
    )
    conn.executemany(
        "insert into points (n, i, sys, t, x, y, z, norm_n, i_lower, source_order) values (?,?,?,?,?,?,?,?,?,?)",
        [(*row, i) for i, row in _rows(data.get("points"), point_row)],
    )
    if data.get("fetched"):
        conn.execute(
            "insert or replace into meta values ('starmap_fetched', ?)",
            (str(data["fetched"]),),
        )


def import_city_places(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    from ..navigation.transit import _city_rows

    rows = _city_rows(_d(sources, "city_places.json", []))  # 它自己会丢坏行
    conn.executemany(
        "insert or ignore into city_places values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                q["id"],
                q["b"],
                q["n"],
                q["zh"],
                q["x"],
                q["y"],
                q["z"],
                q["cat"],
                q["area"],
                q["city"],
                q["city_zh"],
                q["site_en"],
                q["line"],
                q["stop"],
                int(bool(q.get("space"))),
                q.get("sys") or "",
                *(q["up"] if q.get("up") else (None, None, None)),
                i,
            )
            for i, q in enumerate(rows)
        ],
    )
    conn.executemany(
        "insert or ignore into city_place_kinds values (?,?)",
        [(q["id"], k) for q in rows for k in q.get("kinds") or []],
    )


def import_amenities(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    raw = _d(sources, "place_amenities.json", [])
    for i, r in _rows(raw, lambda r: r):
        if not isinstance(r, dict):
            continue
        ref = r.get("ref") or {}
        if not isinstance(ref, dict):
            ref = {}
        local = ref.get("local")
        if not (isinstance(local, list) and len(local) == 3):
            local = (None, None, None)
        try:
            cur = conn.execute(
                "insert into amenities (en, zh, rec_lower, ref_poi, ref_body, ref_local_x, ref_local_y, ref_local_z, ref_point, ref_point_id, ref_city, source_order)"
                " values (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    (r.get("en") or "").strip(),
                    (r.get("zh") or "").strip(),
                    str(r.get("rec") or "").lower(),
                    str(ref.get("poi") or ""),
                    str(ref.get("body") or ""),
                    *[None if v is None else float(v) for v in local],
                    str(ref.get("point") or ""),
                    str(ref.get("point_id") or ""),
                    str(ref.get("city") or ""),
                    i,
                ),
            )
        except (TypeError, ValueError):
            continue
        conn.executemany(
            "insert or ignore into amenity_kinds values (?,?)",
            [(cur.lastrowid, k) for k in (r.get("kinds") or []) if isinstance(k, str)],
        )


def import_station_lifts(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    import json

    from ..navigation.transit import _lift_rows

    stations = _lift_rows(
        _d(sources, "station_lifts.json", None)
    )  # 整站校验，不过的整站丢
    conn.executemany(
        "insert or ignore into station_lifts values (?,?,?,?,?,?,?)",
        [
            (
                key,
                st.get("station") or key,
                st.get("sys") or "",
                int(bool(st.get("space"))),
                st.get("worst_m"),
                json.dumps(st, ensure_ascii=False, separators=(",", ":")),
                i,
            )
            for i, (key, st) in enumerate(stations.items())
        ],
    )


def import_place_names(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    """places_zh / places_extra_zh 两份都存（src 区分），只收非空字符串；读的一方决定谁优先"""
    rows = []
    for src, name in (("zh", "places_zh.json"), ("extra", "places_extra_zh.json")):
        d = _d(sources, name, None)
        if isinstance(d, dict):
            for i, (k, v) in enumerate(d.items()):
                if isinstance(k, str) and isinstance(v, str) and v:
                    rows.append((k, v, src, i))
    conn.executemany("insert or replace into place_names values (?,?,?,?)", rows)
    codes = _d(sources, "place_codes_zh.json", None)
    if isinstance(codes, dict):
        conn.executemany(
            "insert or replace into place_codes values (?,?,?)",
            [
                (k, v, i)
                for i, (k, v) in enumerate(codes.items())
                if isinstance(k, str) and isinstance(v, str)
            ],
        )


def import_mining_spots(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    raw = _d(sources, "mining_spots.json", [])
    conn.executemany(
        "insert into mining_spots (spot_id, sys, zh, en, kind, area, x, y, z, source_order) values (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                r.get("id"),
                r.get("sys") or "",
                r.get("zh") or "",
                r.get("en") or "",
                r.get("kind") or "",
                r.get("area") or "",
                *xyz,
                i,
            )
            for i, (r, xyz) in _rows(raw, lambda r: (r, _xyz(r)))
        ],
    )


# ---------------------------------------------------------------- schema 4：制造 / 维科洛 / 物品属性（批 3 公共层，2026-11-02）
# 规则直接 import 复用：crafting.assign_keys（「名字#序号」编号）、crafting._fold_name / _search_norm、contracts.textkeys.fold_mixed_loose、contracts.textkeys.en_key
# 都是可选源：缺了空表；坏一条跳一条（_rows）


def import_crafting(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    """blueprints + blueprint_materials + meta 三键。
    编号用 crafting.assign_keys 在「n 是字符串的 dict 条目」上算：消费方 crafting._keys() 在全部条目上算，
    但 n 不是字符串的条目不会和字符串名字共用计数键，所以存进库的每份蓝图编号与消费方一致（n 为 None / 数字的条目库里没有这一行）。
    id / source_order 用源下标（和别的表一致）。编号撞车（源里真有叫「X#1」的名字）后出现的那份跳过。"""
    import json

    from ..contracts.textkeys import en_key
    from ..crafting.crafting import _fold_name, _search_norm, assign_keys

    raw = _d(sources, "crafting.json", {}) or {}
    all_bps = _lst(raw.get("blueprints")) if isinstance(raw, dict) else []
    picked = [
        (i, b)
        for i, b in enumerate(all_bps)
        if isinstance(b, dict) and isinstance(b.get("n"), str)
    ]
    keys, _index, _total = assign_keys([b for _i, b in picked])
    known = {r[0] for r in conn.execute("select item_id from items")}
    rows, mats, seen_keys = [], [], set()
    for i, b in picked:
        key = keys[id(b)]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        slots = _lst(b.get("slots"))
        src = _lst(b.get("src"))
        ek = en_key(b["n"])
        try:
            slots_json = json.dumps(slots, ensure_ascii=False, separators=(",", ":"))
            src_json = json.dumps(src, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            continue
        rows.append(
            (
                i,
                _txt(b.get("u")),
                b["n"],
                _txt(b.get("z")),
                _txt(b.get("g")),
                _txt(b.get("t")),
                _txt(b.get("s")),
                _txt(b.get("m")),
                _int(b.get("sec")),
                1 if b.get("d") else 0,
                _int(b.get("nsrc")),
                key,
                _fold_name(b["n"]),
                _fold_name(_s(b.get("z"))),
                _search_norm(b["n"]),
                _search_norm(_s(b.get("z"))),
                ek if ek in known else None,
                slots_json,
                src_json,
                i,
            )
        )
        for si, slot in enumerate(slots):
            if not (
                isinstance(slot, list) and len(slot) >= 2 and isinstance(slot[1], list)
            ):
                continue
            for oi, o in enumerate(slot[1]):
                if not (isinstance(o, list) and len(o) >= 4):
                    continue
                qty, min_q = _num(o[2]), _int(o[3])
                if (
                    qty is None
                    or min_q is None
                    or not isinstance(o[0], str)
                    or not isinstance(o[1], str)
                ):
                    continue
                mats.append((i, si, _s(slot[0]), oi, o[0], o[1], float(qty), min_q))
    conn.executemany(
        "insert into blueprints values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.executemany(
        "insert or ignore into blueprint_materials values (?,?,?,?,?,?,?,?)", mats
    )
    if isinstance(raw, dict):
        meta = []
        if raw.get("version") is not None:
            meta.append(("crafting_version", str(raw["version"])))
        if _num(raw.get("dismantle_efficiency")) is not None:
            meta.append(
                ("dismantle_efficiency", json.dumps(raw["dismantle_efficiency"]))
            )
        if isinstance(raw.get("dismantle_blacklist"), list):
            meta.append(
                (
                    "dismantle_blacklist",
                    json.dumps(raw["dismantle_blacklist"], ensure_ascii=False),
                )
            )
        conn.executemany("insert or replace into meta values (?,?)", meta)


def import_wikelo(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    """合同按 id 去重只留首个（子表也只从首个生成，不会把两份合同的条目混到一起）；标量列不是字符串存空"""
    from ..contracts.textkeys import fold_mixed_loose as _fold

    raw = _d(sources, "wikelo.json", {}) or {}
    contracts = _lst(raw.get("contracts")) if isinstance(raw, dict) else []
    ok, seen = [], set()
    for i, c in enumerate(contracts):
        if (
            not isinstance(c, dict)
            or not isinstance(c.get("id"), str)
            or c["id"] in seen
        ):
            continue
        seen.add(c["id"])
        ok.append((i, c["id"], c))
    conn.executemany(
        "insert into wikelo_contracts values (?,?,?,?,?,?)",
        [
            (
                cid,
                _txt(c.get("type")),
                _txt(c.get("t")),
                _txt(c.get("te")),
                _txt(c.get("rz")),
                i,
            )
            for i, cid, c in ok
        ],
    )
    conn.executemany(
        "insert into wikelo_rewards values (?,?,?)",
        [
            (cid, k, x)
            for _i, cid, c in ok
            for k, x in enumerate(_lst(c.get("rewards")))
            if isinstance(x, str)
        ],
    )
    conn.executemany(
        "insert into wikelo_requirements values (?,?,?,?,?,?,?,?)",
        [
            (
                cid,
                k,
                _txt(r.get("n")),
                _txt(r.get("z")),
                _num(r.get("q")),
                _txt(r.get("u")),
                _fold(_s(r.get("n"))),
                _fold(_s(r.get("z"))),
            )
            for _i, cid, c in ok
            for k, r in enumerate(_lst(c.get("req")))
            if isinstance(r, dict)
        ],
    )
    conn.executemany(
        "insert into wikelo_contract_systems values (?,?,?)",
        [
            (cid, k, x)
            for _i, cid, c in ok
            for k, x in enumerate(_lst(c.get("systems")))
            if isinstance(x, str)
        ],
    )
    if isinstance(raw, dict) and raw.get("version") is not None:
        conn.execute(
            "insert or replace into meta values ('wikelo_version', ?)",
            (str(raw["version"]),),
        )


def import_item_stats(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    """每件一行；size / mass 不是数字存 NULL（行保留——itemstats.item 照样会返回这条）；s 整段 JSON，存不下的当 {}。
    值不是 dict 或是空 dict 的条目不入库（迁移前 `.get(uuid) or None` 对 {} 也是 None；收口 2，importer 7）"""
    import json

    raw = _d(sources, "item_stats.json", {}) or {}
    items = raw.get("items") if isinstance(raw, dict) else None
    rows = []
    for i, (uuid, v) in enumerate(items.items() if isinstance(items, dict) else ()):
        if not isinstance(v, dict) or not v:
            continue
        try:
            stats_json = json.dumps(
                v.get("s") if isinstance(v.get("s"), dict) else {},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            stats_json = "{}"
        rows.append(
            (
                str(uuid),
                _txt(v.get("n")),
                _int(v.get("size")),
                _txt(v.get("grade")),
                _txt(v.get("cls")),
                _txt(v.get("type")),
                _txt(v.get("sub")),
                _num(v.get("mass")),
                _txt(v.get("ver")),
                _txt(v.get("mfr")),
                _txt(v.get("cn")),
                stats_json,
                i,
            )
        )
    conn.executemany(
        "insert or ignore into item_stats values (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    if isinstance(raw, dict) and raw.get("version") is not None:
        conn.execute(
            "insert or replace into meta values ('item_stats_version', ?)",
            (str(raw["version"]),),
        )


def import_print_spots(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    raw = _d(sources, "print_spots.json", {}) or {}
    items = raw.get("items") if isinstance(raw, dict) else None
    ok = [
        (i, str(k), v)
        for i, (k, v) in enumerate(items.items() if isinstance(items, dict) else ())
        if isinstance(v, dict)
    ]
    conn.executemany(
        "insert or ignore into print_spots values (?,?,?,?)",
        [(k, _txt(v.get("zh")), _txt(v.get("class")), i) for i, k, v in ok],
    )
    conn.executemany(
        "insert or ignore into print_spot_places values (?,?,?)",
        [
            (k, j, pl)
            for _i, k, v in ok
            for j, pl in enumerate(_lst(v.get("where")))
            if isinstance(pl, str)
        ],
    )


def import_ship_items(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    raw = _d(sources, "ship_items.json", {}) or {}
    items = raw.get("items") if isinstance(raw, dict) else None
    conn.executemany(
        "insert or ignore into ship_stock_items values (?,?,?)",
        [
            (str(k), j, ship)
            for k, ships in (items.items() if isinstance(items, dict) else ())
            for j, ship in enumerate(_lst(ships))
            if isinstance(ship, str)
        ],
    )


# ---------------------------------------------------------------- schema 6：采矿（批 5 公共层，2026-11-02）
# 三份都存原样 JSON：消费方（mining_area.rocks_table / area_for_spot、shipsig.match、uex.apply_live 的 yields）吃的就是整段 dict，
# 拆表没有查询收益还会改数值类型。「源文件在不在」看 meta 的 src:<文件名> 是否为空串


def import_mining_rocks(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    import json

    raw = _d(sources, "mining_rocks.json", None)
    if not isinstance(raw, dict):
        return  # 缺失 / 坏 / 不是 dict：没有表行、没有 meta 键（批 5 据此判「没有石头表」）
    sections, extra, rows = [], {}, []
    for name, sec in raw.items():
        if isinstance(sec, dict):
            sections.append(name)
            for i, (k, v) in enumerate(sec.items()):
                rows.append(
                    (
                        str(name),
                        str(k),
                        json.dumps(v, ensure_ascii=False, separators=(",", ":")),
                        i,
                    )
                )
        else:
            extra[str(name)] = sec
    conn.executemany("insert or ignore into mining_rock_entries values (?,?,?,?)", rows)
    conn.execute(
        "insert or replace into meta values ('mining_rocks_meta', ?)",
        (
            json.dumps(
                {"sections": sections, "extra": extra},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ),
    )


def import_ship_signatures(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    import json

    raw = _d(sources, "ship_signatures.json", None)
    ships = raw.get("ships") if isinstance(raw, dict) else None
    conn.executemany(
        "insert into ship_signatures values (?,?)",
        [
            (i, json.dumps(s, ensure_ascii=False, separators=(",", ":")))
            for i, s in enumerate(ships if isinstance(ships, list) else [])
            if isinstance(s, dict)
        ],
    )


def import_refinery_yields(
    conn: sqlite3.Connection, sources: dict[str, SourceBytes]
) -> None:
    import json

    raw = _d(sources, "prices.json", None)
    yields = raw.get("yields") if isinstance(raw, dict) else None
    conn.executemany(
        "insert or ignore into refinery_yields values (?,?,?)",
        [
            (
                str(station),
                json.dumps(bonus, ensure_ascii=False, separators=(",", ":")),
                i,
            )
            for i, (station, bonus) in enumerate(
                yields.items() if isinstance(yields, dict) else ()
            )
            if isinstance(bonus, dict)
        ],
    )
