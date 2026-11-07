"""采矿助手、实时读屏与扫描破碎方案业务任务模块（Task: Mining & Scanner）

专职处理：
1. 采矿助手主循环启停控制与配置同步；
2. 实时扫描面板：装配输入，计算在 mining/analysis.py，排版在 app/presenters/mining.py；
3. 采矿激光头与模组配置、自造加成计算与预设管理；
"""

import sys  # noqa: F401
import threading  # noqa: F401
import time
from itertools import combinations
from types import MappingProxyType
from typing import Any, Protocol

# ---------------------------------------------------------------- 依赖（2026-10-30 重构阶段 3：不再经 services 转发）
from .. import gamedata
from ..app.presenters import mining as _present
from ..mining import analysis as _analysis
from . import goals as _t_goals


class _LiveLike(Protocol):
    """采矿助手实际用到的实时读屏接口（bootstrap 造好，接口层和 F5 热键拿着传进来，F 段 B5）"""

    def start(self) -> int | None: ...

    def stop(self) -> Any: ...

    def running(self) -> bool: ...

    def config_changed(self) -> None: ...

    @property
    def prev_stop_pending(self) -> bool: ...


def _goal_for(*args, **kwargs):
    return _t_goals._goal_for(*args, **kwargs)


def _goal_text(*args, **kwargs):
    return _t_goals._goal_text(*args, **kwargs)


# ---------------------------------------------------------------- 实时读屏与扫描面板解析
def _game_front():
    """游戏窗口在不在最前面：True / False；判断不了（不是 Windows、读不到前台窗口）返回 None——照常识别"""
    from ..system import showloc

    return showloc.game_front()


def _quality_hints(composition):
    from . import crafting as _crafting_uc  # 读不到制造数据只丢提示，不影响扫描结果

    return _crafting_uc.scan_hints(composition)


def _mat_summary(*args):
    from . import crafting as _crafting_uc

    return _crafting_uc.material_summary(*args)


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
    from ..core import settings
    from ..mining.data import focus_keys

    out["hud"], out["hud_rich"] = _present.to_hud(
        result, focus=focus_keys(settings.load().get("mining_focus"))
    )
    return out


def live_start(live: _LiveLike, /):
    from ..app.lifecycle_gate import closing_error

    refused = closing_error()
    if refused:
        return refused
    if live.start() is None:
        if live.prev_stop_pending:  # 停止还没收尾：如实回「正在停止」
            return {"running": live.running(), "error": "正在停止，请稍候"}
        return {"running": live.running(), "error": "正在结束 / 正在退出，稍后再开"}
    return {"running": live.running()}


def live_stop(live: _LiveLike, /):
    attempt = live.stop()
    if attempt.timed_out:
        return {"running": live.running(), "error": "正在停止，旧线程还没退出"}
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
    "cluster": "聚集",
}


def _gear_summary(key, lo):
    """一条船当前配置的汇总：同时操作的矿头总功率、满功率能破多重（抗性 30%；使用萨比尔 Sabir 时）。
    和破碎方案同一套公式（laser.evaluate）：在 crew 个矿头的组合里取最强的"""
    from ..mining.laser import (
        HeadSetup,
        evaluate,
        active_model,
        gadget_label,
        carried_gadgets,
    )

    craft = lo.get("craft") or [None] * len(lo["heads"])
    setups = [HeadSetup(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])]
    model, k = active_model()
    n = max(1, min(lo.get("crew") or 1, len(setups)))
    combos = list(combinations(setups, n))
    best = lambda g: max(  # noqa: E731
        evaluate(list(c), g, 1.0, 30, 0, k=k, model=model).max_mass for c in combos
    )  # noqa: E731
    # 带了的手持工具里挑能破最重的那个（以前固定按萨比尔算）；一样都没带就不显示这一项
    carried = carried_gadgets()
    top = max(carried, key=best) if carried else None
    return {
        "crew": n,
        "power": round(max(sum(h.max_power() for h in c) for c in combos)),
        "mass": round(best(None), -1),
        "mass_gadget": round(best(top), -1) if top else None,
        "gadget": gadget_label(top) if top else "",
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
    from ..mining.laser import chosen_ship, carried_gadgets
    from ..mining.data import GADGETS

    carried = set(carried_gadgets())
    gadgets = [
        {
            "key": k,
            "name": gear_label(str(g["name"])),
            "desc": fmt(g, ("res", "instab", "window", "rate", "cluster")),
            "on": k in carried,
        }
        for k, g in GADGETS.items()
    ]
    return {
        "ship": current_ship(),
        "chosen": chosen_ship() is not None,
        "ships": ships,
        "heads": heads,
        "modules": mods,
        "groups": list(dict.fromkeys(g for _, g in MOD_GROUPS)),
        "gadgets": gadgets,
    }


def mining_gear():
    from ..core import settings
    from ..core.i18n import mineral_zh
    from ..mining.data import SIGNATURES, focus_keys

    out = _gear()
    focus = focus_keys(settings.load().get("mining_focus"))
    out["focus"] = [
        {"key": key, "name": mineral_zh(key), "on": focus is None or key in focus}
        for key in SIGNATURES
    ]
    return out


def _save_settings(**kw):
    """存采矿的设置：没存上（设置文件暂时读不到、写不进去）返回给窗口的那句话，存上了返回 None。
    以前不看存没存上：页面说「已保存」，悬浮窗和下次读到的却还是旧的（审查 2026-11-08）"""
    from ..core import settings

    try:
        settings.update_checked(**kw)
    except settings.NotSaved as e:
        return str(e)
    except OSError:
        return settings.NOT_WRITTEN
    return None


def set_mining_focus(live: _LiveLike, /, keys=None):
    """关注列表只过滤悬浮窗；None 恢复全部，空列表不显示矿物。"""
    from ..mining.data import SIGNATURES

    if keys is not None:
        if not isinstance(keys, list) or any(
            not isinstance(key, str) or key not in SIGNATURES for key in keys
        ):
            raise ValueError("关注的矿要从列表中选择")
        keys = [key for key in SIGNATURES if key in keys]
    err = _save_settings(mining_focus=keys)
    if err:
        return {"error": err}
    live.config_changed()
    return mining_gear()


def set_mining_gear(live: _LiveLike, /, ship="mole", loadout=None, reset=False):
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
    err = _save_settings(mining_ship=ship, mining_loadouts=saved)
    if err:
        return {"error": err}
    live.config_changed()
    return mining_gear()


def set_mining_gadgets(live: _LiveLike, /, keys=None):
    """带了哪些手持工具（列表；空列表 = 一样都不带，破碎方案只给不贴的）"""
    from ..mining.data import GADGETS

    if not isinstance(keys, list):
        raise ValueError("手持工具要给一个列表")
    want = {str(k) for k in keys}
    bad = want - set(GADGETS)
    if bad:
        raise ValueError(f"没有这种手持工具：{'、'.join(sorted(bad))}")
    err = _save_settings(mining_gadgets=[k for k in GADGETS if k in want])
    if err:
        return {"error": err}
    live.config_changed()
    return mining_gear()


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
    "MOD_GROUPS",
    "STAT_ZH",
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
