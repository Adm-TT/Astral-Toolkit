"""品质曲线、属性统计和品质提示的纯规则。

只吃传进来的蓝图、曲线、材料名和取数函数，不读库、不读文件、不读汉化包。
"""

from .labels import GEAR_ZH, LASER_POWER, PROP_ZH, prop_zh, slot_zh

PROP_KEY = {  # 属性名 → scmdb 的 property_key（成品基础值按这个到 itemstats 里取）
    "Integrity": "health_maxhealth",
    "Impact Force": "weapon_damage",
    "Max. Shield Strength": "shield_maxhealth",
    "Fire Rate": "weapon_firerate",
    "Recoil Handling": "weapon_recoil_handling",
    "Recoil Smoothness": "weapon_recoil_smoothness",
    "Recoil Kick": "weapon_recoil_kick",
    "Reload Speed": "weapon_reloadspeed",
    "Spread": "weapon_spread",
    "Damage Mitigation": "armor_damagemitigation",
    "Min Temp": "armor_temperaturemin",
    "Max Temp": "armor_temperaturemax",
    "Radiation Dissipation": "armor_radiationdissipation",
    "Coolant Rating": "itemresource_coolantgeneration",
    "Power Pips": "itemresource_powergeneration",
    "Quantum Speed": "quantum_speed",
    "Quantum Fuel Burn": "quantum_fuelrequirement",
    "Min. Assist Distance": "radar_minaimassistdistance",
    "Max. Assist Distance": "radar_maxaimassistdistance",
    "Beam Force": "weapon_tractor_force",
    "Max. Distance": "weapon_tractor_maxdist",
    "Full Strength Dist.": "weapon_tractor_fullstrengthdist",
    "Max. Volume": "weapon_tractor_maxvolume",
    "Speed": "weapon_hullscraping_speed",
    "Efficiency": "weapon_hullscraping_efficiency",
    "Radius": "weapon_hullscraping_radius",
    "Craft Speed": "crafter_craftspeed",
}
LOWER_BETTER = {
    "Recoil Smoothness",
    "Recoil Handling",
    "Recoil Kick",
    "Quantum Fuel Burn",
}


def group_mods(mods):
    """[属性, 起, 止, a, b, 加法] → {属性: [(起, 止, a, b, 加法), ...]}"""
    out = {}
    for p, qs, qe, a, b, add in mods:
        out.setdefault(p, []).append((qs, qe, a, b, add))
    for segs in out.values():
        segs.sort()
    return out


def curve_value(segs, q):
    for qs, qe, a, b, add in segs:
        if qs <= q <= qe:
            return a if qe == qs else a + (b - a) * (q - qs) / (qe - qs)
    return segs[-1][3] if q > segs[-1][1] else segs[0][2]


def _fmt(v, add):
    return f"{v:+g}" if add else f"×{v:.2f}"


def curve_text(prop, segs, name=None):
    """属性随品质的变化，写成一句话"""
    name = name or PROP_ZH.get(prop, prop)
    add = segs[0][4]
    if len(segs) == 1:
        qs, qe, a, b, _ = segs[0]
        return f"{name} {_fmt(a, add)}→{_fmt(b, add)}"
    parts = []
    for qs, qe, a, b, _ in segs:
        val = _fmt(a, add) if a == b else f"{_fmt(a, add)}→{_fmt(b, add)}"
        parts.append(f"{qs}–{qe}:{val}")
    return f"{name}（" + "，".join(parts) + "）"


def _effect_text(v, add):
    """修正值写成玩家看得懂的：乘法 ×0.95 → -5%，加法 +3 → +3"""
    if add:
        return f"{v:+g}"
    return f"{(v - 1) * 100:+.1f}%"


def laser_total(bp, qualities=None):
    """采矿激光：发射器、汇流排两个槽的激光功率加成相加（1.6.47 起；以前相乘。数据里没有合并规则，
    按游戏制造终端、SCM、Crafter 三处一致的「各槽百分比相加」）。
    qualities 不给：返回整份蓝图的范围说明（制造页）；给了（{槽序号或槽名: 品质}）：返回 {name, mult, text}，没填全返回提示"""
    if bp.get("t") != "mininglaser":
        return None
    parts = [
        (idx, slot, group_mods(mods)["Impact Force"])
        for idx, (slot, opts, mods) in enumerate(bp["slots"])
        if "Impact Force" in group_mods(mods)
    ]
    if len(parts) < 2:
        return None
    names = " + ".join(slot_zh(s) for _, s, _ in parts)
    if qualities is None:
        lo = hi = mid = 1.0
        for _, _, segs in parts:
            lo, hi, mid = (
                lo + curve_value(segs, 0) - 1,
                hi + curve_value(segs, 1000) - 1,
                mid + curve_value(segs, 500) - 1,
            )
        return (
            f"{LASER_POWER}合计：{names} 两个槽的加成相加，品质都 0 时 ×{lo:.2f}、都 500 时 ×{mid:.2f}（和商店买的一样）、"
            f"都 1000 时 ×{hi:.2f}。「采矿助手」页的配置里可以填自造矿头的品质，破碎方案按自造的功率算"
        )
    total, bits, missing = 1.0, [], []
    for idx, slot, segs in parts:
        q = qualities.get(idx, qualities.get(str(idx), qualities.get(slot)))
        try:
            q = max(0, min(1000, int(float(q))))
        except (TypeError, ValueError):
            missing.append(slot_zh(slot))
            continue
        v = curve_value(segs, q)
        total += v - 1
        bits.append(f"{slot_zh(slot)} {(v - 1) * 100:+.1f}%")
    if missing:
        return {
            "name": LASER_POWER,
            "mult": None,
            "text": f"{LASER_POWER}合计：{'、'.join(missing)}的品质还没填",
        }
    return {
        "name": LASER_POWER,
        "mult": round(total, 4),
        "text": f"{LASER_POWER}合计 {(total - 1) * 100:+.1f}%（{' + '.join(bits)}）",
    }


def stats(bp, qualities, base_value):
    """成品各属性在给定材料品质下的「基础 → 强化 → 变化」（制造页属性统计表，1.6.47）。
    同一属性几个槽都影响时，倍率类各槽的百分比相加，加法类各槽相加（和游戏制造终端的算法一致）。
    qualities：{槽序号或槽名: 品质}；没填的槽按 500（商店货）算，并在 missing 里列出。
    返回 [{prop, name, key, base, unit, now, delta(倍率类是百分比，加法类是加的数), add, best, worst, lower, slots:[{slot, q, part}]}]"""
    by = {}
    missing = []
    for idx, (slot, opts, mods) in enumerate(bp["slots"]):
        gm = group_mods(mods)
        if not gm:
            continue
        q = qualities.get(idx, qualities.get(str(idx), qualities.get(slot)))
        try:
            q = max(0, min(1000, int(float(q))))
        except (TypeError, ValueError):
            q = 500
            missing.append(slot_zh(slot))
        for prop, segs in gm.items():
            add = segs[0][4]
            vals = (
                [curve_value(segs, x) for x in (0, 1000)]
                + [sg[2] for sg in segs]
                + [sg[3] for sg in segs]
            )
            lower = prop in LOWER_BETTER
            e = by.setdefault(
                prop,
                {
                    "prop": prop,
                    "name": prop_zh(prop, bp),
                    "key": PROP_KEY.get(prop, ""),
                    "add": add,
                    "lower": lower,
                    "delta": 0.0,
                    "best": 0.0,
                    "worst": 0.0,
                    "slots": [],
                },
            )
            now = curve_value(segs, q)
            part = now if add else now - 1
            e["delta"] += part
            hi, lo = (min(vals), max(vals)) if lower else (max(vals), min(vals))
            e["best"] += hi if add else hi - 1
            e["worst"] += lo if add else lo - 1
            e["slots"].append(
                {"slot": slot_zh(slot), "idx": idx, "q": q, "part": round(part, 4)}
            )
    out = []
    for e in by.values():
        base, unit = base_value(bp.get("u"), e["key"]) if e["key"] else (None, "")
        e["base"], e["unit"] = base, unit
        if base is not None:
            e["now"] = round(
                base + e["delta"] if e["add"] else base * (1 + e["delta"]), 4
            )
            e["now_best"] = round(
                base + e["best"] if e["add"] else base * (1 + e["best"]), 4
            )
        else:
            e["now"] = e["now_best"] = None
        e["text"] = f"{e['delta']:+g}" if e["add"] else f"{e['delta'] * 100:+.2f}%"
        e["delta"], e["best"], e["worst"] = (
            round(e["delta"], 6),
            round(e["best"], 6),
            round(e["worst"], 6),
        )
        out.append(e)
    return {"props": out, "missing": missing}


def effect(bp, qualities, material_zh):
    """蓝图每个材料槽在给定品质下对成品属性的影响。qualities：{槽序号或槽名: 品质}，没给的槽不算。
    返回 [{slot, idx, material, q, props:[{name, now, best, worst, pos(0~1，越大越好), text, next_gate}]}]"""
    out = []
    for idx, (slot, opts, mods) in enumerate(bp["slots"]):
        q = qualities.get(idx, qualities.get(str(idx), qualities.get(slot)))
        if q in (None, ""):
            continue
        try:
            q = max(0, min(1000, int(float(q))))
        except (TypeError, ValueError):
            continue
        props = []
        for prop, segs in group_mods(mods).items():
            add = segs[0][4]
            vals = (
                [curve_value(segs, x) for x in (0, 1000)]
                + [seg[2] for seg in segs]
                + [seg[3] for seg in segs]
            )
            lower = prop in LOWER_BETTER
            best, worst = (min(vals), max(vals)) if lower else (max(vals), min(vals))
            now = curve_value(segs, q)
            span = best - worst
            pos = 1.0 if span == 0 else max(0.0, min(1.0, (now - worst) / span))
            nxt = None
            if len(segs) > 1:  # 分段门槛：再高到哪一档会变好
                for qs, qe, a, b, _ in segs:
                    if qs > q and (
                        curve_value(segs, qs) < now
                        if lower
                        else curve_value(segs, qs) > now
                    ):
                        nxt = qs
                        break
            props.append(
                {
                    "name": prop_zh(prop, bp),
                    "now": round(now, 4),
                    "best": round(best, 4),
                    "worst": round(worst, 4),
                    "pos": round(pos, 3),
                    "next_gate": nxt,
                    "text": f"{prop_zh(prop, bp)} {_effect_text(now, add)}（最好 {_effect_text(best, add)}）",
                }
            )
        mats = [material_zh(name) for k, name, qty, minq in opts if k == "r"] or [
            material_zh(name) for k, name, *_ in opts
        ]
        minq = max([m for k, name, qty, m in opts if k == "r"] or [0])
        out.append(
            {
                "slot": slot_zh(slot),
                "idx": idx,
                "material": "/".join(mats),
                "q": q,
                "minq": minq if minq > 1 else 0,
                "ok": q >= minq,
                "props": props,
            }
        )
    return out


def curves_for(blueprints, mineral):
    """用这种矿的部件里出现过的属性曲线：{(属性, 曲线): [蓝图类别...]}"""
    out = {}
    for bp in blueprints():
        for slot, opts, mods in bp["slots"]:
            if any(k == "r" and name == mineral for k, name, *_ in opts):
                for p, segs in group_mods(mods).items():
                    out.setdefault((p, tuple(segs)), set()).add(
                        GEAR_ZH.get((bp["g"], bp["t"]), bp["t"])
                    )
    return out


def quality_hints(composition, curves_of, uses_of, material_zh):
    """扫描联动：[(矿物, 百分比, 品质)] → 每种矿的品质对制造意味着什么（分段门槛最重要，如发电机能量格）"""
    best = {}
    for name, pct, q in composition:
        if name and name != "Inert Materials" and q is not None:
            best[name] = max(best.get(name, 0), q)
    hints = []
    for name, q in best.items():
        agg = {}  # (标签, 当前值文字, 已最好) → 可提升的品质门槛集合
        for (prop, segs), kinds in curves_of(name).items():
            if len(segs) < 2:
                continue  # 线性曲线没有门槛，下面统一说
            now = curve_value(segs, q)
            vals = [curve_value(segs, s_[0]) for s_ in segs]
            better = min(vals) if prop in LOWER_BETTER else max(vals)
            nxt = next((s_[0] for s_ in segs if s_[0] > q), None)
            label = f"{'/'.join(sorted(kinds))}{PROP_ZH.get(prop, prop)}"
            key = (label, "" if now == better else _fmt(now, segs[0][4]), now == better)
            agg.setdefault(key, set())
            if now != better and nxt is not None:
                agg[key].add(nxt)
        notes = []
        for (label, now_txt, at_best), gates_ in agg.items():
            if at_best:
                if not any(k[0] == label and not k[2] and agg[k] for k in agg):
                    notes.append(f"{label}已到最高档")
            elif gates_:
                th = "/".join(f"≥{g}" for g in sorted(gates_))
                notes.append(
                    f"{label}现在 {now_txt}，品质 {th} 可提升（视型号）"
                    if len(gates_) > 1
                    else f"{label}现在 {now_txt}，品质 {th} 可提升"
                )
        notes = list(dict.fromkeys(notes))[:3]
        gates = [minq for _, _, minq in uses_of(name) if minq > 1]
        if gates:
            ok = sum(1 for g in gates if q >= g)
            notes.append(f"有品质门槛的蓝图够做 {ok}/{len(gates)} 份")
        grade = "高" if q >= 800 else ("中" if q >= 500 else "低")
        lead = f"{material_zh(name)} 品质 {q}（{grade}，线性属性约达最好效果的 {q / 10:.0f}%）"
        hints.append(lead + ("：" + "；".join(notes) if notes else ""))
    return hints
