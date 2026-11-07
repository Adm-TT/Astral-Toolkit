"""采矿结果的呈现（运行结构 RT-B1）：MiningResult → 窗口 JSON（to_view）、悬浮窗文字和结构化内容（to_hud）；
采矿助手的活动磁贴（activity，目录迁移 R3 从采矿线程搬来）。只排版，不算数、不取数据"""

import time
from collections.abc import Mapping

from ...mining.analysis import MiningResult, PlanFacts, Rank

RANK_ZH = {Rank.HIGH: "高品质", Rank.MID: "中等品质", Rank.LOW: "低品质"}


def tile_status(on: bool, runtime: dict) -> dict:
    """只映射运行事实；开启仍由运行层复核，旧线程收尾不妨碍停止新会话。"""
    draining = bool(runtime.get("draining"))
    pending_read = bool(runtime.get("pending_read"))
    if on:
        line = (
            "已暂停"
            if runtime.get("state") == "paused" and not pending_read
            else "运行中"
        )
        if draining:
            line += "，旧线程仍在收尾"
        return {"status_line": line, "available": {"ok": True}}
    can_start = bool(runtime.get("can_start")) and not pending_read
    if draining:
        line = "正在收尾，可重新开启" if can_start else "正在收尾，请稍候"
    elif runtime.get("running") or pending_read:
        # 停止消息已到、下一次运行快照还没到：不能用旧的运行态报「已关闭」。
        line = "正在停止，请稍候"
        can_start = False
    else:
        line = "已关闭" if can_start else "暂不能开启"
    available: dict[str, object] = {"ok": can_start}
    if not can_start:
        available["reason"] = line
    return {"status_line": line, "available": available}


def _thaw(value):
    """结果里的只读结构变回 JSON 用的 dict / list，每次新建"""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def _tier_text(tier):
    """第几档：tier = (档名, 第几档, 共几档)"""
    if not tier:
        return ""
    name, pos, total = tier
    if name == "完美":
        return "完美"
    return f"{name} 档" + (
        "（最低）" if pos == 1 else "（最高）" if pos == total else ""
    )


def scu_text(v):
    """精炼后的量：1 SCU 以上写 SCU，不到 1 SCU 写 uSCU（1 SCU = 1,000,000 uSCU）；两种都给"""
    if v >= 1:
        return f"{v:,.2f} SCU（{v * 1e6:,.0f} uSCU）"
    return f"{v * 1e6:,.0f} uSCU（{v:.3f} SCU）"


def lot_rows(lots, amounts):
    """成分表给窗口的每一行：计算结果加上玩家看的 refined_text"""
    rows = []
    for row, v in zip(lots, amounts):
        text = "无精炼产出，仅占用矿袋" if row["inert"] else ""
        if v is not None:
            text = scu_text(v)
        rows.append(
            {
                **row,
                "zh": "惰性物质" if row["inert"] else row["zh"],
                "tier": _tier_text(row["tier"]),
                "rank": RANK_ZH.get(row["rank"], ""),
                "refined_text": text,
            }
        )
    return rows


def lots_hud(r: MiningResult, names=None):
    """悬浮窗一行：「惰性 31%｜钨 662 那份 3.07 SCU」（同一种矿有高低两种品质时写高品质那份）；没什么可说返回空"""
    parts = []
    if names is None and r.inert_pct is not None:
        parts.append(f"惰性 {r.inert_pct:.0f}%")
    for h in r.high_lots:
        if names is not None and h.zh not in names:
            continue
        parts.append(
            f"{h.zh} 品质 {h.q}：{h.scu:.2f} SCU"
            if h.scu is not None
            else f"{h.zh} 品质 {h.q}/{'?' if h.low_q is None else h.low_q}"
        )
    return "｜".join(parts)


def plan_view(p: PlanFacts) -> dict:
    """窗口里一条破碎方案"""
    return {
        "heads": p.heads,
        "short": p.short,
        "summary": p.summary,
        "ratio": p.ratio,
        "breakable": p.breakable,
        "comfortable": p.comfortable,
        "throttle": p.throttle,
    }


def _refine_view(o):
    return {
        "method": o.method_zh,
        "station": o.station_zh,
        "value": o.value,
        "scu": o.scu,
        "fee": o.fee,
        "hours": o.hours,
        "bonus": o.bonus,
        "amount": scu_text(o.scu),
        "yield": [{"zh": zh, "amount": scu_text(v)} for zh, v in o.yields],
    }


def _bag_view(bag):
    if bag is None:
        return None, ""
    view = {
        "used": bag.used,
        "cap": bag.cap,
        "items": [{"name": zh, "scu": v} for zh, v in bag.items],
    }
    text = f"{bag.used:g}/{bag.cap:g} SCU\n" + "，".join(
        f"{zh} {v:g}" for zh, v in bag.items
    )
    return view, text


def to_view(r: MiningResult) -> dict:
    """窗口 JSON（不含 hud、hud_rich，见 to_hud）"""
    lots = lot_rows(r.lots, r.lot_refined)
    refine = [_refine_view(o) for o in r.refine]
    if refine:  # 精炼后按品质分开写：「钨 662 有 1.50 SCU、钨 363 有 5.74 SCU」
        refine[0]["lots"] = [
            {"zh": x["zh"], "q": x["q"], "amount": x["refined_text"]}
            for x in lots
            if not x["inert"] and x["refined"]
        ]
    bag, bag_text = _bag_view(r.bag)
    return {
        "rock": r.rock,
        "mass": r.mass,
        "resistance": r.resistance,
        "instability": r.instability,
        "difficulty": r.difficulty,
        "minerals": [{"name": zh, "en": en, "scu": v} for zh, en, v in r.minerals],
        "refine": refine,
        "sell": [{"name": zh, "where": where or "无收购"} for zh, where in r.sell],
        "craft": _thaw(r.craft),
        "craft_mats": _thaw(r.craft_mats),
        "goal": _thaw(r.goals),
        "plans": [plan_view(p) for p in r.plans],
        "total_scu": r.total_scu,
        "lots": lots,
        "lots_plan": f"{r.refine[0].method_zh}，{r.refine[0].station_zh}"
        if r.refine
        else "",
        "cut": r.cut,
        "note": "扫描面板右侧被屏幕边缘遮挡，无法识别品质和总 SCU：仅计算破碎方案和成分占比。"
        "在游戏设置中调大「FOV视野」使面板完整显示后，可计算精炼收益和价格。"
        if r.cut
        else "",
        "at": r.at,
        "bag": bag,
        "bag_text": bag_text,
    }


def _comp(groups):
    """矿物组成：同一种矿一组，下面列各品质（高品质那份标蓝）；占比照游戏里的两位小数写（1.6.70 用户定）"""
    return [
        {
            "name": "惰性物质" if g.inert else g.zh,
            "inert": g.inert,
            "subs": [
                {
                    "q": "未知" if s.q is None else str(s.q),  # 没认出来的单独一份
                    "pct": f"{s.pct:.2f}%",
                    "hi": s.high,
                }
                for s in g.subs
            ],
            "pct": f"{g.pct:.2f}%",
        }
        for g in groups
    ]


def to_hud(r: MiningResult, focus=None):
    """(文字版 hud（窗口右侧用）, 悬浮窗结构化内容)。
    1.6.64：悬浮窗按层次排（审查意见）：矿名 → 关键读数 → 怎么碎 → 收益 → 次要详情；
    1.6.65 照用户给的样图：矿名、三格读数、矿物组成（每种矿下面列各品质、占整石）、开采建议、精炼产量和净值、次要"""
    from ...core.i18n import mineral_zh

    names = None if focus is None else {mineral_zh(key) for key in focus}
    composition = (
        r.composition
        if names is None
        else tuple(g for g in r.composition if not g.inert and g.zh in names)
    )
    title = (
        r.rock
        if names is None
        else "、".join(g.zh for g in composition) or "未发现关注的矿"
    )
    goal_lines = (
        r.goal_lines
        if names is None
        else tuple(
            g["text"] for g in r.goals if g["zh"] in names and g["text"] in r.goal_lines
        )
    )
    hud = [
        f"{title}｜{r.mass:,.0f} kg｜抗性 {r.resistance:g}%｜不稳定 {r.instability:g}"
    ]
    rich = {
        "title": title,
        "stats": [
            ["质量", f"{r.mass:,.0f}", "kg"],
            ["抗性", f"{r.resistance:g}", "%"],
            ["不稳定性", f"{r.instability:g}", ""],
        ],
        "comp": _comp(composition),
        "advice": None,
        "gain": [],
        "minor": [],
        "foot": "",
    }
    if r.cut:
        hud.append("面板被遮挡：仅计算破碎方案")
        rich["minor"].append("面板被遮挡：仅计算破碎方案")
    if r.refine:
        o = r.refine[0]
        bonus = f" {o.bonus}" if o.bonus and names is None else ""
        hud.append(
            f"精炼后 {scu_text(o.scu)}，价值 {o.value:,.0f} aUEC（建议：{o.method_zh}，{o.station_zh}精炼{bonus}）"
        )
        rich["gain"] = [
            ["预计精炼产量", f"{o.scu:,.2f}", "SCU"],
            ["价格", f"{o.value:,.0f}", "aUEC"],
        ]
        rich["minor"].append(f"{o.method_zh} · {o.station_zh}{bonus}")
        rich["foot"] = "精炼结果为估算"
    if names is not None:
        note = "仅显示关注的矿；产量和收益按整石估算"
        hud.append(note)
        rich["minor"].append(note)
    line = lots_hud(r, names)
    if line:
        hud.append(line)
    hud += goal_lines
    rich["minor"] += goal_lines
    if r.plans:
        p0 = r.plans[0]
        hud.insert(1, p0.short)
        heads = p0.heads + (f" + {p0.gadget_label}" if p0.gadget_label else "")
        rich["advice"] = {
            "heads": heads,
            "power": f"建议功率 {p0.throttle * 100:.0f}%"
            if p0.breakable
            else "满功率也无法破碎",
        }
    return "\n".join(hud), rich


def activity(session_id, ui, quality=None):
    """采矿助手的活动磁贴（目录迁移 R3 从采矿线程搬来）：把本会话的展示状态拼成活动（纯函数：不读 DOM / 全局）。
    quality 不传就用 ui 里记的"""
    ui = ui or {}
    if quality is None:
        quality = ui.get("quality") or "complete"
    scan = ui.get("scan")
    if isinstance(scan, dict) and scan:
        primary = {"value": scan.get("rock") or "岩石", "unit": ""}
        secondary = []
        for key, label, unit in (
            ("mass", "质量", ""),
            ("total_scu", "矿量", "SCU"),
            ("difficulty", "难度", ""),
        ):
            if key in scan and scan[key] is not None:
                item = {"label": label, "value": scan[key]}
                if unit:
                    item["unit"] = unit
                secondary.append(item)
        secondary = secondary[:3]
    else:
        primary = {"value": None, "unit": ""}
        secondary = []
        signals = ui.get("signals")
        if signals:
            lines = signals.get("lines") if isinstance(signals, dict) else None
            secondary = [{"label": "信号", "value": lines[0] if lines else ""}]
    return {
        "activity_id": f"mining:{session_id}",
        "kind": "mining",
        "title": "采矿助手",
        "state": ui.get("state") or "starting",
        "primary": primary,
        "secondary": secondary,
        "progress": None,
        "action": {"id": "stop", "label": "结束"},
        "link": "live",
        "stale_since": ui.get("stale_since"),
        "error": None,
        "updated_wall": time.strftime("%Y-%m-%d %H:%M:%S"),
        "quality": quality,
        "detail_ref": None,
    }
