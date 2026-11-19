"""地点搜索、站点地点、路线规划、导航开关、信号改名（2026-11-19 从 tasks/navigation.py 按段落拆出来，只搬位置、代码没改）"""

import math
import time
from typing import Any

from .base import NavDeps, POS_FRESH, _places, _pos_current


def _start_error(result: Any) -> dict[str, str] | None:
    status = getattr(result, "status", "started")
    if status == "started":
        return None
    if status == "closing":
        return {"error": "正在退出，稍后再试"}
    return {"error": "导航正在停止，请稍候"}


def _start_nav(
    deps: NavDeps, target: Any, row: Any = None, space_mode: bool | None = None
) -> dict[str, str] | None:
    nav = deps.nav
    if row is None:
        row = _place_row(target)
    return _start_error(nav.start(target, target_row=row, space_mode=space_mode))


# ---------------------------------------------------------------- 导航与地点搜索
def _qt_direct(p):
    """游戏里能直接量子跳跃过去的地点（有信标）：照常显示，不给导航（2026-11-13 负责人定）。
    城里的点、玩家自己的路标不算"""
    return p.get("qt") == 1 and p.get("t") not in ("City", "Waypoint")


QT_DIRECT_MSG = "这个地点游戏里可以直接量子跳跃过去，不用导航"


def _place_row(p):
    from ...navigation.navigate import label, body_label, CITY_ZH, TYPE_ZH, QT_ZH

    if (
        p["t"] == "Site"
    ):  # 搜索并出来的一个主城 / 空间站：点开看各层（nav_site），本身不是导航目标，不进 _places
        return {
            "key": f"{p['b']}|Site|{p['site']}",
            "label": label(p),
            "body": body_label(p["b"]),
            "type": "主城" if p["site"] in CITY_ZH else "空间站",
            "qt": QT_ZH.get(p["qt"], "信标未确认"),
            "has_qt": p["qt"] == 1,
            "qt_direct": False,
            "waypoint": False,
            "space": bool(p.get("space")),
            "city": False,
            "site": p["site"],
            "count": p["count"],
        }
    key = f"{p['b']}|{p['t']}|{p.get('id') or p['n']}"  # 城里同名地点靠 id 区分（审查 2026-10-27）
    _places[key] = p
    if p["t"] == "City":  # 哪个站 · 哪一层（跨站列出来时分得清）
        typ = (
            " · ".join(v for v in (p.get("city_zh"), p.get("area")) if v)
            or TYPE_ZH["City"]
        )
    elif p.get("city"):  # 玩家在站里记的路标：路标 · 哪个站
        typ = " · ".join(
            v for v in (TYPE_ZH.get(p["t"], p["t"]), p.get("city_zh")) if v
        )
    else:
        typ = TYPE_ZH.get(p["t"], p["t"])
    return {
        "key": key,
        "label": label(p),
        "body": body_label(p["b"]),
        "type": typ,
        "qt": QT_ZH.get(p["qt"], "信标未确认"),
        "has_qt": p["qt"] == 1,
        "qt_direct": _qt_direct(p),
        "waypoint": p["t"] == "Waypoint",
        "space": bool(p.get("space")),
        "city": p["t"] == "City" or bool(p.get("city")),
    }


def nav_search(q=""):
    from ...navigation.navigate import search as s

    hits, total = s(q, limit=30, sites=True)
    return {"rows": [_place_row(p) for p in hits], "total": total}


def nav_site(deps: NavDeps, /, site=""):
    """一个主城 / 空间站里的地点，按楼层 / 区域分组（2026-11-13 负责人定，换掉以前那排分类按钮和「最近的」）。
    site 不给 = 人现在在的那个（不在任何站里 → site=None）；给了 = 搜索里点开的那个站。
    人就在这个站里时，并成一条的几个点（三部货运电梯）取离得最近的那个"""
    from ...navigation import navigate as n

    t, g, info = _pos_current(deps)
    info = info or {}
    cur, data, here = None, None, None
    if g and time.time() - t <= POS_FRESH:
        try:
            data = n.load()
            here = n.locate(
                g,
                when=info.get("t"),
                data=data,
                local=info.get("local"),
                zone=info.get("zone"),
                local_ok=info.get("local_ok"),
                record=False,
            )
            system, _sure = n.system_info(
                g,
                data,
                **{k: info.get(k) or "" for k in ("zone", "location", "solar_id")},
            )
            cur = n.site_at(g, here, info.get("t"), data, system)
        except Exception:
            cur = None
    want = site or (cur["site"] if cur else "")
    tree = n.site_tree(want) if want else None
    if not tree:
        return {"error": "未找到这个站点，需重新搜索"} if site else {"site": None}
    at = bool(cur and cur["site"] == want)

    def far(q):
        try:
            return math.dist(
                g, n.target_global(q, data, info.get("t"), (g, here, info.get("t")))
            )
        except Exception:
            return math.inf

    groups = []
    for gr in tree["groups"]:
        rows = []
        for it in gr["items"]:
            pts = it["points"]
            p = min(pts, key=far) if at and len(pts) > 1 else pts[0]
            rows.append(
                {
                    "key": _place_row(p)["key"],
                    "label": it["label"],
                    "kinds": it["kinds"],
                    "n": len(pts),
                }
            )
        groups.append({"name": gr["name"], "rows": rows})
    zh, en = tree["zh"], tree["en"]
    return {
        "site": want,
        "name": f"{zh}（{en}）" if zh and zh != en else en,
        "here": at,
        "groups": groups,
    }


def nav_plan(key=""):
    from ...navigation.navigate import load, latlon, pos, approaches, label, compass

    p = _places.get(key)
    if not p:
        return {"error": "未找到此地点，需重新搜索"}
    from ...core import run_records

    run_records.record(
        "NAV",
        "开始路线规划",
        p.get("t"),  # 只记地点类型：自定义路标名是玩家自己起的，会随 F10 上传
        ui_tag="NAV",
    )
    if _qt_direct(p):  # 量子直达：只显示这个地点，不算路线
        return {**_place_row(p), "routes": []}
    data = load()
    if p.get("space"):
        from ...navigation.navigate import space_landmarks

        t = (p["x"], p["y"], p["z"])
        marks = sorted(
            ((math.dist(m[1], t), m[0]) for m in space_landmarks(p["sys"], data))
        )[:3]
        return {
            **_place_row(p),
            "lat": None,
            "lon": None,
            "alt": None,
            "system": p["sys"],
            "routes": [
                {
                    "kind": "参照点",
                    "name": name,
                    "surface": d,
                    "direct": d,
                    "bearing": None,
                    "compass": "",
                }
                for d, name in marks
            ],
        }
    lat, lon, r = latlon(pos(p))
    b = data["bodies"][p["b"]]
    if p.get("t") == "City" or p.get(
        "city"
    ):  # 城里 / 站里（含玩家在站里记的路标）：不给量子跳的参照点
        return {
            **_place_row(p),
            "city": True,
            "city_zh": p.get("city_zh", ""),
            "area": p.get("area", ""),
            "cat": p.get("cat", ""),
            "lat": lat,
            "lon": lon,
            "alt": r * 1000 - b["r"],
            "routes": [],
        }
    routes = [
        {
            "kind": "轨道标记" if q["t"] == "OM" else "信标",
            "name": label(q),
            "surface": ds,
            "direct": d3,
            "bearing": brg,
            "compass": compass(brg),
        }
        for d3, ds, brg, q in approaches(p, data)
    ]
    return {
        **_place_row(p),
        "lat": lat,
        "lon": lon,
        "alt": r * 1000 - b["r"],
        "routes": routes,
    }


def _rt_b6_closing_error():
    from ...app.lifecycle_gate import closing_error

    return closing_error()


def nav_start(deps: NavDeps, /, key=""):
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    p = _places.get(key)
    if not p:
        return {"error": "未找到此地点，需重新搜索"}
    if _qt_direct(p):
        return {"error": QT_DIRECT_MSG}
    row = _place_row(p)
    err = _start_nav(deps, p, row)
    if err:
        return err
    from ...core import run_records

    run_records.record(
        "NAV",
        "开始导航",
        p.get("t"),  # 只记地点类型：自定义路标名是玩家自己起的，会随 F10 上传
        ui_tag="NAV",
    )
    return {"ok": True}


def nav_mode(deps: NavDeps, /, mode="auto"):
    """导航页的开关：实时定位（ground / auto）/ 手动定位（space，只用 /showlocation）；正在导航就按新方式重新开始"""
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    from ...core import settings

    nav = deps.nav
    if mode not in ("auto", "ground", "space"):
        return {"error": "导航方式仅支持 实时定位 / 手动定位"}
    settings.update(nav_mode=mode)
    t = nav.target
    if t:
        err = _start_nav(deps, t, _place_row(t))
        if err:
            return err
    return {"mode": mode, "space": nav.space_mode if t else None}


def sig_name(value=0, name=""):
    """给雷达信号起名记下（下次认到这个数直接显示）；名字空 = 删掉"""
    from ...mining.signals import set_my_signature

    try:
        v = int(value)
    except (TypeError, ValueError):
        return {"error": "信号值需为数字"}
    if not 100 <= v <= 10_000_000:
        return {"error": "信号值不对"}
    return {"mine": set_my_signature(v, name)}


def sig_names():
    from ...mining.signals import my_signatures

    return {"mine": my_signatures()}


def nav_stop(deps: NavDeps, /):
    from ...core import run_records

    nav = deps.nav
    run_records.record("NAV", "停止导航", ui_tag="NAV")
    att = nav.stop()
    if getattr(att, "timed_out", False):
        return {
            "ok": True,
            "stopping": True,
            "message": "正在停止导航，旧线程还没退出",
        }
    return {"ok": True}


def nav_refresh(deps: NavDeps, /):
    deps.nav.refresh()
    return {"ok": True}
