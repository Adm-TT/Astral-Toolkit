"""天体自转相位、OM 标记、球面与空间几何指引计算模块（Navigation: Celestial & Spatial Math）

提供：
1. 星体自转相位计算与实机偏差动态校准（rotation_deg、calibration、phase_from、_calibrate）；
2. 空间局部坐标系（to_local）与绝对星系坐标系（to_global、target_global）相互转换；
3. 经纬度（latlon、from_latlon）、初始航向角（bearing）、大圆距离（surface_km）与直线欧氏距离（direct_km）；
4. 飞船镜头轴向计算（cam_axes）、机头朝向转向提示（steer、steer_text）与屏幕平视十字瞄准投影（project）；
5. 恒星系判断与空间地标参照系统（system_info、system_of、space_landmarks、space_guide、space_text）；
6. 实时读屏坐标归一判定（locate）与最近量子跳跃点规划（orbital_markers、qt_points、approaches、plan_text、nav_text）。
"""

from datetime import datetime, timezone
import json
import math
import re
import statistics
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..core.paths import USER, cached_json, clear_json_cache, write_json
from .names import (
    POINT_ZH,
    QT_ZH,
    SYS_ZH,
    TYPE_ZH,
    _norm,
    body_label,
    label,
)
from .starmap import load
from .waypoints import is_space, waypoints

EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)
R2D = 180 / math.pi

SYS_WORD = re.compile(r"(stanton|pyro|nyx)", re.I)
_solar_ids: Dict[str, Any] = {}
SOLAR_FILE = "solar_ids_v2.json"

BELT_SYS = {
    "keeger": "Nyx",
    "glaciem": "Nyx",
    "akiro": "Pyro",
    "aaron": "Stanton",
}  # 区域名里的矿带名 → 星系

HINTS = dict

CITY_ARRIVE_M = 8  # 城里离目标几米以内算到了（星球上的点是 1 km）
CITY_LEAVE_M = 15  # 算到了以后，走开到这么远才算离开
CITY_NEAR_M = 15  # 这么近就不给转向角度了：位置差一两米角度就乱跳，只说「就在附近」
CITY_FLOOR_M = 4  # 上下差这么多米以上才提示换楼层

CALIB = USER / "rotation_calib.json"
CALIB_TOL = 0.05  # 和现用相位差这么多度以上才算新校准
_calib: Dict[str, Any] = {"stamp": None, "data": {}}
_calib_lock = threading.Lock()

_offsets: Dict[str, List[Tuple[float, Tuple[float, float, float]]]] = {}
OFFSET_KEEP = 600.0

LAST = USER / "last_position.json"
LAST_EVERY = 30.0  # 最多 30 秒写一次
_last_at = [0.0]


def is_city(p: Optional[Dict[str, Any]]) -> bool:
    return bool(p) and p.get("t") == "City"


def city_arrived(d: float, before: bool = False) -> bool:
    """到了没：进 8 米算到；已经算到了，走出 15 米才算离开"""
    return d < (CITY_LEAVE_M if before else CITY_ARRIVE_M)


def deg_text(brg: float) -> str:
    """方位角显示成 000~359（359.6° 显示 000，不显示 360）"""
    return f"{round(brg) % 360:03d}"


def height_ok(here: Dict[str, Any]) -> bool:
    """高度能不能显示：比星图表面低 1 km 以上不可能是真地面"""
    return here.get("height_m") is not None and here["height_m"] >= -1000


def pos(p: Dict[str, Any]) -> Tuple[float, float, float]:
    return (p["x"], p["y"], p["z"])


def _solar_map() -> Dict[str, Any]:
    """SolarSystem_<编号> → 星系：从右上角学来的，存 userdata/solar_ids.json（每个星系一个固定编号）"""
    if not _solar_ids:
        try:
            _solar_ids.update(
                json.loads((USER / SOLAR_FILE).read_text(encoding="utf-8"))
            )
        except Exception:
            pass
        _solar_ids.setdefault("_loaded", True)
    return _solar_ids


def _learn_solar(solar_id: str, system: str) -> None:
    m = _solar_map()
    if solar_id and system and m.get(solar_id) != system:
        m[solar_id] = system
        try:
            write_json(
                USER / SOLAR_FILE,
                {k: v for k, v in m.items() if k != "_loaded"},
                indent=1,
            )
        except OSError:
            pass


def system_info(
    g: Sequence[float],
    data: Optional[Dict[str, Any]] = None,
    zone: str = "",
    location: str = "",
    solar_id: str = "",
) -> Tuple[str, bool]:
    """星系坐标（米）在哪个星系 → (星系, 有没有把握)"""
    data = data or load()
    found = ""
    for text in (location, zone):
        m = SYS_WORD.search(text or "")
        if m:
            found = m.group(1).capitalize()
            break
    if not found:
        low = f"{location} {zone}".lower()
        found = next((sysname for word, sysname in BELT_SYS.items() if word in low), "")
    if found:
        _learn_solar(solar_id, found)
        return found, True
    if solar_id and _solar_map().get(solar_id):
        return _solar_map()[solar_id], True
    if zone:
        key = re.sub(r"[^a-z0-9]", "", zone.lower())
        for p in data.get("points") or []:
            pk = re.sub(r"[^a-z0-9]", "", (p.get("i") or p.get("n") or "").lower())
            if pk and (key.startswith(pk) or pk.startswith(key)) and len(pk) >= 6:
                found = p["sys"]
                break
        if not found:
            for name, b in data["bodies"].items():
                if re.sub(r"[^a-z0-9]", "", name.lower()) in key and len(name) >= 4:
                    found = b["sys"]
                    break
    if found:
        _learn_solar(solar_id, found)
        return found, True
    cands = [
        (math.dist(g, (b["x"], b["y"], b["z"])), b["sys"])
        for b in data["bodies"].values()
    ]
    cands += [
        (math.dist(g, (p["x"], p["y"], p["z"])), p["sys"])
        for p in data.get("points") or []
    ]
    return min(cands)[1], False


def system_of(
    g: Sequence[float],
    data: Optional[Dict[str, Any]] = None,
    zone: str = "",
    location: str = "",
    solar_id: str = "",
) -> str:
    """只要星系名（导航、显示用；没把握时也给最可能的那个）"""
    return system_info(g, data, zone=zone, location=location, solar_id=solar_id)[0]


def space_landmarks(
    system: str, data: Optional[Dict[str, Any]] = None
) -> List[Tuple[str, Tuple[float, float, float]]]:
    """这个星系里能当参照、能量子跳过去的东西：[(名字, 坐标千米)]——星球/卫星、拉格朗日点、跳跃点、恒星"""
    data = data or load()
    out = [
        (body_label(n), (b["x"] / 1000, b["y"] / 1000, b["z"] / 1000))
        for n, b in data["bodies"].items()
        if b["sys"] == system
    ]
    for p in data.get("points", []):
        if p["sys"] == system and p["t"] in POINT_ZH:
            out.append(
                (
                    f"{p['n']}（{POINT_ZH[p['t']]}）",
                    (p["x"] / 1000, p["y"] / 1000, p["z"] / 1000),
                )
            )
    return out


def _angle(u: Sequence[float], v: Sequence[float]) -> float:
    nu, nv = math.hypot(*u), math.hypot(*v)
    if not nu or not nv:
        return 0.0
    c = sum(a * b for a, b in zip(u, v)) / nu / nv
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _hints(hints: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        return hints if hints is not None else (HINTS() or {})
    except Exception:
        return {}


def space_guide(
    g: Sequence[float],
    target: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
    hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """当前星系坐标（米）→ 太空路标：距离、先量子跳到哪、对准哪个标记再偏几度"""
    data = data or load()
    here_sys = system_of(g, data, **_hints(hints))
    here = tuple(v / 1000 for v in g)
    t = (target["x"], target["y"], target["z"])
    out: Dict[str, Any] = {
        "system": here_sys,
        "target_system": target["sys"],
        "same_system": here_sys == target["sys"],
    }
    if not out["same_system"]:
        return out
    marks = space_landmarks(target["sys"], data)
    d = math.dist(here, t)
    out["direct"] = d
    out["arrived"] = d < 1
    near = min(marks, key=lambda m: math.dist(m[1], t)) if marks else None
    if near and math.dist(near[1], t) < d * 0.5 and d > 100:
        out["qt"] = {"name": near[0], "km": math.dist(near[1], t)}
    vt = tuple(b - a for a, b in zip(here, t))
    best: Optional[Tuple[str, float, bool]] = None
    for name, pos_ in marks:
        if math.dist(here, pos_) < 1:
            continue
        ang = _angle(vt, tuple(b - a for a, b in zip(here, pos_)))
        if best is None or ang < best[1]:
            best = (name, ang, math.dist(here, pos_) > d)
    if best:
        out["aim"] = {"name": best[0], "angle": best[1], "beyond": best[2]}
    return out


def cam_axes(
    pitch: float, roll: float, yaw: float
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """镜头的 (前方, 头顶) 单位向量"""
    p, r, y = (math.radians(a) for a in (pitch, roll, yaw))
    sp, cp, sr, cr, sy, cy = (
        math.sin(p),
        math.cos(p),
        math.sin(r),
        math.cos(r),
        math.sin(y),
        math.cos(y),
    )
    forward = (sr * sp * cy - cp * sy, sr * sp * sy + cp * cy, cr * sp)
    up = (cp * sr * cy + sp * sy, cp * sr * sy - sp * cy, cp * cr)
    return forward, up


def target_global(
    target: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
    when: Optional[Union[datetime, float]] = None,
    ref: Optional[Tuple[Any, Any, Any]] = None,
) -> Tuple[float, float, float]:
    """目标在星系坐标系里的位置（米）"""
    if is_space(target):
        return (target["x"] * 1000, target["y"] * 1000, target["z"] * 1000)
    data = data or load()

    def _t(w: Any) -> Any:
        return (
            datetime.fromtimestamp(w, timezone.utc)
            if isinstance(w, (int, float))
            else w
        )

    b = data["bodies"][target["b"]]
    out = to_global(b, pos(target), _t(when))
    if ref:
        g0, h0, w0 = ref
        if g0 and h0 and h0.get("body") == target["b"]:
            c = tuple(a - e for a, e in zip(g0, to_global(b, pos(h0), _t(w0))))
            if math.dist(c, (0, 0, 0)) < 60_000:
                out = tuple(a + e for a, e in zip(out, c))
    return out


def steer(
    g: Sequence[float],
    cam: Tuple[float, float, float],
    target_g: Sequence[float],
) -> Dict[str, float]:
    """当前位置 g、镜头朝向 cam=(俯仰,横滚,偏航)、目标 target_g（都是星系坐标，米）"""
    f, u = cam_axes(*cam)
    r = (
        f[1] * u[2] - f[2] * u[1],
        f[2] * u[0] - f[0] * u[2],
        f[0] * u[1] - f[1] * u[0],
    )
    d = tuple(b - a for a, b in zip(g, target_g))
    x, y, z = (sum(a * b for a, b in zip(d, axis)) for axis in (r, f, u))
    return {
        "turn": math.degrees(math.atan2(x, y)),
        "pitch": math.degrees(math.atan2(z, math.hypot(x, y))),
        "off": _angle(d, f),
    }


def project(
    g: Sequence[float],
    cam: Tuple[float, float, float],
    fov: float,
    target_g: Sequence[float],
    w: float,
    h: float,
    vertical: bool = True,
) -> Dict[str, Any]:
    """目标在屏幕上的哪个位置（导航记号）"""
    f, u = cam_axes(*cam)
    r = (
        f[1] * u[2] - f[2] * u[1],
        f[2] * u[0] - f[0] * u[2],
        f[0] * u[1] - f[1] * u[0],
    )
    d = tuple(b - a for a, b in zip(g, target_g))
    x, y, z = (sum(a * b for a, b in zip(d, axis)) for axis in (r, f, u))
    half = math.radians(max(10.0, min(170.0, fov or 70.0))) / 2
    if vertical:
        ty = math.tan(half)
        tx = ty * w / h
    else:
        tx = math.tan(half)
        ty = tx * h / w
    out: Dict[str, Any] = {
        "on": False,
        "behind": y <= 0,
        "off": _angle(d, f),
        "dist": math.dist(g, target_g),
        "angle": math.degrees(math.atan2(z, x)) if abs(x) + abs(z) > 1e-9 else -90.0,
    }
    if y > 1e-9:
        nx, ny = x / y / tx, z / y / ty
        if abs(nx) <= 1 and abs(ny) <= 1:
            out.update(on=True, x=w / 2 + nx * w / 2, y=h / 2 - ny * h / 2)
    return out


def dist_text(m: float) -> str:
    """记号旁边的距离：1,234 m / 12.3 km / 1,234 km / 12.3 Gm"""
    if m < 1000:
        return f"{m:,.0f} m"
    if m < 100_000:
        return f"{m / 1000:,.1f} km"
    if m < 1e9:
        return f"{m / 1000:,.0f} km"
    return f"{m / 1e9:,.1f} Gm"


def steer_text(s: Dict[str, float], walk: bool = False) -> str:
    """walk=True：城里走路，只说左右转，不说机头、直飞"""
    if walk:
        t = s["turn"]
        if abs(t) < 5:
            return "✅ 面向目标，往前走"
        return (
            "掉头 · " if abs(t) > 120 else ""
        ) + f"{'右' if t > 0 else '左'}转 {abs(t):.0f}°"
    if s["off"] < 3:
        return "✅ 机头正对目标，直飞"
    parts = []
    t, p = s["turn"], s["pitch"]
    if abs(t) >= 2:
        parts.append(
            ("掉头 · " if abs(t) > 120 else "")
            + f"{'右' if t > 0 else '左'}转 {abs(t):.0f}°"
        )
    if abs(p) >= 2:
        parts.append(f"{'抬头' if p > 0 else '低头'} {abs(p):.0f}°")
    return "机头：" + "，".join(parts)


def space_text(
    g: Sequence[float], target: Dict[str, Any], data: Optional[Dict[str, Any]] = None
) -> str:
    """悬浮窗 / 命令行用的一两行"""
    s = space_guide(g, target, data)
    if not s["same_system"]:
        return f"目标在 {s['target_system']} 星系，当前在 {s['system']}：先跳过去"
    if s["arrived"]:
        return f"✅ 已经到了（{s['direct'] * 1000:,.0f} m 内），找找周围"
    line = f"直线 {s['direct']:,.1f} km"
    if s.get("aim"):
        a = s["aim"]
        line += f"｜对准「{a['name']}」的标记" + (
            "" if a["angle"] < 3 else f"，再偏 {a['angle']:.0f}°"
        )
    if s.get("qt"):
        line += (
            f"\n太远了：先量子跳到 {s['qt']['name']}（离目标 {s['qt']['km']:,.0f} km）"
        )
    return line


def fix_guide(
    fixes: Sequence[Tuple[float, Sequence[float]]],
    target: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
    prev_arrived: bool = False,
    hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """fixes = [(时间秒, 星系坐标米), ...]，最新的在最后 → 距离、近了多少、偏离角、预计多久到"""
    data = data or load()
    t1, g1 = fixes[-1]
    if is_space(target):
        out = space_guide(g1, target, data, hints)
        tgt = (target["x"], target["y"], target["z"])

        def frame(t: float, g: Sequence[float]) -> Tuple[float, float, float]:
            return tuple(v / 1000 for v in g)  # type: ignore[return-value]
    else:
        key = target["b"]
        b = data["bodies"][key]
        out = {
            "system": system_of(g1, data, **_hints(hints)),
            "target_system": b["sys"],
        }
        out["same_system"] = out["system"] == out["target_system"]
        if not out["same_system"]:
            return out
        tgt = pos(target)

        def frame(t: float, g: Sequence[float]) -> Tuple[float, float, float]:
            return to_local(b, g, datetime.fromtimestamp(t, timezone.utc))

        out["direct"] = math.dist(frame(t1, g1), tgt)
        out["arrived"] = out["direct"] < 1
        if is_city(target):
            out["city"] = True
            out["arrived"] = city_arrived(out["direct"] * 1000, prev_arrived)
            out["close"] = not out["arrived"] and out["direct"] * 1000 < CITY_NEAR_M
            out["updown"] = (math.hypot(*tgt) - math.hypot(*frame(t1, g1))) * 1000
        if out["direct"] > max(1000, b["r"] / 1000 * 3):
            out["qt"] = {"name": body_label(key), "km": None}
    if not out["same_system"] or len(fixes) < 2:
        return out
    t0, g0 = fixes[-2]
    p0, p1 = frame(t0, g0), frame(t1, g1)
    out["moved"] = math.dist(p0, p1)
    out["delta"] = out["direct"] - math.dist(p0, tgt)
    if out["moved"] >= 0.02:
        out["deviation"] = _angle(
            tuple(b_ - a for a, b_ in zip(p0, p1)),
            tuple(b_ - a for a, b_ in zip(p1, tgt)),
        )
    dt = t1 - t0
    if dt > 0 and out["delta"] < -0.001:
        out["eta"] = out["direct"] / (-out["delta"] / dt)
    return out


def fix_text(f: Dict[str, Any], key: str = "") -> str:
    """悬浮窗几行：距离和变化、偏离角、多久到、先跳到哪"""
    if not f["same_system"]:
        return (
            f"目标在 {SYS_ZH.get(f['target_system'], f['target_system'])}星系：先跳过去"
        )
    if f["arrived"]:
        return f"✅ 已经到了（{f['direct'] * 1000:,.0f} m 内），找找周围"
    d = f["direct"]
    if f.get("close"):
        lines = [f"就在附近 {d * 1000:,.0f} m"]
        up = f.get("updown")
        if up is not None and abs(up) > CITY_FLOOR_M:
            lines.append(
                f"目标在{'上' if up > 0 else '下'}方 {abs(up):,.0f} 米：找电梯{'上' if up > 0 else '下'}楼"
            )
        return "\n".join(lines)
    if f.get("city"):
        line = f"直线 {d * 1000:,.0f} m"
        if "delta" in f:
            line += (
                f"（{'近了' if f['delta'] < 0 else '远了'} {abs(f['delta']) * 1000:,.0f} m）"
                if abs(f["delta"]) >= 0.002
                else "（没变）"
            )
    else:
        line = f"直线 {d:,.2f} km" if d < 100 else f"直线 {d:,.0f} km"
        if "delta" in f:
            line += (
                f"（{'近了' if f['delta'] < 0 else '远了'} {abs(f['delta']):,.2f} km）"
                if abs(f["delta"]) >= 0.005
                else "（没变）"
            )
    lines = [line]
    up = f.get("updown")
    if up is not None and abs(up) > CITY_FLOOR_M:
        lines.append(
            f"目标在{'上' if up > 0 else '下'}方 {abs(up):,.0f} 米：找电梯{'上' if up > 0 else '下'}楼"
        )
    if f.get("qt"):
        km = f["qt"].get("km")
        lines.append(
            f"太远了：先量子跳到 {f['qt']['name']}"
            + (f"（离目标 {km:,.0f} km）" if km else "")
        )
    if "deviation" in f:
        dev = f["deviation"]
        mark = "✅" if dev <= 10 else ("⚠️" if dev <= 20 else "❌")
        go = "走" if f.get("city") else "飞"
        lines.append(
            f"{mark} 偏离 {dev:.0f}°"
            + ("" if dev <= 10 else f"：转一点再{go}，再定位一次看变大还是变小")
            + (f"（在往反方向{go}）" if dev > 120 else "")
        )
    else:
        go = "走一段" if f.get("city") else "直线飞一段"
        lines.append(
            f"朝目标方向{go}，再{f'按 {key}' if key else '输入 /showlocation'}，就能算出偏了几度"
        )
    if f.get("eta"):
        e = f["eta"]
        lines.append(
            f"照这个速度约 {int(e // 60)} 分 {int(e % 60)} 秒到"
            if e < 3600
            else f"照这个速度约 {e / 3600:.1f} 小时到"
        )
    if f.get("aim") and "deviation" not in f:
        a = f["aim"]
        lines.append(
            f"参考：对准「{a['name']}」的标记"
            + ("" if a["angle"] < 3 else f"，再偏 {a['angle']:.0f}°")
        )
    return "\n".join(lines)


def rotation_deg(body: Dict[str, Any], when: Optional[datetime] = None) -> float:
    """星球当前自转角（度）"""
    when = when or datetime.now(timezone.utc)
    days = (when - EPOCH).total_seconds() / 86400
    turn = (days / (body["rot"] / 24)) % 1 if body["rot"] else 0
    c = calibration().get(body.get("name") or "")
    adj = c["adj"] if c else body["adj"]
    return adj + turn * 360


def calibration() -> Dict[str, Any]:
    return cached_json(
        CALIB,
        lambda raw: {
            k: v
            for k, v in raw.items()
            if isinstance(v, dict)
            and isinstance(v.get("adj"), (int, float))
            and math.isfinite(v["adj"])
        },
        {},
    )


def phase_from(
    body: Dict[str, Any],
    g: Sequence[float],
    local: Sequence[float],
    when: Optional[datetime] = None,
) -> Optional[float]:
    """星系坐标 g（米）+ 同一时刻的星球坐标 local（千米）→ 这颗星球在 2020-01-01 的相位 adj（度）"""
    v = (g[0] - body["x"], g[1] - body["y"])
    if math.hypot(*v) < 1000 or math.hypot(local[0], local[1]) < 1:
        return None
    dz = (g[2] - body["z"]) / 1000 - local[2]
    if (
        abs(dz) > 1.0
        or abs(math.hypot(*v) / 1000 - math.hypot(local[0], local[1])) > 1.0
    ):
        return None
    a = math.atan2(local[1], local[0]) - math.atan2(v[1], v[0])
    rot_deg = (360 - a * R2D) % 360
    when = when or datetime.now(timezone.utc)
    days = (when - EPOCH).total_seconds() / 86400
    turn = (days / (body["rot"] / 24)) % 1 if body["rot"] else 0
    return (rot_deg - turn * 360) % 360


def _ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _calibrate(
    name: str,
    body: Dict[str, Any],
    g: Sequence[float],
    local: Sequence[float],
    when: datetime,
) -> bool:
    """locate() 里信得过的一次读数：和现用相位差 CALIB_TOL 以上就记下"""
    adj = phase_from(body, g, local, when)
    if adj is None:
        return False
    cal = calibration()
    cur = cal.get(name, {}).get("adj", body["adj"])
    if _ang_diff(adj, cur) < CALIB_TOL:
        return False
    entry = {
        "adj": round(adj, 5),
        "n": cal.get(name, {}).get("n", 0) + 1,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "was": round(cur, 5),
        "rot": body["rot"],
    }
    with _calib_lock:
        pend = _calib.setdefault("pending", {})
        last = pend.get(name)
        now_s = time.time()
        if last is None or _ang_diff(last[0], adj) > CALIB_TOL or now_s - last[1] > 600:
            pend[name] = (adj, now_s)
            return False
        pend.pop(name, None)
        try:
            raw = (
                json.loads(CALIB.read_text(encoding="utf-8")) if CALIB.exists() else {}
            )
            if not isinstance(raw, dict):
                raw = {}
        except OSError:
            raw = {}
        except ValueError:
            return False
        raw[name] = entry
        tmp = CALIB.with_name(f"rotation_calib.{threading.get_ident()}.tmp")
        try:
            CALIB.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            tmp.replace(CALIB)
            clear_json_cache(CALIB)
            _offsets.pop(name, None)
            print(f"自转相位校准：{name} {cur:.3f}° → {adj:.3f}°")
            return True
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    return False


def to_local(
    body: Dict[str, Any], g: Sequence[float], when: Optional[datetime] = None
) -> Tuple[float, float, float]:
    """星系坐标（米）→ 星球自转坐标系（千米），和 POI 数据同一坐标系"""
    dx, dy = body["x"] - g[0], body["y"] - g[1]
    a = (360 - rotation_deg(body, when)) / R2D
    c, s = math.cos(a), math.sin(a)
    return (
        -(dx * c - dy * s) / 1000,
        -(dx * s + dy * c) / 1000,
        (g[2] - body["z"]) / 1000,
    )


def to_global(
    body: Dict[str, Any], loc: Sequence[float], when: Optional[datetime] = None
) -> Tuple[float, float, float]:
    """to_local 的逆运算"""
    a = (360 - rotation_deg(body, when)) / R2D
    c, s = math.cos(a), math.sin(a)
    X, Y = loc[0] * 1000, loc[1] * 1000
    dx, dy = -(c * X + s * Y), -(-s * X + c * Y)
    return (body["x"] - dx, body["y"] - dy, loc[2] * 1000 + body["z"])


def latlon(p: Sequence[float]) -> Tuple[float, float, float]:
    """局部坐标（千米）→ (纬度, 经度, 到球心距离km)"""
    x, y, z = p
    r = math.sqrt(x * x + y * y + z * z) or 1e-9
    lon = (-math.atan2(x, y) * R2D + 270) % 360
    return math.asin(max(-1, min(1, z / r))) * R2D, (lon - 360 if lon > 180 else lon), r


def from_latlon(
    lat: float, lon: float, radius_km: float, height_m: float = 0.0
) -> Tuple[float, float, float]:
    """经纬度 + 高度 → 局部坐标（千米），latlon() 的逆运算"""
    r = radius_km + height_m / 1000
    th = -((lon - 270) / R2D)
    rho = r * math.cos(lat / R2D)
    return (rho * math.sin(th), rho * math.cos(th), r * math.sin(lat / R2D))


def bearing(a: Sequence[float], b: Sequence[float]) -> float:
    """从 a 到 b 的初始方位角（0=北，顺时针），a、b 是局部坐标"""
    la1, lo1, _ = latlon(a)
    la2, lo2, _ = latlon(b)
    f1, f2, dl = la1 / R2D, la2 / R2D, (lo2 - lo1) / R2D
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return (math.atan2(y, x) * R2D) % 360


def surface_km(a: Sequence[float], b: Sequence[float], radius_km: float) -> float:
    """两点在地表投影之间的大圆距离"""
    la1, lo1, _ = latlon(a)
    la2, lo2, _ = latlon(b)
    f1, f2, dl = la1 / R2D, la2 / R2D, (lo2 - lo1) / R2D
    c = math.sin(f1) * math.sin(f2) + math.cos(f1) * math.cos(f2) * math.cos(dl)
    return radius_km * math.acos(max(-1, min(1, c)))


def direct_km(a: Sequence[float], b: Sequence[float]) -> float:
    return math.dist(a, b)


def compass(deg: float) -> str:
    names = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    return names[int((deg + 22.5) // 45) % 8]


def zone_body(zone: str, data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """游戏右上角的 Zone 名 → 星图里的星球名；认不出返回 None"""
    from .gridtext import fold

    data = data or load()
    z = fold(_norm(zone or ""))
    hits = [name for name in data["bodies"] if _norm(name) and fold(_norm(name)) in z]
    return max(hits, key=len) if hits else None


def _note_offset(body: str, d: Tuple[float, float, float]) -> None:
    lst = _offsets.setdefault(body, [])
    lst.append((time.time(), d))
    del lst[:-7]


def _offset(body: str) -> Optional[Tuple[float, float, float]]:
    lst = [d for t, d in _offsets.get(body, []) if time.time() - t < OFFSET_KEEP]
    if not lst:
        return None
    return tuple(statistics.median(v[i] for v in lst) for i in range(3))  # type: ignore[return-value]


def _remember(g: Sequence[float], body: str) -> None:
    """记下最近一次读到的位置"""
    now = time.time()
    if now - _last_at[0] < LAST_EVERY:
        return
    _last_at[0] = now
    try:
        write_json(LAST, {"t": now, "x": g[0], "y": g[1], "z": g[2], "body": body})
    except Exception:
        pass


def locate(
    g: Sequence[float],
    when: Optional[Union[datetime, float]] = None,
    data: Optional[Dict[str, Any]] = None,
    local: Optional[Sequence[float]] = None,
    zone: Optional[str] = None,
    local_ok: Optional[bool] = None,
    use_offset: bool = True,
    record: bool = True,
) -> Dict[str, Any]:
    """判断坐标在哪个星球附近，返回 dict（body、局部坐标、经纬度、高度、src）；在深空返回最近星球 + inside=False"""
    data = data or load()
    best = None
    for name, b in data["bodies"].items():
        d = math.dist(g, (b["x"], b["y"], b["z"]))
        limit = max(b["grid"], b["om"] * 1.5, b["r"] * 2)
        score = d - b["r"]
        if best is None or score < best[0]:
            best = (score, name, b, d <= limit)
    assert best is not None
    _, name, b, inside = best
    if record:
        _remember(g, name)
    if isinstance(when, (int, float)):
        when = datetime.fromtimestamp(when, timezone.utc)
    calc = to_local(b, g, when)
    loc, src = calc, "推算"
    off = _offset(name)
    same = bool(local and zone and zone_body(zone, data) == name)
    if same and local_ok and record:
        try:
            if _calibrate(name, b, g, tuple(local), when):  # type: ignore[arg-type]
                calc = to_local(b, g, when)
        except Exception:
            pass
    if (
        same
        and local_ok is not False
        and local is not None
        and math.dist(local, calc) < (50 if local_ok else 5)
    ):
        if (
            local_ok
            or off is None
            or math.dist(local, tuple(c + o for c, o in zip(calc, off))) < 1.0
        ):
            loc, src = tuple(local), "游戏"
            if record:
                _note_offset(name, tuple(a - c for a, c in zip(local, calc)))  # type: ignore[arg-type]
    if src == "推算" and off is not None and use_offset:
        loc, src = tuple(c + o for c, o in zip(calc, off)), "推算+偏差"
    lat, lon, r = latlon(loc)
    return dict(
        body=name,
        inside=inside,
        x=loc[0],
        y=loc[1],
        z=loc[2],
        lat=lat,
        lon=lon,
        height_m=r * 1000 - b["r"],
        radius_km=b["r"] / 1000,
        src=src,
    )


def orbital_markers(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    om = body["om"] / 1000
    pts = [(0, 0, om), (0, 0, -om), (0, om, 0), (0, -om, 0), (om, 0, 0), (-om, 0, 0)]
    return [
        dict(b=None, n=f"OM-{i + 1}", t="OM", x=p[0], y=p[1], z=p[2], qt=1)
        for i, p in enumerate(pts)
    ]


def qt_points(
    body_name: str, data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """这个星球上能量子跳过去的点：轨道标记 OM-1~6 + 有信标的地点"""
    data = data or load()
    b = data["bodies"][body_name]
    return orbital_markers(b) + [
        p for p in data["pois"] if p["b"] == body_name and p["qt"] == 1
    ]


def approaches(
    target: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
    top: int = 3,
) -> List[Tuple[float, float, float, Dict[str, Any]]]:
    """离目标最近的几个量子点：[(直线km, 地表km, 从该点出发的方位, 点)]"""
    data = data or load()
    b = data["bodies"][target["b"]]
    rkm = b["r"] / 1000
    t = pos(target)
    rows = []
    for q in qt_points(target["b"], data):
        if q["n"] == target["n"] and q.get("t") == target.get("t"):
            continue
        rows.append(
            (direct_km(pos(q), t), surface_km(pos(q), t, rkm), bearing(pos(q), t), q)
        )
    rows.sort(key=lambda r: r[0])
    return rows[:top]


def plan_text(target: Dict[str, Any], data: Optional[Dict[str, Any]] = None) -> str:
    data = data or load()
    lines = [
        f"目的地：{label(target)}｜{body_label(target['b'])}｜{TYPE_ZH.get(target['t'], target['t'])}"
        f"｜{QT_ZH.get(target['qt'], '信标未确认')}"
    ]
    lat, lon, r = latlon(pos(target))
    b = data["bodies"][target["b"]]
    lines.append(
        f"  位置：纬度 {lat:.3f}°，经度 {lon:.3f}°，海拔约 {r * 1000 - b['r']:,.0f} m"
    )
    if target.get("qt") == 1:
        lines.append("  这个地点有量子信标，直接在星图里选它量子跳过去就行。")
    lines.append("  推荐路线（先量子跳到下面的点，再按方位飞过去）：")
    for d3, ds, brg, q in approaches(target, data):
        kind = "轨道标记" if q["t"] == "OM" else "信标"
        lines.append(
            f"    {kind} {label(q)}：到目标 {ds:,.1f} km（直线 {d3:,.1f} km），"
            f"出发后朝 {deg_text(brg)}°（{compass(brg)}）"
        )
    return "\n".join(lines)


def nav_text(
    here: Dict[str, Any],
    target: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
) -> str:
    """当前位置 → 目标：方位、距离"""
    data = data or load()
    if not here["inside"] or here["body"] != target["b"]:
        return (
            f"当前在 {body_label(here['body'])} 附近，目标在 {body_label(target['b'])}。"
            f"先量子跳到 {body_label(target['b'])}，按上面的推荐路线走。"
        )
    a, t = pos(here), pos(target)
    brg = bearing(a, t)
    ds = surface_km(a, t, here["radius_km"])
    d3 = direct_km(a, t)
    tgt_h = latlon(t)[2] * 1000 - here["radius_km"] * 1000
    dh = tgt_h - here["height_m"]
    line = (
        f"→ 朝 {deg_text(brg)}°（{compass(brg)}）飞 {ds:,.1f} km（直线 {d3:,.1f} km）"
    )
    if height_ok(here):
        line += f"｜当前高度 {here['height_m']:,.0f} m，目标 {tgt_h:,.0f} m（{'需上升' if dh > 0 else '需下降'} {abs(dh):,.0f} m）"
    if ds < 1:
        line += "\n  ✅ 已经到了（1 km 内），找找周围"
    else:
        best = approaches(target, data, top=1)
        if best and best[0][1] < ds * 0.5 and ds > 30:
            d3q, dsq, brgq, q = best[0]
            line += (
                f"\n  提示：直接飞太远，先量子跳到 {label(q)}（离目标 {dsq:,.1f} km），"
                f"再朝 {deg_text(brgq)}° 飞更快"
            )
    return line


def nearby(
    here: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
    within_km: float = 50,
) -> Optional[Tuple[float, Dict[str, Any]]]:
    """离当前位置最近的已知地点（含路标）：(地表km, 地点) 或 None"""
    data = data or load()
    if not here["inside"]:
        return None
    a = pos(here)
    best: Optional[Tuple[float, Dict[str, Any]]] = None
    for p in waypoints() + data["pois"]:
        if p["b"] != here["body"]:
            continue
        d = surface_km(a, pos(p), here["radius_km"])
        if best is None or d < best[0]:
            best = (d, p)
    return best if best and best[0] <= within_km else None


def near_text(here: Dict[str, Any], data: Optional[Dict[str, Any]] = None) -> str:
    hit = nearby(here, data)
    if not hit:
        return ""
    d, p = hit
    dist = f"{d * 1000:,.0f} m" if d < 1 else f"{d:,.1f} km"
    return f"附近：{label(p)}（{dist}）"


def here_text(here: Dict[str, Any], data: Optional[Dict[str, Any]] = None) -> str:
    if not here["inside"]:
        return f"深空中，最近的星球是 {body_label(here['body'])}"
    near = near_text(here, data)
    return (
        f"当前在 {body_label(here['body'])}：纬度 {here['lat']:.3f}°，经度 {here['lon']:.3f}°"
        + (f"，高度 {here['height_m']:,.0f} m" if height_ok(here) else "")
        + (f"｜{near}" if near else "")
    )
