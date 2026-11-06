"""改件反推的纯规则：从说明框加成倒推材料品质。

只吃传进来的蓝图、加成、品质档位和材料中文名函数，不读库、不读文件、不读汉化包。
"""

import re
from itertools import product

from .labels import slot_zh
from .quality import curve_value, group_mods

# ================================================================ 1.6.67：制造出来的东西 → 倒推材料品质
# 游戏说明框最下面列着加成（冲击力：+17.50 %）。属性名照玩家汉化包 global.ini 的 StatName_GPP_*（2026-10-25 从用户电脑里查的）。
GAME_STAT = {
    "冲击力": "Impact Force",
    "激光功率": "Impact Force",
    "后坐力操控": "Recoil Handling",
    "后坐力冲击": "Recoil Kick",
    "后坐力平滑度": "Recoil Smoothness",
    "射速": "Fire Rate",
    "装填速度": "Reload Speed",
    "散布": "Spread",
    "伤害减免": "Damage Mitigation",
    "辐射消散": "Radiation Dissipation",
    "最高温度": "Max Temp",
    "最低温度": "Min Temp",
    "完整性": "Integrity",
    "冷却效率": "Coolant Rating",
    "能量点数": "Power Pips",
    "量子速度": "Quantum Speed",
    "量子燃料消耗": "Quantum Fuel Burn",
    "最小辅助距离": "Min. Assist Distance",
    "最大辅助距离": "Max. Assist Distance",
    "最大护盾强度": "Max. Shield Strength",
    "最大强度距离": "Full Strength Dist.",
    "最大距离": "Max. Distance",
    "最大体积": "Max. Volume",
    "速度": "Speed",
    "效率": "Efficiency",
    "半径": "Radius",
    "制造速度": "Craft Speed",
}
_MOD = re.compile(r"^(.{1,10}?)\s*[:：]\s*([+\-−–])\s*(\d+(?:[.,]\d+)?)\s*(%?)$")


def parse_mods(tokens):
    """说明框文字 → [(游戏里的属性名, 带符号的数, 是不是百分比, 属性)]。只认带 +/- 号的行（「射速：200rpm」这种基础值不算）"""
    rows = []
    for t in sorted(tokens or [], key=lambda k: (k.box[1], k.box[0])):
        h = t.box[3] or 16
        if rows and abs(rows[-1][0] - t.box[1]) <= h * 0.6:
            rows[-1][1].append(t)
        else:
            rows.append([t.box[1], [t]])
    out = []
    for _, ts in rows:
        text = "".join(k.text for k in sorted(ts, key=lambda k: k.box[0])).replace(
            " ", ""
        )
        m = _MOD.match(text)
        if not m:
            continue
        label = m.group(1).strip()
        prop = GAME_STAT.get(label)
        if not prop:
            continue
        v = float(m.group(3).replace(",", "."))
        out.append((label, -v if m.group(2) in "-−–" else v, bool(m.group(4)), prop))
    return out


def _slot_material(opts):
    for k, name, *_ in opts:
        if k in ("r", "i"):
            return name
    return opts[0][1] if opts else ""


def solve_slots(bp, mods, tiers, material_zh):
    """按说明框里的加成倒推每个材料槽的品质：每个槽只在这种材料的固定几档品质里找（quality_tiers），
    同一属性几个槽都影响时各槽百分比相加（和制造终端一致，那把枪验证过）。
    返回 {"slots": [{idx, slot, mat, q}], "avg": 平均品质, "exact": 每个属性都对得上（差 ≤0.02）}；对不上返回 None"""
    if not bp or not mods:
        return None
    obs = {}
    for _, v, pct, prop in mods:
        obs[prop] = abs(v)
    slots = []
    for idx, (slot, opts, ms) in enumerate(bp["slots"]):
        gm = group_mods(ms)
        hit = {p: segs for p, segs in gm.items() if p in obs}
        if not hit:
            continue
        mat = _slot_material(opts)
        cand = tiers(mat) or list(range(0, 1001, 1))
        slots.append((idx, slot, mat, hit, cand))
    if not slots or len(slots) > 6:
        return None
    total = 1
    for s in slots:
        total *= len(s[4])
    if total > 300_000:
        return None

    def size(prop, segs, q):  # 倍率类写成百分比（×0.7136 → -28.64），加法类就是加的数
        v = curve_value(segs, q)
        return v if segs[0][4] else (v - 1) * 100

    best = None
    for qs in product(*[s[4] for s in slots]):
        err = 0.0
        worst = 0.0
        for prop, want in obs.items():
            got = 0.0
            for (idx, slot, mat, hit, _), q in zip(slots, qs):
                if prop in hit:
                    got += size(prop, hit[prop], q)
            e = abs(abs(got) - want)
            err += e
            worst = max(worst, e)
        if best is None or err < best[0]:
            best = (err, worst, qs)
    err, worst, qs = best
    out = [
        {
            "idx": idx,
            "slot": slot_zh(slot),
            "mat": material_zh(mat),
            "mat_en": mat,
            "q": int(q),
        }
        for (idx, slot, mat, _, _), q in zip(slots, qs)
    ]
    return {
        "slots": out,
        "avg": round(sum(x["q"] for x in out) / len(out)),
        "exact": worst <= 0.02,
    }


def craft_text(slots):
    """「框架 858 · 线缆 916 · 稳压器 959」"""
    return " · ".join(f"{x['slot']} {x['q']}" for x in slots or [])


def craft_slots(bp, tiers, material_zh):
    """入库时手填：这个蓝图会影响属性的材料槽 [{idx, slot, mat, mat_en, tiers}]"""
    out = []
    for idx, (slot, opts, ms) in enumerate((bp or {}).get("slots") or []):
        if not group_mods(ms):
            continue
        mat = _slot_material(opts)
        out.append(
            {
                "idx": idx,
                "slot": slot_zh(slot),
                "mat": material_zh(mat),
                "mat_en": mat,
                "tiers": tiers(mat) or [],
            }
        )
    return out
