"""哪里挖：按矿物推荐开采地点（数据：SCMiner「Ore by Location」，4.10.2，船挖 Ship Laser Ores）

百分比是 SCMiner 页面上的原值，含义是该矿在这个地点的出现概率（用户确认）；
各矿独立计算，所以同一地点加起来不等于 100%。
"""
import re

# 地点|母星|星系|类型|矿物 百分比;…（SCMiner 原文，Aluminium 统一写成 Aluminum）
_RAW = """
Aaron Halo|Stanton Star|Stanton|Belt|Beryl 18;Agricium 14;Aslarite 14;Titanium 14;Ice 10;Aluminum 10;Copper 10;Corundum 10;Hephaestanite 10;Iron 10;Silicon 10;Tin 10;Quantainium 2
Aberdeen|Hurston|Stanton|Moon|Aluminum 30;Corundum 30;Agricium 29;Aslarite 29;Titanium 29;Ouratite 10;Beryl 2;Quantainium 2
Akiro Cluster|Pyro Star|Pyro|Belt|Torite 29;Copper 15;Hephaestanite 15;Ice 15;Silicon 15;Tin 15;Iron 15;Laranite 10;Riccite 10;Stileron 2;Taranite 2
ARC-L1|ArcCorp|Stanton|Belt|Tungsten 20;Taranite 13;Corundum 12;Aluminum 12;Hephaestanite 12
ARC-L2|ArcCorp|Stanton|Belt|Tungsten 20;Taranite 13;Corundum 12;Aluminum 12;Hephaestanite 12
ARC-L3|ArcCorp|Stanton|Belt|Agricium 9;Beryl 6;Iron 6;Copper 6;Ice 6
ARC-L4|ArcCorp|Stanton|Belt|Tungsten 20;Taranite 13;Corundum 12;Aluminum 12;Hephaestanite 12
ARC-L5|ArcCorp|Stanton|Belt|Aslarite 16;Gold 10;Iron 10;Copper 10;Ice 10
Arial|Hurston|Stanton|Moon|Aluminum 22;Copper 22;Corundum 22;Hephaestanite 22;Quartz 22;Silicon 22;Tin 22;Agricium 10;Ouratite 10;Beryl 2;Quantainium 2
Breaker Stations Large Geode|Nyx Star|Nyx|Moon|Savrilium 100;Torite 100
Calliope|microTech|Stanton|Moon|Iron 33;Hephaestanite 33;Ice 33;Quartz 33;Silicon 33;Beryl 2;Quantainium 2
Cellin|Crusader|Stanton|Moon|Agricium 29;Aslarite 29;Titanium 29;Hephaestanite 26;Silicon 26;Quartz 26;Taranite 18;Beryl 2;Quantainium 2
Clio|microTech|Stanton|Moon|Copper 40;Ice 40;Tin 40;Taranite 18;Beryl 2;Quantainium 2
CRU-L1|Crusader|Stanton|Belt|Titanium 15;Bexalite 10;Iron 9;Copper 9;Ice 9
CRU-L2|Crusader|Stanton|Belt|Titanium 15;Bexalite 10;Iron 9;Copper 9;Ice 9
CRU-L3|Crusader|Stanton|Belt|Torite 11;Aluminum 9;Corundum 9;Hephaestanite 9
CRU-L4|Crusader|Stanton|Belt|Aslarite 16;Gold 10;Iron 10;Copper 10;Ice 10
CRU-L5|Crusader|Stanton|Belt|Agricium 9;Beryl 6;Iron 6;Copper 6;Ice 6
Daymar|Crusader|Stanton|Moon|Hephaestanite 35;Silicon 35;Quartz 35;Agricium 29;Aslarite 29;Titanium 29;Beryl 2;Quantainium 2
Euterpe|microTech|Stanton|Moon|Copper 40;Ice 40;Tin 40;Taranite 18;Beryl 2;Quantainium 2
Glaciem Ring|Nyx Star|Nyx|Belt|Torite 29;Ice 21;Iron 21;Bexalite 18;Borase 18;Gold 18;Lindinium 10;Tungsten 10;Savrilium 2
HUR-L1|Hurston|Stanton|Belt|Laranite 13;Borase 8;Aluminum 8;Corundum 8;Hephaestanite 8
HUR-L2|Hurston|Stanton|Belt|Tungsten 20;Taranite 13;Corundum 12;Aluminum 12;Hephaestanite 12
HUR-L3|Hurston|Stanton|Belt|Titanium 15;Bexalite 10;Iron 9;Copper 9;Ice 9
HUR-L4|Hurston|Stanton|Belt|Laranite 13;Borase 8;Aluminum 8;Corundum 8;Hephaestanite 8
HUR-L5|Hurston|Stanton|Belt|Torite 11;Aluminum 9;Corundum 9;Hephaestanite 9
Hurston|Stanton Star|Stanton|Planet|Aluminum 44;Copper 44;Corundum 44;Tin 44;Agricium 10;Ouratite 10;Beryl 2;Quantainium 2
Ita|Hurston|Stanton|Moon|Copper 35;Tin 35;Aluminum 35;Corundum 35;Agricium 29;Aslarite 29;Titanium 29;Beryl 2;Quantainium 2
Keeger Belt|Nyx Star|Nyx|Belt|Torite 29;Aluminum 21;Corundum 21;Ice 21;Bexalite 18;Borase 18;Gold 18;Lindinium 10;Tungsten 10;Savrilium 2
Lyria|ArcCorp|Stanton|Moon|Copper 35;Iron 35;Tin 35;Laranite 28;Tungsten 28;Beryl 2;Quantainium 2
Magda|Hurston|Stanton|Moon|Aluminum 35;Corundum 35;Iron 35;Agricium 14;Aslarite 14;Titanium 14;Beryl 2;Quantainium 2
MIC-L1|microTech|Stanton|Belt|Torite 11;Aluminum 9;Corundum 9;Hephaestanite 9
MIC-L2|microTech|Stanton|Belt|Torite 11;Aluminum 9;Corundum 9;Hephaestanite 9
MIC-L3|microTech|Stanton|Belt|Aslarite 16;Gold 10;Iron 10;Copper 10;Ice 10
MIC-L4|microTech|Stanton|Belt|Agricium 9;Beryl 6;Iron 6;Copper 6;Ice 6
MIC-L5|microTech|Stanton|Belt|Torite 11;Aluminum 9;Corundum 9;Hephaestanite 9
microTech|Stanton Star|Stanton|Planet|Hephaestanite 33;Ice 33;Quartz 33;Silicon 33;Iron 33;Beryl 2;Quantainium 2
Pyro I|Pyro Star|Pyro|Planet|Iron 33;Copper 33;Tin 33;Stileron 2;Taranite 2
Pyro II (Monox)|Pyro Star|Pyro|Planet|Hephaestanite 33;Quartz 33;Silicon 33;Copper 33;Iron 33;Tin 33;Stileron 2;Taranite 2
Pyro III (Bloom)|Pyro Star|Pyro|Planet|Hephaestanite 35;Iron 35;Quartz 35;Silicon 35;Bexalite 18;Borase 18;Gold 18;Laranite 10;Riccite 10;Stileron 2;Taranite 2
Pyro IV|Pyro Star|Pyro|Planet|Laranite 29;Tungsten 29;Copper 26;Iron 26;Tin 26;Bexalite 18;Borase 18;Gold 18;Stileron 2;Taranite 2
Pyro V-a (Ignis)|Pyro V|Pyro|Moon|Copper 36;Hephaestanite 36;Silicon 36;Tin 36;Bexalite 18;Borase 18;Gold 18;Laranite 10;Riccite 10
Pyro V-b (Vatra)|Pyro V|Pyro|Moon|Hephaestanite 36;Iron 36;Silicon 36;Bexalite 18;Borase 18;Gold 18;Laranite 10;Riccite 10
Pyro V-c (Adir)|Pyro V|Pyro|Moon|Iron 44;Laranite 29;Tungsten 29;Bexalite 18;Borase 18;Gold 18;Riccite 10
Pyro V-d (Fairo)|Pyro V|Pyro|Moon|Laranite 29;Tungsten 29;Hephaestanite 27;Silicon 27;Iron 27;Bexalite 9;Borase 9;Gold 9
Pyro V-e (Fuego)|Pyro V|Pyro|Moon|Agricium 29;Aslarite 29;Titanium 29;Iron 27;Hephaestanite 27;Quartz 27;Silicon 27;Bexalite 9;Borase 9;Gold 9
Pyro V-f (Vuur)|Pyro V|Pyro|Moon|Hephaestanite 27;Iron 27;Quartz 27;Silicon 27;Bexalite 18;Borase 18;Gold 18;Agricium 14;Aslarite 14;Titanium 14
Pyro VI (Terminus)|Pyro Star|Pyro|Planet|Copper 21;Ice 21;Tin 21;Bexalite 18;Borase 18;Gold 18;Agricium 14;Aslarite 14;Titanium 14;Laranite 10;Riccite 10;Stileron 2;Taranite 2
Wala|ArcCorp|Stanton|Moon|Laranite 29;Tungsten 29;Copper 26;Tin 26;Iron 26;Beryl 18;Quantainium 2
Yela|Crusader|Stanton|Moon|Agricium 29;Aslarite 29;Titanium 29;Hephaestanite 26;Silicon 26;Quartz 26;Taranite 18;Beryl 2;Quantainium 2
Yela Asteroid Belt|Stanton Star|Stanton|Belt|Agricium 29;Aslarite 29;Titanium 29;Copper 21;Ice 21;Iron 21;Tin 21;Ouratite 10
"""

# 中文名（来自用户的汉化包）
_ZH = {
    "Hurston": "赫斯顿", "Arial": "艾瑞尔", "Aberdeen": "阿伯丁", "Magda": "玛格达", "Ita": "依塔",
    "Crusader": "十字军", "Cellin": "赛琳", "Daymar": "戴玛尔", "Yela": "耶拉",
    "ArcCorp": "弧光星", "Lyria": "莉瑞雅", "Wala": "瓦菈",
    "microTech": "微科星", "Calliope": "卡利俄佩", "Clio": "克利俄", "Euterpe": "欧忒耳佩",
    "Aaron Halo": "亚伦环", "Yela Asteroid Belt": "耶拉小行星带",
    "Pyro I": "派罗 I", "Pyro II (Monox)": "殁氧星（派罗 II）", "Pyro III (Bloom)": "盛放星（派罗 III）",
    "Pyro IV": "派罗 IV", "Pyro VI (Terminus)": "端点星（派罗 VI）",
    "Pyro V-a (Ignis)": "伊格尼斯（派罗 V-a）", "Pyro V-b (Vatra)": "瓦塔拉（派罗 V-b）",
    "Pyro V-c (Adir)": "阿迪尔（派罗 V-c）", "Pyro V-d (Fairo)": "法伊罗（派罗 V-d）",
    "Pyro V-e (Fuego)": "弗果（派罗 V-e）", "Pyro V-f (Vuur)": "伏尔（派罗 V-f）",
    "Akiro Cluster": "阿克罗团", "Glaciem Ring": "冰川环带", "Keeger Belt": "基格小行星带",
    "Breaker Stations Large Geode": "Breaker 站大晶洞",
    "Hathor Caves": "校准站矿洞", "Breaker Stations Interior": "Breaker 站内部",
}
_NO_EN = {"Hathor Caves"}          # 只写中文（用户 2026-10-25：Hathor 矿洞写成「校准站矿洞」）
_SYS_ZH = {"Stanton": "斯坦顿", "Pyro": "派罗", "Nyx": "尼克斯"}
_TYPE_ZH = {"Belt": "小行星带", "Moon": "卫星地表", "Planet": "行星地表", "Cave": "矿洞", "Interior": "空间站内部"}


def _parse():
    out = []
    for line in _RAW.strip().splitlines():
        name, parent, system, kind, ores = line.split("|")
        minerals = {}
        for item in ores.split(";"):
            m, pct = item.rsplit(" ", 1)
            minerals[m] = float(pct)
        out.append(dict(name=name, parent=parent, system=system, kind=kind, minerals=minerals))
    return out


LOCATIONS = _parse()


def zh_name(loc) -> str:
    name = loc["name"]
    if m := re.fullmatch(r"(ARC|CRU|HUR|MIC)-(L\d)", name):
        return f"{_ZH.get(loc['parent'], loc['parent'])} {m.group(2)} 拉格朗日点（{name}）"
    zh = _ZH.get(name)
    if name in _NO_EN:
        return zh
    return f"{zh}（{name}）" if zh and "（" not in zh and zh != name else (zh or name)


def _gem_rows(mineral, system=None):
    """地面小矿（gems.py）的地点，做成和飞船矿一样的地点 dict；矿洞、空间站内部不在飞船矿地点表里"""
    from .gems import GEMS
    by_name = {loc["name"]: loc for loc in LOCATIONS}
    rows = []
    for name, sys_, pct in GEMS[mineral]["locs"]:
        if system and sys_ != system:
            continue
        base = by_name.get(name)
        kind = base["kind"] if base else ("Cave" if "Cave" in name else "Interior")
        rows.append((pct, dict(name=name, parent=base["parent"] if base else "", system=sys_, kind=kind, minerals={})))
    return rows


def where(mineral: str, system: str | None = None):
    """返回 [(百分比, 地点dict)]，按百分比从高到低；同百分比时，同场竞争矿物少的排前"""
    from .gems import GEMS
    if mineral in GEMS:
        return _gem_rows(mineral, system)
    rows = []
    for loc in LOCATIONS:
        if system and loc["system"] != system:
            continue
        pct = loc["minerals"].get(mineral)
        if pct:
            rows.append((pct, loc))
    rows.sort(key=lambda r: (-r[0], len(r[1]["minerals"])))
    return rows


def report(mineral: str, top: int = 8) -> str:
    """一段中文报告：推荐地点、同场的值钱矿、最佳精炼站、卖到哪"""
    from .data import best_price, REFINERIES, RARITY
    from ..core.i18n import station_zh
    from ..core.i18n import mineral_zh
    rows = where(mineral)
    zh = mineral_zh(mineral)
    if not rows:
        return f"{zh}：SCMiner 的船挖地点数据里没有这种矿。"
    price, city = best_price(mineral)
    lines = [f"【{zh}】{RARITY.get(mineral, '')}｜精炼后 {price:,}/SCU（{city or '无收购'}）",
             f"共 {len(rows)} 个地点有，按出现概率排序："]
    for pct, loc in rows[:top]:
        others = sorted(((best_price(m)[0], m) for m in loc["minerals"] if m != mineral), reverse=True)[:3]
        extra = "、".join(mineral_zh(m) for p, m in others if p)
        lines.append(f"  {pct:>4.0f}%  {zh_name(loc)}｜{_SYS_ZH[loc['system']]} · {_TYPE_ZH[loc['kind']]}"
                     + (f"｜同场值钱的：{extra}" if extra else ""))
    if len(rows) > top:
        lines.append(f"  …另有 {len(rows) - top} 个地点概率更低")
    bonus = sorted(((b.get(mineral, 0), st, sys_) for st, (sys_, b) in REFINERIES.items()), reverse=True)
    best = [f"{station_zh(st)} {b:+.0f}%" for b, st, _ in bonus[:3] if b > 0]
    lines.append("精炼加成最高：" + "，".join(best) if best else "无可用精炼加成")
    try:
        from ..crafting.crafting import uses, GEAR_ZH
        from collections import Counter
        kinds = Counter(GEAR_ZH.get((bp["g"], bp["t"]), bp["t"]) for bp, _, _ in uses(mineral))
        if kinds:
            lines.append(f"制造用途：{sum(kinds.values())} 份蓝图（"
                         + "、".join(f"{k} {n}" for k, n in kinds.most_common(4)) + "），菜单 3 可查详情")
    except Exception:
        pass
    return "\n".join(lines)


def ask():
    """交互：输入矿名（中文或英文，可一次输入多个，用空格或逗号分开）"""
    from .data import SIGNATURES
    from ..core.i18n import mineral_en
    en_names = {k.lower(): k for k in SIGNATURES}
    print("输入想挖的矿（中文或英文，可多个，用空格分开），直接回车退出。例：量子 金 钨\n")
    while True:
        try:
            raw = input("> ").strip()
        except EOFError:
            return
        if not raw:
            return
        for token in re.split(r"[\s,，、]+", raw):
            m = en_names.get(token.lower()) or _match_zh(token)
            print(report(m) if m else f"{token}：认不出这个矿名", end="\n\n")


def _match_zh(token):
    """中文矿名：先精确/模糊匹配，再按"包含"匹配（如 "量子" → 量子矿物）"""
    from ..core.i18n import mineral_en, _tables
    hit = mineral_en(token)
    if hit:
        return hit
    zh2en, _ = _tables(True)
    cands = {en for zh, en in zh2en.items() if token in zh}
    return cands.pop() if len(cands) == 1 else None
