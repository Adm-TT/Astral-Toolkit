"""路标、折跃光环与导航业务任务模块（Task: Navigation & Halo）

专职处理：
1. 地点搜索、最近地点推荐、站点识别与导航路线规划；
2. 实时/手动定位模式切换、雷达信号重命名；
3. 路标增删改查、剪贴板坐标导入与 /showlocation 实时抓取；
4. 小行星带（Aaron Halo）航线计算、断开距离监控与 HUD 联动核对；
5. 原矿扫描记录及导航追溯。
"""

import math
import os  # noqa: F401
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from ..app import bus
from .system.settings import hotkey_conflicts


class _NavLike(Protocol):
    target: Any
    space_mode: bool

    @property
    def session(self) -> Any: ...

    def start(
        self,
        target: Any,
        target_row: Any = None,
        space_mode: bool | None = None,
    ) -> Any: ...

    def stop(self) -> Any: ...

    def refresh(self) -> None: ...

    def add_fix(self, g: Any, clip: Any = None, session: int | None = None) -> Any: ...


class _PosLike(Protocol):
    def snapshot(self) -> Any: ...

    def read_now(self, force: bool = True) -> Any: ...

    def hints(self, max_age: float = 5.0) -> dict[str, str]: ...

    def set_demand(self, key: str, until: float, fps: float | None = None) -> None: ...


class _GameEventsLike(Protocol):
    arrived_at: float


class _ResultsLike(Protocol):
    def get(self, slot: str) -> Any: ...


# ---------------------------------------------------------------- 基础状态与常量
_places = {}

try:
    from ..update.data_pack import CACHE_HOOKS as _CACHE_HOOKS

    _CACHE_HOOKS.append(_places.clear)
except Exception:
    pass

POS_FRESH = 120  # 「用当前位置」：位置最多是多少秒前读到的
_WHERE = {"t": 0.0, "v": None, "tried": 0.0}

_AREA = {"key": None, "v": None}
AREA_MAX_AGE = (
    10  # 位置超过 10 秒没更新就不判断产矿区（不过滤），刚跳跃、读不到时宁可不过滤
)

HERE_WAIT = 90  # 点「用当前位置新建」后等 /showlocation 坐标多少秒
_HERE = {"name": None, "until": 0.0, "thread": None}
_MARKING = {
    "on": False
}  # 热键记路标正在等 /showlocation（只有它会用「新建」填的名字；一键定位、原矿记录不会）

_HALO = {
    "plan": None,
    "sess": 0,
    "seen": None,
    "last": None,
    "ends": None,  # 方案起点、目标的坐标（Gm）：挂上时查好，每秒核对不再碰星图库
    "near": 0.1,  # 离起点多近（Gm）算还在起点：挂上时按路线算
    "jumped": False,  # 挂上以后测到过起跳
    "first": False,  # 这一跳是从起点跳的、断开后还没核对过：下一次带「多飞 / 少飞」的核对在导航日志里标出来
    "logged": None,  # 导航日志上一次记的核对：一样的不再记
    "ev": threading.Event(),
    "lock": threading.Lock(),
}

QT_SPEED = 50_000  # 米/秒：比这快就是在量子跳跃（普通飞行最快一千多米每秒）
LEFT_START = (
    0.1  # Gm：离方案起点这么近算还在起点（普通飞行一千多米每秒，飞 0.1 Gm 要一天多）
)


# ---------------------------------------------------------------- 依赖与辅助
# 2026-10-30 重构阶段 2：悬浮窗从 app.hud_state 拿，引擎和最近结果（ResultStore）由 bootstrap 造好的 NavDeps 当参数传进来（F 段 B5），
# 不再经 services 转发、出错也不再回头找 services 兜底。接口由 app/api/navigation.py 的 ROUTES 注册，不再用 api 装饰器。
from ..app.hud_state import _hud, _note_hud  # noqa: E402


def _hud_set(section, text):
    """悬浮窗写一段字；悬浮窗建不起来（_hud() 是 None）就不写，小行星带、一键定位照常跑（以前直接
    _hud().set 会抛 AttributeError，待做原第 342 行）"""
    h = _hud()
    if h is not None:
        h.set(section, text)


def _hud_clear(section):
    """悬浮窗收起一段字；悬浮窗建不起来就不管"""
    h = _hud()
    if h is not None:
        h.clear(section)


from ..runtime.results import MINING_SCAN  # noqa: E402


@dataclass(frozen=True)
class NavDeps:
    """导航任务要的后台对象（F 段 B5）：导航引擎、位置服务、游戏事件、最近结果。
    bootstrap 造一份，交给接口层（routes）和热键 / 采矿读屏，不经模块级绑定"""

    nav: _NavLike
    pos: _PosLike
    game_events: _GameEventsLike
    results: _ResultsLike


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


def _pos_current(deps: NavDeps) -> Any:
    pos = deps.pos
    snap = getattr(pos, "snapshot", None)
    if callable(snap):
        return getattr(snap(), "current", (0.0, None, None))
    return getattr(pos, "current", (0.0, None, None))


def _pos_latest(deps: NavDeps) -> Any:
    pos = deps.pos
    snap = getattr(pos, "snapshot", None)
    if callable(snap):
        return getattr(snap(), "latest", (0.0, None, None))
    return getattr(pos, "latest", (0.0, None, None))


# ---------------------------------------------------------------- 导航与地点搜索
def _place_row(p):
    from ..navigation.navigate import label, body_label, TYPE_ZH, QT_ZH

    key = f"{p['b']}|{p['t']}|{p.get('id') or p['n']}"  # 城里同名地点靠 id 区分（审查 2026-10-27）
    _places[key] = p
    typ = (
        (p.get("area") or p.get("city_zh") or TYPE_ZH["City"])
        if p["t"] == "City"
        else TYPE_ZH.get(p["t"], p["t"])
    )
    return {
        "key": key,
        "label": label(p),
        "body": body_label(p["b"]),
        "type": typ,
        "qt": QT_ZH.get(p["qt"], "信标未确认"),
        "has_qt": p["qt"] == 1,
        "waypoint": p["t"] == "Waypoint",
        "space": bool(p.get("space")),
        "city": p["t"] == "City",
    }


def nav_search(q=""):
    from ..navigation.navigate import search as s

    hits, total = s(q, limit=30)
    return {"rows": [_place_row(p) for p in hits], "total": total}


def nav_near(deps: NavDeps, /, kind=""):
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    """导航页「医院 / 空港 / 买船」：知道当前位置就直接导航到最近的那个，列表按远近排；
    位置不知道就只列出来让玩家自己挑（2026-10-27 负责人定）"""
    from ..navigation import navigate as n

    if kind not in n.NEAR_KINDS and kind not in n.SITE_KINDS:
        return {"error": "不支持的分类"}
    data = n.load()
    t, g, info = _pos_current(deps)
    info = info or {}
    fresh = bool(g) and time.time() - t < POS_FRESH
    here, system, when, sure = None, "", None, False
    if fresh:
        when = info.get("t")
        try:
            here = n.locate(
                g,
                when=when,
                local=info.get("local"),
                zone=info.get("zone"),
                local_ok=info.get("local_ok"),
            )
            # 星系线索用这份位置自己带的（hints 只给 5 秒内的，可能已经过期）；没把握就只列不自动走（二审 2026-10-27）
            system, sure = n.system_info(
                g,
                data,
                **{k: info.get(k) or "" for k in ("zone", "location", "solar_id")},
            )
        except Exception:
            here = None
        if (
            here and here.get("inside")
        ):  # 站在星球上：星系就是这颗星球的——但右上角明写了别的星系时以它为准（复审 2026-10-27）
            b = data["bodies"].get(here.get("body"))
            if b and (not sure or b["sys"] == system):
                system, sure = b["sys"], True
    site = (
        n.site_at(g, here, when, data, system) if fresh else None
    )  # 站内识别也核对星系（二审 2026-10-27）
    if (
        kind in n.SITE_KINDS and kind not in n.NEAR_KINDS
    ):  # 主城 / 空间站里才有的分类：只找这里的
        if not site:
            return {
                "rows": [],
                "total": 0,
                "started": None,
                "error": "不在主城或空间站内",
            }
        hits = n.site_nearest(
            site["site"], kind, g, when, data, here
        )  # 星系只是猜的：只列出来，不自动开始（复审 2026-10-27）
    else:
        hits = n.nearest(kind, g if fresh else None, system, when, data, here)
    rows = []
    for d, p in hits[:40]:
        r = _place_row(p)
        r["dist"] = d
        if p.get("t") == "City" and p.get("city_zh"):  # 跨城列出来时分得清是哪个城
            r["label"] = f"{p['city_zh']} · {r['label']}"
        rows.append(r)
    if (
        fresh
        and sure
        and rows
        and rows[0]["dist"] is not None
        and n.target_system(hits[0][1], data) == system
    ):
        err = _start_nav(
            deps, _places[rows[0]["key"]]
        )  # 目标行由 _place_row 现算，和手动开始一致
        if err:
            return err
        return {"rows": rows, "total": len(rows), "started": rows[0]["key"]}
    return {"rows": rows, "total": len(rows), "started": None}


def nav_site(deps: NavDeps, /):
    """现在在哪个主城 / 空间站里、这里有哪些分类（导航页那排按钮，2026-10-27）；不在就 site=None"""
    from ..navigation import navigate as n

    t, g, info = _pos_current(deps)
    info = info or {}
    if not g or time.time() - t > POS_FRESH:
        return {"site": None, "all": list(n.SITE_KINDS)}
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
            g, data, **{k: info.get(k) or "" for k in ("zone", "location", "solar_id")}
        )
        s = n.site_at(g, here, info.get("t"), data, system)
    except Exception:
        s = None
    if not s:
        return {"site": None, "all": list(n.SITE_KINDS)}
    name = f"{s['zh']}（{s['en']}）" if s["zh"] and s["zh"] != s["en"] else s["en"]
    return {
        "site": s["site"],
        "name": name,
        "kinds": s["kinds"],
        "all": list(n.SITE_KINDS),
    }


def nav_plan(key=""):
    from ..navigation.navigate import load, latlon, pos, approaches, label, compass

    p = _places.get(key)
    if not p:
        return {"error": "未找到此地点，需重新搜索"}
    from ..core import run_records

    run_records.record(
        "NAV",
        "开始路线规划",
        p.get("t"),  # 只记地点类型：自定义路标名是玩家自己起的，会随 F10 上传
        ui_tag="NAV",
    )
    data = load()
    if p.get("space"):
        from ..navigation.navigate import space_landmarks

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
    if p.get("t") == "City":  # 城里：不给量子跳的参照点（审查 2026-10-27）
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
    from ..app.lifecycle_gate import closing_error

    return closing_error()


def nav_start(deps: NavDeps, /, key=""):
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    p = _places.get(key)
    if not p:
        return {"error": "未找到此地点，需重新搜索"}
    row = _place_row(p)
    err = _start_nav(deps, p, row)
    if err:
        return err
    from ..core import run_records

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
    from ..core import settings

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
    from ..mining.signals import set_my_signature

    try:
        v = int(value)
    except (TypeError, ValueError):
        return {"error": "信号值需为数字"}
    if not 100 <= v <= 10_000_000:
        return {"error": "信号值不对"}
    return {"mine": set_my_signature(v, name)}


def sig_names():
    from ..mining.signals import my_signatures

    return {"mine": my_signatures()}


def nav_stop(deps: NavDeps, /):
    from ..core import run_records

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


# ---------------------------------------------------------------- 路标管理
def waypoints():
    from ..navigation import navigate as n

    data = n.load()
    out = []
    for p in n.waypoints():
        if n.is_space(p):
            out.append(
                {
                    **_place_row(p),
                    "lat": None,
                    "lon": None,
                    "alt": None,
                    "saved": p.get("saved", ""),
                    "name": p["n"],
                    "system": p["sys"],
                }
            )
            continue
        if p["b"] not in data["bodies"]:
            continue
        lat, lon, r = n.latlon(n.pos(p))
        out.append(
            {
                **_place_row(p),
                "lat": lat,
                "lon": lon,
                "alt": r * 1000 - data["bodies"][p["b"]]["r"],
                "saved": p.get("saved", ""),
                "name": p["n"],
            }
        )
    return out


def waypoint_add(
    deps: NavDeps, /, name="", body="", lat=None, lon=None, alt=0.0, here=False
):
    from ..navigation import navigate as n

    data = n.load()
    if not name.strip():
        return {"error": "需填写路标名称"}
    if here:
        # 只用 /showlocation 的坐标（不读右上角）：等你在游戏聊天框自己输入 /showlocation（AT 不替你输入）
        _HERE.update(name=name.strip(), until=time.time() + HERE_WAIT)
        if not _MARKING[
            "on"
        ]:  # 热键记路标已经在等 /showlocation：名字交给它，不另起一份（合并后审查）
            _start_here_watch(deps)
        return {
            "pending": True,
            "message": f"切回游戏在聊天框输入 /showlocation 后回车；{HERE_WAIT} 秒内获取到坐标即保存为「{name.strip()}」",
        }
    else:
        body = n._find_body(body, data) if body else None
        if not body:
            return {"error": "无法识别星球名称"}
        b = data["bodies"][body]
        try:
            g = n.from_latlon(float(lat), float(lon), b["r"] / 1000, float(alt or 0))
        except (TypeError, ValueError):
            return {"error": "纬度、经度需为数字"}
        local = g
    n.add_waypoint(name.strip(), body, local)
    return waypoints()


def waypoint_preview(deps: NavDeps, /, text=""):
    """粘贴框里的 /showlocation 结果 → 认出在哪个星球、经纬度、高度（还没保存）；不是坐标返回 error"""
    from ..navigation import navigate as n

    g = n.parse_clip(text or "")
    if not g:
        return {
            "error": "未找到坐标：需粘贴聊天框中 /showlocation 输出的那一行（Coordinates: x:… y:… z:…）"
        }
    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    if here.get("inside") and here.get("height_m", 0) < _surface_limit(here):
        return {
            "ok": True,
            "space": False,
            "body": here["body"],
            "body_zh": n.body_label(here["body"]),
            "lat": round(here["lat"], 4),
            "lon": round(here["lon"], 4),
            "alt": round(here["height_m"]),
            "desc": f"{n.body_label(here['body'])}，纬度 {here['lat']:.3f}°，经度 {here['lon']:.3f}°"
            + (f"，海拔 {here['height_m']:,.0f} m" if n.height_ok(here) else ""),
        }
    system = n.system_of(g, data, **_hints_near(deps, g))
    return {
        "ok": True,
        "space": True,
        "body": "@" + system,
        "body_zh": n.body_label("@" + system),
        "desc": f"太空：{n.body_label('@' + system)} 星系坐标 {tuple(round(v / 1000, 1) for v in g)} km",
    }


def waypoint_from_text(deps: NavDeps, /, name="", text=""):
    """粘贴 /showlocation 的输出新建路标（星球自动认，名字自己起）"""
    from ..navigation import navigate as n

    if not name.strip():
        return {"error": "需填写路标名称"}
    g = n.parse_clip(text or "")
    if not g:
        return {"error": "未找到坐标：需粘贴聊天框中 /showlocation 输出的那一行"}
    desc = _save_here(deps, name.strip(), g)
    _wp_log(
        f"粘贴新建路标「{name.strip()}」：{tuple(round(v / 1000, 3) for v in g)} km → {desc}"
    )
    bus.publish("waypoints", {"changed": True})
    return {"rows": waypoints(), "desc": desc}


def waypoint_delete(name=""):
    from ..navigation.navigate import delete_waypoint

    delete_waypoint(name)
    return waypoints()


# ---------------------------------------------------------------- 位置与区域感知
def _where_now(deps: NavDeps):
    """玩家现在在星球表面附近（"ground"）还是太空（"space"），不知道返回 None。
    信号值不在飞船矿表里时才用（地面的 3,000 是手采矿，太空的 3,000 是残骸）。
    需要右上角调试信息（r_DisplayInfo 2）；结果记 60 秒，读不到 20 秒内不再试"""
    import re
    from ..navigation import navigate as n

    pos = deps.pos
    now = time.time()
    if now - _WHERE["t"] < 60:
        return _WHERE["v"]
    t, g, info = _pos_latest(deps)
    if not g or now - t > 60:
        if now - _WHERE["tried"] < 20:
            return None
        _WHERE["tried"] = now
        try:
            rd = pos.read_now(force=True)
        except Exception:
            return None
        info = rd.info or {}
        if not info.get("global") or now - rd.ok_at > 5:
            return None
        g = tuple(info["global"])
    info = info or {}
    if re.search(r"asteroid", info.get("location") or "", re.I):
        v = "space"  # 小行星带
    else:
        try:
            here = n.locate(
                g,
                when=info.get("t"),
                local=info.get("local"),
                zone=info.get("zone"),
                local_ok=info.get("local_ok"),
            )
        except Exception:
            return None
        v = (
            "ground"
            if here.get("inside") and here.get("height_m", 1e12) < 50_000
            else "space"
        )
    _WHERE.update(t=now, v=v)
    return v


def _area_now(deps: NavDeps):
    """玩家现在在哪个产矿区（mining_area.area），认不出返回 None。雷达信号只报当地会刷的矿（2026-10-27 用户要求
    「位置和矿种对得上号」）。只用后台 10 秒内读到的位置；星系必须是右上角线索定下的（只靠坐标猜的不算，
    三个星系坐标系重叠，猜错会把真矿判成「不刷」，2026-10-27 补审）。同一次读数只算一次"""
    from ..navigation import navigate as n
    from ..mining import mining_area

    now = time.time()
    t, g, info = _pos_current(deps)
    if not g or now - t > AREA_MAX_AGE:
        return None
    info = info or {}
    key = (
        tuple(g),
        info.get("location"),
        info.get("zone"),
        info.get("solar_id"),
        mining_area.rocks_stamp(),
    )  # 位置或地名、区域、星系编号、石头表变了才重算
    if _AREA["key"] == key:
        return _AREA["v"]
    v = None
    info = info or {}
    try:
        sysname, sure = n.system_info(
            g,
            zone=info.get("zone") or "",
            location=info.get("location") or "",
            solar_id=info.get("solar_id") or "",
        )
        here = n.locate(
            g,
            when=info.get("t"),
            local=info.get("local"),
            zone=info.get("zone"),
            local_ok=info.get("local_ok"),
        )
        body = here.get("body")
        ground = bool(
            here.get("inside")
            and here.get("height_m", 1e12) < 50_000
            and (n.load()["bodies"].get(body) or {}).get("sys") == sysname
        )
        if sure or ground:
            v = mining_area.area(
                g,
                sysname,
                body=body,
                ground=ground,
                location=info.get("location") or "",
                zone=info.get("zone") or "",
            )
    except Exception:
        v = None
    _AREA.update(key=key, v=v)
    return v


# ---------------------------------------------------------------- 热键提示
def fix_key_hint():
    """导航面板上的定位提示：热键能用就说按哪个键，被占用了就说自己输 /showlocation"""
    key = settings_key("fix_key", "")
    bad = [w for w in hotkey_conflicts() if "一键定位" in w]
    if bad:
        return key, bad[0]
    return key, (
        f"一键定位：按 {key} 后在聊天框输入 /showlocation"
        if key
        else "在聊天框输入 /showlocation 定位"
    )


def settings_key(k, default):
    try:
        from ..core import settings

        return settings.load().get(k) or default
    except Exception:
        return default


# ---------------------------------------------------------------- 路标保存与快捷记录
# nav_log.txt 会打进问题反馈包上传：用户目录（C:\Users\<用户名>）换成 ~（审查 2026-10-31）
_HOME_RE = re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+[^\\/:*?\"'<>|\r\n]+", re.I)


def _no_home(msg):
    return _HOME_RE.sub("~", str(msg))


def _wp_log(msg):
    try:
        from ..core import paths

        with open(paths.log("nav_log.txt"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %T')} 路标 {_no_home(msg)}\n")
    except OSError:
        pass


def nav_log(here, info, view):
    """导航时每次算出新位置记一行（logs/nav_log.txt），方向不对时用来查是哪一步的问题
    （目录迁移 R2 从 app/engines/nav 搬来，和 _wp_log 写同一个文件；bootstrap 接进导航线程的 NavLinks.trace）"""
    try:
        from ..core import paths

        p = paths.log("nav_log.txt")
        if p.exists() and p.stat().st_size > 300_000:
            p.write_text(
                "\n".join(p.read_text(encoding="utf-8").splitlines()[-1000:]) + "\n",
                encoding="utf-8",
            )
        loc = info.get("local")
        line = (
            f"{time.strftime('%H:%M:%S')} 来源={here.get('src', '?')} 核对={info.get('local_ok')} "
            f"游戏局部={tuple(round(v, 4) for v in loc) if loc else None} "
            f"用的=({here['x']:.4f}, {here['y']:.4f}, {here['z']:.4f}) "
            f"方位={view.get('raw_bearing', 0):.1f}° 显示={view.get('bearing', 0):.0f}° 距离={view.get('surface', 0):.2f}km"
        )
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _surface_limit(here):
    """离地多高以内算「在星球上」（跟着星球自转记坐标）；再高就当太空，记星系坐标"""
    return max(100_000, here.get("radius_km", 0) * 1000 * 0.25)


def _hints_near(deps: NavDeps, g, km=100):
    """右上角线索（定星系用）只在 g 就是你现在的位置时才可信：粘贴别人给的坐标、事后补存的原矿坐标，
    线索说的是你现在在哪个星系，不是那个坐标在哪个星系（审查 2026-10-31）"""
    pos = deps.pos
    try:
        _, live, _ = _pos_current(deps)
        if live is None or math.dist(live, g) > km * 1000:
            return {}
        return pos.hints()
    except Exception:
        return {}


def _save_here(deps: NavDeps, name, g, info=None, system=None):
    """在 g（/showlocation 给的星系坐标，米）记一个路标：星球上/贴地记星球坐标，太空或高轨道记星系坐标。返回说明。
    只用 /showlocation 的坐标换算，不掺右上角调试信息（也不用从右上角学来的偏差）。
    system = 记录时就定下的星系（原矿记录），不给就现在判断"""
    from ..navigation import navigate as n

    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    if here.get("inside") and here.get("height_m", 0) < _surface_limit(here):
        n.add_waypoint(name, here["body"], n.pos(here))
        desc = n.body_label(here["body"]) + (
            f"，海拔 {here['height_m']:,.0f} m" if n.height_ok(here) else ""
        )
    else:
        system = system or n.system_of(g, data, **_hints_near(deps, g))
        n.add_space_waypoint(name, system, g)
        desc = f"{n.body_label('@' + system)}"
    _wp_log(f"已记下「{name}」：{desc}，坐标 {tuple(round(v, 1) for v in g)}")
    return desc


def _take_here_name():
    """「用当前位置新建」等着的路标名（过期就不算）"""
    if _HERE["name"] and time.time() < _HERE["until"]:
        name, _HERE["name"] = _HERE["name"], None
        return name
    return None


def _saved(name, desc):
    _note_hud("路标", f"📍 已保存：{name}\n{desc}", 6)
    bus.publish("waypoints", {"changed": True})
    from ..core import run_records

    run_records.record("NAV", "保存路标", ui_tag="NAV")


def _start_here_watch(deps: NavDeps):
    """点了「用当前位置新建」：盯剪贴板，你自己打 /showlocation 也能接住"""
    if _HERE["thread"] and _HERE["thread"].is_alive():
        return

    def run():
        from ..navigation.navigate import read_clipboard
        from ..system.showloc import wait_new_coords

        old = read_clipboard()
        while _HERE["name"] and time.time() < _HERE["until"]:
            g, clip = wait_new_coords(old, 1.0)
            if g and _HERE["name"]:
                name = _take_here_name()
                if name:
                    _wp_log(f"剪贴板读到 {clip!r}")
                    try:
                        _saved(name, _save_here(deps, name, g))
                    except Exception as e:  # 路标文件读不到 / 坏了：和 mark_here 一样提示，不让线程悄悄退出（审查 2026-10-31）
                        _note_hud("路标", f"未保存：{e}", 8)
                        _wp_log(f"失败：{e}")
                return
        if _HERE["name"]:
            _HERE["name"] = None
            _note_hud("路标", "未获取到 /showlocation 坐标，路标未保存", 6)
            _wp_log("等 /showlocation 超时")

    _HERE["thread"] = threading.Thread(target=run, daemon=True, name="here-watch")
    _HERE["thread"].start()


def _wait_showloc():
    """等玩家自己在聊天框输入 /showlocation（AT 不替你输入，整改第 4 批）：先在悬浮窗上提示一下"""
    from ..system import showloc

    if (
        not showloc._WAITING.locked()
    ):  # 已经有一份在等：不再挂提示，showlocation 会马上说「已经在等」（合并后审查）
        _note_hud(
            "定位",
            f"请在游戏聊天框输入 /showlocation 后回车（{showloc.TYPE_WAIT} 秒内）",
            showloc.TYPE_WAIT,
        )  # 等多久就挂多久（第 4 批审查）
    g, why = showloc.showlocation(log=_wp_log)
    if g:
        _note_hud(
            "定位", "", 1
        )  # 拿到坐标：提示马上收起，免得以为没定上位（合并后审查）
    return g, why


def mark_here(deps: NavDeps, /):
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    """游戏里按热键：等你在聊天框输入 /showlocation，读剪贴板里的坐标记成路标（AT 不替你输入）。
    点过「用当前位置新建」就用那里填的名字，否则按时间和地点起名"""
    if (
        _HERE["name"]
        and time.time() < _HERE["until"]
        and _HERE["thread"]
        and _HERE["thread"].is_alive()
    ):
        # 「用当前位置新建」已经在盯剪贴板：这里再等一份，输一次 /showlocation 会记成两个路标（第 4 批审查）
        _note_hud(
            "路标",
            f"已经在等你输入 /showlocation（保存为「{_HERE['name']}」），在聊天框输入后回车即可",
            8,
        )
        return {"pending": True}
    _MARKING["on"] = True
    try:
        g, why = _wait_showloc()
    finally:
        _MARKING["on"] = False
    if not g:
        _note_hud("路标", f"未保存：{why}", 8)
        _wp_log(f"失败：{why}")
        return {"error": why}
    name = _take_here_name() or time.strftime("路标 %m-%d %H:%M:%S")
    try:
        desc = _save_here(deps, name, g)
    except Exception as e:  # 路标文件读不到 / 坏了：游戏里也要看得到（二审 2026-10-28）
        _note_hud("路标", f"未保存：{e}", 8)
        _wp_log(f"失败：{e}")
        return {"error": str(e)}
    _saved(name, desc)
    return {"name": name, "where": desc}


# ---------------------------------------------------------------- 原矿记录
def _coord_desc(deps: NavDeps, g):
    """/showlocation 坐标 → 「戴玛，海拔 1,234 m」这种说明（只说明，不记路标）"""
    from ..navigation import navigate as n

    data = n.load()
    here = n.locate(g, data=data, use_offset=False)
    if here.get("inside") and here.get("height_m", 0) < _surface_limit(here):
        return n.body_label(here["body"]) + (
            f"，海拔 {here['height_m']:,.0f} m" if n.height_ok(here) else ""
        )
    return n.body_label("@" + n.system_of(g, data, **_hints_near(deps, g)))


def ore_record(deps: NavDeps, /, here=False):
    """记下最近这块矿。here=True（游戏里按热键）：等玩家自己输 /showlocation，把坐标一起记下；窗口里点的不记坐标"""
    from ..mining import ore_log

    results = deps.results
    entry = results.get(MINING_SCAN)
    view = entry.value if entry else None
    if not view:
        _note_hud("原矿", "暂无扫描结果，先扫描矿石", 5)
        return {"error": "暂无扫描结果，先在游戏中扫描矿石"}
    rec = ore_log.from_view(view)
    where = ""
    if here:
        try:
            g, why = _wait_showloc()
        except Exception as e:
            g, why = None, str(e)
        if g:
            rec["coords"] = [round(v, 1) for v in g]
            try:
                rec["where"] = where = _coord_desc(deps, g)
            except Exception:
                rec["where"] = ""
            try:  # 星系现在就定下（「去这里」可能是换了星系以后才点）
                from ..navigation import navigate as n

                rec["system"] = n.system_of(g, None, **_hints_near(deps, g))
            except Exception:
                pass
        else:
            rec["where_err"] = why or "未获取到坐标"
    try:
        rec = ore_log.add(rec)
    except Exception as e:
        _note_hud("原矿", f"未记录：{e}", 8)
        return {"error": str(e)}
    _note_hud(
        "原矿",
        f"已记录：{rec['rock']}"
        + (f"｜{where}" if where else "｜未获取到坐标" if here else ""),
        5,
    )
    bus.publish("ore_log", {"changed": True})
    return rec


def ore_list():
    from ..mining import ore_log

    rows = list(reversed(ore_log.load()))
    return {"rows": rows, "rocks": sorted({r.get("rock") or "?" for r in rows})}


def ore_delete(id=""):
    from ..mining import ore_log

    rec = ore_log.delete(id)
    if not rec:
        return {"error": "此记录已不存在"}
    bus.publish("ore_log", {"changed": True})
    return rec


def ore_restore(rec=None):
    from ..mining import ore_log

    rec = ore_log.restore(rec)
    bus.publish("ore_log", {"changed": True})
    return rec


def ore_go(deps: NavDeps, /, id=""):
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    """「去这里」：把这条记录的坐标记成路标（同一条只记一次），然后开始导航"""
    from ..mining import ore_log

    rec = next((r for r in ore_log.load() if r.get("id") == id), None)
    if not rec:
        return {"error": "此记录已不存在"}
    if not rec.get("coords"):
        return {"error": "此记录没有坐标"}
    name = rec.get("waypoint")
    rows = {w["name"]: w for w in waypoints()}
    if not name or name not in rows:
        name = f"原矿 {rec.get('rock') or ''} {(rec.get('at') or '')[5:16]}".strip()
        if (
            name in rows
        ):  # 同一分钟记了两块同种矿：同名会覆盖别的记录的路标（审查 2026-10-31）
            name = f"{name} #{(rec.get('id') or '')[:4]}"
        _save_here(deps, name, tuple(rec["coords"]), system=rec.get("system"))
        ore_log.update(id, waypoint=name)
        bus.publish("waypoints", {"changed": True})
        rows = {w["name"]: w for w in waypoints()}
    w = rows.get(name)
    if not w:
        return {"error": "路标保存失败，详情见导航页"}
    r = nav_start(deps, w["key"])
    if r.get("error"):
        return r
    return {"ok": True, "name": name}


# ---------------------------------------------------------------- 小行星带（Aaron Halo）导航与一键定位
def halo_options():
    """小行星带页要的选项：10 条带、出发点、量子引擎、上次选的引擎、悬浮窗上正挂着的方案"""
    from ..navigation import halo

    return {
        "bands": [halo.band_row(r) for r in halo.BANDS],
        "points": [{"key": k, "label": halo.point_zh(k)} for k in halo.points()],
        "qds": [{"name": f"{a} ({b})", "speed": v} for a, b, v in halo.QDS],
        "qd": settings_key("halo_qd", "Atlas (S1)"),
        "plan": _HALO["plan"],
    }


def halo_routes(frm="ARC-L1", band=5, qd=""):
    """从 frm 出发、能在第 band 带断开的所有目标"""
    from ..navigation import halo
    from ..core import settings

    try:
        row = halo.band(band)
    except (TypeError, ValueError):
        return {"error": "带号需为 1–10"}
    pts = halo.points()
    if frm not in pts:
        return {"error": f"未找到出发点 {frm}"}
    if qd:
        settings.update(halo_qd=qd)
    speed = halo.qd_speed(qd or settings_key("halo_qd", "Atlas (S1)"))
    return {
        "from": frm,
        "band": halo.band_row(row),
        "speed": speed,
        "rows": halo.routes(frm, band, speed, pts),
    }


def halo_pin(deps: NavDeps, /, frm="", to="", band=5, qd=""):
    """把这条路线挂到悬浮窗：游戏里看着 HUD 剩余距离断开；断开后按一键定位键（或自己输 /showlocation）核对在不在带里"""
    from ..navigation import halo
    from ..navigation import navigate as n

    pts: dict = {}
    try:
        pts = halo.points()
        r = halo.route(
            frm,
            to,
            band,
            halo.qd_speed(qd or settings_key("halo_qd", "Atlas (S1)")),
            pts=pts,
        )
    except (TypeError, ValueError):
        r = None
    if not r:
        return {"error": "此航线不穿过该带"}
    r["text"] = halo.plan_text(r) + "\n退出量子后自动核对是否在带内"
    ev = threading.Event()
    with _HALO["lock"]:
        _HALO["ev"].set()  # 旧方案的剪贴板监听停掉
        _HALO["sess"] += 1
        sess = _HALO["sess"]
        _HALO.update(
            plan=r,
            last=None,
            ev=ev,
            ends=(pts[frm], pts[to]),
            # 断开点离起点很近的路线（CRU-L2 本身就在带里）：门槛缩到起点到安全窗口那段的一半
            near=min(LEFT_START, (r["total"] - r["early"]) / 2),
            jumped=False,
            first=False,
            logged=None,
        )
        try:
            _HALO["seen"] = n.read_clipboard()  # 挂上之前剪贴板里的旧坐标不算
        except Exception:
            _HALO["seen"] = None
        _hud_set("小行星带", r["text"])
    threading.Thread(
        target=_halo_watch, args=(deps, sess, ev), daemon=True, name="halo"
    ).start()
    _wp_log(f"小行星带方案：{frm} → {to} 第{band}带，剩 {r['dropout']} Gm 断开")
    return r


def halo_unpin():
    with _HALO["lock"]:
        _HALO["ev"].set()
        _HALO["sess"] += 1
        _HALO.update(
            plan=None, last=None, ends=None, jumped=False, first=False, logged=None
        )
        _hud_clear("小行星带")
    return {"ok": True}


def _halo_watch(deps: NavDeps, sess, ev):
    """挂着方案时：读右上角的实时坐标自动核对（每秒一次）；读不到时玩家自己在聊天框输 /showlocation 也能核对
    （/showlocation 只在必要时用，2026-10-27 用户定；太空导航进行中时剪贴板归导航管）"""
    from ..navigation import navigate as n

    nav = deps.nav
    events = deps.game_events
    seen_live, live_at, prev, arr = None, 0.0, None, events.arrived_at
    in_qt = False  # 上一次读数在量子里（每秒几万公里）
    while not ev.is_set():
        try:
            if (
                events.arrived_at != arr
            ):  # 游戏日志说量子到了：马上核对，不用等测速（2026-10-27）
                arr, prev, live_at, in_qt = events.arrived_at, None, 0.0, False
            t, g_live, _ = _pos_current(
                deps
            )  # 每次读到都更新（停着不动也有新的一份），latest 只在坐标变了才换（审查 2026-10-27）
            if g_live and t != seen_live and time.time() - t < 3:
                seen_live = t
                fast = (
                    prev
                    and t > prev[0]
                    and math.dist(g_live, prev[1]) / (t - prev[0]) > QT_SPEED
                )
                # 从慢变快就是起跳了，每次起跳都算：起跳前最后一次读数在方案起点附近，就是从起点跳的那一趟
                if fast and not in_qt:
                    _halo_jump(sess, prev is not None and _near_start(prev[1]))
                in_qt = bool(fast)
                prev = (t, g_live)
                if (
                    not fast and time.time() - live_at >= 1.0
                ):  # 量子途中（每秒几万公里）不核对，等断开
                    live_at = time.time()
                    halo_check(g_live, None, sess)
            clip = n.read_clipboard()
            g = n.parse_clip(clip)
            if g and clip != _HALO["seen"] and not (nav.target and nav.space_mode):
                halo_check(g, clip, sess)
        except Exception:
            pass
        ev.wait(0.3)


def _halo_jump(sess, from_start):
    """挂着方案时测到一次起跳（每次起跳都算）：悬浮窗刷回只剩方案那几行，起跳前、上一跳的核对别冻在上面；
    记下挂上以后跳过了（每秒自动核对这才说「多飞 / 少飞」）；从方案起点跳的这一趟，
    断开后第一次说那句的核对在导航日志里标出来（审查 2026-11-08）"""
    with _HALO["lock"]:
        p = _HALO["plan"]
        if not p or sess != _HALO["sess"]:
            return
        _HALO.update(jumped=True, first=bool(from_start))
        _hud_set("小行星带", p["text"])


def _near_start(g):
    """坐标（米）离方案起点不超过 near（挂方案时按路线算好）"""
    ends = _HALO["ends"]
    return (
        bool(ends) and math.dist(ends[0], [float(v) / 1e9 for v in g]) <= _HALO["near"]
    )


def halo_check(g, clip=None, sess=None):
    """拿到 /showlocation 坐标：离恒星多远、在不在要去的那条带里。
    F9 和剪贴板监听可能拿到同一份坐标：查重、发布在同一把锁里；方案已取下或换了就丢掉"""
    from ..navigation import halo

    with _HALO["lock"]:
        p = _HALO["plan"]
        if not p or (sess is not None and sess != _HALO["sess"]):
            return None
        if clip is not None and clip == _HALO["seen"] and _HALO["last"]:
            return _HALO["last"]
        if clip is not None:
            _HALO["seen"] = clip
        w = halo.where(g)
        w["text"] = halo.where_text(w, p["band"])
        # 比方案的断开点多飞 / 少飞多少：老大实飞量断开后船滑多远（2026-11-08）。在方案起点附近不说；
        # 每秒自动核对还要挂上以后测到过起跳才说（还没跳就说「少飞了」像是玩家错了）；
        # 手动定位（剪贴板、F9）没有实时坐标测起跳，只看离起点多远（审查 2026-11-08）
        target = (_HALO["ends"] or (None, None))[1]
        over, first = None, False
        if target and not _near_start(g) and (clip is not None or _HALO["jumped"]):
            over = halo.overshoot(p, g, {p.get("to"): target})
        if over:
            w["left"], w["over"] = over["left"], over["over"]
            w["text"] += "\n" + over["text"]
            first, _HALO["first"] = _HALO["first"], False
        _HALO["last"] = w
        _hud_set(
            "小行星带", p["text"] + "\n" + w["text"]
        )  # 退出距离、安全区间一直留着（审查 2026-10-27：自动核对不能把它盖掉）
        bus.publish("halo", w)
        # 每秒自动核对：跟上次一样就不再记（审查 2026-11-08）
        log_it = w["text"] != _HALO["logged"]
        _HALO["logged"] = w["text"]
    if log_it:
        mark = "（量子后第一次）" if first else ""
        _wp_log(f"小行星带核对{mark}：{w['text']}".replace("\n", "｜"))
    return w


def fix_here(deps: NavDeps, /):
    """游戏里按一键定位热键：导航去太空路标时，等你输 /showlocation 更新距离和偏离角（AT 不替你输入）；
    挂着小行星带方案时，核对现在在不在那条带里"""
    from ..navigation import navigate as n

    nav = deps.nav
    if (not nav.target or not nav.space_mode) and _HALO["plan"]:
        sess = _HALO["sess"]  # 等坐标期间方案取下或换了，这次结果就作废
        g, clip = _wait_showloc()
        with _HALO["lock"]:
            plan = _HALO["plan"] if _HALO["sess"] == sess else None
            if not g and plan:
                _hud_set("小行星带", plan["text"] + f"\n本次定位失败：{clip}")
        if not g:
            return {"error": clip}
        return halo_check(g, clip, sess) or {
            "error": "小行星带方案已移除或更换，本次定位无效"
        }
    if not nav.target or not nav.space_mode:
        _hud_set("导航", "一键定位仅用于手动定位（可在导航页切换）")
        threading.Timer(
            5, lambda: _hud_clear("导航") if not nav.target else None
        ).start()
        return {"error": "当前未导航到太空路标"}
    sess = nav.session  # 等坐标期间导航结束或换了目标，这次结果就作废
    g, clip = _wait_showloc()
    if not g:
        if nav.session == sess and nav.target:
            _hud_set("导航", f"→ {n.label(nav.target)}\n这次没定位成功：{clip}")
        return {"error": clip}
    return nav.add_fix(g, clip, session=sess) or {
        "error": "导航已结束或目标已更换，本次定位无效"
    }


__all__ = [
    # 状态与常量
    "_places",
    "POS_FRESH",
    "_WHERE",
    "_AREA",
    "AREA_MAX_AGE",
    "HERE_WAIT",
    "_HERE",
    "_HALO",
    "QT_SPEED",
    # 核心函数
    "NavDeps",
    "_place_row",
    "nav_search",
    "nav_near",
    "nav_site",
    "nav_plan",
    "nav_start",
    "nav_mode",
    "sig_name",
    "sig_names",
    "nav_stop",
    "nav_refresh",
    "waypoints",
    "waypoint_add",
    "waypoint_preview",
    "waypoint_from_text",
    "_where_now",
    "_area_now",
    "fix_key_hint",
    "settings_key",
    "_wp_log",
    "_save_here",
    "_take_here_name",
    "_saved",
    "_start_here_watch",
    "mark_here",
    "_coord_desc",
    "ore_record",
    "ore_list",
    "ore_delete",
    "ore_restore",
    "ore_go",
    "halo_options",
    "halo_routes",
    "halo_pin",
    "halo_unpin",
    "_halo_watch",
    "halo_check",
    "fix_here",
    "_surface_limit",
    "waypoint_delete",
]
