"""星图读取与坐标改正（Navigation: Starmap & POI Data）

星图只来自 AT 自己整理的游戏数据（starmap.json，随安装包和数据包来）；2026-11-13 老大定：不再从 starmap.space 下载。
提供：
1. 星图读取（load：从游戏数据层组装，坐标改正 fix_points 在建库时套）；
2. 坐标改正（fix_points）。
"""

import math
from typing import Any, Dict, List

from .. import gamedata
from ..core.paths import DATA

CACHE = DATA / "starmap.json"


def fix_points(data: Dict[str, Any], fixes: Any) -> None:
    """和游戏数据核对出来的星图坐标改正（data/starmap_fixes.json：{点名: [x, y, z] 米}）套到 data["points"] 上：
    早先从 starmap.space 来的个别点坐标不对（2026-10-27：QV 碎岩站 BRK-304 差了 53 万 km，和 BRK-204 重了）。
    游戏数据层建库时调；改正表不是 dict / 条目不对就跳过，保留原坐标（文件坏了建库时当作没有）"""
    if not isinstance(fixes, dict):
        return
    good: Dict[str, List[float]] = {}
    for name, f in fixes.items():
        if (
            isinstance(f, (list, tuple))
            and len(f) == 3
            and all(
                isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(v)
                for v in f
            )
        ):
            good[name] = [float(v) for v in f]
    for p in data.get("points") or []:
        f = good.get(p.get("n"))
        if f:
            p["x"], p["y"], p["z"] = f


def load() -> Dict[str, Any]:
    """星图：{bodies, pois, points, fetched}，从游戏数据层组装（按内容版本缓存，更新数据后自动换新的）。
    还没有 starmap.json（正常随安装包带着）：明说等数据包，不去外面的网站下"""
    if not CACHE.exists():
        raise RuntimeError(
            "星图数据还没到：到「设置与更新」里点「开始更新」，等数据包下载好再用导航"
        )
    return gamedata.starmap.data_dict()
