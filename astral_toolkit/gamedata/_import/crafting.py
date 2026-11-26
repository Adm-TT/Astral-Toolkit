"""schema 4：制造、维科洛、物品属性、打印点、船自带物品"""

import sqlite3

from .._sources import SourceBytes
from ._common import _d, _int, _lst, _num, _s, _txt


# ---------------------------------------------------------------- schema 4：制造 / 维科洛 / 物品属性（批 3 公共层，2026-11-02）
# 规则直接 import 复用：contracts.blueprints.assign_keys（「名字#序号」编号）、contracts.textkeys 的 blueprint_norm / blueprint_search_norm / fold_mixed_loose / en_key
# 都是可选源：缺了空表；坏一条跳一条（_rows）


def import_crafting(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    """blueprints + blueprint_materials + meta 三键。
    编号用 contracts.blueprints.assign_keys 在「n 是字符串的 dict 条目」上算：消费方 crafting._keys() 在全部条目上算，
    但 n 不是字符串的条目不会和字符串名字共用计数键，所以存进库的每份蓝图编号与消费方一致（n 为 None / 数字的条目库里没有这一行）。
    id / source_order 用源下标（和别的表一致）。编号撞车（源里真有叫「X#1」的名字）后出现的那份跳过。"""
    import json

    from ...contracts.blueprints import assign_keys
    from ...contracts.textkeys import blueprint_norm, blueprint_search_norm, en_key

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
                blueprint_norm(b["n"]),
                blueprint_norm(_s(b.get("z"))),
                blueprint_search_norm(b["n"]),
                blueprint_search_norm(_s(b.get("z"))),
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
    from ...contracts.textkeys import fold_mixed_loose as _fold

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
