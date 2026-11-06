"""混料计算的纯规则：多箱不同品质材料混到目标品质。

只吃传进来的数量、品质和材料中文名函数，不读库、不读文件、不读汉化包。
"""

import math

from .labels import PROP_ZH, slot_zh

# ---------------------------------------------------------------- 混料计算器
# 制造机里同一种材料可以投好几箱不同品质的，成品这一项的品质 = 按投入量（SCU）加权平均。
# 只要过某个品质线就行的东西（比如电源 900 以上多一格能量），用便宜的低品质料打底、补最少的高品质料刚好过线最省。


def mix_plan(need, target, boxes, margin=2.0):
    """need：这种材料要投多少 SCU（0 或不填 = 全部合成一箱）；target：要达到的品质；margin：多留几点余量
    （游戏显示会四舍五入，按 900 混可能卡线，默认按 902 混）；boxes：[(品质, 有多少 SCU)]。
    返回 dict：ok、goal（实际按多少混）、plan（按「先低后高」排好的 [{q, have, use}]）、avg（混完的品质）、
    total（投了多少）、high（高于目标的料用了多少）、best（这些料最高能混到多少）、msg"""
    boxes = [(float(q), float(s)) for q, s in boxes if s and float(s) > 0]
    if not boxes:
        return {"ok": False, "msg": "需填写每箱材料的品质和数量"}
    if any(not 0 < q <= 1000 for q, _ in boxes):
        return {"ok": False, "msg": "品质需在 1–1000 之间"}
    merged = {}
    for q, s in boxes:  # 同品质的几箱当一箱
        merged[q] = merged.get(q, 0.0) + s
    boxes = sorted(merged.items())
    have = sum(s for _, s in boxes)
    need = float(need or 0)
    if need <= 0:  # 合箱：全部混成一箱
        avg = sum(q * s for q, s in boxes) / have
        plan = [{"q": q, "have": s, "use": s} for q, s in sorted(boxes)]
        return {
            "ok": True,
            "goal": None,
            "plan": plan,
            "avg": avg,
            "total": have,
            "high": 0.0,
            "best": avg,
            "msg": f"全部合并为一箱：{have:g} SCU，品质 {avg:.1f}",
        }
    if need > have + 1e-9:
        return {"ok": False, "msg": f"材料不足：需要 {need:g} SCU，现有 {have:g} SCU"}
    goal = min(1000.0, float(target or 0) + float(margin or 0)) if target else 0.0
    by_best = sorted(boxes, key=lambda b: -b[0])
    best = _avg(_take(by_best, need))
    if goal and best < goal - 1e-9:
        return {
            "ok": False,
            "goal": goal,
            "best": best,
            "msg": f"现有材料最高可混合到 {best:.1f}，无法达到 {goal:g}：需要更高品质的材料",
        }
    low = sorted(
        [b for b in boxes if b[0] < goal], key=lambda b: -b[0]
    )  # 低于目标的：越接近目标越先用
    high = sorted(
        [b for b in boxes if b[0] >= goal], key=lambda b: -b[0]
    )  # 高于目标的：品质最高的先用，用得最少
    low_total, high_total = sum(s for _, s in low), sum(s for _, s in high)
    lo, hi = max(0.0, need - high_total), min(need, low_total)

    def ok(L):
        return _avg(_take(low, L) + _take(high, need - L)) >= goal - 1e-9

    if not ok(lo):
        lo = hi = 0.0
    for _ in range(60):  # 低品质料最多能用多少还能过线
        if hi - lo < 1e-7:
            break
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    L = _floor3(lo)
    picks = _take(low, L)
    picks = [(q, _floor3(s)) for q, s in picks]
    rest = round(need - sum(s for _, s in picks), 6)
    picks += _take(high, rest)
    use = {}
    for q, s in picks:
        use[q] = use.get(q, 0.0) + s
    plan = [
        {"q": q, "have": s, "use": round(min(s, use.get(q, 0.0)), 6)} for q, s in boxes
    ]  # 先低后高
    avg = _avg([(p["q"], p["use"]) for p in plan if p["use"] > 0])
    high_used = sum(p["use"] for p in plan if p["q"] >= goal)
    return {
        "ok": True,
        "goal": goal,
        "plan": plan,
        "avg": avg,
        "total": need,
        "high": high_used,
        "best": best,
        "msg": f"按 {goal:g} 混合：平均 {avg:.1f}，高品质材料 {high_used:g} SCU（占 {high_used / need:.0%}）",
    }


def _take(boxes, amount):
    """按顺序从这几箱里拿 amount SCU：[(品质, 拿多少)]"""
    out, left = [], amount
    for q, s in boxes:
        if left <= 1e-12:
            break
        t = min(s, left)
        out.append((q, t))
        left -= t
    return out


def _avg(parts):
    tot = sum(s for _, s in parts)
    return sum(q * s for q, s in parts) / tot if tot > 1e-12 else 0.0


def _floor3(x):
    return math.floor(x * 1000 + 1e-6) / 1000


def mix_targets(bp, material_zh):
    """这份蓝图里每种矿：要多少 SCU、品质到多少换档（只列分档的属性，连续变化的没有「过线」一说）"""
    out = []
    for slot, opts, mods in bp["slots"]:
        steps = {}
        for prop, q0, q1, v0, v1, stepped in mods:
            if stepped and q0 > 1:
                steps.setdefault(q0, []).append(
                    f"{PROP_ZH.get(prop, prop)} {v0:+g}"
                    if isinstance(v0, (int, float))
                    else prop
                )
        for kind_, name, qty, minq in opts:
            if kind_ != "r":
                continue
            out.append(
                {
                    "slot": slot_zh(slot),
                    "material": name,
                    "zh": material_zh(name),
                    "scu": qty,
                    "min": minq,
                    "steps": [
                        {"q": q, "text": "、".join(t)} for q, t in sorted(steps.items())
                    ],
                }
            )
    return out
