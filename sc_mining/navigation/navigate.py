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
    _places_zh,
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
    _apply_fixes,
    _data,
    _data_stamp,
    _fetch,
    _files_stamp,
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

# ---------------------------------------------------------------- 挖矿点（2026-10-27 解包：能量子过去、而且刷船挖矿的太空地点）

_spots = {}


def mining_spots(data=None):
    """导航里的「挖矿点」（太空目标，b = "@星系"，坐标千米）：
    - data/mining_spots.json（tools/unpack_spots.py 解物件容器生成）：派罗 15 个小行星群、86 个远矿站，冰川环带中转点、QV 碎岩站
    - 星图里有刷矿表的拉格朗日点（斯坦顿 20 个、派罗 25 个，data/mining_rocks.json 里有表的才算）
    每个点带 rocks：这里刷哪几种石头（搜「贝沙电气石」能搜到会刷它的点）"""
    from ..mining.mining_area import rocks_stamp, area_for_spot
    from ..core.paths import DATA

    p = DATA / "mining_spots.json"
    data = data or load()
    try:
        mt = p.stat().st_mtime_ns
    except OSError:
        mt = None
    stamp = (
        mt,
        rocks_stamp(),
        id(data),
        _data_stamp,
    )  # 挖矿点文件、石头表、星图任何一个换了都重算（Codex 2026-10-27）
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
    """星图里的太空站、跳跃点（2026-10-28 解包星图后有了：拉格朗日点的站、派罗 / 尼克斯的门户站、INS Jericho）→ 导航的太空目标（b = "@星系"，千米）"""
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


# ---------------------------------------------------------------- 城里导航（2026-10-27，先做新巴贝奇）

_city = {}


def city_places():
    """data/city_places.json（tools/unpack_city.py 解城市物件容器生成）→ 导航用的地点（星球坐标，千米）"""
    from ..core.paths import cached_json

    return cached_json(DATA / "city_places.json", _city_rows, [])


def _city_rows(raw):
    """city_places.json 原始条目 → 导航用的地点列表（只在文件变了时跑一次）"""
    if True:

        def txt(v):
            return v.strip() if isinstance(v, str) else ""

        out, ids, names = [], set(), {}
        for i, r in enumerate(raw if isinstance(raw, list) else []):
            space = (
                isinstance(r, dict) and bool(r.get("space")) and bool(txt(r.get("sys")))
            )
            if (
                not isinstance(r, dict)
                or not (txt(r.get("body")) or space)
                or not txt(r.get("en"))
            ):
                continue  # 坏条目跳过，别的照常（Codex 2026-10-27）
            try:
                xyz = [float(r[k]) for k in ("x", "y", "z")]
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in xyz):
                continue
            pid = (
                txt(r.get("src")) or f"#{i}"
            )  # 同名地点（4 个 ASOP…）靠它区分，搜索、开始导航都用
            while pid in ids:
                pid += "+"
            ids.add(pid)
            zh = txt(r.get("zh"))
            if zh:  # 同一个城 / 站里中文名重名（空港两台取船终端）：后面的加 2、3
                nk = (txt(r.get("city")), zh)
                names[nk] = names.get(nk, 0) + 1
                if names[nk] > 1:
                    zh = f"{zh} {names[nk]}"
            city = txt(r.get("city"))
            kinds = [k for k in (r.get("kinds") or []) if isinstance(k, str)]
            up = r.get("up")
            q = dict(
                b=("@" + txt(r["sys"])) if space else txt(r["body"]),
                n=txt(r["en"]),
                zh=zh,
                t="City",
                x=xyz[0],
                y=xyz[1],
                z=xyz[2],
                qt=0,
                id=pid,
                cat=txt(r.get("cat")),
                area=txt(r.get("area")),
                city=city,
                city_zh=txt(r.get("site_zh")) or CITY_ZH.get(city, ""),
                site_en=txt(r.get("site_en")),
                line=txt(r.get("line")),
                stop=txt(r.get("stop")),
                kinds=kinds,
            )
            if space:  # 拉格朗日点、跳跃点的空间站：星系坐标（千米），不跟星球转
                q.update(space=True, sys=txt(r["sys"]))
            if (
                isinstance(up, list)
                and len(up) == 3
                and all(isinstance(v, (int, float)) for v in up)
            ):
                q["up"] = tuple(float(v) for v in up)  # 空间站的「上」（楼层提示用）
            out.append(q)
    return out


def city_metrics(here, target):
    """城里：直线距离（米）、目标比你高多少米（正数在上方）"""
    a, t = pos(here), pos(target)
    d = math.dist(a, t) * 1000
    if target.get("up"):  # 空间站：按站自己的朝向分上下
        up = sum((x - y) * u for x, y, u in zip(t, a, target["up"])) * 1000
    else:
        up = (math.hypot(*t) - math.hypot(*a)) * 1000
    return d, up




def city_text(here, target, brg=None, arrived=None):
    a, t = pos(here), pos(target)
    brg = bearing(a, t) if brg is None else brg
    d, up = city_metrics(here, target)
    if city_arrived(d) if arrived is None else arrived:
        return f"✅ 到了（{d:,.0f} m 内）"
    if d < CITY_NEAR_M:
        out = f"就在附近 {d:,.0f} m"
    elif target.get("up"):  # 空间站里南北没意义：只给距离，转向看机头 / 屏幕记号
        out = f"{d:,.0f} m"
    else:
        out = f"朝 {deg_text(brg)}°（{compass(brg)}） {d:,.0f} m"
    if up > CITY_FLOOR_M:
        out += f"\n目标在上方 {up:,.0f} 米：找电梯上楼"
    elif up < -CITY_FLOOR_M:
        out += f"\n目标在下方 {-up:,.0f} 米：找电梯下楼"
    return out


# ---------------------------------------------------------------- 找最近的医院 / 空港 / 买船（2026-10-27 老大定）

NEAR_KINDS = ("医院", "空港", "买船")
# 城里同一类有好几个点时，指向能直接办事的那个：医院 → 登记处，空港 → 取船终端（ASOP）；买船就是店本身
NEAR_PREFER = {
    "医院": ("Hospital Check-In", "Clinic Check-In"),
    "空港": ("Fleet Manager Terminal",),
}
NEAR_ALIAS = {"空港": "取船"}  # 空间站里没有「空港」这个类，取船终端就是
# 在主城 / 空间站里能点的分类（2026-10-27 老大定），顺序就是按钮顺序
SITE_KINDS = (
    "取船",
    "交易",
    "货梯",
    "医院",
    "武器",
    "护甲",
    "服装",
    "部件",
    "吃喝",
    "精炼",
    "行政",
    "罚款",
    "租船",
    "买船",
    "地铁",
)
SITE_NEAR_M = 6000  # 离空间站最近的点这么近（米）算在站里
_amen = {}


def amenity_targets(kind, data=None):
    """城外有这类设施的地点（data/place_amenities.json，tools/unpack_amenities.py 从星图记录生成）→ 导航目标。
    休息站在星图里只有所在的拉格朗日点 / 跳跃点，就导航到那个点；城市用城里的点（city_places）"""
    from ..core.paths import cached_json

    data = data or load()
    rows = cached_json(
        DATA / "place_amenities.json", lambda r: r if isinstance(r, list) else [], []
    )
    pois = {}
    for q in data["pois"]:
        pois.setdefault(_norm(q["n"]), q)
    pts = {q["n"]: q for q in data.get("points") or []}
    pts_id = {
        q["i"]: q for q in data.get("points") or [] if q.get("i")
    }  # 星门站重名，按编号找（2026-10-30）
    inside = {
        q.get("city") for q in city_targets(kind)
    }  # 站里有这一类的点才用站里的（派罗死局等站没解出取船终端，审查 2026-10-30）
    out = []
    for r in rows:
        if not isinstance(r, dict) or kind not in (r.get("kinds") or []):
            continue
        if (
            str(r.get("rec") or "").lower() in inside
        ):  # 站里的点已经有了（tools/unpack_stations.py）：用站里的
            continue
        ref, zh, en = (
            r.get("ref") or {},
            (r.get("zh") or "").strip(),
            (r.get("en") or "").strip(),
        )
        if not en:
            continue
        if ref.get("poi"):
            q = pois.get(_norm(ref["poi"]))
            if q and q["b"] in data["bodies"]:
                out.append(q)
            elif (
                ref.get("body") in data["bodies"]
                and isinstance(ref.get("local"), list)
                and len(ref["local"]) == 3
            ):
                x, y, z = ref[
                    "local"
                ]  # 星图地点表里没有的轨道站（Everus Harbor）：相对星球的位置
                out.append(
                    dict(
                        b=ref["body"],
                        n=en,
                        zh=zh,
                        t="Orbital Station",
                        qt=1,
                        x=x,
                        y=y,
                        z=z,
                    )
                )
            continue
        src = (
            pts_id.get(ref.get("point_id")) or pts.get(ref.get("point"))
            if ref.get("point")
            else data["bodies"].get(ref.get("body") or "")
        )
        if src and src.get("sys"):
            out.append(
                dict(
                    b="@" + src["sys"],
                    sys=src["sys"],
                    space=True,
                    n=en,
                    zh=zh,
                    t="Orbital Station",
                    qt=1,
                    x=src["x"] / 1000,
                    y=src["y"] / 1000,
                    z=src["z"] / 1000,
                )
            )
    return out


def city_targets(kind):
    """城里这类的点：有能直接办事的（登记处 / 取船终端）就只要这些（一个城可能有好几台，按远近挑），没有就这类全部"""
    by_city = {}
    alias = NEAR_ALIAS.get(kind, kind)
    for q in city_places():
        if q.get("cat") == kind or alias in (q.get("kinds") or ()):
            by_city.setdefault(q.get("city"), []).append(q)
    pref = NEAR_PREFER.get(kind)
    out = []
    for qs in by_city.values():
        good = [q for q in qs if pref and q["n"] in pref]
        out += good or qs
    return out


def site_at(g=None, here=None, when=None, data=None, system=""):
    """现在在哪个主城 / 空间站里 → {"site", "zh", "en", "kinds": [这里有的分类]}；不在就 None。
    星球上的（主城、绕星球轨道的站）：同一颗星球、离最近的点 20 km 内；拉格朗日点 / 跳跃点的站：离最近的点 SITE_NEAR_M 米内"""
    best = None
    pts = city_places()
    if here and here.get("inside"):
        for q in pts:
            if not q.get("space") and q["b"] == here.get("body"):
                d = math.dist(pos(q), pos(here)) * 1000
                if d < 20_000 and (best is None or d < best[0]):
                    best = (d, q)
    if best is None and g is not None:
        for q in pts:
            if q.get("space") and (
                not system or q.get("sys") == system
            ):  # 别的星系同一个坐标也可能有站（二审 2026-10-27）
                d = math.dist(g, (q["x"] * 1000, q["y"] * 1000, q["z"] * 1000))
                if d < SITE_NEAR_M and (best is None or d < best[0]):
                    best = (d, q)
    if best is None:
        return None
    q = best[1]
    have = {
        k for p in pts if p.get("city") == q.get("city") for k in (p.get("kinds") or ())
    }
    return {
        "site": q.get("city"),
        "zh": q.get("city_zh") or "",
        "en": q.get("site_en") or q.get("city") or "",
        "kinds": [k for k in SITE_KINDS if k in have],
    }


def site_nearest(site, kind, g=None, when=None, data=None, here=None):
    """主城 / 空间站里这一类的点，近的在前 → [(距离米或 None, 点)]。
    here：locate() 的结果，同一颗星球上用它校准（和实时导航、屏幕记号同一个基准，二审 2026-10-27）"""
    data = data or load()
    out = []
    qs = [
        q
        for q in city_places()
        if q.get("city") == site and kind in (q.get("kinds") or ())
    ]
    pref = NEAR_PREFER.get(kind)
    good = [q for q in qs if pref and q["n"] in pref]
    for q in good or qs:
        d = None
        if g is not None:
            try:
                d = math.dist(
                    g, target_global(q, data, when, (g, here, when) if here else None)
                )
            except Exception:
                d = None
        out.append((d is None, d or 0.0, label(q), d, q))
    out.sort(key=lambda r: r[:3])
    return [(d, q) for *_, d, q in out]


def station_text(g, target, data=None, when=None, arrived=None):
    """拉格朗日点 / 跳跃点空间站里（星系坐标）：距离 + 上下楼层；转向看机头一行和屏幕记号"""
    tg = target_global(target, data, when)
    d = math.dist(g, tg)
    if city_arrived(d) if arrived is None else arrived:
        return f"✅ 到了（{d:,.0f} m 内）"
    out = f"就在附近 {d:,.0f} m" if d < CITY_NEAR_M else f"{d:,.0f} m"
    up = sum((t - a) * u for t, a, u in zip(tg, g, target.get("up") or (0, 0, 0)))
    if up > CITY_FLOOR_M:
        out += f"\n目标在上方 {up:,.0f} 米：找电梯上楼"
    elif up < -CITY_FLOOR_M:
        out += f"\n目标在下方 {-up:,.0f} 米：找电梯下楼"
    return out


def target_system(p, data=None):
    data = data or load()
    if is_space(p):
        return p.get("sys") or ""
    b = data["bodies"].get(p.get("b"))
    return b["sys"] if b else ""


def nearest(kind, g=None, system="", when=None, data=None, here=None):
    """最近的医院 / 空港 / 买船。g：玩家星系坐标（米），不知道就给 None。
    → [(距离米或 None, 目标)]，近的在前；同星系的排在前面。城里：同一个城里只按城里的点算（不会跑去城外的站）"""
    data = data or load()
    cands = city_targets(kind) + amenity_targets(kind, data)
    site = site_at(g, here, when, data, system)
    if site:  # 已经在某个主城 / 空间站里：只要这里的
        inside = [q for q in city_targets(kind) if q.get("city") == site["site"]]
        if inside:
            cands = inside
    out = []
    for q in cands:
        d = None
        if g is not None:
            try:
                d = math.dist(
                    g, target_global(q, data, when, (g, here, when) if here else None)
                )
            except Exception:
                d = None
        same = not system or target_system(q, data) == system
        if not same:  # 每个星系各有自己的坐标系：跨星系的距离没意义（二审 2026-10-27）
            d = None
        out.append((not same, d is None, d or 0.0, label(q), d, q))
    out.sort(key=lambda r: r[:4])
    seen, res = set(), []
    for *_, d, q in out:
        k = (q.get("id") or q["n"], q.get("b"))
        if k not in seen:
            seen.add(k)
            res.append((d, q))
    return res


# ---------------------------------------------------------------- 城里分段路线：走到站台 → 坐地铁（可换乘一次）→ 出站走到目的地

METRO_MIN_M = 400  # 起点和目的地隔这么远（米）以上才考虑坐地铁
METRO_BOARD_M = 25  # 离上车的站台这么近：提示上车
LINE_ZH = {
    "loop": "微科地铁环线",
    "perim_line_a": "外环 A 线",
    "perim_line_b": "外环 B 线",
    "sp_line": "空港线",
    "com_line": "商业线",
    "cen_line": "中央线",
}


def _metro_lines(city):
    """城里的地铁：{线: {站: 站台}}；只有一个站的线（另一头的站台没解出来）不算"""
    lines = {}
    for q in city_places():
        if (
            q.get("city") == city
            and q.get("cat") == "地铁"
            and q.get("line")
            and q.get("stop")
        ):
            lines.setdefault(q["line"], {}).setdefault(q["stop"], q)
    return {k: v for k, v in lines.items() if len(v) >= 2}


def city_route(here, target):
    """城里怎么去：[(动作, 站台, 线)]，动作 walk / ride / transfer；不用坐地铁（太近、没地铁、走路更快）返回 None"""
    if not is_city(target) or here.get("body") != target.get("b"):
        return None
    lines = _metro_lines(target.get("city"))
    stops = [(ln, q) for ln, st in lines.items() for q in st.values()]
    if not stops:
        return None
    a, t = pos(here), pos(target)
    direct = math.dist(a, t) * 1000
    if direct < METRO_MIN_M:
        return None
    l0, s0 = min(stops, key=lambda x: math.dist(a, pos(x[1])))
    l1, s1 = min(stops, key=lambda x: math.dist(t, pos(x[1])))
    if s0["stop"] == s1["stop"]:
        return None
    walk = (math.dist(a, pos(s0)) + math.dist(pos(s1), t)) * 1000
    if walk > direct * 0.8:  # 走到站台再走出来，比直接走还远
        return None
    on = [ln for ln, st in lines.items() if s0["stop"] in st and s1["stop"] in st]
    if on:  # 一条线直达
        return [
            ("walk", lines[on[0]][s0["stop"]], on[0]),
            ("ride", lines[on[0]][s1["stop"]], on[0]),
        ]
    for (
        la,
        sa,
    ) in (
        lines.items()
    ):  # 换乘一次：起点那条线和终点那条线有同一个站（罗威尔的地铁中心）
        if s0["stop"] not in sa:
            continue
        for lb, sb in lines.items():
            if lb == la or s1["stop"] not in sb:
                continue
            mid = set(sa) & set(sb)
            if mid:
                m = sorted(mid)[0]
                return [
                    ("walk", sa[s0["stop"]], la),
                    ("ride", sa[m], la),
                    ("transfer", sb[m], lb),
                    ("ride", sb[s1["stop"]], lb),
                ]
    return None


LINE_EN = {
    "loop": "MetroLoop",
    "perim_line_a": "Perimeter Line A",
    "perim_line_b": "Perimeter Line B",
    "sp_line": "Spaceport Line",
    "com_line": "Commerce Line",
    "cen_line": "Central Line",
}


def _bi(zh, en):
    """导航双语（2026-10-27 老大定）：中文（English）；没中文或一样就只写英文"""
    zh, en = (zh or "").strip(), (en or "").strip()
    return f"{zh}（{en}）" if zh and en and zh != en else (zh or en)


def _line_name(ln):
    return _bi(LINE_ZH.get(ln, ""), LINE_EN.get(ln, ln))


def _stop_name(q):
    """站名：「地铁中心（Metro Center）」"""
    zh = q.get("zh") or ""
    zh = zh.replace("地铁站台 · ", "").split("（")[0] if "·" in zh else zh
    en = q["n"].split(" - ", 1)[1] if " - " in q["n"] else q["n"]
    return _bi(zh, en)


REROUTE_M = 150  # 比离这一段的目标最近时又远了这么多（米）：走偏了，重新规划
REROUTE_RIDE_M = 3000  # 坐车那几段：轨道会绕弯，放宽


def city_leg(here, target, plan=None, inner=""):
    """这一段该去哪：(该指向的点, 步骤文字[]）。不用坐地铁：指向目的地、没有步骤。
    plan：导航时传同一个 dict 进来——路线定下来按段往前走（到了一段的站台就进下一段），
    走偏了才重新规划；不然每帧重算，坐车坐到一半会跳回第一步（二审 2026-10-27）。
    绕星球轨道的空间站：按区域坐电梯分段（station_leg，inner 是右上角最里层 Zone 名）"""
    a = pos(here)
    if station_lifts().get(target.get("city") or ""):
        if here.get("body") != target.get("b"):
            return target, []
        return station_leg(a, target, plan, inner)
    if plan is None:
        route = city_route(here, target)
        i = 1 if route and math.dist(a, pos(route[0][1])) * 1000 < METRO_BOARD_M else 0
    else:
        key = (target.get("id") or target["n"], target.get("b"), here.get("body"))
        if plan.get("key") == key and "route" in plan:
            route, i = plan["route"], plan["i"]
            goal = route[i][1] if route and i < len(route) else target
            d = math.dist(a, pos(goal)) * 1000
            ride = bool(route) and i < len(route) and route[i][0] == "ride"
            if d > plan["best"] + (REROUTE_RIDE_M if ride else REROUTE_M):
                plan.clear()
            else:
                plan["best"] = min(plan["best"], d)
        if plan.get("key") != key or "route" not in plan:
            route = city_route(here, target)
            plan.clear()
            plan.update(key=key, route=route, i=0, best=float("inf"))
            i = 0
        while (
            route
            and i < len(route)
            and math.dist(a, pos(route[i][1])) * 1000 < METRO_BOARD_M
        ):
            i += 1  # 到了这一段的站台：下一段
            plan["best"] = float("inf")
        plan["i"] = i
        if plan["best"] == float("inf"):
            goal = route[i][1] if route and i < len(route) else target
            plan["best"] = math.dist(a, pos(goal)) * 1000
    if not route:
        return target, []
    goal = route[i][1] if i < len(route) else target
    steps, n = [], 0
    for act, q, ln in route:
        n += 1
        if act == "walk":
            steps.append(f"{n}. 步行到 {label(q)}")
        elif act == "ride":
            steps.append(f"{n}. 坐 {_line_name(ln)} 到 {_stop_name(q)} 下车")
        else:
            steps.append(f"{n}. 换乘 {_line_name(ln)}")
    steps.append(f"{n + 1}. 出站步行到 {label(target)}")
    steps = [
        ("→ " if k == i else "   ") + s for k, s in enumerate(steps)
    ]  # 当前这步用 →（悬浮窗的字体没有 ▶，画成方块，2026-10-28）
    return goal, steps


# ---------------------------------------------------------------- 空间站里分段路线：走到电梯门 → 坐电梯（可换乘一次）→ 出电梯走到目的地（2026-10-28）
# 数据：data/station_lifts.json（tools/unpack_lifts.py 解包生成）：每个站的区域、电梯线（每站的门）、机库电梯门、站里的点在哪个区域

LIFT_BOARD_M = 25  # 坐电梯：离下车的门这么近算到了（居住区各层的门上下只隔 16 米：以后加居住区目的地时这里要注意）
LIFT_SWITCH_M = 8  # 在电梯里直接换乘（一帧大厅都没读到）：离这一段的上车门这么近、又比离上一段下车门近，算换到了新轿厢
LIFT_SPOT_M = (
    10  # 读不到区域名时：离某个已知点（电梯门、站里的点）这么近，就当在那个点的区域
)
LIFT_OFF_N = 3  # 读不到区域名、连续这么多帧都在路线外的区域：重新规划
LIFT_WALK_M = 4  # 读不到区域名时：离上车的门这么近算进了电梯（各部电梯的门最近只隔 3 米，审查 2026-10-28）
LIFT_NEAR_M = (
    300  # 读不到区域名时按坐标认区域：离最近的已知点（电梯门、站里的点）这么近才算数
)
LIFT_FAR_M = 3000  # 离站里所有已知点都这么远：不在这个站里
HANGAR_LIFT_M = 250  # 在机库里：离机库电梯门这么近才算是这个机库的


def station_lifts():
    """rr_* 站记录名 → 这个站的区域 / 电梯 / 机库数据"""
    from ..core.paths import cached_json

    return cached_json(DATA / "station_lifts.json", _lift_rows, {})


def _lift_rows(raw):
    """station_lifts.json → {站: 数据}；结构不对的站整个跳过，别的照常（坏数据不能让导航线程抛错退出）"""

    def xyz(v):
        return (
            isinstance(v, list)
            and len(v) == 3
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)
        )

    def ok(st):
        if (
            isinstance(st, dict) and st.get("ok") is False
        ):  # 解包自检没过（点和电梯门对不上）：不分段，照旧直线指
            return False
        if not (
            isinstance(st, dict)
            and isinstance(st.get("areas"), dict)
            and isinstance(st.get("places"), dict)
            and isinstance(st.get("lifts"), list)
            and isinstance(st.get("hangars"), list)
        ):
            return False
        if not all(
            isinstance(a, str) and isinstance(v, dict) for a, v in st["areas"].items()
        ):
            return False
        if not all(
            isinstance(k, str) and isinstance(v, str) for k, v in st["places"].items()
        ):
            return False

        def names(d):
            return isinstance(d.get("en"), str) and isinstance(d.get("zh"), str)

        for ln in st["lifts"]:
            if not (
                isinstance(ln, dict) and isinstance(ln.get("stops"), list) and names(ln)
            ):
                return False
            for s in ln["stops"]:
                if not (
                    isinstance(s, dict)
                    and names(s)
                    and isinstance(s.get("gates"), list)
                    and all(xyz(g) for g in s["gates"])
                    and (s.get("area") is None or isinstance(s.get("area"), str))
                ):
                    return False
        return all(
            isinstance(h, dict)
            and isinstance(h.get("size"), str)
            and all(xyz(h.get(k)) for k in ("door", "lift", "spawn"))
            for h in st["hangars"]
        )

    sts = raw.get("stations") if isinstance(raw, dict) else None
    return {k: v for k, v in sts.items() if ok(v)} if isinstance(sts, dict) else {}


def _zkey(s):
    return re.sub(r"[\s_\-]", "", s or "").lower()


ZONE_MARGIN = 0.04  # 区域名模糊比较：第一名和第二名差不到这么多就不认（ObjectContainer-000 / -001 只差一位）


def zone_kind(inner, st):
    """右上角最里层 Zone 名 → 站里的区域 id；"lift" = 在电梯轿厢里；"hangar" = 在机库里；认不出 None。
    轿厢、机库名字末尾的 _<数字> 是每次随机的编号，只看开头（字模认错一两个字母也算）；
    区域名两边都不去编号（rs_refin_occu_001、ObjectContainer-001 的编号是名字的一部分），先找一模一样的，再模糊比较"""
    from difflib import SequenceMatcher

    k = _zkey(inner)
    if not k:
        return None
    if (
        k.startswith("transitcarriage")
        or SequenceMatcher(None, k[:15], "transitcarriage").ratio() >= 0.85
    ):
        return "lift"
    if k.startswith("hangar") or (
        SequenceMatcher(None, k[:6], "hangar").ratio() >= 0.8
        and ("front" in k or "reststop" in k)
    ):
        return "hangar"
    names = [a for a, v in st["areas"].items() if v.get("zone")]
    exact = [a for a in names if _zkey(a) == k]
    if exact:
        return exact[0] if len(exact) == 1 else None
    sc = sorted(
        ((SequenceMatcher(None, _zkey(a), k).ratio(), a) for a in names), reverse=True
    )
    if not sc or sc[0][0] < 0.85 or (len(sc) > 1 and sc[0][0] - sc[1][0] < ZONE_MARGIN):
        return None
    return sc[0][1]


def _hangar_size(inner):
    m = re.search(r"(small|medium|large)", _zkey(inner))
    return m[1].capitalize() if m else None


def _station_points(st, site):
    """站里已知的点 → [(位置千米, 区域)]：电梯门、机库（门、电梯门、出生点）、站里的导航点"""
    pts = [
        (tuple(g), s["area"])
        for ln in st["lifts"]
        for s in ln["stops"]
        if s.get("area")
        for g in s["gates"]
    ]
    pts += [
        (tuple(h[k]), "hangar")
        for h in st["hangars"]
        for k in ("door", "lift", "spawn")
    ]
    pts += [
        (pos(q), st["places"][q["id"]])
        for q in city_places()
        if q.get("city") == site and q["id"] in st["places"]
    ]
    return pts


def _hangar_lift(st, a, size=None):
    """在机库里：自己这个机库的电梯门（离得最近的、尺寸对得上的，HANGAR_LIFT_M 内）"""
    hs = [h for h in st["hangars"] if not size or h["size"] == size]
    best = min(hs, key=lambda h: math.dist(a, h["lift"]), default=None)
    return (
        tuple(best["lift"])
        if best and math.dist(a, best["lift"]) * 1000 < HANGAR_LIFT_M
        else None
    )


def _goal(target, xyz, en, zh, tag):
    """分段的目标点：坐标系、所属站都跟着最终目的地（指向、屏幕记号照常用）"""
    return dict(
        target,
        x=xyz[0],
        y=xyz[1],
        z=xyz[2],
        n=en,
        zh=zh,
        id=f"{target.get('id') or target['n']}#{tag}",
        cat="",
    )


def station_route(st, a, cur, dest, target, size=None):
    """从区域 cur 到区域 dest 怎么坐电梯（最多两段）→ [段]，段 = dict(act=walk/ride, goal, line, stop, frm, to)；没路返回 None。
    a：现在的位置（千米）；目的地在同一个区域里返回 []"""
    if cur == dest:
        return []
    t = pos(target)

    def gates(stop, ref):
        if stop["area"] == "hangar":
            g = _hangar_lift(st, ref, size)
            return [g] if g else []
        return [tuple(g) for g in stop["gates"]]

    found, frontier = [], [(cur, [])]
    for _depth in range(2):
        nxt = []
        for area, path in frontier:
            for ln in st["lifts"]:
                for on in ln["stops"]:
                    if on.get("area") != area:
                        continue
                    for off in ln["stops"]:
                        if (
                            not off.get("area")
                            or off["area"] == area
                            or off["area"] == "hangar"
                            or not off["gates"]
                        ):
                            continue
                        p2 = path + [(ln, on, off)]
                        (found if off["area"] == dest else nxt).append(
                            (off["area"], p2)
                        )
        if found:
            break
        frontier = nxt
    best = None
    for (
        _area,
        path,
    ) in found:  # 几条一样少换乘的：最后下车的门离目的地最近的那条（居住区按楼层）
        legs, ref, prev = [], a, None
        for ln, on, off in path:
            ga = gates(on, ref)
            if not ga:
                legs = None
                break
            g_on = min(ga, key=lambda g: math.dist(g, ref))
            g_off = min((tuple(g) for g in off["gates"]), key=lambda g: math.dist(g, t))
            board = _goal(target, g_on, ln["en"], ln["zh"], f"{len(legs)}")
            # on_gates：上车站所有的门（走哪扇都算）；prev_gates：上一段下车站的门（在电梯里直接换乘时比远近）
            legs.append(
                dict(
                    act="walk",
                    goal=board,
                    line=ln,
                    stop=off,
                    frm=on["area"],
                    to=on["area"],
                    on_gates=ga,
                    prev_gates=prev,
                )
            )
            prev = [tuple(g) for g in off["gates"]]
            legs.append(
                dict(
                    act="ride",
                    goal=_goal(target, g_off, off["en"], off["zh"], f"{len(legs)}"),
                    line=ln,
                    stop=off,
                    frm=on["area"],
                    to=off["area"],
                    board=board,
                    gates=[tuple(g) for g in off["gates"]],
                    on_gates=ga,
                )
            )
            ref = g_off
        if (
            legs is not None
        ):  # 下车门一样近（居住区各层都能下到大厅）：比第一段上车门离人多远
            cost = (round(math.dist(ref, t), 6), math.dist(a, pos(legs[0]["goal"])))
            if best is None or cost < best[0]:
                best = (cost, legs)
    return best[1] if best else None


def _lift_steps(legs, i, kind, target):
    """路线 → 步骤文字：「1. 去机库电梯」「2. 坐机库电梯到「大厅」」「3. 换站内电梯到「购物中心」」「4. 出电梯到 …」；当前这步标 →"""
    rows, cur = [], None
    for k, L in enumerate(legs):
        ln = _bi(
            L["line"]["zh"], L["line"]["en"]
        )  # 导航文字一律「中文（English）」（S2 审查 2026-10-31）
        st = _bi(L["stop"]["zh"], L["stop"]["en"])
        if L["act"] == "walk" and k == 0:
            rows.append(f"去{ln}")
        elif L["act"] == "ride" and k == 1:
            rows.append(f"坐{ln}到「{st}」")
        elif L["act"] == "ride":
            rows.append(f"换{ln}到「{st}」")
        if k == i:
            cur = len(rows) - 1 if L["act"] == "ride" or k == 0 else len(rows)
    rows.append(f"出电梯到 {label(target)}")
    cur = len(rows) - 1 if cur is None else cur
    out = [("→ " if n == cur else "   ") + f"{n + 1}. {s}" for n, s in enumerate(rows)]
    if kind == "lift" and i < len(legs) and legs[i]["act"] == "ride":
        out.insert(
            cur + 1,
            f"   在电梯里选「{_bi(legs[i]['stop']['zh'], legs[i]['stop']['en'])}」",
        )
    return out


def _car_no(inner):
    """轿厢 Zone 名末尾的编号（每部电梯的轿厢不一样）"""
    m = re.search(r"(\S+)\s*$", (inner or "").replace("_", " "))
    return m[1] if m else ""


def _car_changed(a, b):
    """两个轿厢编号明显不同（逐位比，差 3 位以上；允许字模认错一两位）"""
    if not a or not b:
        return True
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b)) > 2


def station_leg(a, target, plan=None, inner=""):
    """空间站里这一段该去哪：(该指向的点, 步骤文字[])；同一个区域、没数据、认不出在哪：指向目的地、没有步骤。
    a：现在的位置（千米，和目的地同一个坐标系）；inner：右上角最里层 Zone 名（displayinfo 的 inner_zone）。
    plan：导航时传同一个 dict——路线定下来按段往前走：
      走到电梯门：读得到区域名时进了电梯（区域名变成轿厢、并且已经出过上一部电梯）才算完成；读不到时离门 LIFT_WALK_M 米内；
      坐电梯：区域名变成下车的区域，或离下车站任一个门 25 米内（读得到区域名时要在电梯里）；没进电梯（区域名是上车的区域）时指针还指上车门。
    区域名对不上路线（走错了）才重新规划"""
    st = station_lifts().get(target.get("city") or "")
    dest = st and st["places"].get(
        target.get("id") or ""
    )  # 按导航的 id（同名的店两处各一个：id 带 +）
    plan = {} if plan is None else plan
    if not dest:
        plan.clear()
        return target, []
    pts = _station_points(st, target.get("city"))
    near = min(
        ((math.dist(a, p) * 1000, ar) for p, ar in pts), default=(float("inf"), None)
    )
    if near[0] > LIFT_FAR_M:  # 不在这个站里
        plan.clear()
        return target, []
    kind = zone_kind(inner, st)
    key = (target.get("id") or target["n"], target.get("city"))
    legs = plan.get("legs") if plan.get("key") == key else None

    def near_m(gs):
        return min(math.dist(a, g) for g in gs) * 1000

    def advance(i):
        """到了这一段就往下推，返回推到第几段"""
        if kind and kind != "lift":
            plan["out"] = True
        while i < len(legs):
            L = legs[i]
            if L["act"] == "walk":
                d_on = near_m(L["on_gates"])
                if (
                    kind is None
                ):  # 读不到区域名：离任一扇上车门 4 米内，或已经到了下一段的下车门附近（比离上车门近）
                    nx = (
                        near_m(legs[i + 1]["gates"])
                        if i + 1 < len(legs)
                        else float("inf")
                    )
                    done = d_on < LIFT_WALK_M or (nx < LIFT_BOARD_M and nx < d_on)
                elif kind == "lift":
                    # 进了电梯要在这段上车门 8 米内（误进别的电梯不算）；没出过上一部电梯时（一帧大厅都没读到）
                    # 还要轿厢编号跟上一部明显不同、离这段上车门比离上一段下车门近
                    done = d_on < LIFT_SWITCH_M and (
                        plan["out"]
                        or bool(L.get("prev_gates"))
                        and d_on < near_m(L["prev_gates"])
                        and _car_changed(_car_no(inner), plan.get("car", ""))
                    )
                else:
                    done = False  # 还没进电梯
            else:
                d = near_m(
                    L["gates"]
                )  # 到站：离下车门 25 米内而且比离上车门近（居住区各层门只隔 16–23 米）
                done = (
                    kind in (None, "lift")
                    and d < LIFT_BOARD_M
                    and d < near_m(L["on_gates"])
                ) or (kind not in (None, "lift") and kind == L["to"])
            if not done:
                break
            i += 1
            plan["out"] = kind != "lift"
        if kind == "lift" and i < len(legs) and legs[i]["act"] == "ride":
            plan["car"] = _car_no(inner)  # 正坐着的这部电梯的轿厢编号（换乘时比）
        return i

    if legs is not None:
        i = advance(plan["i"])
        want = (legs[i]["frm"], legs[i]["to"]) if i < len(legs) else (dest,)
        if (
            kind not in (None, "lift") and kind not in want
        ):  # 区域名对不上路线：重新规划
            legs = None
        elif (
            kind is None
        ):  # 读不到区域名：按坐标纠正，都要连着 LIFT_OFF_N 帧（坐电梯路过、读空一帧不算）
            spot = near[1] if near[0] < LIFT_SPOT_M else None
            if math.dist(a, pos(target)) * 1000 < LIFT_BOARD_M or spot == dest:
                plan["off"] = 0
                plan["arr"] = plan.get("arr", 0) + 1  # 已经在目的地（的区域）
                if plan["arr"] >= LIFT_OFF_N:
                    i = len(legs)
            elif spot and spot not in {x for L in legs for x in (L["frm"], L["to"])} | {
                dest
            }:
                plan["arr"] = 0
                plan["off"] = plan.get("off", 0) + 1  # 在路线外的区域
                if plan["off"] >= LIFT_OFF_N:
                    legs = None
            else:
                plan["off"] = plan["arr"] = 0
        else:  # 在电梯里、或读得出区域名：两个计数都从头数
            plan["off"] = plan["arr"] = 0
        if legs is not None:
            plan["i"] = i
    if legs is None:
        if (
            kind == "lift"
        ):  # 在电梯里开始（或重新）规划：只有就在某扇门口才知道在哪，不然先直接指目的地，出了电梯再规划
            gates = [
                (math.dist(a, g) * 1000, s["area"])
                for ln in st["lifts"]
                for s in ln["stops"]
                if s.get("area")
                for g in s["gates"]
            ]
            gates += [(math.dist(a, h["lift"]) * 1000, "hangar") for h in st["hangars"]]
            g0 = min(gates, default=(float("inf"), None))
            cur = g0[1] if g0[0] < LIFT_SWITCH_M else None
        else:
            cur = (
                kind
                if kind is not None
                else (near[1] if near[0] < LIFT_NEAR_M else None)
            )
        legs = (
            station_route(st, a, cur, dest, target, _hangar_size(inner))
            if cur
            else None
        )
        plan.clear()
        if legs is None:
            return target, []
        plan.update(
            key=key, legs=legs, i=0, out=True
        )  # 开始时就在电梯里：当它就是要坐的那部
        i = plan["i"] = advance(0)  # 规划完马上往下推（人已经在电梯里才开始导航）
    if not legs:
        return target, []
    if i >= len(legs):
        goal = target
    elif (
        legs[i]["act"] == "ride"
        and kind not in (None, "lift")
        and kind == legs[i]["frm"]
    ):
        goal = legs[i]["board"]  # 还没进电梯：继续指上车的门
    else:
        goal = legs[i]["goal"]
    return goal, _lift_steps(legs, i, kind, target)




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
        from . import celestial as _celestial, names as _names, starmap as _starmap, waypoints as _waypoints

        for sub in (_celestial, _names, _starmap, _waypoints):
            if hasattr(sub, name):
                setattr(sub, name, value)


sys.modules[__name__].__class__ = _NavigateModule


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        update()
    else:
        ask()
