"""采矿助手、实时读屏与扫描破碎方案业务任务模块（Task: Mining & Scanner）

从 app/services.py 中解耦提取，专职处理：
1. 采矿助手主循环启停控制与配置同步；
2. 实时扫描面板：装配输入，计算在 mining/analysis.py，排版在 app/presenters/mining.py；
3. 采矿激光头与模组配置、自造加成计算与预设管理；
4. 导航记号（Marker Tick）计算与投射、3D 空间站/太空指引与导览日志。
"""

import math
import sys  # noqa: F401
import threading  # noqa: F401
import time
from itertools import combinations
from types import MappingProxyType

# ---------------------------------------------------------------- 依赖（2026-10-30 重构阶段 3：不再经 services 转发）
from ..app.engines.manager import EngineManager
from ..app.hud_state import _hud, _off
from .. import gamedata
from ..app.presenters import mining as _present
from ..mining import analysis as _analysis
from . import goals as _t_goals


def _engines():
    """后台引擎用时才取：导入本模块不创建引擎（架构稿 §4.3 规则 8）"""
    return EngineManager.get_instance()


def settings_key(k, default=None):
    try:
        from ..core import settings

        return settings.load().get(k, default)
    except Exception:
        return default


def _goal_for(*args, **kwargs):
    return _t_goals._goal_for(*args, **kwargs)


def _goal_text(*args, **kwargs):
    return _t_goals._goal_text(*args, **kwargs)


# ---------------------------------------------------------------- 导航记号与 3D HUD 投射
def _mark_hud(data):
    try:
        _hud().marker(data)
    except Exception:  # 测试里的假悬浮窗没有这个接口
        pass


_MK_CFG = {"on": True, "at": 0.0}


def _marker_on():
    """设置里的 nav_marker（两秒读一次，导航每 0.1 秒问一次）"""
    if time.time() - _MK_CFG["at"] > 2:
        _MK_CFG["at"] = time.time()
        try:
            from ..core import settings

            _MK_CFG["on"] = settings.load().get("nav_marker", True) is not False
        except Exception:
            _MK_CFG["on"] = True
    return _MK_CFG["on"]


MARKER_STALE = 4.0  # 右上角多少秒没读到就收起导航记号（城里偶尔几次读不到，1.5 秒就收会一直闪，2026-10-27 实测）


def _marker_tick(target, data, state, shown, ref=None):
    """导航记号（2026-10-27）：每圈先判断该不该显示（还没算出位置、到了、跨星系、1.5 秒没读到、切出游戏、玩家关了、
    采矿助手开着——记号窗口读屏时会被涂黑，会挡住扫描面板和雷达信号），不该显示就收起；
    该显示且右上角有新截图（停着只转镜头也算）就按镜头朝向和视角重算位置。返回这次画的截图时间，收起了返回 None"""
    from ..navigation import navigate as n
    from ..system.showloc import game_foreground

    t, g, info = _engines().pos.current
    h = state.get("here")
    cam = (info or {}).get("camdir")
    try:
        fg = game_foreground()
    except Exception:
        fg = True
    show = (
        h is not None
        and g
        and cam
        and time.time() - t < MARKER_STALE
        and not h.get("arrived")
        and not h.get("far")
        and fg
        and not _engines().live.running()
        and _marker_on()
        and not _off("nav_marker")
    )
    if not show:
        if shown is not None:
            _mark_hud(None)
        return None
    if t == shown:
        return shown
    try:
        from ..navigation.displayinfo import last_fov
        from ..core.perf import game_area

        a = game_area()
        fov = info.get("fov") or last_fov() or 70.0
        tg = n.target_global(target, data, info.get("t"), ref)
        pr = n.project(
            g,
            cam,
            fov,
            tg,
            a["width"],
            a["height"],
            vertical=settings_key("fov_axis", "v") != "h",
        )
        _mark_hud(
            {
                "area": (a["left"], a["top"], a["width"], a["height"]),
                "proj": pr,
                "label": n.dist_text(pr["dist"]),
            }
        )
        return t
    except Exception:
        _mark_hud(None)
        return None


def _nav_log(here, info, view):
    """导航时每次算出新位置记一行（logs/nav_log.txt），方向不对时用来查是哪一步的问题"""
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


def _space_view(g, target, data):
    """导航去太空路标：没有南北，给直线距离、先量子跳到哪、对准哪个标记偏几度"""
    from ..navigation import navigate as n

    s = n.space_guide(g, target, data)
    out = {
        "space": True,
        "same_body": False,
        "inside": False,
        "text": n.space_text(g, target, data),
    }
    if not s["same_system"]:
        out["far"] = (
            f"目标位于 {n.SYS_ZH.get(s['target_system'], s['target_system'])}星系，需先跃迁到该星系"
        )
        return out
    out.update(
        direct=s["direct"], arrived=s["arrived"], aim=s.get("aim"), qt=s.get("qt")
    )
    return out


def _station_view(g, target, data, when=None, prev=None, info=None):
    """拉格朗日点 / 跳跃点空间站里走路：距离按米、按站自己的朝向分上下；转向靠机头那一行和屏幕记号"""
    from ..navigation import navigate as n

    out = {
        "space": True,
        "city": True,
        "station": True,
        "inside": True,
        "same_body": True,
    }
    try:  # 先核对星系：别的星系同一个坐标也可能有东西（二审 2026-10-27）
        system, sure = n.system_info(
            g,
            data,
            **{k: (info or {}).get(k) or "" for k in ("zone", "location", "solar_id")},
        )
    except Exception:
        system, sure = "", False  # noqa: F841
    if (
        target.get("sys") and system and system != target["sys"]
    ):  # 猜出来的星系不一样也不算到（复审 2026-10-27）
        out["far"] = (
            f"目标位于 {n.SYS_ZH.get(target['sys'], target['sys'])}星系，需先跃迁到该星系"
        )
        return out
    tg = n.target_global(target, data, when)
    d = math.dist(g, tg)
    out.update(direct=d / 1000, direct_m=d)
    if d > 50_000:
        out["far"] = (
            f"先前往{target.get('city_zh') or target.get('site_en') or '空间站'}，到站后按步行指引前往"
        )
        return out
    up = sum((t - a) * u for t, a, u in zip(tg, g, target.get("up") or (0, 0, 0)))
    arrived = n.city_arrived(
        d, bool(prev and prev.get("station") and prev.get("arrived"))
    )
    out.update(
        arrived=arrived,
        close=not arrived and d < n.CITY_NEAR_M,
        updown=up,
        text=n.station_text(g, target, data, when, arrived),
    )
    return out


def _nav_view(here, target, data, steady=None, prev=None):
    from ..navigation import navigate as n

    out = {
        "text": n.here_text(here, data),
        "inside": here["inside"],
        "body": n.body_label(here["body"]),
        "same_body": here["inside"] and here["body"] == target["b"],
    }
    if not out["same_body"]:
        out["far"] = (
            f"先前往{target.get('city_zh') or n.body_label(target['b'])}，到达城市后按步行指引前往"
            if n.is_city(target)
            else f"先量子跳跃到 {n.body_label(target['b'])}，再按推荐路线前往"
        )
        return out
    a, t = n.pos(here), n.pos(target)
    out["raw_bearing"] = n.bearing(a, t)
    out["bearing"] = steady(out["raw_bearing"]) if steady else out["raw_bearing"]
    out["compass"] = n.compass(out["bearing"])
    out["surface"] = n.surface_km(a, t, here["radius_km"])
    out["direct"] = n.direct_km(a, t)
    out["height"] = here["height_m"]
    out["target_height"] = n.latlon(t)[2] * 1000 - here["radius_km"] * 1000
    out["lat"], out["lon"] = here["lat"], here["lon"]
    out["arrived"] = out["surface"] < 1
    if n.is_city(target):  # 城里：几米以内才算到，距离按米、加上下楼层（2026-10-27）
        d, up = n.city_metrics(here, target)
        arrived = n.city_arrived(
            d, bool(prev and prev.get("city") and prev.get("arrived"))
        )
        out.update(
            city=True,
            arrived=arrived,
            close=not arrived and d < n.CITY_NEAR_M,
            direct_m=d,
            updown=up,
            near=None,
            station=bool(target.get("up")),
        )  # 绕星球轨道的空间站：不给南北方位
        return out
    near = n.nearby(here, data)
    out["near"] = {"name": n.label(near[1]), "km": near[0]} if near else None
    best = n.approaches(target, data, top=1)
    if best and best[0][1] < out["surface"] * 0.5 and out["surface"] > 30:
        d3q, dsq, brgq, q = best[0]
        out["hint"] = (
            f"距离过远：先量子跳跃到 {n.label(q)}（距目标 {dsq:,.1f} km），再朝 {n.deg_text(brgq)}° 飞行"
        )
    return out


# ---------------------------------------------------------------- 实时读屏与扫描面板解析
def _game_front():
    """游戏窗口在不在最前面：True / False；判断不了（不是 Windows、读不到前台窗口）返回 None——照常识别"""
    from ..system import showloc

    return showloc.game_front()


def _quality_hints(composition):
    from ..crafting.crafting import (
        quality_hints,
    )  # 读不到制造数据只丢提示，不影响扫描结果

    return quality_hints(composition)


def _mat_summary(*args):
    from ..crafting.crafting import mat_summary

    return mat_summary(*args)


def _craft_and_goal_facts(scan, mineral_zh):
    """(制造提示, 可制造矿, 目标缺口, 目标查全了没)。查询中途出错就停在那里，已查到的留着（只丢提示，不影响扫描结果）"""
    hints, mats, targets, complete = (), (), [], False
    try:
        hints = tuple(_quality_hints(scan.composition))
        best = _analysis.best_quality(scan.composition)
        mats = tuple(
            (nm, _mat_summary(nm, qq))
            for nm, qq in best.items()
            if _mat_summary(nm)["count"]
        )
        for nm in best:
            g = _goal_for(nm, mineral_zh(nm))
            if g:
                targets.append((nm, _analysis.freeze(g)))  # 不和目标缓存共用对象
        complete = True
    except Exception:
        pass
    return hints, mats, tuple(targets), complete


def _one_round_facts(scan, mineral_zh):
    """这块石头的制造和目标事实，在一个数据快照里查（架构稿 §6.2）。石头里没有算钱的矿就不查"""
    if not _analysis.minerals_of(scan):
        return (), (), (), False
    try:  # 先等库就绪再钉版本：不然这一轮钉在旧那一代。建库失败只影响制造数据，和以前查询时出错一样不抛出去
        gamedata.ensure()
    except Exception:
        pass
    try:
        with gamedata.snapshot():
            return _craft_and_goal_facts(scan, mineral_zh)
    except (
        Exception
    ):  # 还没建库：制造数据当成没有，目标照查（里面的查询出错不会到这里）
        return _craft_and_goal_facts(scan, mineral_zh)


def collect_inputs(scan):
    """这块石头一轮计算要的外部东西，一次取好（配装、矿价、精炼站、制造提示、目标、时间）"""
    from ..core.i18n import mineral_zh, method_zh, station_zh
    from ..mining import data
    from ..mining.laser import gadget_label, loadout_facts, recommend
    from ..mining.refinery import refined_plan, refined_scu

    hints, mats, targets, complete = _one_round_facts(scan, mineral_zh)
    cities = data.CITY_PRICES  # 只读一次：更新数据会整表替换，中途换了不能新旧混一份
    return _analysis.MiningInputs(
        at=time.strftime("%H:%M:%S"),
        mineral_zh=mineral_zh,
        method_zh=method_zh,
        station_zh=station_zh,
        gadget_label=gadget_label,
        goal_text=_goal_text,
        prices=MappingProxyType({m: data.best_price(m, cities) for m in cities}),
        refineries=MappingProxyType(
            {
                k: (sys_, MappingProxyType(dict(bonus)))
                for k, (sys_, bonus) in data.REFINERIES.items()
            }
        ),
        loadout=loadout_facts(),
        refined_plan=refined_plan,
        refined_scu=refined_scu,
        recommend=recommend,
        craft_hints=hints,
        craft_mats=mats,
        goal_targets=targets,
        goals_complete=complete,
    )


def scan_view(scan, bag, cut=False):
    """一块石头的读屏结果（窗口用）。cut=True：面板被屏幕右边挡住，品质和总 SCU 读不到，只有破碎方案和成分占比"""
    result = _analysis.analyze(scan, bag, collect_inputs(scan), cut=cut)
    out = _present.to_view(result)
    out["hud"], out["hud_rich"] = _present.to_hud(result)
    return out


def live_start():
    live = _engines().live
    if live.start() is None:  # 正在结束 / 正在退出：如实回话
        return {"running": live.running(), "error": "正在结束 / 正在退出，稍后再开"}
    return {"running": True}


def live_stop():
    live = _engines().live
    live.stop()
    return {"running": live.running()}


# ---------------------------------------------------------------- 采矿装备与自造配置
MOD_GROUPS = (
    ("rieger", "提高功率"),
    ("vaux", "提高提取功率"),
    ("focus", "扩大绿区"),
    ("xtr", "扩大绿区"),
    ("torrent", "加快充能"),
    ("deluge", "降低抗性"),
    ("overrun", "降低抗性"),
    ("fltr", "过滤惰性物质"),
)
STAT_ZH = {
    "power": "功率",
    "extract": "提取功率",
    "res": "抗性",
    "instab": "不稳定性",
    "window": "绿区",
    "rate": "充能",
    "filter": "过滤",
}


def _gear_summary(key, lo):
    """一条船当前配置的汇总：同时操作的矿头总功率、满功率能破多重（抗性 30%；使用萨比尔 Sabir 时）。
    和破碎方案同一套公式（laser.evaluate）：在 crew 个矿头的组合里取最强的"""
    from ..mining.laser import HeadSetup, evaluate, active_model, gadget_label

    craft = lo.get("craft") or [None] * len(lo["heads"])
    setups = [HeadSetup(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])]
    model, k = active_model()
    n = max(1, min(lo.get("crew") or 1, len(setups)))
    combos = list(combinations(setups, n))
    best = lambda g: max(  # noqa: E731
        evaluate(list(c), g, 1.0, 30, 0, k=k, model=model).max_mass for c in combos
    )  # noqa: E731
    return {
        "crew": n,
        "power": round(max(sum(h.max_power() for h in c) for c in combos)),
        "mass": round(best(None), -1),
        "mass_gadget": round(best("sabir"), -1),
        "gadget": gadget_label("sabir"),
    }


def _gear(ship=None):
    """配置区要的东西：几条船、每条船现在的配置（每个矿头加上模组后的读数、汇总）、能选的矿头和模组。
    名字一律「中文 English」（2026-10-26 用户定：霍夫斯泰德 Hofstede-S2）"""
    from ..mining.data import SHIPS, HEADS, MODULES, DEFAULT_LOADOUTS, AUTHOR_MOLE
    from ..mining.laser import (
        ship_loadout,
        current_ship,
        clean_loadout,
        HeadSetup,
        _mult,
    )
    from ..core.i18n import gear_label

    def fmt(d, keys):
        return "，".join(f"{STAT_ZH[k]} {d[k]:+g}%" for k in keys if d.get(k))

    from ..mining.laser import craft_slots, craft_mult
    from ..mining.quality import tiers

    def power(k, craft):
        """矿头自己的激光功率（不算模组）：商店买的 → 自造的"""
        m = craft_mult(k, craft)
        return {
            "base": HEADS[k]["pmax"],
            "now": round(HEADS[k]["pmax"] * m),
            "pct": round((m - 1) * 100, 1),
            "craft": bool(craft),
        }

    def card(k, mods, craft):
        """一个矿头装上模组（和自造）后的读数：功率 W，其余是相对没有修正时的变化 %"""
        h = HeadSetup(k, mods, craft)
        pct = lambda m: round((m - 1) * 100)  # noqa: E731
        return {
            "power": round(h.max_power()),
            "base": HEADS[k]["pmax"],
            "stats": {
                "power": pct(h.max_power() / HEADS[k]["pmax"]),
                "res": pct(_mult(HEADS[k]["res"], *h.res_mods())),
                "instab": pct(h.instab_mult()),
                "window": pct(h.window_mult()),
                "rate": pct(h.rate_mult()),
            },
        }

    ships = []
    for key, spec in SHIPS.items():
        _, lo = ship_loadout(key)
        craft = lo.get("craft") or [None] * len(lo["heads"])
        presets = [{"key": "factory", "name": "出厂配置"}]
        if key == "mole":
            presets.append(
                {
                    "key": "author",
                    "name": "作者推荐（2 人）",
                    "loadout": clean_loadout(key, AUTHOR_MOLE),
                }
            )
        ships.append(
            {
                "key": key,
                "name": spec["name"],
                "size": spec["size"],
                "heads": spec["heads"],
                "crew_max": spec["crew_max"],
                "fixed": spec.get("fixed"),
                "loadout": lo,
                "power": [power(k, craft[i]) for i, (k, _) in enumerate(lo["heads"])],
                "cards": [
                    card(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])
                ],
                "summary": _gear_summary(key, lo),
                "presets": presets,
                "is_default": lo == clean_loadout(key, DEFAULT_LOADOUTS[key]),
            }
        )
    heads = [
        {
            "key": k,
            "name": gear_label(h["name"]),
            "en": h["name"],
            "size": h["size"],
            "slots": h["slots"],
            "ship": h.get("ship"),
            "pmax": h["pmax"],
            "desc": f"最大功率 {h['pmax']:,.0f} W｜"
            + (fmt(h, ("res", "instab", "window", "rate")) or "无修正"),
            # 自造时影响激光功率的材料槽，和这种材料的品质档位（选档或者直接填数字）
            "craft": [
                {
                    "slot": s["slot"],
                    "slot_zh": s["slot_zh"],
                    "mat_zh": s["mat_zh"],
                    "segs": [list(x[:4]) for x in s["segs"]],
                    "tiers": [["商店标准", 500]] + [[n, q] for n, q in tiers(s["mat"])],
                }
                for s in craft_slots(k)
            ],
        }
        for k, h in HEADS.items()
    ]
    mods = [
        {
            "key": k,
            "name": gear_label(m["name"]),
            "en": m["name"],
            "desc": fmt(
                m, ("power", "extract", "res", "instab", "window", "rate", "filter")
            ),
            "group": next((g for p, g in MOD_GROUPS if k.startswith(p)), "其他"),
        }
        for k, m in MODULES.items()
    ]
    from ..mining.laser import chosen_ship

    return {
        "ship": current_ship(),
        "chosen": chosen_ship() is not None,
        "ships": ships,
        "heads": heads,
        "modules": mods,
        "groups": list(dict.fromkeys(g for _, g in MOD_GROUPS)),
    }


def mining_gear():
    return _gear()


def set_mining_gear(ship="mole", loadout=None, reset=False):
    """选船 / 保存这条船的配置（reset=True 恢复出厂配置）"""
    from ..core import settings
    from ..mining.data import SHIPS
    from ..mining.laser import clean_loadout

    if ship not in SHIPS:
        raise ValueError("未找到此飞船")
    saved = dict(settings.load().get("mining_loadouts") or {})
    if reset:
        saved.pop(ship, None)
    elif loadout is not None:
        saved[ship] = clean_loadout(ship, loadout)
    settings.update(mining_ship=ship, mining_loadouts=saved)
    _engines().live.config_changed()
    return _gear()


def manual_scan(mass=0, resistance=0, instability=0):
    """手动输入扫描数据：只算破碎方案"""
    import math
    from ..mining.laser import gadget_label, recommend

    mass, resistance, instability = float(mass), float(resistance), float(instability)
    # 质量为 0 时比值是 inf，json 写成 Infinity，前端解析失败只会说「连不上」（2026-10-31 审查）
    if not (math.isfinite(mass) and mass > 0):
        raise ValueError("质量要填大于 0 的数")
    if not (math.isfinite(resistance) and 0 <= resistance <= 100):
        raise ValueError("抗性要填 0 到 100")
    if not (math.isfinite(instability) and instability >= 0):
        raise ValueError("不稳定性要填 0 或更大的数")
    return [
        _present.plan_view(_analysis.plan_facts(p, gadget_label))
        for p in recommend(mass, resistance, instability)
    ]


__all__ = [
    # 常量与状态
    "MARKER_STALE",
    "_MK_CFG",
    "MOD_GROUPS",
    "STAT_ZH",
    # 依赖与辅助
    "_mark_hud",
    "_marker_on",
    "_marker_tick",
    "_nav_log",
    "_space_view",
    "_station_view",
    "_nav_view",
    # 读屏与扫描
    "_game_front",
    "scan_view",
    "live_start",
    "live_stop",
    # 装备与自造配置
    "_gear_summary",
    "_gear",
    "mining_gear",
    "set_mining_gear",
    "manual_scan",
]
