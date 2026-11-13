"""地表导航：去没有量子信标的地点（洞穴、残骸、自定义路标……），思路同 starmap.space

用法：游戏控制台输入 r_DisplayInfo 2，右上角会显示坐标；AT 读这几行（displayinfo.py）
→ 算出你在哪个星球、经纬度 → 告诉你朝哪个方位飞、还有多远。

坐标换算照搬 starmap.space 的公式（星球自转相位从 2020-01-01 UTC 起算），
星球/地点数据是 AT 自己从游戏数据整理的（starmap.json，随安装包和数据包来）。
方位：0°=北（OM-1 方向），90°=东，应该和游戏头盔指南针一致（待游戏内确认）。
"""

import math
import re
import sys
import threading
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
from .. import gamedata  # noqa: E402
from ..core.paths import DATA, USER, write_json  # noqa: E402
from .names import (
    BODY_ZH,
    CITY_ZH,
    POINT_ZH,
    QT_ZH,
    SYS_ZH,
    TYPE_ZH,
    _RR,
    _RULE_HEAD,
    _RULE_TAIL,
    _SEGMENT,
    _SHIP_ZH,
    _WRECK,
    _norm,
    body_label,
    label,
    poi_zh,
    point_zh,
    rule_zh,
)
from .waypoints import (
    WAYPOINTS,
    add_space_waypoint,
    add_waypoint,
    delete_waypoint,
    is_space,
    parse_clip,
    read_clipboard,
    waypoints,
    _waypoints_strict,
)
from .starmap import (
    CACHE,
    load,
)
from .celestial import (
    BELT_SYS,
    CALIB,
    CALIB_TOL,
    CITY_ARRIVE_M,
    CITY_FLOOR_M,
    CITY_LEAVE_M,
    CITY_NEAR_M,
    EPOCH,
    HINTS,
    LAST,
    LAST_EVERY,
    OFFSET_KEEP,
    R2D,
    SOLAR_FILE,
    SYS_WORD,
    _ang_diff,
    _angle,
    _calib,
    _calib_lock,
    _calibrate,
    _hints,
    _last_at,
    _learn_solar,
    _note_offset,
    _offset,
    _offsets,
    _remember,
    _solar_ids,
    _solar_map,
    approaches,
    bearing,
    calibration,
    cam_axes,
    city_arrived,
    compass,
    deg_text,
    direct_km,
    dist_text,
    fix_guide,
    fix_text,
    from_latlon,
    height_ok,
    here_text,
    is_city,
    latlon,
    locate,
    nav_text,
    near_text,
    nearby,
    orbital_markers,
    phase_from,
    plan_text,
    pos,
    project,
    qt_points,
    rotation_deg,
    space_guide,
    space_landmarks,
    space_text,
    steer,
    steer_text,
    surface_km,
    system_info,
    system_of,
    target_global,
    to_global,
    to_local,
    zone_body,
)
from .transit import (
    HANGAR_LIFT_M,
    LIFT_BOARD_M,
    LIFT_FAR_M,
    LIFT_NEAR_M,
    LIFT_OFF_N,
    LIFT_SPOT_M,
    LIFT_SWITCH_M,
    LIFT_WALK_M,
    LINE_EN,
    LINE_ZH,
    METRO_BOARD_M,
    METRO_MIN_M,
    NEAR_ALIAS,
    NEAR_KINDS,
    NEAR_PREFER,
    REROUTE_M,
    REROUTE_RIDE_M,
    SITE_KINDS,
    SITE_NEAR_M,
    ZONE_MARGIN,
    _bi,
    _car_changed,
    _car_no,
    _city_rows,
    _hangar_lift,
    _hangar_size,
    _lift_rows,
    _lift_steps,
    _line_name,
    _metro_lines,
    _station_points,
    _stop_name,
    _zkey,
    amenity_targets,
    city_leg,
    city_metrics,
    city_places,
    city_route,
    city_targets,
    city_text,
    nearest,
    site_at,
    site_nearest,
    station_leg,
    station_lifts,
    station_route,
    station_text,
    target_system,
    zone_kind,
)

# ---------------------------------------------------------------- 挖矿点（2026-10-27 游戏数据：能量子过去、而且刷船挖矿的太空地点）

_spots = {}


def mining_spots(data=None):
    """导航里的「挖矿点」（太空目标，b = "@星系"，坐标千米）：
    - mining_spots.json（数据构建脚本从游戏数据生成，从游戏数据层读）：派罗 15 个小行星群、86 个远矿站，冰川环带中转点、QV 碎岩站
    - 星图里有刷矿表的拉格朗日点（斯坦顿 20 个、派罗 25 个，data/mining_rocks.json 里有表的才算）
    每个点带 rocks：这里刷哪几种石头（搜「贝沙电气石」能搜到会刷它的点）"""
    from ..mining.mining_area import area_for_spot, rocks_stamp

    data = data or load()
    ver = rocks_stamp()  # = 游戏数据版本，清单坏了 / 没库给 None（和下面 spots() 退回空一致，别在算键时就抛；收口 2，待做 ⑳）
    stamp = (
        ver,
        id(data),
    )  # 游戏数据（挖矿点、石头表、星图）或传进来的星图换了都重算；石头表也在库里，不用另记
    if _spots.get("stamp") == stamp and "list" in _spots:
        return _spots["list"]
    out = []
    try:
        raw = gamedata.mining.spots()
    except gamedata.GamedataError:
        raw = ()  # 库不可用：和以前没有文件一样，只剩拉格朗日点
    for r in raw:
        n = r.get("en") or r.get("id")
        if not n:  # 没名字的一条跳过（以前 r["id"] 抛 KeyError 被吞，也是丢这一条）
            continue
        x, y, z = r["x"] / 1000, r["y"] / 1000, r["z"] / 1000
        out.append(
            dict(
                b="@" + r["sys"],
                sys=r["sys"],
                space=True,
                n=n,
                zh=r.get("zh") or "",
                t="Mining Spot",
                x=round(x, 3),
                y=round(y, 3),
                z=round(z, 3),
                qt=1,
                rocks=area_for_spot(r, (r["x"], r["y"], r["z"])),
            )
        )
    for q in data.get("points") or []:
        if q.get("t") != "Lagrange Point":
            continue
        g = (q["x"], q["y"], q["z"])
        rocks = area_for_spot(
            {
                "lagrange": (q.get("i") if q.get("sys") == "Pyro" else q.get("n")),
                "sys": q.get("sys"),
            },
            g,
        )
        if rocks:
            out.append(
                dict(
                    b="@" + q["sys"],
                    sys=q["sys"],
                    space=True,
                    n=q["n"],
                    zh=point_zh(q),
                    t="Mining Spot",
                    x=round(q["x"] / 1000, 3),
                    y=round(q["y"] / 1000, 3),
                    z=round(q["z"] / 1000, 3),
                    qt=1,
                    rocks=rocks,
                )
            )
    _spots.update(stamp=stamp, list=out)
    return out


def space_points(data=None):
    """星图里的太空站、跳跃点（2026-10-28 用游戏数据补全星图后有了：拉格朗日点的站、派罗 / 尼克斯的门户站、INS Jericho）→ 导航的太空目标（b = "@星系"，千米）"""
    data = data or load()
    out = []
    for q in data.get("points") or []:
        if q.get("t") not in ("Orbital Station", "Naval Station", "Jumppoint"):
            continue
        out.append(
            dict(
                b="@" + q["sys"],
                sys=q["sys"],
                space=True,
                n=q["n"],
                zh=point_zh(q),
                t=q["t"],
                x=round(q["x"] / 1000, 3),
                y=round(q["y"] / 1000, 3),
                z=round(q["z"] / 1000, 3),
                qt=1,
            )
        )
    return out


# ---------------------------------------------------------------- 搜索


def search(query, data=None, limit=15):
    """按中文名/英文名/星球名/类型搜地点；多个词都要命中。没信标的排前面"""
    data = data or load()
    with ExitStack() as stack:
        try:  # 一次搜索钉在一个版本上：几千次地名查询复用这个快照，不每次读清单
            stack.enter_context(gamedata.snapshot())
        except gamedata.GamedataError:
            pass  # 库不可用（调用方自己传了星图）：不钉快照照常搜，地名退化成空
        return _search(query, data, limit)


def _search(query, data, limit):
    words = [w for w in re.split(r"[\s,，]+", query.strip().lower()) if w]
    rows = []
    try:
        spots = mining_spots(data)
    except Exception:
        spots = []
    try:
        spots = spots + city_places()
    except Exception:
        pass
    try:
        spots = spots + space_points(data)
    except Exception:
        pass
    from ..core.i18n import mineral_zh

    try:  # 对玩家可见清单（发给玩家的数据才有；没有清单 / 库不可用 = 全部可见）
        shown = gamedata.place_registry.checker()
    except gamedata.GamedataError:
        shown = lambda p: True  # noqa: E731

    for p in waypoints() + data["pois"] + spots:
        if p["b"] not in data["bodies"] and not is_space(p):
            continue
        if not shown(p):
            continue
        rocks = " ".join(
            f"{o.lower()} {mineral_zh(o)}" for o in (p.get("rocks") or {})
        )  # 挖矿点：按会刷的矿也能搜到
        hay = " ".join(
            [
                p["n"].lower(),
                p.get("zh", ""),
                rocks,
                poi_zh(p["n"]),
                p["b"].lower(),
                BODY_ZH.get(p["b"], ""),
                p["t"].lower(),
                TYPE_ZH.get(p["t"], ""),
                "太空 space" if is_space(p) else "",
                SYS_ZH.get(p.get("sys", ""), "").lower(),
                p.get("sys", "").lower(),
                p.get("cat", ""),
                p.get("area", ""),
                p.get("city_zh", ""),
                p.get("city", "").lower(),
            ]
        )
        if all(w in hay for w in words):
            exact = _norm(p["n"]) == _norm(query) or poi_zh(p["n"]) == query.strip()
            rows.append(
                (not exact, p["t"] != "Waypoint", p["qt"] == 1, p["b"], p["n"], p)
            )
    rows.sort(key=lambda r: r[:5])
    return [r[-1] for r in rows[:limit]], len(rows)


def _short(here, target, brg=None, arrived=None):
    """悬浮窗那一行；brg：要显示的方位角（导航时做过防抖），不给就现算；arrived：城里到了没（导航时带缓冲）"""
    if not here["inside"] or here["body"] != target["b"]:
        return f"先量子跳到 {body_label(target['b'])}"
    if is_city(target):
        return city_text(here, target, brg, arrived)
    a, t = pos(here), pos(target)
    brg = bearing(a, t) if brg is None else brg
    ds = surface_km(a, t, here["radius_km"])
    return f"朝 {deg_text(brg)}°（{compass(brg)}） {ds:,.1f} km" + (
        "\n✅ 到了" if ds < 1 else ""
    )


# ---------------------------------------------------------------- 路标用：按名字找星体


def _find_body(text, data):
    t = text.strip().lower()
    for name in data["bodies"]:
        if t in (name.lower(), BODY_ZH.get(name, "\0")):
            return name
    cands = [n for n in data["bodies"] if t in n.lower() or t in BODY_ZH.get(n, "")]
    return cands[0] if len(cands) == 1 else None


# ---------------------------------------------------------------- 门面动态属性同步（支持测试与热键动态 monkeypatch）
class _NavigateModule(sys.modules[__name__].__class__):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        from . import (
            celestial as _celestial,
            names as _names,
            starmap as _starmap,
            transit as _transit,
            waypoints as _waypoints,
        )

        for sub in (_celestial, _names, _starmap, _transit, _waypoints):
            if hasattr(sub, name):
                setattr(sub, name, value)


sys.modules[__name__].__class__ = _NavigateModule
