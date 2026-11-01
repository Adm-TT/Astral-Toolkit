"""主城地铁捷运路线规划与空间站多层立体电梯图导航算法模块（Navigation: Transit & Lifts）

提供：
1. 城市设施与点位解析（city_places、city_metrics、city_text）；
2. 空间站与主城按分类查找（amenity_targets、city_targets、site_at、site_nearest、nearest、station_text）；
3. 城市地铁捷运多段换乘路径规划与分步指引（city_route、city_leg、_metro_lines）；
4. 空间站/主城多层电梯（含机库电梯）拓扑图寻路与实时轿厢换乘跟随算法（station_lifts、station_route、station_leg、zone_kind）。
"""

from difflib import SequenceMatcher
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.paths import DATA, cached_json
from .celestial import (
    CITY_FLOOR_M,
    CITY_NEAR_M,
    bearing,
    city_arrived,
    compass,
    deg_text,
    is_city,
    pos,
    target_global,
)
from .names import (
    CITY_ZH,
    _norm,
    label,
)
from .starmap import load
from .waypoints import is_space

_city: Dict[str, Any] = {}


def city_places() -> List[Dict[str, Any]]:
    """data/city_places.json（tools/unpack_city.py 解城市物件容器生成）→ 导航用的地点（星球坐标，千米）"""
    return cached_json(DATA / "city_places.json", _city_rows, [])


def _city_rows(raw: Any) -> List[Dict[str, Any]]:
    """city_places.json 原始条目 → 导航用的地点列表（只在文件变了时跑一次）"""

    def txt(v: Any) -> str:
        return v.strip() if isinstance(v, str) else ""

    out, ids, names = [], set(), {}
    for i, r in enumerate(raw if isinstance(raw, list) else []):
        space = isinstance(r, dict) and bool(r.get("space")) and bool(txt(r.get("sys")))
        if (
            not isinstance(r, dict)
            or not (txt(r.get("body")) or space)
            or not txt(r.get("en"))
        ):
            continue
        try:
            xyz = [float(r[k]) for k in ("x", "y", "z")]
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in xyz):
            continue
        pid = txt(r.get("src")) or f"#{i}"
        while pid in ids:
            pid += "+"
        ids.add(pid)
        zh = txt(r.get("zh"))
        if zh:
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
        if space:
            q.update(space=True, sys=txt(r["sys"]))
        if (
            isinstance(up, list)
            and len(up) == 3
            and all(isinstance(v, (int, float)) for v in up)
        ):
            q["up"] = tuple(float(v) for v in up)
        out.append(q)
    return out


def city_metrics(here: Dict[str, Any], target: Dict[str, Any]) -> Tuple[float, float]:
    """城里：直线距离（米）、目标比你高多少米（正数在上方）"""
    a, t = pos(here), pos(target)
    d = math.dist(a, t) * 1000
    if target.get("up"):
        up = sum((x - y) * u for x, y, u in zip(t, a, target["up"])) * 1000
    else:
        up = (math.hypot(*t) - math.hypot(*a)) * 1000
    return d, up


def city_text(
    here: Dict[str, Any],
    target: Dict[str, Any],
    brg: Optional[float] = None,
    arrived: Optional[bool] = None,
) -> str:
    a, t = pos(here), pos(target)
    brg = bearing(a, t) if brg is None else brg
    d, up = city_metrics(here, target)
    if city_arrived(d) if arrived is None else arrived:
        return f"✅ 到了（{d:,.0f} m 内）"
    if d < CITY_NEAR_M:
        out = f"就在附近 {d:,.0f} m"
    elif target.get("up"):
        out = f"{d:,.0f} m"
    else:
        out = f"朝 {deg_text(brg)}°（{compass(brg)}） {d:,.0f} m"
    if up > CITY_FLOOR_M:
        out += f"\n目标在上方 {up:,.0f} 米：找电梯上楼"
    elif up < -CITY_FLOOR_M:
        out += f"\n目标在下方 {-up:,.0f} 米：找电梯下楼"
    return out


NEAR_KINDS = ("医院", "空港", "买船")
NEAR_PREFER = {
    "医院": ("Hospital Check-In", "Clinic Check-In"),
    "空港": ("Fleet Manager Terminal",),
}
NEAR_ALIAS = {"空港": "取船"}
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
SITE_NEAR_M = 6000
_amen: Dict[str, Any] = {}


def amenity_targets(
    kind: str, data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """城外有这类设施的地点（data/place_amenities.json）→ 导航目标"""
    data = data or load()
    rows = cached_json(
        DATA / "place_amenities.json", lambda r: r if isinstance(r, list) else [], []
    )
    pois: Dict[str, Dict[str, Any]] = {}
    for q in data["pois"]:
        pois.setdefault(_norm(q["n"]), q)
    pts = {q["n"]: q for q in data.get("points") or []}
    pts_id = {q["i"]: q for q in data.get("points") or [] if q.get("i")}
    inside = {q.get("city") for q in city_targets(kind)}
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict) or kind not in (r.get("kinds") or []):
            continue
        if str(r.get("rec") or "").lower() in inside:
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
                x, y, z = ref["local"]
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


def city_targets(kind: str) -> List[Dict[str, Any]]:
    """城里这类的点：有能直接办事的（登记处 / 取船终端）就只要这些，没有就这类全部"""
    by_city: Dict[str, List[Dict[str, Any]]] = {}
    alias = NEAR_ALIAS.get(kind, kind)
    for q in city_places():
        if q.get("cat") == kind or alias in (q.get("kinds") or ()):
            by_city.setdefault(q.get("city") or "", []).append(q)
    pref = NEAR_PREFER.get(kind)
    out: List[Dict[str, Any]] = []
    for qs in by_city.values():
        good = [q for q in qs if pref and q["n"] in pref]
        out += good or qs
    return out


def site_at(
    g: Optional[Sequence[float]] = None,
    here: Optional[Dict[str, Any]] = None,
    when: Optional[Any] = None,
    data: Optional[Dict[str, Any]] = None,
    system: str = "",
) -> Optional[Dict[str, Any]]:
    """现在在哪个主城 / 空间站里 → {"site", "zh", "en", "kinds": [这里有的分类]}；不在就 None"""
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
            if q.get("space") and (not system or q.get("sys") == system):
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


def site_nearest(
    site: str,
    kind: str,
    g: Optional[Sequence[float]] = None,
    when: Optional[Any] = None,
    data: Optional[Dict[str, Any]] = None,
    here: Optional[Dict[str, Any]] = None,
) -> List[Tuple[Optional[float], Dict[str, Any]]]:
    """主城 / 空间站里这一类的点，近的在前 → [(距离米或 None, 点)]"""
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


def station_text(
    g: Sequence[float],
    target: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
    when: Optional[Any] = None,
    arrived: Optional[bool] = None,
) -> str:
    """拉格朗日点 / 跳跃点空间站里（星系坐标）：距离 + 上下楼层"""
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


def target_system(p: Dict[str, Any], data: Optional[Dict[str, Any]] = None) -> str:
    data = data or load()
    if is_space(p):
        return p.get("sys") or ""
    b = data["bodies"].get(p.get("b"))
    return b["sys"] if b else ""


def nearest(
    kind: str,
    g: Optional[Sequence[float]] = None,
    system: str = "",
    when: Optional[Any] = None,
    data: Optional[Dict[str, Any]] = None,
    here: Optional[Dict[str, Any]] = None,
) -> List[Tuple[Optional[float], Dict[str, Any]]]:
    """最近的医院 / 空港 / 买船 → [(距离米或 None, 目标)]，近的在前"""
    data = data or load()
    cands = city_targets(kind) + amenity_targets(kind, data)
    site = site_at(g, here, when, data, system)
    if site:
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
        if not same:
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


METRO_MIN_M = 400
METRO_BOARD_M = 25
LINE_ZH = {
    "loop": "微科地铁环线",
    "perim_line_a": "外环 A 线",
    "perim_line_b": "外环 B 线",
    "sp_line": "空港线",
    "com_line": "商业线",
    "cen_line": "中央线",
}
LINE_EN = {
    "loop": "MetroLoop",
    "perim_line_a": "Perimeter Line A",
    "perim_line_b": "Perimeter Line B",
    "sp_line": "Spaceport Line",
    "com_line": "Commerce Line",
    "cen_line": "Central Line",
}


def _metro_lines(city: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """城里的地铁：{线: {站: 站台}}"""
    lines: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for q in city_places():
        if (
            q.get("city") == city
            and q.get("cat") == "地铁"
            and q.get("line")
            and q.get("stop")
        ):
            lines.setdefault(q["line"], {}).setdefault(q["stop"], q)
    return {k: v for k, v in lines.items() if len(v) >= 2}


def _bi(zh: Optional[str], en: Optional[str]) -> str:
    """导航双语：中文（English）"""
    z, e = (zh or "").strip(), (en or "").strip()
    return f"{z}（{e}）" if z and e and z != e else (z or e)


def _line_name(ln: str) -> str:
    return _bi(LINE_ZH.get(ln, ""), LINE_EN.get(ln, ln))


def _stop_name(q: Dict[str, Any]) -> str:
    """站名：「地铁中心（Metro Center）」"""
    zh = q.get("zh") or ""
    zh = zh.replace("地铁站台 · ", "").split("（")[0] if "·" in zh else zh
    en = q["n"].split(" - ", 1)[1] if " - " in q["n"] else q["n"]
    return _bi(zh, en)


def city_route(
    here: Dict[str, Any], target: Dict[str, Any]
) -> Optional[List[Tuple[str, Dict[str, Any], str]]]:
    """城里怎么去：[(动作, 站台, 线)]，动作 walk / ride / transfer；不用坐地铁返回 None"""
    if not is_city(target) or here.get("body") != target.get("b"):
        return None
    lines = _metro_lines(target.get("city") or "")
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
    if walk > direct * 0.8:
        return None
    on = [ln for ln, st in lines.items() if s0["stop"] in st and s1["stop"] in st]
    if on:
        return [
            ("walk", lines[on[0]][s0["stop"]], on[0]),
            ("ride", lines[on[0]][s1["stop"]], on[0]),
        ]
    for la, sa in lines.items():
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


REROUTE_M = 150
REROUTE_RIDE_M = 3000


def city_leg(
    here: Dict[str, Any],
    target: Dict[str, Any],
    plan: Optional[Dict[str, Any]] = None,
    inner: str = "",
) -> Tuple[Dict[str, Any], List[str]]:
    """这一段该去哪：(该指向的点, 步骤文字[]）"""
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
            i += 1
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
    steps = [("→ " if k == i else "   ") + s for k, s in enumerate(steps)]
    return goal, steps


LIFT_BOARD_M = 25
LIFT_SWITCH_M = 8
LIFT_SPOT_M = 10
LIFT_OFF_N = 3
LIFT_WALK_M = 4
LIFT_NEAR_M = 300
LIFT_FAR_M = 3000
HANGAR_LIFT_M = 250


def station_lifts() -> Dict[str, Any]:
    """rr_* 站记录名 → 这个站的区域 / 电梯 / 机库数据"""
    return cached_json(DATA / "station_lifts.json", _lift_rows, {})


def _lift_rows(raw: Any) -> Dict[str, Any]:
    """station_lifts.json → {站: 数据}"""

    def xyz(v: Any) -> bool:
        return (
            isinstance(v, list)
            and len(v) == 3
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)
        )

    def ok(st: Any) -> bool:
        if isinstance(st, dict) and st.get("ok") is False:
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

        def names(d: Any) -> bool:
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


def _zkey(s: Optional[str]) -> str:
    return re.sub(r"[\s_\-]", "", s or "").lower()


ZONE_MARGIN = 0.04


def zone_kind(inner: Optional[str], st: Dict[str, Any]) -> Optional[str]:
    """右上角最里层 Zone 名 → 站里的区域 id；"lift" = 在电梯轿厢里；"hangar" = 在机库里；认不出 None"""
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


def _hangar_size(inner: Optional[str]) -> Optional[str]:
    m = re.search(r"(small|medium|large)", _zkey(inner))
    return m[1].capitalize() if m else None


def _station_points(
    st: Dict[str, Any], site: Optional[str]
) -> List[Tuple[Tuple[float, float, float], str]]:
    """站里已知的点 → [(位置千米, 区域)]"""
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


def _hangar_lift(
    st: Dict[str, Any], a: Sequence[float], size: Optional[str] = None
) -> Optional[Tuple[float, float, float]]:
    hs = [h for h in st["hangars"] if not size or h["size"] == size]
    best = min(hs, key=lambda h: math.dist(a, h["lift"]), default=None)
    return (
        tuple(best["lift"])
        if best and math.dist(a, best["lift"]) * 1000 < HANGAR_LIFT_M
        else None
    )


def _goal(
    target: Dict[str, Any],
    xyz: Sequence[float],
    en: str,
    zh: str,
    tag: str,
) -> Dict[str, Any]:
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


def station_route(
    st: Dict[str, Any],
    a: Sequence[float],
    cur: str,
    dest: str,
    target: Dict[str, Any],
    size: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """从区域 cur 到区域 dest 怎么坐电梯（最多两段）"""
    if cur == dest:
        return []
    t = pos(target)

    def gates(
        stop: Dict[str, Any], ref: Sequence[float]
    ) -> List[Tuple[float, float, float]]:
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
    for _area, path in found:
        legs: Optional[List[Dict[str, Any]]] = []
        ref, prev = a, None
        for ln, on, off in path:
            ga = gates(on, ref)
            if not ga:
                legs = None
                break
            g_on = min(ga, key=lambda g: math.dist(g, ref))
            g_off = min((tuple(g) for g in off["gates"]), key=lambda g: math.dist(g, t))
            board = _goal(target, g_on, ln["en"], ln["zh"], f"{len(legs)}")
            assert legs is not None
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
        if legs is not None:
            cost = (round(math.dist(ref, t), 6), math.dist(a, pos(legs[0]["goal"])))
            if best is None or cost < best[0]:
                best = (cost, legs)
    return best[1] if best else None


def _lift_steps(
    legs: Sequence[Dict[str, Any]], i: int, kind: Optional[str], target: Dict[str, Any]
) -> List[str]:
    rows, cur = [], None
    for k, L in enumerate(legs):
        ln = _bi(L["line"]["zh"], L["line"]["en"])
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


def _car_no(inner: Optional[str]) -> str:
    m = re.search(r"(\S+)\s*$", (inner or "").replace("_", " "))
    return m[1] if m else ""


def _car_changed(a: str, b: str) -> bool:
    if not a or not b:
        return True
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b)) > 2


def station_leg(
    a: Sequence[float],
    target: Dict[str, Any],
    plan: Optional[Dict[str, Any]] = None,
    inner: str = "",
) -> Tuple[Dict[str, Any], List[str]]:
    """空间站里这一段该去哪：(该指向的点, 步骤文字[])"""
    st = station_lifts().get(target.get("city") or "")
    dest = st and st["places"].get(target.get("id") or "")
    plan = {} if plan is None else plan
    if not dest:
        plan.clear()
        return target, []
    pts = _station_points(st, target.get("city"))
    near = min(
        ((math.dist(a, p) * 1000, ar) for p, ar in pts), default=(float("inf"), None)
    )
    if near[0] > LIFT_FAR_M:
        plan.clear()
        return target, []
    kind = zone_kind(inner, st)
    key = (target.get("id") or target["n"], target.get("city"))
    legs = plan.get("legs") if plan.get("key") == key else None

    def near_m(gs: Sequence[Sequence[float]]) -> float:
        return min(math.dist(a, g) for g in gs) * 1000

    def advance(i: int) -> int:
        if kind and kind != "lift":
            plan["out"] = True
        while i < len(legs):
            L = legs[i]
            if L["act"] == "walk":
                d_on = near_m(L["on_gates"])
                if kind is None:
                    nx = (
                        near_m(legs[i + 1]["gates"])
                        if i + 1 < len(legs)
                        else float("inf")
                    )
                    done = d_on < LIFT_WALK_M or (nx < LIFT_BOARD_M and nx < d_on)
                elif kind == "lift":
                    done = d_on < LIFT_SWITCH_M and (
                        plan["out"]
                        or bool(L.get("prev_gates"))
                        and d_on < near_m(L["prev_gates"])
                        and _car_changed(_car_no(inner), plan.get("car", ""))
                    )
                else:
                    done = False
            else:
                d = near_m(L["gates"])
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
            plan["car"] = _car_no(inner)
        return i

    if legs is not None:
        i = advance(plan["i"])
        want = (legs[i]["frm"], legs[i]["to"]) if i < len(legs) else (dest,)
        if kind not in (None, "lift") and kind not in want:
            legs = None
        elif kind is None:
            spot = near[1] if near[0] < LIFT_SPOT_M else None
            if math.dist(a, pos(target)) * 1000 < LIFT_BOARD_M or spot == dest:
                plan["off"] = 0
                plan["arr"] = plan.get("arr", 0) + 1
                if plan["arr"] >= LIFT_OFF_N:
                    i = len(legs)
            elif spot and spot not in {x for L in legs for x in (L["frm"], L["to"])} | {
                dest
            }:
                plan["arr"] = 0
                plan["off"] = plan.get("off", 0) + 1
                if plan["off"] >= LIFT_OFF_N:
                    legs = None
            else:
                plan["off"] = plan["arr"] = 0
        else:
            plan["off"] = plan["arr"] = 0
        if legs is not None:
            plan["i"] = i
    if legs is None:
        if kind == "lift":
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
        plan.update(key=key, legs=legs, i=0, out=True)
        i = plan["i"] = advance(0)
    if not legs:
        return target, []
    if i >= len(legs):
        goal = target
    elif (
        legs[i]["act"] == "ride"
        and kind not in (None, "lift")
        and kind == legs[i]["frm"]
    ):
        goal = legs[i]["board"]
    else:
        goal = legs[i]["goal"]
    return goal, _lift_steps(legs, i, kind, target)
