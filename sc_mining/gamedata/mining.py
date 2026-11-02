"""采矿 topic：挖矿点（mining_spots 表，mining_spots.json 原样，坐标是星系坐标米）。本批（导航）只有 spots()，批 5 扩"""

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
