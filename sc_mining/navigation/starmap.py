"""星图数据拉取、解析压缩与本地增量缓存模块（Navigation: Starmap & POI Data）

提供：
1. starmap.space 接口数据拉取与失败重试（_fetch、update）；
2. 原始星体与地点信息精简压缩（compact）；
3. 星图读取（load：从游戏数据层组装，坐标改正 fix_points 在建库时套）。
"""

from datetime import datetime, timezone
import json
import math
import time
from typing import Any, Dict, List, Optional, Sequence
import urllib.error
import urllib.request

from .. import gamedata
from ..core.net import read
from ..core.paths import DATA
from .names import _POI_BODY

CACHE = DATA / "starmap.json"
API = "https://starmap.space/api/v3/"
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://starmap.space/",
}


def _fetch(path: str, tries: int = 3) -> Any:
    """下载一个接口；失败自动重试（隔 2、5 秒），最后一次的原因翻成中文抛出去"""
    last: Optional[Exception] = None
    for n in range(tries):
        try:
            body = read(urllib.request.Request(API + path, headers=UA), timeout=60)
            try:
                return json.loads(body)
            except ValueError:
                head = body[:200].decode("utf-8", "replace").lower()
                last = RuntimeError(
                    "starmap.space 返回的不是数据"
                    + ("（被网站防护拦截，稍后重试）" if "<html" in head else "")
                )
        except urllib.error.HTTPError as e:
            last = RuntimeError(
                f"starmap.space 拒绝了请求（HTTP {e.code}"
                + ("，被网站防护拦截，过一会再试" if e.code in (403, 429, 503) else "")
                + "）"
            )
        except Exception as e:
            reason = str(getattr(e, "reason", e))
            last = RuntimeError(
                "无法连接 starmap.space（"
                + ("超时" if "timed out" in reason.lower() else reason)
                + "）"
            )
        if n < tries - 1:
            time.sleep((2, 5)[min(n, 1)])
    if last:
        raise last
    raise RuntimeError("无法连接 starmap.space")


def compact(
    oc: Sequence[Dict[str, Any]], pois: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """把 starmap 接口的原始数据压缩成程序用的格式"""
    bodies: Dict[str, Dict[str, Any]] = {}
    for x in oc:
        if (
            x.get("Type") != "Planet"
            or not float(x.get("BodyRadius") or 0)
            or x.get("System") not in ("Stanton", "Pyro", "Nyx")
        ):
            continue
        name = x.get("ObjectContainer") or x.get("Planet")
        if not name:
            continue
        bodies[name] = dict(
            sys=x["System"],
            x=float(x["XCoord"]),
            y=float(x["YCoord"]),
            z=float(x["ZCoord"]),
            rot=float(x["RotationSpeedX"] or 0),
            adj=float(x["RotationAdjustmentX"] or 0),
            r=float(x["BodyRadius"]),
            om=float(x["OrbitalMarkerRadius"] or 0),
            grid=float(x["GRIDRadius"] or 0),
        )
    # 所有星体/拉格朗日点/跳跃点的位置（商店「离我多远」用）
    points: List[Dict[str, Any]] = []
    for x in oc:
        if x.get("System") not in ("Stanton", "Pyro", "Nyx"):
            continue
        try:
            points.append(
                dict(
                    n=x.get("ObjectContainer") or x.get("Planet") or "",
                    i=x.get("InternalName") or "",
                    sys=x["System"],
                    t=x.get("Type") or "",
                    x=float(x["XCoord"]),
                    y=float(x["YCoord"]),
                    z=float(x["ZCoord"]),
                )
            )
        except (TypeError, ValueError, KeyError):
            pass
    out: List[Dict[str, Any]] = []
    for p in pois:
        b = _POI_BODY.get(p.get("Planet") or "", p.get("Planet"))
        if not b or b not in bodies:
            continue
        qt = p.get("QTMarker")
        out.append(
            dict(
                b=b,
                n=(p.get("PoiName") or "").strip(),
                t=(p.get("Type") or "").strip(),
                x=round(float(p["XCoord"]), 3),
                y=round(float(p["YCoord"]), 3),
                z=round(float(p["ZCoord"]), 3),
                qt=None if qt in (None, "") else int(qt),
            )
        )
    return dict(
        source="starmap.space",
        fetched=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        bodies=bodies,
        pois=out,
        points=points,
    )


def update() -> Dict[str, Any]:
    """从 starmap.space 下载最新的星球和地点数据"""
    print("下载 starmap.space 星图数据（星球 + 约 2000 个地点）…")
    data = compact(_fetch("oc/index.php"), _fetch("pois/index.php"))
    if len(data.get("bodies", [])) < 10 or len(data.get("pois", [])) < 300:
        raise RuntimeError(
            f"starmap.space 返回的数据不完整（{len(data.get('bodies', []))} 个星球、"
            f"{len(data.get('pois', []))} 个地点），保留原来的星图"
        )
    tmp = CACHE.with_suffix(
        ".tmp"
    )  # 先写临时文件再换上：导航正在读的时候不会读到半个文件
    with gamedata.updating():  # 只套写文件这一步（联网不占数据目录写锁）；退出时重建游戏数据库，load() 跟着换代
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(CACHE)
    n_no = sum(1 for p in data["pois"] if p.get("qt") != 1)
    print(
        f"星图数据已更新：{len(data['bodies'])} 个星球/卫星，{len(data['pois'])} 个地点（其中 {n_no} 个没有确认的量子信标）"
    )
    return data


def fix_points(data: Dict[str, Any], fixes: Any) -> None:
    """和游戏数据核对出来的星图坐标改正（data/starmap_fixes.json：{点名: [x, y, z] 米}）套到 data["points"] 上：
    starmap.space 个别点的坐标不对（2026-10-27：QV 碎岩站 BRK-304 差了 53 万 km，和 BRK-204 重了）。
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
    还没有 starmap.json 就先下载一次（和以前一样）"""
    if not CACHE.exists():
        print("第一次使用导航，需要先下载星图数据。")
        update()
    return gamedata.starmap.data_dict()
