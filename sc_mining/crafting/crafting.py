"""制造联动（数据：scmdb.net，4.10.2；由 tools/build_crafting.py 生成 crafting.json）

- 查蓝图：要哪些矿、多少 SCU、最低品质；矿的品质怎样影响成品属性；去哪挖；哪些任务给蓝图
- 反查：某种矿能做什么
- 扫描联动：扫到的矿石各成分品质，够做多少蓝图
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from ..core.paths import DATA as _D
DATA = _D / "crafting.json"

GEAR_ZH = {
    ("fpsgear", "armour"): "护甲", ("fpsgear", "weapons"): "个人武器", ("fpsgear", "ammo"): "弹匣",
    ("vehiclegear", "weapons"): "舰船武器", ("vehiclegear", "cooler"): "冷却器", ("vehiclegear", "powerplant"): "发电机",
    ("vehiclegear", "shield"): "护盾生成器", ("vehiclegear", "radar"): "雷达", ("vehiclegear", "quantumdrive"): "量子驱动器",
    ("vehiclegear", "mininglaser"): "采矿激光器", ("vehiclegear", "miningmodule"): "采矿模组",
    ("vehiclegear", "orepod"): "矿石吊舱", ("vehiclegear", "tractorbeam"): "牵引光束",
    ("vehiclegear", "refuelling"): "燃料喷嘴", ("vehiclegear", "salvage"): "刮削模块",
    ("missionitems", None): "任务物品",
}
PROP_ZH = {
    "Min Temp": "最低耐温", "Max Temp": "最高耐温", "Damage Mitigation": "伤害减免", "Integrity": "结构强度",
    "Power Pips": "能量格", "Impact Force": "冲击力", "Coolant Rating": "冷却能力",
    "Max. Shield Strength": "护盾强度上限", "Recoil Smoothness": "后坐力平滑", "Recoil Handling": "后坐力控制",
    "Recoil Kick": "后坐力", "Fire Rate": "射速", "Min. Assist Distance": "最小辅助距离",
    "Max. Assist Distance": "最大辅助距离", "Quantum Speed": "量子速度", "Quantum Fuel Burn": "量子燃料消耗",
    "Full Strength Dist.": "满强度距离", "Max. Distance": "最大距离", "Radius": "半径", "Speed": "速度",
    "Beam Force": "光束力", "Max. Volume": "最大体积", "Efficiency": "效率", "Radiation Dissipation": "辐射消散",
}
PROP_KEY = {        # 属性名 → scmdb 的 property_key（成品基础值按这个到 itemstats 里取）
    "Integrity": "health_maxhealth", "Impact Force": "weapon_damage", "Max. Shield Strength": "shield_maxhealth",
    "Fire Rate": "weapon_firerate", "Recoil Handling": "weapon_recoil_handling", "Recoil Smoothness": "weapon_recoil_smoothness",
    "Recoil Kick": "weapon_recoil_kick", "Reload Speed": "weapon_reloadspeed", "Spread": "weapon_spread",
    "Damage Mitigation": "armor_damagemitigation", "Min Temp": "armor_temperaturemin", "Max Temp": "armor_temperaturemax",
    "Radiation Dissipation": "armor_radiationdissipation", "Coolant Rating": "itemresource_coolantgeneration",
    "Power Pips": "itemresource_powergeneration", "Quantum Speed": "quantum_speed", "Quantum Fuel Burn": "quantum_fuelrequirement",
    "Min. Assist Distance": "radar_minaimassistdistance", "Max. Assist Distance": "radar_maxaimassistdistance",
    "Beam Force": "weapon_tractor_force", "Max. Distance": "weapon_tractor_maxdist", "Full Strength Dist.": "weapon_tractor_fullstrengthdist",
    "Max. Volume": "weapon_tractor_maxvolume", "Speed": "weapon_hullscraping_speed", "Efficiency": "weapon_hullscraping_efficiency",
    "Radius": "weapon_hullscraping_radius", "Craft Speed": "crafter_craftspeed",
}
ITEM_ZH = {"Sadaryx": "萨达瑞晶", "Saldynium (Ore)": "烁迪银矿石", "Yormandi Eye": "约曼迪之眼"}
# 采矿激光的「Impact Force」在游戏里叫 Laser Power（scmdb 数据 nameOverrides: WeaponMining → Laser Power）
LASER_POWER = "激光功率"


def prop_zh(prop, bp=None):
    """属性的中文名；采矿激光的冲击力其实是激光功率"""
    if prop == "Impact Force" and bp is not None and bp.get("t") == "mininglaser":
        return LASER_POWER
    return PROP_ZH.get(prop, prop)


def laser_total(bp, qualities=None):
    """采矿激光：发射器、汇流排两个槽的激光功率加成相加（1.6.47 起；以前相乘。数据里没有合并规则，
    按游戏制造终端、SCM、Crafter 三处一致的「各槽百分比相加」）。
    qualities 不给：返回整份蓝图的范围说明（制造页）；给了（{槽序号或槽名: 品质}）：返回 {name, mult, text}，没填全返回提示"""
    if bp.get("t") != "mininglaser":
        return None
    parts = [(idx, slot, group_mods(mods)["Impact Force"]) for idx, (slot, opts, mods) in enumerate(bp["slots"])
             if "Impact Force" in group_mods(mods)]
    if len(parts) < 2:
        return None
    names = " + ".join(slot_zh(s) for _, s, _ in parts)
    if qualities is None:
        lo = hi = mid = 1.0
        for _, _, segs in parts:
            lo, hi, mid = lo + curve_value(segs, 0) - 1, hi + curve_value(segs, 1000) - 1, mid + curve_value(segs, 500) - 1
        return (f"{LASER_POWER}合计：{names} 两个槽的加成相加，品质都 0 时 ×{lo:.2f}、都 500 时 ×{mid:.2f}（和商店买的一样）、"
                f"都 1000 时 ×{hi:.2f}。「采矿助手」页的配置里可以填自造矿头的品质，破碎方案按自造的功率算")
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
        return {"name": LASER_POWER, "mult": None, "text": f"{LASER_POWER}合计：{'、'.join(missing)}的品质还没填"}
    return {"name": LASER_POWER, "mult": round(total, 4), "text": f"{LASER_POWER}合计 {(total - 1) * 100:+.1f}%（{' + '.join(bits)}）"}


def stats(bp, qualities):
    """成品各属性在给定材料品质下的「基础 → 强化 → 变化」（制造页属性统计表，1.6.47）。
    同一属性几个槽都影响时，倍率类各槽的百分比相加，加法类各槽相加（和游戏制造终端的算法一致）。
    qualities：{槽序号或槽名: 品质}；没填的槽按 500（商店货）算，并在 missing 里列出。
    返回 [{prop, name, key, base, unit, now, delta(倍率类是百分比，加法类是加的数), add, best, worst, lower, slots:[{slot, q, part}]}]"""
    from . import itemstats
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
            vals = [curve_value(segs, x) for x in (0, 1000)] + [sg[2] for sg in segs] + [sg[3] for sg in segs]
            lower = prop in LOWER_BETTER
            e = by.setdefault(prop, {"prop": prop, "name": prop_zh(prop, bp), "key": PROP_KEY.get(prop, ""), "add": add,
                                     "lower": lower, "delta": 0.0, "best": 0.0, "worst": 0.0, "slots": []})
            now = curve_value(segs, q)
            part = now if add else now - 1
            e["delta"] += part
            hi, lo = (min(vals), max(vals)) if lower else (max(vals), min(vals))
            e["best"] += hi if add else hi - 1
            e["worst"] += lo if add else lo - 1
            e["slots"].append({"slot": slot_zh(slot), "idx": idx, "q": q, "part": round(part, 4)})
    out = []
    for e in by.values():
        base, unit = itemstats.base_value(bp.get("u"), e["key"]) if e["key"] else (None, "")
        e["base"], e["unit"] = base, unit
        if base is not None:
            e["now"] = round(base + e["delta"] if e["add"] else base * (1 + e["delta"]), 4)
            e["now_best"] = round(base + e["best"] if e["add"] else base * (1 + e["best"]), 4)
        else:
            e["now"] = e["now_best"] = None
        e["text"] = (f"{e['delta']:+g}" if e["add"] else f"{e['delta'] * 100:+.2f}%")
        e["delta"], e["best"], e["worst"] = round(e["delta"], 6), round(e["best"], 6), round(e["worst"], 6)
        out.append(e)
    return {"props": out, "missing": missing}


def header(bp):
    """制造页的标题信息：中文名、英文名、类别、尺寸 / 等级 / 类别标签、厂商、制造时间"""
    from . import itemstats
    t = itemstats.tags(bp.get("u"))
    size = t.get("size")
    sz = bp.get("s") or ""
    if size is None and sz.startswith("size") and sz[4:].isdigit():
        size = int(sz[4:])
    cls_zh = {"Civilian": "民用", "Military": "军用", "Industrial": "工业", "Stealth": "隐形", "Competition": "竞速"}
    tags = []
    if size is not None:
        tags.append(f"S{size}")
    if t.get("grade") and str(t["grade"]).upper() in "ABCD":
        tags.append(f"{t['grade']} 级")
    if t.get("cls"):
        tags.append(cls_zh.get(t["cls"], t["cls"]))
    return {"zh": bp["z"] or "", "en": bp["n"], "kind": GEAR_ZH.get((bp["g"], bp["t"]), bp["t"] or bp["g"]),
            "tags": tags, "maker": bp["m"] or "", "sec": bp["sec"], "unlocked": bool(bp["d"]),
            "stats_version": itemstats.version() if t else ""}


@lru_cache
def data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def blueprints():
    return data()["blueprints"]


def material_zh(name: str) -> str:
    from ..core.i18n import mineral_zh
    return ITEM_ZH.get(name) or mineral_zh(name)


@lru_cache
def _keys():
    """每份蓝图的唯一编号：名字不重复就用名字；有十几个名字对应两份不同配方（比如 Main Powerplant），
    这些用「名字#1」「名字#2」区分（Codex 二审 2026-10-23 发现：只按名字会点开别的配方）"""
    from collections import Counter
    total = Counter(b["n"] for b in blueprints())
    seen, keys, index = Counter(), {}, {}
    for b in blueprints():
        seen[b["n"]] += 1
        k = b["n"] if total[b["n"]] == 1 else f"{b['n']}#{seen[b['n']]}"
        keys[id(b)] = k
        index[k] = b
    return keys, index, total


def bp_key(bp) -> str:
    return _keys()[0].get(id(bp), bp["n"])


def by_key(key):
    """按编号找蓝图；旧的只有名字的编号（以前存的目标）取同名的第一份"""
    _, index, _ = _keys()
    return index.get(key) or index.get(f"{key}#1")


def variant_note(bp) -> str:
    """同名多份配方时的区分说明，比如「配方 2/2 · 42 分钟」"""
    _, _, total = _keys()
    if total[bp["n"]] < 2:
        return ""
    k = bp_key(bp).rsplit("#", 1)[-1]
    return f"配方 {k}/{total[bp['n']]} · {bp['sec'] // 60} 分钟"


def name_parts(bp):
    """(中文, 英文)：采矿装备的中文不带型号（霍夫斯泰德），其他用汉化包全名"""
    from ..core.i18n import gear_zh_of_item
    return gear_zh_of_item(bp["n"]) or bp["z"] or "", bp["n"]


def display_name(bp) -> str:
    """蓝图名「中文 English」（2026-10-26 统一写法）：「霍夫斯泰德 Hofstede-S2 Mining Laser」「卡纳 步枪 Karna Rifle」"""
    zh, en = name_parts(bp)
    return f"{zh} {en}" if zh else en


def for_item(name_en="", name_zh=""):
    """做这件东西的蓝图（英文名一样，或者中文名一样）；没有返回 None"""
    fold = lambda s: re.sub(r"[\W_]+", "", (s or "").lower())
    en, zh = fold(name_en), fold(name_zh)
    return (next((b for b in blueprints() if en and fold(b["n"]) == en), None)
            or next((b for b in blueprints() if zh and b["z"] and fold(b["z"]) == zh), None))


def search(query: str, limit: int = 20):
    """按中文或英文名搜索蓝图：完全匹配优先，再按包含匹配"""
    q = query.strip().lower().replace(" ", "")
    if not q:
        return []
    exact, part = [], []
    for bp in blueprints():
        names = [bp["n"].lower().replace(" ", ""), bp["z"].lower().replace(" ", "")]
        if q in names:
            exact.append(bp)
        elif any(q in n for n in names if n):
            part.append(bp)
    part.sort(key=lambda b: (len(b["n"]), b["n"]))
    return (exact + part)[:limit]


# ---------------------------------------------------------------- 蓝图字典：按类别 / 子类 / 部位 / 厂商筛选

# 类别、子类的叫法照游戏汉化包（物品说明里的「物品类型：…」），2026-10-23 用户要求以游戏内汉化为准
SUB_ZH = {
    "combat": "战斗", "engineer": "工程", "hunter": "猎人", "stealth": "潜行", "miner": "矿工", "medic": "医疗",
    "explorer": "探索", "cosmonaut": "宇航", "environment": "环境", "flightsuit": "飞行服", "racer": "竞速",
    "radiation": "防辐射", "salvager": "打捞", "undersuit": "基底服",
    "pistol": "手枪", "rifle": "突击步枪", "smg": "冲锋枪", "shotgun": "霰弹枪", "sniper": "狙击步枪", "lmg": "轻机枪",
    "ballistic": "实弹", "laser": "激光", "electron": "电子", "plasma": "电浆", "distortion": "畸变",
    "neutron": "中子", "tachyon": "快子", "active": "手动激活", "passive": "被动生效", "nozzle": "燃料喷嘴",
    "small": "小型", "medium": "中型", "large": "大型",
    **{f"size{i}": f"S{i}" for i in range(0, 11)},             # 尺寸照游戏里写 S1 / S2
}
PART_ZH = {"Helmet": "头盔", "Core": "胸甲", "Arms": "臂甲", "Legs": "腿甲", "Backpack": "背包", "Undersuit": "基底服"}
_PART_RE = re.compile(r"\b(Helmet|Core|Arms|Legs|Backpack|Undersuit)\b")


def category(bp):
    return f"{bp['g']}/{bp['t'] or ''}"


def category_zh(bp):
    return GEAR_ZH.get((bp["g"], bp["t"]), bp["t"] or bp["g"])


def part_of(bp):
    """护甲部位（头盔/胸甲/…）；不是分部位的护甲返回「其他」"""
    if bp["t"] != "armour":
        return ""
    m = _PART_RE.search(bp["n"])
    return PART_ZH[m.group(1)] if m else "其他"


def _facet(rows, key):
    from collections import Counter
    c = Counter(key(b) for b in rows)
    return [{"key": k, "count": n} for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0])) if k]


def needs(bp, mineral):
    """这份蓝图要这种矿：[(数量 SCU, 最低品质)]（一个槽一条）"""
    return [(qty, minq) for slot, opts, mods in bp["slots"] for kind_, name, qty, minq in opts
            if kind_ == "r" and name == mineral]


def mat_summary(mineral, q=None):
    """多少份蓝图用到这种矿；给了品质再算其中多少份品质够（每个槽的最低品质都满足）"""
    rows = [bp for bp in blueprints() if needs(bp, mineral)]
    ok = None if q is None else sum(1 for bp in rows if all(q >= m for _, m in needs(bp, mineral)))
    gated = sum(1 for bp in rows if any(m > 1 for _, m in needs(bp, mineral)))
    gates = sorted({m for bp in rows for _, m in needs(bp, mineral) if m > 1})
    return {"count": len(rows), "ok": ok, "gated": gated, "gates": gates,
            "gated_ok": None if q is None else ok - (len(rows) - gated)}


def browse(cat="", sub="", part="", maker="", q="", unlocked=False, offset=0, limit=60, mat=""):
    """蓝图字典：按条件筛，按名字排（同一系列排在一起）。返回 {rows, total, cats, subs, parts, makers}
    mat：只看用到这种矿的蓝图（从扫描结果、矿物页点过来）"""
    allbp = blueprints()
    if mat:
        allbp = [b for b in allbp if needs(b, mat)]
    cats = [{"key": k, "label": GEAR_ZH.get(tuple(None if x == "" else x for x in k.split("/", 1)), k), "count": n}
            for k, n in ((f["key"], f["count"]) for f in _facet(allbp, category))]
    rows = [b for b in allbp if not cat or category(b) == cat]
    subs = [{"key": f["key"], "label": SUB_ZH.get(f["key"], f["key"]), "count": f["count"]} for f in _facet(rows, lambda b: b["s"] or "")]
    if sub:
        rows = [b for b in rows if (b["s"] or "") == sub]
    parts = [{"key": f["key"], "label": f["key"], "count": f["count"]} for f in _facet(rows, part_of)]
    if part:
        rows = [b for b in rows if part_of(b) == part]
    makers = [{"key": f["key"], "label": f["key"], "count": f["count"]} for f in _facet(rows, lambda b: b["m"] or "")]
    if maker:
        rows = [b for b in rows if (b["m"] or "") == maker]
    if unlocked:
        rows = [b for b in rows if b["d"]]
    qq = q.strip().lower().replace(" ", "")
    if qq:
        rows = [b for b in rows if qq in b["n"].lower().replace(" ", "") or qq in (b["z"] or "").lower().replace(" ", "")]
    if mat:     # 按矿筛时，有品质门槛的排前面（玩家最想知道这几份够不够）
        rows = sorted(rows, key=lambda b: (not any(m > 1 for _, m in needs(b, mat)), b["n"].lower()))
    else:
        rows = sorted(rows, key=lambda b: (b["n"].lower(),))
    return {"rows": rows[offset:offset + limit], "total": len(rows), "cats": cats, "subs": subs, "parts": parts, "makers": makers}


def _clean_title(t: str) -> str:
    return re.sub(r"~mission\([^)]*\)", "[地点]", t)


def describe(bp, with_locations: bool = True) -> str:
    """一份蓝图的完整中文说明"""
    from ..mining.data import best_price
    from ..mining.locations import where, zh_name
    kind = GEAR_ZH.get((bp["g"], bp["t"]), bp["t"] or bp["g"])
    lines = [f"【{display_name(bp)}】{kind}｜{bp['m'] or '—'}｜制造 {bp['sec'] // 60} 分 {bp['sec'] % 60} 秒"
             + ("｜默认已解锁" if bp["d"] else "")]
    minerals = []
    for slot, opts, mods in bp["slots"]:
        alts = " 或 ".join(
            f"{material_zh(name)} {qty:g} {'SCU' if kind_ == 'r' else '个'}"
            + (f"（品质 ≥{minq}）" if minq > 1 else "")
            for kind_, name, qty, minq in opts)
        effect = "；".join(curve_text(p, segs, prop_zh(p, bp)) for p, segs in group_mods(mods).items())
        lines.append(f"  · {slot_zh(slot)}：{alts}" + (f"｜品质影响：{effect}" if effect else ""))
        minerals += [name for kind_, name, *_ in opts if kind_ == "r"]
    total = laser_total(bp)
    if total:
        lines.append(f"  · {total}")
    if with_locations and minerals:
        lines.append("  去哪挖：")
        for m in dict.fromkeys(minerals):
            rows = where(m)[:2]
            price, city = best_price(m)
            spots = "，".join(f"{zh_name(loc)} {pct:.0f}%" for pct, loc in rows) or "SCMiner 没有船挖地点"
            lines.append(f"    {material_zh(m)}：{spots}｜精炼后 {price:,}/SCU（{city or '无收购'}）")
    if bp["src"]:
        lines.append(f"  蓝图来源（{bp['nsrc']} 个任务，列出前 {min(len(bp['src']), 5)} 个）：")
        for title, who, mtype, systems, chance in bp["src"][:5]:
            p = "" if chance >= 1 else f"，掉率 {chance:.0%}"
            lines.append(f"    {_clean_title(title)}｜{who}｜{mtype}｜{systems or '—'}{p}")
    elif not bp["d"]:
        lines.append("  蓝图来源：scmdb 的任务数据里没有找到")
    return "\n".join(lines)


def uses(mineral: str):
    """某种矿能做什么：返回 [(蓝图, 数量, 最低品质)]"""
    out = []
    for bp in blueprints():
        for slot, opts, mods in bp["slots"]:
            for kind_, name, qty, minq in opts:
                if kind_ == "r" and name == mineral:
                    out.append((bp, qty, minq))
    return out


def uses_report(mineral: str, examples: int = 6) -> str:
    rows = uses(mineral)
    zh = material_zh(mineral)
    if not rows:
        return f"{zh}：没有蓝图用到它。"
    by_kind = {}
    for bp, qty, minq in rows:
        by_kind.setdefault(GEAR_ZH.get((bp["g"], bp["t"]), bp["t"]), []).append((bp, qty, minq))
    lines = [f"【{zh}】被 {len(rows)} 份蓝图用到："]
    for kind, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        high = sum(1 for _, _, q in items if q >= 500)
        ex = "、".join(dict.fromkeys(display_name(b) for b, _, _ in items))
        ex = "、".join(list(dict.fromkeys(display_name(b) for b, _, _ in items))[:examples])
        lines.append(f"  {kind} {len(items)} 份" + (f"（其中 {high} 份要求品质 ≥500）" if high else "")
                     + f"：{ex}{' 等' if len(items) > examples else ''}")
    return "\n".join(lines)


# 蓝图材料槽（部件）名：游戏汉化包里没有这些词，按部件用途译（2026-10-23）
SLOT_ZH = {
    "Acceleration Unit": "加速单元", "Anchor Pins": "固定销", "Aperture Iris": "光圈", "Armored Carapace": "装甲外壳",
    "Barrel": "枪管", "Barrels": "枪管", "Bus Bars": "汇流排", "Cabling": "线缆", "Case": "外壳", "Casing": "壳体",
    "Casing Weave": "壳体编织层", "Charge Chamber": "充能室", "Conduit": "导管", "Conduit Channel": "导流通道",
    "Containment Matrix": "约束矩阵", "Coolant": "冷却剂", "Core": "核心", "Cycler": "循环器", "Distorter Unit": "畸变单元",
    "Drive Motor": "驱动电机", "Electronics": "电子元件", "Emitter": "发射器", "Field Array": "力场阵列",
    "Filament Coating": "灯丝涂层", "Filter": "滤芯", "Focus Zone Plate": "聚焦波带片", "Frame": "框架",
    "Frequency Controller": "频率控制器", "Grip": "握把", "Injector Nozzles": "喷射嘴", "Insulative Liner": "绝缘内衬",
    "Internal Array": "内部阵列", "Lattice": "晶格", "Lenses": "透镜", "Magazine": "弹匣", "Magnetizer": "磁化器",
    "Main Valve": "主阀", "Ocular Enhancer": "目镜增强器", "Panel Covering": "面板覆层", "Plating": "镀层",
    "Plating Barrier": "镀层屏障", "Power Regulator": "功率调节器", "Precision Parts": "精密零件",
    "Protective Sheathing": "防护护套", "Pump Impeller": "泵叶轮", "Radiator": "散热器", "Reinforced Frame": "加固框架",
    "Segment Paneling": "分段面板", "Sheathing Coating": "护套涂层", "Shell": "外壳", "Shot": "弹丸",
    "Signal Provessor": "信号处理器", "Signal Processor": "信号处理器", "Stabilizer": "稳定器", "Stator Cores": "定子铁芯",
    "Stock": "枪托", "Substrate": "基板", "Suit Underlay": "服装内衬", "Support Structure": "支撑结构",
    "Tensive Fibre": "张力纤维", "Thermal Sink": "散热片", "Torque Junction": "扭矩接头", "Transmitter": "发射机",
    "Voltage Regulator": "稳压器", "Wiring": "布线",
}


def slot_zh(slot):
    """材料槽名的中文；占位名、没收录的照原样"""
    if not slot or "PLACEHOLDER" in slot:
        return "材料"
    return SLOT_ZH.get(slot, slot)


LOWER_BETTER = {"Recoil Smoothness", "Recoil Handling", "Recoil Kick", "Quantum Fuel Burn"}


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


def effect(bp, qualities):
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
            vals = [curve_value(segs, x) for x in (0, 1000)] + [seg[2] for seg in segs] + [seg[3] for seg in segs]
            lower = prop in LOWER_BETTER
            best, worst = (min(vals), max(vals)) if lower else (max(vals), min(vals))
            now = curve_value(segs, q)
            span = best - worst
            pos = 1.0 if span == 0 else max(0.0, min(1.0, (now - worst) / span))
            nxt = None
            if len(segs) > 1:          # 分段门槛：再高到哪一档会变好
                for qs, qe, a, b, _ in segs:
                    if qs > q and (curve_value(segs, qs) < now if lower else curve_value(segs, qs) > now):
                        nxt = qs
                        break
            props.append({"name": prop_zh(prop, bp), "now": round(now, 4), "best": round(best, 4),
                          "worst": round(worst, 4), "pos": round(pos, 3), "next_gate": nxt,
                          "text": f"{prop_zh(prop, bp)} {_effect_text(now, add)}（最好 {_effect_text(best, add)}）"})
        mats = [material_zh(name) for k, name, qty, minq in opts if k == "r"] or [material_zh(name) for k, name, *_ in opts]
        minq = max([m for k, name, qty, m in opts if k == "r"] or [0])
        out.append({"slot": slot_zh(slot), "idx": idx, "material": "/".join(mats), "q": q, "minq": minq if minq > 1 else 0,
                    "ok": q >= minq, "props": props})
    return out


def curves_for(mineral: str):
    """用这种矿的部件里出现过的属性曲线：{(属性, 曲线): [蓝图类别...]}"""
    out = {}
    for bp in blueprints():
        for slot, opts, mods in bp["slots"]:
            if any(k == "r" and name == mineral for k, name, *_ in opts):
                for p, segs in group_mods(mods).items():
                    out.setdefault((p, tuple(segs)), set()).add(GEAR_ZH.get((bp["g"], bp["t"]), bp["t"]))
    return out


def quality_hints(composition) -> list:
    """扫描联动：[(矿物, 百分比, 品质)] → 每种矿的品质对制造意味着什么（分段门槛最重要，如发电机能量格）"""
    best = {}
    for name, pct, q in composition:
        if name and name != "Inert Materials" and q is not None:
            best[name] = max(best.get(name, 0), q)
    hints = []
    for name, q in best.items():
        agg = {}     # (标签, 当前值文字, 已最好) → 可提升的品质门槛集合
        for (prop, segs), kinds in curves_for(name).items():
            if len(segs) < 2:
                continue                      # 线性曲线没有门槛，下面统一说
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
                notes.append(f"{label}现在 {now_txt}，品质 {th} 可提升（视型号）" if len(gates_) > 1
                             else f"{label}现在 {now_txt}，品质 {th} 可提升")
        notes = list(dict.fromkeys(notes))[:3]
        gates = [minq for _, _, minq in uses(name) if minq > 1]
        if gates:
            ok = sum(1 for g in gates if q >= g)
            notes.append(f"有品质门槛的蓝图够做 {ok}/{len(gates)} 份")
        grade = "高" if q >= 800 else ("中" if q >= 500 else "低")
        lead = f"{material_zh(name)} 品质 {q}（{grade}，线性属性约达最好效果的 {q / 10:.0f}%）"
        hints.append(lead + ("：" + "；".join(notes) if notes else ""))
    return hints


def ask():
    """交互：输入物品名查蓝图，或输入矿名反查用途"""
    from ..mining.locations import _match_zh
    from ..mining.data import SIGNATURES
    en_minerals = {k.lower(): k for k in SIGNATURES}
    print("输入想造的东西（中文或英文，可只输一部分，如 螺旋 II / Helix），"
          "或输入矿名反查能造什么（如 砬兰石）。直接回车退出。\n")
    while True:
        try:
            raw = input("> ").strip()
        except EOFError:
            return
        if not raw:
            return
        mineral = en_minerals.get(raw.lower()) or (_match_zh(raw) if len(raw) <= 6 else None)
        found = search(raw)
        if mineral and not any(bp["z"] == raw or bp["n"].lower() == raw.lower() for bp in found):
            print(uses_report(mineral), end="\n\n")
            continue
        if not found:
            print("没找到，换个关键词试试（中文名或英文名的一部分都行）\n")
        elif len(found) == 1:
            print(describe(found[0]), end="\n\n")
        else:
            print(f"找到 {len(found)} 个，输入序号查看：")
            for i, bp in enumerate(found, 1):
                print(f"  {i}. {display_name(bp)}｜{GEAR_ZH.get((bp['g'], bp['t']), bp['t'])}")
            pick = input("序号> ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(found):
                print(describe(found[int(pick) - 1]), end="\n\n")


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
    for q, s in boxes:                             # 同品质的几箱当一箱
        merged[q] = merged.get(q, 0.0) + s
    boxes = sorted(merged.items())
    have = sum(s for _, s in boxes)
    need = float(need or 0)
    if need <= 0:                                  # 合箱：全部混成一箱
        avg = sum(q * s for q, s in boxes) / have
        plan = [{"q": q, "have": s, "use": s} for q, s in sorted(boxes)]
        return {"ok": True, "goal": None, "plan": plan, "avg": avg, "total": have, "high": 0.0, "best": avg,
                "msg": f"全部合并为一箱：{have:g} SCU，品质 {avg:.1f}"}
    if need > have + 1e-9:
        return {"ok": False, "msg": f"材料不足：需要 {need:g} SCU，现有 {have:g} SCU"}
    goal = min(1000.0, float(target or 0) + float(margin or 0)) if target else 0.0
    by_best = sorted(boxes, key=lambda b: -b[0])
    best = _avg(_take(by_best, need))
    if goal and best < goal - 1e-9:
        return {"ok": False, "goal": goal, "best": best,
                "msg": f"现有材料最高可混合到 {best:.1f}，无法达到 {goal:g}：需要更高品质的材料"}
    low = sorted([b for b in boxes if b[0] < goal], key=lambda b: -b[0])     # 低于目标的：越接近目标越先用
    high = sorted([b for b in boxes if b[0] >= goal], key=lambda b: -b[0])   # 高于目标的：品质最高的先用，用得最少
    low_total, high_total = sum(s for _, s in low), sum(s for _, s in high)
    lo, hi = max(0.0, need - high_total), min(need, low_total)

    def ok(L):
        return _avg(_take(low, L) + _take(high, need - L)) >= goal - 1e-9
    if not ok(lo):
        lo = hi = 0.0
    for _ in range(60):                            # 低品质料最多能用多少还能过线
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
    plan = [{"q": q, "have": s, "use": round(min(s, use.get(q, 0.0)), 6)} for q, s in boxes]   # 先低后高
    avg = _avg([(p["q"], p["use"]) for p in plan if p["use"] > 0])
    high_used = sum(p["use"] for p in plan if p["q"] >= goal)
    return {"ok": True, "goal": goal, "plan": plan, "avg": avg, "total": need, "high": high_used, "best": best,
            "msg": f"按 {goal:g} 混合：平均 {avg:.1f}，高品质材料 {high_used:g} SCU（占 {high_used / need:.0%}）"}


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
    import math
    return math.floor(x * 1000 + 1e-6) / 1000


def mix_targets(bp):
    """这份蓝图里每种矿：要多少 SCU、品质到多少换档（只列分档的属性，连续变化的没有「过线」一说）"""
    out = []
    for slot, opts, mods in bp["slots"]:
        steps = {}
        for prop, q0, q1, v0, v1, stepped in mods:
            if stepped and q0 > 1:
                steps.setdefault(q0, []).append(f"{PROP_ZH.get(prop, prop)} {v0:+g}" if isinstance(v0, (int, float)) else prop)
        for kind_, name, qty, minq in opts:
            if kind_ != "r":
                continue
            out.append({"slot": slot_zh(slot), "material": name, "zh": material_zh(name), "scu": qty, "min": minq,
                        "steps": [{"q": q, "text": "、".join(t)} for q, t in sorted(steps.items())]})
    return out


# ================================================================ 1.6.67：制造出来的东西 → 倒推材料品质
# 游戏说明框最下面列着加成（冲击力：+17.50 %）。属性名照玩家汉化包 global.ini 的 StatName_GPP_*（2026-10-25 从用户电脑里查的）。
GAME_STAT = {
    "冲击力": "Impact Force", "激光功率": "Impact Force", "后坐力操控": "Recoil Handling", "后坐力冲击": "Recoil Kick",
    "后坐力平滑度": "Recoil Smoothness", "射速": "Fire Rate", "装填速度": "Reload Speed", "散布": "Spread",
    "伤害减免": "Damage Mitigation", "辐射消散": "Radiation Dissipation", "最高温度": "Max Temp", "最低温度": "Min Temp",
    "完整性": "Integrity", "冷却效率": "Coolant Rating", "能量点数": "Power Pips", "量子速度": "Quantum Speed",
    "量子燃料消耗": "Quantum Fuel Burn", "最小辅助距离": "Min. Assist Distance", "最大辅助距离": "Max. Assist Distance",
    "最大护盾强度": "Max. Shield Strength", "最大强度距离": "Full Strength Dist.", "最大距离": "Max. Distance",
    "最大体积": "Max. Volume", "速度": "Speed", "效率": "Efficiency", "半径": "Radius", "制造速度": "Craft Speed",
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
        text = "".join(k.text for k in sorted(ts, key=lambda k: k.box[0])).replace(" ", "")
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


def solve_slots(bp, mods):
    """按说明框里的加成倒推每个材料槽的品质：每个槽只在这种材料的固定几档品质里找（quality_tiers），
    同一属性几个槽都影响时各槽百分比相加（和制造终端一致，那把枪验证过）。
    返回 {"slots": [{idx, slot, mat, q}], "avg": 平均品质, "exact": 每个属性都对得上（差 ≤0.02）}；对不上返回 None"""
    from ..mining.quality_tiers import tiers
    from itertools import product
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

    def size(prop, segs, q):                     # 倍率类写成百分比（×0.7136 → -28.64），加法类就是加的数
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
    out = [{"idx": idx, "slot": slot_zh(slot), "mat": material_zh(mat), "mat_en": mat, "q": int(q)}
           for (idx, slot, mat, _, _), q in zip(slots, qs)]
    return {"slots": out, "avg": round(sum(x["q"] for x in out) / len(out)), "exact": worst <= 0.02}


def craft_text(slots):
    """「框架 858 · 线缆 916 · 稳压器 959」"""
    return " · ".join(f"{x['slot']} {x['q']}" for x in slots or [])


def craft_slots(bp):
    """入库时手填：这个蓝图会影响属性的材料槽 [{idx, slot, mat, mat_en, tiers}]"""
    from ..mining.quality_tiers import tiers
    out = []
    for idx, (slot, opts, ms) in enumerate((bp or {}).get("slots") or []):
        if not group_mods(ms):
            continue
        mat = _slot_material(opts)
        out.append({"idx": idx, "slot": slot_zh(slot), "mat": material_zh(mat), "mat_en": mat, "tiers": tiers(mat) or []})
    return out
