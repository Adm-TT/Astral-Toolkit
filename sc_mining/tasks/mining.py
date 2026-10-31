"""采矿助手、实时读屏与扫描破碎方案业务任务模块（Task: Mining & Scanner）

从 app/services.py 中解耦提取，专职处理：
1. 采矿助手主循环启停控制与配置同步；
2. 实时扫描面板解析、成分分档计算（_lots）、HUD 结构化排版与破碎方案推荐；
3. 采矿激光头与模组配置、自造加成计算与预设管理；
4. 导航记号（Marker Tick）计算与投射、3D 空间站/太空指引与导览日志。
"""
import math
import sys
import threading
import time
from collections import defaultdict
from itertools import combinations

# ---------------------------------------------------------------- 依赖（2026-10-30 重构阶段 3：不再经 services 转发）
from ..app.engines.manager import EngineManager
from ..app.hud_state import _hud, _off
from . import goals as _t_goals

_pos = EngineManager.get_instance().pos
_live = EngineManager.get_instance().live


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
    except Exception:            # 测试里的假悬浮窗没有这个接口
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


MARKER_STALE = 4.0         # 右上角多少秒没读到就收起导航记号（城里偶尔几次读不到，1.5 秒就收会一直闪，2026-10-27 实测）


def _marker_tick(target, data, state, shown, ref=None):
    """导航记号（2026-10-27）：每圈先判断该不该显示（还没算出位置、到了、跨星系、1.5 秒没读到、切出游戏、玩家关了、
    采矿助手开着——记号窗口读屏时会被涂黑，会挡住扫描面板和雷达信号），不该显示就收起；
    该显示且右上角有新截图（停着只转镜头也算）就按镜头朝向和视角重算位置。返回这次画的截图时间，收起了返回 None"""
    from ..navigation import navigate as n
    from ..system.showloc import game_foreground
    t, g, info = _pos.current
    h = state.get("here")
    cam = (info or {}).get("camdir")
    try:
        fg = game_foreground()
    except Exception:
        fg = True
    show = (h is not None and g and cam and time.time() - t < MARKER_STALE and not h.get("arrived") and not h.get("far")
            and fg and not _live.running() and _marker_on() and not _off("nav_marker"))
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
        pr = n.project(g, cam, fov, tg, a["width"], a["height"], vertical=settings_key("fov_axis", "v") != "h")
        _mark_hud({"area": (a["left"], a["top"], a["width"], a["height"]), "proj": pr, "label": n.dist_text(pr["dist"])})
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
            p.write_text("\n".join(p.read_text(encoding="utf-8").splitlines()[-1000:]) + "\n", encoding="utf-8")
        loc = info.get("local")
        line = (f"{time.strftime('%H:%M:%S')} 来源={here.get('src', '?')} 核对={info.get('local_ok')} "
                f"游戏局部={tuple(round(v, 4) for v in loc) if loc else None} "
                f"用的=({here['x']:.4f}, {here['y']:.4f}, {here['z']:.4f}) "
                f"方位={view.get('raw_bearing', 0):.1f}° 显示={view.get('bearing', 0):.0f}° 距离={view.get('surface', 0):.2f}km")
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _space_view(g, target, data):
    """导航去太空路标：没有南北，给直线距离、先量子跳到哪、对准哪个标记偏几度"""
    from ..navigation import navigate as n
    s = n.space_guide(g, target, data)
    out = {"space": True, "same_body": False, "inside": False, "text": n.space_text(g, target, data)}
    if not s["same_system"]:
        out["far"] = f"目标位于 {n.SYS_ZH.get(s['target_system'], s['target_system'])}星系，需先跃迁到该星系"
        return out
    out.update(direct=s["direct"], arrived=s["arrived"], aim=s.get("aim"), qt=s.get("qt"))
    return out


def _station_view(g, target, data, when=None, prev=None, info=None):
    """拉格朗日点 / 跳跃点空间站里走路：距离按米、按站自己的朝向分上下；转向靠机头那一行和屏幕记号"""
    from ..navigation import navigate as n
    out = {"space": True, "city": True, "station": True, "inside": True, "same_body": True}
    try:                                                   # 先核对星系：别的星系同一个坐标也可能有东西（二审 2026-10-27）
        system, sure = n.system_info(g, data, **{k: (info or {}).get(k) or "" for k in ("zone", "location", "solar_id")})
    except Exception:
        system, sure = "", False
    if target.get("sys") and system and system != target["sys"]:   # 猜出来的星系不一样也不算到（复审 2026-10-27）
        out["far"] = f"目标位于 {n.SYS_ZH.get(target['sys'], target['sys'])}星系，需先跃迁到该星系"
        return out
    tg = n.target_global(target, data, when)
    d = math.dist(g, tg)
    out.update(direct=d / 1000, direct_m=d)
    if d > 50_000:
        out["far"] = f"先前往{target.get('city_zh') or target.get('site_en') or '空间站'}，到站后按步行指引前往"
        return out
    up = sum((t - a) * u for t, a, u in zip(tg, g, target.get("up") or (0, 0, 0)))
    arrived = n.city_arrived(d, bool(prev and prev.get("station") and prev.get("arrived")))
    out.update(arrived=arrived, close=not arrived and d < n.CITY_NEAR_M, updown=up,
               text=n.station_text(g, target, data, when, arrived))
    return out


def _nav_view(here, target, data, steady=None, prev=None):
    from ..navigation import navigate as n
    out = {"text": n.here_text(here, data), "inside": here["inside"], "body": n.body_label(here["body"]),
           "same_body": here["inside"] and here["body"] == target["b"]}
    if not out["same_body"]:
        out["far"] = (f"先前往{target.get('city_zh') or n.body_label(target['b'])}，到达城市后按步行指引前往" if n.is_city(target)
                      else f"先量子跳跃到 {n.body_label(target['b'])}，再按推荐路线前往")
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
    if n.is_city(target):                         # 城里：几米以内才算到，距离按米、加上下楼层（2026-10-27）
        d, up = n.city_metrics(here, target)
        arrived = n.city_arrived(d, bool(prev and prev.get("city") and prev.get("arrived")))
        out.update(city=True, arrived=arrived, close=not arrived and d < n.CITY_NEAR_M, direct_m=d, updown=up, near=None,
                   station=bool(target.get("up")))      # 绕星球轨道的空间站：不给南北方位
        return out
    near = n.nearby(here, data)
    out["near"] = {"name": n.label(near[1]), "km": near[0]} if near else None
    best = n.approaches(target, data, top=1)
    if best and best[0][1] < out["surface"] * 0.5 and out["surface"] > 30:
        d3q, dsq, brgq, q = best[0]
        out["hint"] = f"距离过远：先量子跳跃到 {n.label(q)}（距目标 {dsq:,.1f} km），再朝 {n.deg_text(brgq)}° 飞行"
    return out


# ---------------------------------------------------------------- 实时读屏与扫描面板解析
def _game_front():
    """游戏窗口在不在最前面：True / False；判断不了（不是 Windows、读不到前台窗口）返回 None——照常识别"""
    from ..system import showloc
    return showloc.game_front()


def scu_text(v):
    """精炼后的量：1 SCU 以上写 SCU，不到 1 SCU 写 uSCU（1 SCU = 1,000,000 uSCU）；两种都给"""
    if v >= 1:
        return f"{v:,.2f} SCU（{v * 1e6:,.0f} uSCU）"
    return f"{v * 1e6:,.0f} uSCU（{v:.3f} SCU）"


def _station_bonus(station, minerals):
    """精炼站对这块石头里的矿的加成：只有一种值钱的矿写「+3%」，几种不一样就写「铁 +3%、金 -2%」，都是 0 返回空"""
    from ..mining.data import REFINERIES, best_price
    from ..core.i18n import mineral_zh
    bonus = REFINERIES.get(station, ("", {}))[1]
    worth = sorted(minerals, key=lambda m: -(minerals[m] * (best_price(m)[0] or 0)))
    worth = [m for m in worth if (best_price(m)[0] or 0) > 0] or worth
    vals = {m: bonus.get(m, 0) for m in worth}
    if not any(vals.values()):
        return ""
    if len(set(vals.values())) == 1:
        return f"{next(iter(vals.values())):+g}%"         # :+g：UEX 给小数加成时 :+d 会抛错、连崩 3 次关掉采矿助手
    return "、".join(f"{mineral_zh(m)} {v:+g}%" for m, v in vals.items() if v)


def _lots(scan, plan=None):
    """成分表（1.6.42）：石头里的每一份（矿 × 品质、惰性物质）一行。同一种矿有几种品质时标「高品质 / 低品质」；
    品质写上这种矿的第几档（quality.py，4.8 起每种矿只有 7 档）。plan = (精炼方式, 站点)：按它算这一份精炼后多少。
    精炼保留品质、不同品质精炼完还是分开的两份（expcarry、scopique、The Impound），所以按份算"""
    total = scan.total_scu
    from ..core.i18n import mineral_zh
    from ..mining.quality import tier_of
    from ..mining.refinery import refined_scu, INERT
    groups = defaultdict(list)
    for i, (n, p, q) in enumerate(scan.composition):
        if n and n != INERT:
            groups[n].append(i)
    rank = {}
    for n, idx in groups.items():
        qs = [scan.composition[i][2] for i in idx]
        if len(idx) < 2 or None in qs or len(set(qs)) < 2:
            continue
        order = sorted(idx, key=lambda i: scan.composition[i][2])
        for k, i in enumerate(order):
            rank[i] = "低品质" if k == 0 else "高品质" if k == len(order) - 1 else "中等品质"
    rows = []
    for i, (n, p, q) in enumerate(scan.composition):
        inert = n == INERT
        scu = total * p / 100 if total else None
        row = {"en": n or "", "zh": "惰性物质" if inert else (mineral_zh(n) if n else "?"), "pct": p,
               "scu": round(scu, 4) if scu is not None else None, "q": None if inert else q, "tier": "",
               "rank": rank.get(i, ""), "inert": inert, "refined": None, "refined_text": ""}
        t = tier_of(n, q) if (n and not inert and q is not None) else None
        if t:
            row["tier"] = "完美" if t[0] == "完美" else f"{t[0]} 档" + ("（最低）" if t[1] == 1 else "（最高）" if t[1] == t[2] else "")
        if inert:
            row["refined_text"] = "无精炼产出，仅占用矿袋"
        elif plan and scu is not None and n:
            v = refined_scu({n: scu}, plan[1], plan[0]).get(n, 0.0)
            row["refined"] = round(v, 6)
            row["refined_text"] = scu_text(v)
        rows.append(row)
    return rows


def _lots_hud(lots):
    """悬浮窗一行：「惰性 31%｜钨 662 那份 3.07 SCU」（同一种矿有高低两种品质时写高品质那份）；没什么可说返回空"""
    parts = []
    inert = sum(r["pct"] for r in lots if r["inert"])
    if inert >= 0.5:
        parts.append(f"惰性 {inert:.0f}%")
    for r in lots:
        if r["rank"] == "高品质":
            low = [x["q"] for x in lots if x["en"] == r["en"] and x["rank"] == "低品质"]
            parts.append(f"{r['zh']} 品质 {r['q']}：{r['scu']:.2f} SCU" if r["scu"] is not None
                         else f"{r['zh']} 品质 {r['q']}/{low[0] if low else '?'}")
    return "｜".join(parts)


def scan_view(scan, bag, cut=False):
    """一块石头的读屏结果（窗口用）。cut=True：面板被屏幕右边挡住，品质和总 SCU 读不到，只有破碎方案和成分占比"""
    from ..core.i18n import mineral_zh, method_zh, station_zh
    from ..mining.laser import recommend
    from ..mining.data import best_price, GADGETS
    from ..mining.refinery import refined_plan
    rock = mineral_zh(scan.main_mineral) if scan.main_mineral else "?"
    out = {"rock": rock, "mass": scan.mass, "resistance": scan.resistance, "instability": scan.instability,
           "difficulty": scan.difficulty or "", "minerals": [], "refine": [], "sell": [], "craft": [], "craft_mats": [], "goal": [], "plans": [],
           "total_scu": scan.total_scu, "lots": [], "lots_plan": "", "cut": bool(cut), "note": "",
           "at": time.strftime("%H:%M:%S")}
    hud = [f"{rock}｜{scan.mass:,.0f} kg｜抗性 {scan.resistance:g}%｜不稳定 {scan.instability:g}"]
    # 1.6.64：悬浮窗按层次排（审查意见）：矿名 → 关键读数 → 怎么碎 → 收益 → 次要详情；文字版 hud 还给窗口右侧用
    # 1.6.65 照用户给的样图：矿名、三格读数、矿物组成（每种矿下面列各品质、占整石）、开采建议、精炼产量和净值、次要
    rich = {"title": rock, "stats": [["质量", f"{scan.mass:,.0f}", "kg"], ["抗性", f"{scan.resistance:g}", "%"],
                                     ["不稳定性", f"{scan.instability:g}", ""]], "comp": [], "advice": None, "gain": [], "minor": [], "foot": ""}
    if cut:
        out["note"] = ("扫描面板右侧被屏幕边缘遮挡，无法识别品质和总 SCU：仅计算破碎方案和成分占比。"
                       "在游戏设置中调大「FOV视野」使面板完整显示后，可计算精炼收益和价格。")
        hud.append("面板被遮挡：仅计算破碎方案")
        rich["minor"].append("面板被遮挡：仅计算破碎方案")
    minerals = {k: v for k, v in scan.minerals_scu().items() if k not in ("Inert Materials", "?")}
    out["minerals"] = [{"name": mineral_zh(k), "en": k, "scu": v} for k, v in minerals.items()]
    first = None
    if minerals:
        for i, (method, station, value, rscu, fee, hours) in enumerate(refined_plan(minerals)):
            bonus = _station_bonus(station, minerals)
            from ..mining.refinery import refined_scu
            per = refined_scu(minerals, station, method)
            out["refine"].append({"method": method_zh(method), "station": station_zh(station), "value": value,
                                  "scu": rscu, "fee": fee, "hours": hours, "bonus": bonus, "amount": scu_text(rscu),
                                  "yield": [{"zh": mineral_zh(k), "amount": scu_text(v)} for k, v in per.items() if v > 0]})
            if i == 0:
                first = (method, station)
                out["lots_plan"] = f"{method_zh(method)}，{station_zh(station)}"
                hud.append(f"精炼后 {scu_text(rscu)}，价值 {value:,.0f} aUEC（建议：{method_zh(method)}，{station_zh(station)}精炼"
                           + (f" {bonus}" if bonus else "") + "）")
                rich["gain"] = [["预计精炼产量", f"{rscu:,.2f}", "SCU"], ["价格", f"{value:,.0f}", "aUEC"]]
                rich["minor"].append(f"{method_zh(method)} · {station_zh(station)}" + (f" {bonus}" if bonus else ""))
                rich["foot"] = "精炼结果为估算"
        out["sell"] = [{"name": mineral_zh(k), "where": best_price(k)[1] or "无收购"} for k in minerals]
    out["lots"] = _lots(scan, first)
    if out["refine"]:          # 精炼后按品质分开写：「钨 662 有 1.50 SCU、钨 363 有 5.74 SCU」
        out["refine"][0]["lots"] = [{"zh": r["zh"], "q": r["q"], "amount": r["refined_text"]}
                                    for r in out["lots"] if not r["inert"] and r["refined"]]
    line = _lots_hud(out["lots"])
    if line:
        hud.append(line)
    groups = {}                                                # 矿物组成：同一种矿合在一起，下面列各品质（高品质那份标蓝）
    for row in out["lots"]:                                    # 占比照游戏里的两位小数写
        key = "惰性物质" if row["inert"] else row["zh"]
        g = groups.setdefault(key, {"name": key, "inert": row["inert"], "pct_n": 0.0, "subs": []})
        g["pct_n"] += row["pct"] or 0
        if not row["inert"]:                                  # 品质没认出来写「未知」，单独一份，不混进别的品质
            g["subs"].append({"q": "未知" if row["q"] is None else str(row["q"]), "pct": f"{row['pct'] or 0:.2f}%",
                              "hi": row["rank"] == "高品质", "n": row["pct"] or 0})
    for g in groups.values():
        g["subs"].sort(key=lambda x: -int(x["q"]) if x["q"].isdigit() else 1)
        g["pct"] = f"{g.pop('pct_n'):.2f}%"                  # 1.6.70（用户）：游戏里读到多少写多少，不四舍五入
        for x in g["subs"]:
            x.pop("n", None)
    rich["comp"] = sorted(groups.values(), key=lambda g: (g["inert"], -float(g["pct"][:-1] or 0)))
    if minerals:
        try:
            from ..crafting.crafting import quality_hints
            out["craft"] = list(quality_hints(scan.composition))
            from ..crafting.crafting import mat_summary
            best = {}
            for nm, pct, qq in scan.composition:
                if nm and nm not in ("Inert Materials", "?"):
                    best[nm] = max(best.get(nm) or 0, qq or 0) if qq is not None else best.get(nm)
            out["craft_mats"] = [{"en": nm, "zh": mineral_zh(nm), "q": qq, **mat_summary(nm, qq)}
                                 for nm, qq in best.items() if mat_summary(nm)["count"]]
            for nm, qq in best.items():                       # 目标还缺这种矿：窗口和悬浮窗都标出来（有品质门槛的按每一份判断）
                g = _goal_for(nm, mineral_zh(nm))
                if g:
                    lots = [r for r in out["lots"] if r["en"] == nm]
                    ok = any((r["q"] or 0) >= g["minq"] for r in lots) if g["minq"] > 1 else True
                    out["goal"].append({"en": nm, "zh": g["zh"] or mineral_zh(nm), "short": g["short"], "unit": g["unit"],
                                        "minq": g["minq"], "q": qq, "ok": ok, "goals": g["goals"], "text": _goal_text(g, qq, lots)})
            hud += [x["text"] for x in out["goal"][:2]]
            rich["minor"] += [x["text"] for x in out["goal"][:2]]
        except Exception:
            pass
    plans = recommend(scan.mass, scan.resistance, scan.instability)
    for p in plans:
        out["plans"].append({"heads": p.names, "short": p.short(), "summary": p.summary(),
                             "ratio": p.ratio, "breakable": p.breakable, "comfortable": p.comfortable,
                             "throttle": p.throttle if p.breakable else None})
    if plans:
        hud.insert(1, plans[0].short())
        p0 = plans[0]
        from ..mining.laser import gadget_label
        heads = p0.names + (f" + {gadget_label(p0.gadget)}" if p0.gadget else "")
        rich["advice"] = {"heads": heads, "power": f"建议功率 {p0.throttle * 100:.0f}%" if p0.breakable else "满功率也无法破碎"}
    contents, used, cap = bag
    out["bag"] = None
    out["bag_text"] = ""
    if used is not None:
        out["bag"] = {"used": used, "cap": cap, "items": [{"name": mineral_zh(k), "scu": v} for k, v in contents.items()]}
        out["bag_text"] = f"{used:g}/{cap:g} SCU\n" + "，".join(f"{mineral_zh(k)} {v:g}" for k, v in contents.items())
    out["hud"] = "\n".join(hud)
    out["hud_rich"] = rich
    return out


def live_start():
    from ..core import settings
    _live.start()
    settings.update(live_on=True)          # 记住：重启、升级后自动接着扫
    return {"running": True}


def live_stop():
    from ..core import settings
    _live.stop()
    settings.update(live_on=False)
    return {"running": False}


# ---------------------------------------------------------------- 采矿装备与自造配置
MOD_GROUPS = (("rieger", "提高功率"), ("vaux", "提高提取功率"), ("focus", "扩大绿区"), ("xtr", "扩大绿区"),
              ("torrent", "加快充能"), ("deluge", "降低抗性"), ("overrun", "降低抗性"), ("fltr", "过滤惰性物质"))
STAT_ZH = {"power": "功率", "extract": "提取功率", "res": "抗性", "instab": "不稳定性", "window": "绿区", "rate": "充能",
           "filter": "过滤"}


def _gear_summary(key, lo):
    """一条船当前配置的汇总：同时操作的矿头总功率、满功率能破多重（抗性 30%；使用萨比尔 Sabir 时）。
    和破碎方案同一套公式（laser.evaluate）：在 crew 个矿头的组合里取最强的"""
    from ..mining.laser import HeadSetup, evaluate, active_model, gadget_label
    craft = lo.get("craft") or [None] * len(lo["heads"])
    setups = [HeadSetup(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])]
    model, k = active_model()
    n = max(1, min(lo.get("crew") or 1, len(setups)))
    combos = list(combinations(setups, n))
    best = lambda g: max(evaluate(list(c), g, 1.0, 30, 0, k=k, model=model).max_mass for c in combos)
    return {"crew": n, "power": round(max(sum(h.max_power() for h in c) for c in combos)),
            "mass": round(best(None), -1), "mass_gadget": round(best("sabir"), -1), "gadget": gadget_label("sabir")}


def _gear(ship=None):
    """配置区要的东西：几条船、每条船现在的配置（每个矿头加上模组后的读数、汇总）、能选的矿头和模组。
    名字一律「中文 English」（2026-10-26 用户定：霍夫斯泰德 Hofstede-S2）"""
    from ..mining.data import SHIPS, HEADS, MODULES, DEFAULT_LOADOUTS, AUTHOR_MOLE
    from ..mining.laser import ship_loadout, current_ship, clean_loadout, HeadSetup, _mult
    from ..core.i18n import gear_label

    def fmt(d, keys):
        return "，".join(f"{STAT_ZH[k]} {d[k]:+g}%" for k in keys if d.get(k))

    from ..mining.laser import craft_slots, craft_mult
    from ..mining.quality import tiers

    def power(k, craft):
        """矿头自己的激光功率（不算模组）：商店买的 → 自造的"""
        m = craft_mult(k, craft)
        return {"base": HEADS[k]["pmax"], "now": round(HEADS[k]["pmax"] * m), "pct": round((m - 1) * 100, 1), "craft": bool(craft)}

    def card(k, mods, craft):
        """一个矿头装上模组（和自造）后的读数：功率 W，其余是相对没有修正时的变化 %"""
        h = HeadSetup(k, mods, craft)
        pct = lambda m: round((m - 1) * 100)
        return {"power": round(h.max_power()), "base": HEADS[k]["pmax"],
                "stats": {"power": pct(h.max_power() / HEADS[k]["pmax"]),
                          "res": pct(_mult(HEADS[k]["res"], *h.res_mods())), "instab": pct(h.instab_mult()),
                          "window": pct(h.window_mult()), "rate": pct(h.rate_mult())}}

    ships = []
    for key, spec in SHIPS.items():
        _, lo = ship_loadout(key)
        craft = lo.get("craft") or [None] * len(lo["heads"])
        presets = [{"key": "factory", "name": "出厂配置"}]
        if key == "mole":
            presets.append({"key": "author", "name": "作者推荐（2 人）", "loadout": clean_loadout(key, AUTHOR_MOLE)})
        ships.append({"key": key, "name": spec["name"], "size": spec["size"], "heads": spec["heads"],
                      "crew_max": spec["crew_max"], "fixed": spec.get("fixed"), "loadout": lo,
                      "power": [power(k, craft[i]) for i, (k, _) in enumerate(lo["heads"])],
                      "cards": [card(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])],
                      "summary": _gear_summary(key, lo), "presets": presets,
                      "is_default": lo == clean_loadout(key, DEFAULT_LOADOUTS[key])})
    heads = [{"key": k, "name": gear_label(h["name"]), "en": h["name"], "size": h["size"], "slots": h["slots"], "ship": h.get("ship"),
              "pmax": h["pmax"], "desc": f"最大功率 {h['pmax']:,.0f} W｜" + (fmt(h, ("res", "instab", "window", "rate")) or "无修正"),
              # 自造时影响激光功率的材料槽，和这种材料的品质档位（选档或者直接填数字）
              "craft": [{"slot": s["slot"], "slot_zh": s["slot_zh"], "mat_zh": s["mat_zh"], "segs": [list(x[:4]) for x in s["segs"]],
                         "tiers": [["商店标准", 500]] + [[n, q] for n, q in tiers(s["mat"])]} for s in craft_slots(k)]}
             for k, h in HEADS.items()]
    mods = [{"key": k, "name": gear_label(m["name"]), "en": m["name"], "desc": fmt(m, ("power", "extract", "res", "instab", "window", "rate", "filter")),
             "group": next((g for p, g in MOD_GROUPS if k.startswith(p)), "其他")}
            for k, m in MODULES.items()]
    from ..mining.laser import chosen_ship
    return {"ship": current_ship(), "chosen": chosen_ship() is not None, "ships": ships, "heads": heads, "modules": mods,
            "groups": list(dict.fromkeys(g for _, g in MOD_GROUPS))}


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
    _live.gear_rev += 1                     # 正在显示的石头按新配置重算（采矿助手最多 5 秒后重新发布）
    return _gear()


def manual_scan(mass=0, resistance=0, instability=0):
    """手动输入扫描数据：只算破碎方案"""
    import math
    from ..mining.laser import recommend
    mass, resistance, instability = float(mass), float(resistance), float(instability)
    # 质量为 0 时比值是 inf，json 写成 Infinity，前端解析失败只会说「连不上」（2026-10-31 审查）
    if not (math.isfinite(mass) and mass > 0):
        raise ValueError("质量要填大于 0 的数")
    if not (math.isfinite(resistance) and 0 <= resistance <= 100):
        raise ValueError("抗性要填 0 到 100")
    if not (math.isfinite(instability) and instability >= 0):
        raise ValueError("不稳定性要填 0 或更大的数")
    plans = recommend(mass, resistance, instability)
    return [{"heads": p.names, "short": p.short(), "summary": p.summary(),
             "ratio": p.ratio, "breakable": p.breakable, "comfortable": p.comfortable,
             "throttle": p.throttle if p.breakable else None} for p in plans]


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
    "scu_text",
    "_station_bonus",
    "_lots",
    "_lots_hud",
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
