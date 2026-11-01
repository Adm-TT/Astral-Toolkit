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

    zh_names = _d(sources, "zh_names.json", None)
    if zh_names is None:
        return {}  # names.table() 读不到 zh_names.json 直接返回空，不补 zh_only_names：这里保持一致（审查 2026-11-02 第 6 条）
    known = _known_en(sources)
    out = {zh: en for zh, en in zh_names.items() if not _junk(en, known)}
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

    conn.executemany(
        "insert into pois (b, n, t, x, y, z, qt, norm_n, source_order) values (?,?,?,?,?,?,?,?,?)",
        [
            (
                q["b"],
                q["n"],
                q.get("t") or "",
                *_xyz(q),
                qt(q.get("qt")),
                _norm(q["n"]),
                i,
            )
            for i, q in _rows(data.get("pois"), lambda q: q)
            if isinstance(q.get("b"), str) and isinstance(q.get("n"), str)
        ],
    )
    conn.executemany(
        "insert into points (n, i, sys, t, x, y, z, norm_n, i_lower, source_order) values (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                p["n"],
                p.get("i") or "",
                p.get("sys") or "",
                p.get("t") or "",
                *_xyz(p),
                _norm(p["n"]),
                (p.get("i") or "").lower(),
                i,
            )
            for i, p in _rows(data.get("points"), lambda p: p)
            if isinstance(p.get("n"), str)
        ],
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
