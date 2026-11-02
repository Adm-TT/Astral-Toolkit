"""采矿结果的呈现（运行结构 RT-B1）：MiningResult → 窗口 JSON（to_view）、悬浮窗文字和结构化内容（to_hud）。只排版，不算数、不取数据"""

import copy

from ...mining.analysis import MiningResult


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
        rows.append({**row, "refined_text": text})
    return rows


def lots_hud(lots):
    """悬浮窗一行：「惰性 31%｜钨 662 那份 3.07 SCU」（同一种矿有高低两种品质时写高品质那份）；没什么可说返回空"""
    parts = []
    inert = sum(r["pct"] for r in lots if r["inert"])
    if inert >= 0.5:
        parts.append(f"惰性 {inert:.0f}%")
    for r in lots:
        if r["rank"] == "高品质":
            low = [x["q"] for x in lots if x["en"] == r["en"] and x["rank"] == "低品质"]
            parts.append(
                f"{r['zh']} 品质 {r['q']}：{r['scu']:.2f} SCU"
                if r["scu"] is not None
                else f"{r['zh']} 品质 {r['q']}/{low[0] if low else '?'}"
            )
    return "｜".join(parts)


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
        "craft": list(r.craft),
        "craft_mats": copy.deepcopy(list(r.craft_mats)),
        "goal": copy.deepcopy(list(r.goals)),
        "plans": [
            {
                "heads": p.heads,
                "short": p.short,
                "summary": p.summary,
                "ratio": p.ratio,
                "breakable": p.breakable,
                "comfortable": p.comfortable,
                "throttle": p.throttle,
            }
            for p in r.plans
        ],
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


def _comp(lots):
    """矿物组成：同一种矿合在一起，下面列各品质（高品质那份标蓝）；占比照游戏里的两位小数写"""
    groups = {}
    for row in lots:
        key = "惰性物质" if row["inert"] else row["zh"]
        g = groups.setdefault(
            key, {"name": key, "inert": row["inert"], "pct_n": 0.0, "subs": []}
        )
        g["pct_n"] += row["pct"] or 0
        if not row["inert"]:  # 品质没认出来写「未知」，单独一份，不混进别的品质
            g["subs"].append(
                {
                    "q": "未知" if row["q"] is None else str(row["q"]),
                    "pct": f"{row['pct'] or 0:.2f}%",
                    "hi": row["rank"] == "高品质",
                    "n": row["pct"] or 0,
                }
            )
    for g in groups.values():
        g["subs"].sort(key=lambda x: -int(x["q"]) if x["q"].isdigit() else 1)
        g["pct"] = (
            f"{g.pop('pct_n'):.2f}%"  # 1.6.70（用户）：游戏里读到多少写多少，不四舍五入
        )
        for x in g["subs"]:
            x.pop("n", None)
    return sorted(
        groups.values(), key=lambda g: (g["inert"], -float(g["pct"][:-1] or 0))
    )


def to_hud(r: MiningResult):
    """(文字版 hud（窗口右侧用）, 悬浮窗结构化内容)。
    1.6.64：悬浮窗按层次排（审查意见）：矿名 → 关键读数 → 怎么碎 → 收益 → 次要详情；
    1.6.65 照用户给的样图：矿名、三格读数、矿物组成（每种矿下面列各品质、占整石）、开采建议、精炼产量和净值、次要"""
    hud = [
        f"{r.rock}｜{r.mass:,.0f} kg｜抗性 {r.resistance:g}%｜不稳定 {r.instability:g}"
    ]
    rich = {
        "title": r.rock,
        "stats": [
            ["质量", f"{r.mass:,.0f}", "kg"],
            ["抗性", f"{r.resistance:g}", "%"],
            ["不稳定性", f"{r.instability:g}", ""],
        ],
        "comp": _comp(r.lots),
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
        bonus = f" {o.bonus}" if o.bonus else ""
        hud.append(
            f"精炼后 {scu_text(o.scu)}，价值 {o.value:,.0f} aUEC（建议：{o.method_zh}，{o.station_zh}精炼{bonus}）"
        )
        rich["gain"] = [
            ["预计精炼产量", f"{o.scu:,.2f}", "SCU"],
            ["价格", f"{o.value:,.0f}", "aUEC"],
        ]
        rich["minor"].append(f"{o.method_zh} · {o.station_zh}{bonus}")
        rich["foot"] = "精炼结果为估算"
    line = lots_hud(r.lots)
    if line:
        hud.append(line)
    hud += r.goal_lines
    rich["minor"] += r.goal_lines
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
