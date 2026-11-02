"""地点 topic：主城 / 空间站里的地点（city_places）、城外设施（amenities）、空间站电梯（station_lifts）、地名中文对照（place_names / place_codes）

place_names 存两份：src='zh' 是 places_zh.json（汉化包对出来的，键是规范化英文名），src='extra' 是 places_extra_zh.json
（从游戏数据补的）。读的一方决定看哪份：names.poi_zh 用合并表（extra 盖过 zh）；position 那一路只看 zh（以前就是只读
places_zh.json）。"""

import json
from typing import Any

from ._cache import VersionCache
from ._ready import use

_merged: VersionCache[dict[str, str]] = VersionCache()


def _load_merged(s) -> dict[str, str]:
    out: dict[str, str] = {}
    for src in ("zh", "extra"):  # 后放的盖过先放的
        out.update(
            s.execute(
                "select norm_key, zh from place_names where src = ? order by source_order",
                (src,),
            )
        )
    return out


def poi_names(snap=None) -> dict[str, str]:
    """规范化英文名 → 中文的合并表（places_extra_zh 盖过 places_zh），按内容版本缓存一份。
    names.poi_zh 在搜索里一次要查几千个名字，查整张表的 dict 比逐个 SQL 快（调用方别改它）"""
    with use(snap) as s:
        return _merged.get(s, _load_merged)


def zh_of(norm_key: str, snap=None) -> str | None:
    """places_zh（不看 extra）里这个规范化键的中文；没有返回 None"""
    with use(snap) as s:
        rows = s.execute(
            "select zh from place_names where src = 'zh' and norm_key = ?", (norm_key,)
        )
    return rows[0][0] if rows else None


def zh_by_prefix(prefix: str, snap=None) -> str | None:
    """places_zh 里以 prefix 开头（区分大小写）的键中最短的那个的中文；同样长取源里靠前的。没有返回 None"""
    with use(snap) as s:
        rows = s.execute(
            "select zh from place_names where src = 'zh' and substr(norm_key, 1, ?) = ? "
            "order by length(norm_key), source_order limit 1",
            (len(prefix), prefix),
        )
    return rows[0][0] if rows else None


def code_zh(code: str, snap=None) -> str | None:
    """place_codes_zh.json：小写地点代码 → 中文；没有返回 None"""
    with use(snap) as s:
        rows = s.execute("select zh from place_codes where code = ?", (code,))
    return rows[0][0] if rows else None


_COLS_CITY = "id, b, n, zh, x, y, z, cat, area, city, city_zh, site_en, line, stop, space, sys, up_x, up_y, up_z"


def _load_city(s) -> list[dict[str, Any]]:
    kinds: dict[str, list[str]] = {}
    for pid, k in s.execute(
        "select place_id, kind from city_place_kinds order by rowid"
    ):
        kinds.setdefault(pid, []).append(k)
    out = []
    for (
        pid,
        b,
        n,
        zh,
        x,
        y,
        z,
        cat,
        area,
        city,
        city_zh,
        site_en,
        line,
        stop,
        space,
        sys_,
        *up,
    ) in s.execute(f"select {_COLS_CITY} from city_places order by source_order"):
        q: dict[str, Any] = dict(
            b=b,
            n=n,
            zh=zh,
            t="City",
            x=x,
            y=y,
            z=z,
            qt=0,
            id=pid,
            cat=cat,
            area=area,
            city=city,
            city_zh=city_zh,
            site_en=site_en,
            line=line,
            stop=stop,
            kinds=kinds.get(pid, []),
        )
        if space:
            q.update(space=True, sys=sys_)
        if up[0] is not None:
            q["up"] = tuple(up)
        out.append(q)
    return out


_city: VersionCache[list[dict[str, Any]]] = VersionCache()


def city_places(snap=None) -> list[dict[str, Any]]:
    """主城 / 空间站里的地点：和以前 transit._city_rows(city_places.json) 的结果一样的 dict 列表（建库时已经变换好，
    t='City'、qt=0 读时补），按源顺序；按内容版本缓存一份（调用方别改它）"""
    with use(snap) as s:
        return _city.get(s, _load_city)


_lifts: VersionCache[dict[str, Any]] = VersionCache()


def _load_lifts(s) -> dict[str, Any]:
    return {
        k: json.loads(p)
        for k, p in s.execute(
            "select station_key, payload_json from station_lifts order by source_order"
        )
    }


def station_lifts(snap=None) -> dict[str, Any]:
    """rr_* 站记录名 → 这个站的区域 / 电梯 / 机库数据（建库时经 transit._lift_rows 整站校验），按源顺序；按内容版本缓存一份"""
    with use(snap) as s:
        return _lifts.get(s, _load_lifts)


def amenities(kind: str, snap=None) -> list[dict[str, Any]]:
    """城外有这类设施的地点（place_amenities.json），按源顺序：{en, zh, rec（小写）, ref: {poi, body, local, point, point_id}}；
    local 不是三元组时为 None。ref 读时由调用方回查当前星图（星图和设施可能分开更新）"""
    with use(snap) as s:
        rows = s.execute(
            "select a.en, a.zh, a.rec_lower, a.ref_poi, a.ref_body, a.ref_local_x, a.ref_local_y, a.ref_local_z, "
            "a.ref_point, a.ref_point_id from amenities a join amenity_kinds k on k.amenity_id = a.id "
            "where k.kind = ? order by a.source_order",
            (kind,),
        )
    return [
        dict(
            en=en,
            zh=zh,
            rec=rec,
            ref=dict(
                poi=poi,
                body=body,
                local=None if lx is None else [lx, ly, lz],
                point=point,
                point_id=point_id,
            ),
        )
        for en, zh, rec, poi, body, lx, ly, lz, point, point_id in rows
    ]
