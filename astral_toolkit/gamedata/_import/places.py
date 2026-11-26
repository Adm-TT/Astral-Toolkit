"""schema 2：导航（星图、城市地点、设施、电梯、地名、矿点）和地点注册表（import_places）"""

import sqlite3
from typing import Any

from .._sources import SourceBytes
from ._common import _d, _rows, _s, _txt, _xyz


# ---------------------------------------------------------------- schema 2：导航（批 2 公共层，2026-11-02）
# 变换规则直接 import 复用 navigation 里的现有函数，不抄：transit._city_rows、transit._lift_rows、starmap.fix_points、names._norm
# 导航源都是可选源：坏一条跳一条、坏一个文件空一张表，不拖垮物品 / 商店（审查 2026-11-02 第 3 条）


def import_starmap(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    import copy

    from ...navigation.names import _norm
    from ...navigation.starmap import fix_points

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
    from ...navigation.transit import _city_rows

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

    from ...navigation.transit import _lift_rows

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


def import_places(conn: sqlite3.Connection, sources: dict[str, SourceBytes]) -> None:
    """places.json → place_registry / place_navkeys；place_visibility.json → place_visible + meta 'place_visibility'。
    navkey 用 place_registry.navkey 那一套拼（建库和查询同一个规则）；城内点要对上 _city_rows 给的 id（src 重复时带 +）"""
    import json

    from ...navigation.transit import _city_rows
    from ..place_registry import poi_key

    raw = _d(sources, "places.json", None)
    rows = raw.get("places") if isinstance(raw, dict) else None
    city_ids: dict[tuple, list[str]] = {}
    for q in _city_rows(_d(sources, "city_places.json", None)):
        city_ids.setdefault(
            (q["city"], q["n"], round(q["x"], 3), round(q["y"], 3), round(q["z"], 3)),
            [],
        ).append(q["id"])
    reg, keys, seen = [], set(), set()
    used: dict[
        tuple, int
    ] = {}  # 同城同名同坐标的重复点：按源顺序一个编号对一个 id，不能互相借光
    for i, r in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(r, dict):
            continue
        pid = r.get("id")
        if not isinstance(pid, str) or not pid or pid in seen:
            continue
        seen.add(pid)
        kind, system, en = _s(r.get("kind")), _s(r.get("system")), _s(r.get("en"))
        parent = _txt(r.get("parent"))
        reg.append(
            (
                pid,
                kind,
                parent,
                system,
                en,
                json.dumps(r, ensure_ascii=False, separators=(",", ":")),
                i,
            )
        )
        lg0 = r.get("legacy")
        lg: dict[str, Any] = lg0 if isinstance(lg0, dict) else {}
        t = lg.get("t")
        if t == "pois":
            keys.add(
                (
                    poi_key(
                        lg.get("b"), lg.get("n"), lg.get("x"), lg.get("y"), lg.get("z")
                    ),
                    pid,
                )
            )
        elif t == "points":
            keys.add((f"pt|{system}|{en}", pid))
            if kind == "lagrange_point":  # 有刷矿表的拉格朗日点在导航里是「挖矿点」
                keys.add((f"ms|{system}|{en}", pid))
        elif t == "mining_spots":
            keys.add((f"ms|{system}|{en or _s(lg.get('id'))}", pid))
        elif t == "city_places":
            c0 = r.get("coord")
            c: dict[str, Any] = c0 if isinstance(c0, dict) else {}
            city = (
                parent[5:]
                if isinstance(parent, str) and parent.startswith("site:")
                else ""
            )
            try:
                ck = (
                    city,
                    en,
                    round(float(c["x"]), 3),
                    round(float(c["y"]), 3),
                    round(float(c["z"]), 3),
                )
            except (KeyError, TypeError, ValueError):
                continue
            cids = city_ids.get(ck, ())
            k = used.get(ck, 0)
            used[ck] = k + 1
            if k < len(cids):
                keys.add((f"ct|{cids[k]}", pid))
    conn.executemany("insert into place_registry values (?,?,?,?,?,?,?)", reg)
    conn.executemany("insert or ignore into place_navkeys values (?,?)", sorted(keys))
    vis = _d(sources, "place_visibility.json", None)
    if isinstance(vis, dict) and isinstance(vis.get("ids"), list):
        ids = sorted({x for x in vis["ids"] if isinstance(x, str) and x})
        conn.executemany(
            "insert or ignore into place_visible values (?)", [(x,) for x in ids]
        )
        conn.execute(
            "insert or replace into meta values ('place_visibility', ?)",
            (
                json.dumps(
                    {"version": _s(vis.get("version")), "count": len(ids)},
                    ensure_ascii=False,
                ),
            ),
        )
