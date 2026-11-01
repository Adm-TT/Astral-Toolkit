"""地表导航：去没有量子信标的地点（洞穴、残骸、自定义路标……），思路同 starmap.space

用法：游戏控制台输入 r_DisplayInfo 2，右上角会显示坐标；天枢读这几行（displayinfo.py）
→ 算出你在哪个星球、经纬度 → 告诉你朝哪个方位飞、还有多远。

坐标换算照搬 starmap.space 的公式（星球自转相位从 2020-01-01 UTC 起算），
星球/地点数据来自 starmap.space 的公开接口，缓存在 starmap.json。
方位：0°=北（OM-1 方向），90°=东，应该和游戏头盔指南针一致（待游戏内确认）。
"""

import json
import math
import re
import sys
import threading
import time
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
    _POI_BODY,
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
    API,
    CACHE,
    UA,
    _fetch,
    compact,
    load,
    update,
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
    - data/mining_spots.json（数据构建脚本从游戏数据生成）：派罗 15 个小行星群、86 个远矿站，冰川环带中转点、QV 碎岩站
    - 星图里有刷矿表的拉格朗日点（斯坦顿 20 个、派罗 25 个，data/mining_rocks.json 里有表的才算）
    每个点带 rocks：这里刷哪几种石头（搜「贝沙电气石」能搜到会刷它的点）"""
    from ..mining.mining_area import rocks_stamp, area_for_spot
    from ..core import paths as _paths  # 调用时现取 paths.DATA（测试会换掉它）

    p = _paths.DATA / "mining_spots.json"
    data = data or load()
    try:
        mt = p.stat().st_mtime_ns
    except OSError:
        mt = None
    stamp = (
        mt,
        rocks_stamp(),
        id(data),
    )  # 挖矿点文件、石头表、星图任何一个换了都重算（审查 2026-10-27）
    if _spots.get("stamp") == stamp and "list" in _spots:
        return _spots["list"]
    out = []
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) if mt is not None else []
    except Exception:
        raw = []
    for r in raw:
        x, y, z = r["x"] / 1000, r["y"] / 1000, r["z"] / 1000
        out.append(
            dict(
                b="@" + r["sys"],
                sys=r["sys"],
                space=True,
                n=r.get("en") or r["id"],
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
    with (
        gamedata.snapshot()
    ):  # 一次搜索钉在一个版本上：几千次地名查询复用这个快照，不每次读清单
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

    for p in waypoints() + data["pois"] + spots:
        if p["b"] not in data["bodies"] and not is_space(p):
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


def _read_position(timeout=None):
    """读一次游戏右上角的位置：(星系坐标, 读到的信息)；超时返回 (None, None)"""
    from .displayinfo import Reader

    r = Reader(every=1.0)
    end = time.time() + timeout if timeout else None
    while end is None or time.time() < end:
        g = r.poll(force=True)
        if g:
            return g, r.info
        time.sleep(1.0)
    return None, None


def track(target, data=None):
    """导航（命令行版）：每秒读一次右上角的位置，刷新方位和距离"""
    from ..app.overlay import hud
    from .displayinfo import Reader

    data = data or load()
    ov = hud()
    print(
        "\n切回游戏就行。要先在游戏控制台（~ 键）输入 r_DisplayInfo 2，右上角显示坐标。"
    )
    print("  按 Ctrl+C 结束导航。\n")
    head = f"→ {label(target)}"
    ov.set("导航", f"{head}\n等待位置…")
    reader = Reader(every=1.0)
    try:
        while True:
            g = reader.poll()
            if g:
                info = reader.info or {}
                here = locate(
                    g,
                    when=info.get("t"),
                    data=data,
                    local=info.get("local"),
                    zone=info.get("zone"),
                    local_ok=info.get("local_ok"),
                )
                print(time.strftime("%H:%M:%S"), here_text(here, data))
                print("  " + nav_text(here, target, data).replace("\n", "\n  "))
                near = near_text(here, data)
                ov.set(
                    "导航",
                    f"{head}\n{_short(here, target)}" + (f"\n{near}" if near else ""),
                )
            ov.sleep(0.2)
    finally:
        ov.clear("导航")


def where_am_i(data):
    """读一次位置并返回（读不到返回 None）"""
    print("切回游戏，读右上角的位置（要开着 r_DisplayInfo 2）…")
    g, info = _read_position(timeout=20)
    if not g:
        print("20 秒没读到：游戏控制台输入 r_DisplayInfo 2，右上角显示坐标后再试")
        return None
    here = locate(
        g,
        when=info.get("t"),
        data=data,
        local=info.get("local"),
        zone=info.get("zone"),
        local_ok=info.get("local_ok"),
    )
    print(here_text(here, data))
    return here


# ---------------------------------------------------------------- 菜单


def ask():
    data = load()
    print(f"星图数据：starmap.space（{data.get('fetched', '?')}）。菜单 5 可更新。")
    print(
        "输入目的地（中文或英文，可加星球名或类型，例：戴玛尔 洞穴 / Kudre / 残骸 耶拉）"
    )
    print("输入「路标」管理自定义路标；直接回车看自己在哪；输入 q 退出。\n")
    while True:
        try:
            q = input("目的地 > ").strip()
        except EOFError:
            return
        if q.lower() == "q":
            return
        if not q:
            where_am_i(data)
            continue
        if q in ("路标", "lubiao", "wp"):
            target = waypoint_menu(data)
            if not target:
                continue
        else:
            hits, total = search(q, data)
            if not hits:
                print("没找到，换个词试试（地名、星球名都行）\n")
                continue
            target = pick(hits, total)
            if not target:
                continue
        print()
        print(plan_text(target, data))
        try:
            track(target, data)
        except KeyboardInterrupt:
            print("\n（导航结束）\n")


def pick(hits, total=None):
    for i, p in enumerate(hits, 1):
        print(
            f"  {i:>2}. {label(p)}｜{body_label(p['b'])}｜{TYPE_ZH.get(p['t'], p['t'])}"
            f"｜{QT_ZH.get(p['qt'], '信标未确认')}"
        )
    if total and total > len(hits):
        print(f"  …共 {total} 个，加个词缩小范围（比如星球名）")
    sel = input("选序号（回车返回）> ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(hits):
        return hits[int(sel) - 1]
    return None


def _find_body(text, data):
    t = text.strip().lower()
    for name in data["bodies"]:
        if t in (name.lower(), BODY_ZH.get(name, "\0")):
            return name
    cands = [n for n in data["bodies"] if t in n.lower() or t in BODY_ZH.get(n, "")]
    return cands[0] if len(cands) == 1 else None


def waypoint_menu(data):
    """自定义路标：输入坐标或用当前位置新建；返回要导航去的路标（或 None）"""
    while True:
        wps = [w for w in waypoints() if w["b"] in data["bodies"]]
        print("\n路标：" + ("还没有" if not wps else ""))
        for i, w in enumerate(wps, 1):
            lat, lon, r = latlon(pos(w))
            h = r * 1000 - data["bodies"][w["b"]]["r"]
            print(
                f"  {i:>2}. {w['n']}｜{body_label(w['b'])}｜纬度 {lat:.3f}° 经度 {lon:.3f}° 高度 {h:,.0f} m"
            )
        print(
            "  序号 = 导航过去｜+ = 用坐标新建｜* = 用当前位置新建｜- 序号 = 删除｜回车返回"
        )
        cmd = input("路标 > ").strip()
        if not cmd:
            return None
        if cmd.isdigit() and 1 <= int(cmd) <= len(wps):
            return wps[int(cmd) - 1]
        if (
            cmd.startswith("-")
            and cmd[1:].strip().isdigit()
            and 1 <= int(cmd[1:]) <= len(wps)
        ):
            name = wps[int(cmd[1:]) - 1]["n"]
            delete_waypoint(name)
            print(f"已删除：{name}")
        elif cmd == "+":
            print("格式：星球 纬度 经度 [高度米]，例：戴玛尔 54.54 38.01 500")
            parts = re.split(r"[\s,，]+", input("坐标 > ").strip())
            try:
                body = _find_body(parts[0], data)
                lat, lon = float(parts[1]), float(parts[2])
                h = float(parts[3]) if len(parts) > 3 else 0.0
                assert body and -90 <= lat <= 90 and -360 <= lon <= 360
            except Exception:
                print("没看懂，按格式再输一次")
                continue
            name = (
                input("路标名字 > ").strip()
                or f"{BODY_ZH.get(body, body)} {lat:.2f},{lon:.2f}"
            )
            add_waypoint(
                name, body, from_latlon(lat, lon, data["bodies"][body]["r"] / 1000, h)
            )
            print(f"已添加：{name}")
        elif cmd == "*":
            here = where_am_i(data)
            if not here:
                continue
            if not here["inside"]:
                print("不在星球附近，没法在这里放路标")
                continue
            name = input("路标名字 > ").strip() or time.strftime("路标 %m-%d %H:%M")
            add_waypoint(name, here["body"], pos(here))
            print(f"已添加：{name}")


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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        update()
    else:
        ask()
