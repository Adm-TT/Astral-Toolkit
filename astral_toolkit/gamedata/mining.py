"""采矿 topic：挖矿点（mining_spots 表，mining_spots.json 原样，坐标是星系坐标米）、
雷达石头表（mining_rock_entries 表 + meta，还原成 mining_rocks.json 同形）、飞船信号（ship_signatures 表）"""

import json
from typing import Any

from ._cache import VersionCache
from ._ready import use

_spots: VersionCache[tuple[dict[str, Any], ...]] = VersionCache()


def _load_spots(s) -> tuple[dict[str, Any], ...]:
    return tuple(
        dict(id=i, sys=sys_, zh=zh, en=en, kind=kind, area=area, x=x, y=y, z=z)
        for i, sys_, zh, en, kind, area, x, y, z in s.execute(
            "select spot_id, sys, zh, en, kind, area, x, y, z from mining_spots order by source_order"
        )
    )


def spots(snap=None) -> tuple[dict[str, Any], ...]:
    """全部挖矿点 {id, sys, zh, en, kind, area, x, y, z}，按源顺序、不去重（源里没有 id 的 id 是 None）；
    按内容版本缓存一份（调用方别改它）"""
    with use(snap) as s:
        return _spots.get(s, _load_spots)


_rocks: VersionCache[dict[str, Any]] = VersionCache()
_ships: VersionCache[tuple[dict[str, Any], ...]] = VersionCache()


def _load_rocks(s) -> dict[str, Any]:
    meta = s.execute("select value from meta where key = 'mining_rocks_meta'")
    if not meta:
        return {}  # 没有文件 / 坏了 / 不是 dict
    m = json.loads(meta[0][0])
    out: dict[str, Any] = {name: {} for name in m["sections"]}
    for section, key, value in s.execute(
        "select section, key, value_json from mining_rock_entries order by section, source_order"
    ):
        out[section][key] = json.loads(value)
    out.update(m["extra"])
    return out


def rocks(snap=None) -> dict[str, Any]:
    """mining_rocks.json 同形的 dict（段缺了就没有那个键；没有石头表 {}）；按内容版本缓存一份（调用方别改它）"""
    with use(snap) as s:
        return _rocks.get(s, _load_rocks)


def _load_ships(s) -> tuple[dict[str, Any], ...]:
    return tuple(
        json.loads(j)
        for (j,) in s.execute(
            "select ship_json from ship_signatures order by source_order"
        )
    )


def ship_signatures(snap=None) -> tuple[dict[str, Any], ...]:
    """ship_signatures.json 的 ships，整条原样、按源顺序；没有 ()；按内容版本缓存一份（调用方别改它）"""
    with use(snap) as s:
        return _ships.get(s, _load_ships)
