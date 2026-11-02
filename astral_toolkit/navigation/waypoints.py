"""用户自定义路标与剪贴板坐标导入模块（Navigation: Waypoints & Clipboard）

提供：
1. 本地自定义地表路标与太空路标持久化管理（WAYPOINTS、waypoints、add_waypoint、add_space_waypoint、delete_waypoint）；
2. 游戏内 /showlocation 剪贴板提取与解析（read_clipboard、parse_clip）。
"""

from datetime import datetime
import json
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.paths import USER, write_json
from .names import POINT_ZH  # noqa: F401

WAYPOINTS = USER / "waypoints.json"  # 自定义路标，放 userdata，更新不会覆盖


def is_space(p: Optional[Dict[str, Any]]) -> bool:
    """是否为太空路标（非星球地表）"""
    return bool(p and p.get("space"))


def waypoints() -> List[Dict[str, Any]]:
    """路标表（查询用：读不到就当没有，搜索 / 导航照常）"""
    try:
        return _waypoints_strict()
    except RuntimeError:
        return []


def _waypoints_strict() -> List[Dict[str, Any]]:
    """路标表（改写前用）：文件读不到（被占着）或坏了就抛错，别当成空表——不然接下来存一个路标会把整份覆盖掉（细查 2026-10-28）"""
    try:
        rows = json.loads(WAYPOINTS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RuntimeError(f"路标文件暂时读不到：{e}")
    except ValueError as e:
        raise RuntimeError(f"路标文件损坏（userdata 里的 waypoints.json）：{e}")
    return rows if isinstance(rows, list) else []


def add_waypoint(name: str, body: str, local_xyz: Sequence[float]) -> None:
    """新建/覆盖一个路标；local_xyz 是星球自转坐标系里的千米坐标"""
    wps = [w for w in _waypoints_strict() if w.get("n") != name]
    wps.append(
        dict(
            b=body,
            n=name,
            t="Waypoint",
            x=round(local_xyz[0], 3),
            y=round(local_xyz[1], 3),
            z=round(local_xyz[2], 3),
            qt=0,
            saved=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )
    write_json(WAYPOINTS, wps, indent=1)


def add_space_waypoint(name: str, system: str, g: Sequence[float]) -> None:
    """g：游戏右上角读到的星系坐标（米）；存成千米"""
    wps = [w for w in _waypoints_strict() if w.get("n") != name]
    wps.append(
        dict(
            b="@" + system,
            sys=system,
            space=True,
            n=name,
            t="Waypoint",
            x=round(g[0] / 1000, 3),
            y=round(g[1] / 1000, 3),
            z=round(g[2] / 1000, 3),
            qt=0,
            saved=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )
    )
    write_json(WAYPOINTS, wps, indent=1)


def delete_waypoint(name: str) -> bool:
    """按名称删除指定路标，成功删除返回 True"""
    wps = _waypoints_strict()
    left = [w for w in wps if w.get("n") != name]
    write_json(WAYPOINTS, left, indent=1)
    return len(left) < len(wps)


def parse_clip(text: str) -> Optional[Tuple[float, float, float]]:
    """'Coordinates: x:-18930539540.1 y:-2610158765.2 z:295000.3' → (x, y, z)，星系坐标，单位米；不是坐标返回 None"""
    if not text or "Coordinates:" not in text:
        return None
    m = re.search(r"x:\s*(-?[\d.]+)\s+y:\s*(-?[\d.]+)\s+z:\s*(-?[\d.]+)", text)
    return tuple(float(v) for v in m.groups()) if m else None  # type: ignore[return-value]


def read_clipboard() -> str:
    """Windows 剪贴板文本（不依赖第三方库）"""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes

    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetClipboardData.restype = wintypes.HANDLE
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not u32.OpenClipboard(None):
        return ""
    try:
        h = u32.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return ""
        p = k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()
