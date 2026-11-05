"""维科洛（Wikelo）兑换：每个兑换要交哪些材料、换来什么；某样东西能拿去换什么

数据来自 scmdb 的任务数据（和制造蓝图同一份 merged-*.json），中文名来自用户的汉化包。
菜单 5 更新制造数据时会一起重建 wikelo.json。
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
from ..contracts.textkeys import fold_mixed_loose as _fold  # noqa: E402
from ..core.paths import DATA  # noqa: E402

OUT = DATA / "wikelo.json"
TYPE_ZH = {
    "Wikelo - Vehicles": "载具",
    "Wikelo - Other Items": "装备/物品",
    "Collection": "收集",
}
# 汉化包里没有中文名、或者需要说明来源的材料（游戏里 RCMBNT 本身就显示英文代号）
NOTES = {
    "RCMBNT-": (
        "重组样本",
        "玛瑙设施（Onyx Facility）任务里在终端合成：催化剂 XTL/PWL/RGL 配反应物，"
        "做出的样本送到设施货梯",
    ),
    "Wikelo Favor": ("维科洛人情", "做维科洛的「换人情」兑换拿到"),
}


# 掉落数据里没有、或者开箱只是次要来源的材料：主要来源（星际公民维基 starcitizen.tools 等，2026-10-23 查）
# 标「未核实」的是维基没写清楚、按最可能的来源写的；珍珠、科力晶和三种 PAF 矿、堂会凭证、两种勋章由用户 2026-10-23 核实
SOURCES = {
    "Vanduul Metal": "尼克斯（Nyx）星系的剜度飞行员尸体上搜；「剜度科技走私者」任务目标",
    "Vanduul Plating": "尼克斯（Nyx）星系的剜度飞行员尸体上搜；「剜度科技走私者」任务目标",
    "ASD Secure Drive": "玛瑙设施（ASD Onyx Facility）的 Jorrit 卷宗调查任务奖励（电力/能量异常/安保/地震数据），寄到你的家",
    "Irradiated Valakkar Pearl (Grade AAA)": "「风暴突破者」活动产出（派罗 I 辐射风暴里的受辐射瓦拉卡）",
    "Irradiated Valakkar Pearl (Grade AA)": "「风暴突破者」活动产出（派罗 I 辐射风暴里的受辐射瓦拉卡）",
    "Irradiated Valakkar Fang (Juvenile)": "派罗 I（Pyro I）辐射风暴里的幼年受辐射瓦拉卡，打死后从嘴里取，地上也能捡到脱落的牙",
    "Irradiated Valakkar Fang (Adult)": "派罗 I（Pyro I）辐射风暴里的成年受辐射瓦拉卡，打死后从嘴里取",
    "Irradiated Valakkar Fang (Apex)": "派罗 I（Pyro I）辐射风暴里的巅峰期受辐射瓦拉卡，打死后从嘴里取",
    "Yormandi Eye": "玛瑙设施 B 区地下挖掘洞穴的约曼迪 Boss：拉气闸旁的拉杆开打，打死后取；琥珀色灯亮前离开，否则掉落会被毁",
    "Yormandi Tongue": "玛瑙设施 B 区地下挖掘洞穴的约曼迪 Boss：拉气闸旁的拉杆开打，打死后取；琥珀色灯亮前离开，否则掉落会被毁",
    "DCHS-05 Orbital Positioning Comp-Board": "派罗的废墟站（Ruin Station）宝库，要地穴钥匙卡（在地穴里打印，冷却 30 分钟）",
    "Metamaterial Test #146": "只能制造：接维科洛「Extra Special Wolf」兑换得到蓝图，要钛 Q≥900、愈金 Q≥800",
    "Metamaterial Test #152": "只能制造：接维科洛「Extra Special Wolf」兑换得到蓝图，要钛 Q≥900、愈金 Q≥800、约曼迪之眼 ×4",
    "Polaris Bit": "维科洛「Want Polaris?」兑换的奖励：把量子矿物（约 24 个换 1 个）交到任务指定的维科洛商店（Dasi / Selo / Kinga）",
    "MG Scrip": "雇佣兵公会任务奖励，也能开箱拿到；50 个可换 1 个维科洛人情",
    "Council Scrip": "SoO 的奥里森突袭任务（4.10）奖励，也能开箱拿到；50 个可换 1 个维科洛人情",
    "Carinite (Pure)": "激光校准站（PAF）开启后的矿洞里挖（阿伯丁、戴马尔的 Hathor 轨道激光），稀有，信号 3,000（手采）",
    "Carinite": "只在激光校准站（PAF）开启后的矿洞里挖（阿伯丁、戴马尔的 Hathor 轨道激光），信号 3,000（手采）",
    "Jaclium (Ore)": "激光校准站（PAF）开启后的矿洞里挖；斯坦顿可卖到 ArcCorp 045 号采矿区、HDMS-Norgaard / Anderson",
    "Saldynium (Ore)": "激光校准站（PAF）开启后的矿洞里挖，信号 3,000",
    "Sadaryx": "激光校准站（PAF）开启后的矿洞里挖；尼克斯 Castra 门户站可精炼",
    "Expired Quantanium Fuel Canister": "「寻找战术打击群」任务里，QV 采矿站的 A 号货仓",
    "Bluemoon Fungus": "采集：派罗（灰原、废弃前哨站、落日台地等）和斯坦顿（Dunboro、Jumptown、Paradise Cove、玛瑙设施等）",
    "Tundra Kopion Horn": "微科星（microTech）雪地低地旁草原上的苔原寇骈犬，打死后取角",
    "Irradiated Kopion Horn": "玛瑙设施（ASD）研究层下层逃出来的受辐射寇骈犬，打死后取角",
    "Large Artifact Fragment (Pristine)": "尼克斯 QV 站的仓库区开箱",
    "Government Cartography Agency Medal (Pristine)": "雇佣兵巡逻任务里的王牌飞行员（Ace Pilot）尸体上搜",
    "UEE 6th Platoon Medal (Pristine)": "王牌飞行员（Ace Pilot）尸体上大概率刷；蓝色箱子里也会掉",
    "Tevarin War Service Marker (Pristine)": "王牌飞行员（Ace Pilot）尸体上大概率刷；蓝色箱子里也会掉",
    "Ace Interceptor Helmet": "王牌飞行员（Ace Pilot）尸体上搜，或 PAF 据点的护甲箱",
    "Argo ATLS": "商店买：罗威尔 Teasa 太空港 New Deal 最便宜（约 7.2 万 aUEC）；A18 Astro Armada、废墟站 Buy and Fly 等也有",
}


def note_for(name):
    for prefix, v in NOTES.items():
        if name.startswith(prefix):
            return v
    return None


def make_data(merged_path, names_path):
    """merged-*.json + 汉化名 → wikelo.json 的内容（只算不写，不拿锁）"""
    from .build_crafting import _load_names, _item_names

    merged = json.loads(Path(merged_path).read_text(encoding="utf-8"))
    ini, items = _load_names(names_path)
    en2zh = _item_names(items)
    pools = merged.get("resourcePools") or {}

    def text(key):
        v = ini.get((key or "").lstrip("@").lower(), "")
        return re.sub(r"<[^>]+>", "", v)

    # 汉化包里所有「中文 + 英文名」格式的文本都拿来对照（任务道具不在物品表里，比如 ASD 安全驱动器、维科洛人情）
    any_en = {}
    for v in ini.values():
        v = re.sub(r"<[^>]+>", "", v)
        m = re.fullmatch(
            r"(.*?[\u4e00-\u9fff][^\\]*?)\s*(?:\\n)?([A-Za-z][\x20-\x7e]*)", v.strip()
        )
        if m and len(m.group(2)) > 2:
            any_en.setdefault(m.group(2).strip().lower(), m.group(1).strip())

    def zh_of(name, key=None):
        if note_for(name):
            return note_for(name)[0]
        z = text(key) if key else ""
        if z:  # 「幽影 臂甲 ASD 版\nGeist Armor Arms ASD Edition」→ 只留中文名（2026-10-28 改用和蓝图一样的 _strip_en，不在第一个英文字母处截断）
            from .build_crafting import _strip_en

            first, _, rest = z.partition("\\n")
            return (_strip_en(first.strip(), rest.strip(), name) or first).strip()
        return (
            en2zh.get(name.lower())
            or en2zh.get(name.lower().replace("-", ""))
            or any_en.get(name.lower(), "")
        )

    out_rows = []
    for c in merged.get("contracts") or []:
        if (
            "wikelo" not in (c.get("contractorName") or "").lower()
        ):  # scmdb 写 Wikelo，游戏数据写 Wikelo Emporium（2026-10-28）
            continue
        req = []
        for h in c.get("haulingOrders") or []:
            pool = pools.get(h.get("resource"), {})
            name = pool.get("name") or h.get("resource")
            if "minSCU" in h:
                qty, unit = h.get("minSCU") or 0, "SCU"
            else:
                qty, unit = max(h.get("minAmount") or 0, h.get("maxAmount") or 0), "个"
            req.append(
                {"n": name, "z": zh_of(name, pool.get("nameKey")), "q": qty, "u": unit}
            )
        rewards = []
        for r in c.get("itemRewards") or []:
            if r.get("name"):
                rewards.append(r["name"])
            for g in r.get("groups") or []:
                rewards += [i["name"] for i in g.get("items") or [] if i.get("name")]
        title_raw = text(c.get("titleLocKey") or c.get("titleKey"))
        title_zh, _, bracket = title_raw.partition("\\n")
        reward_zh = re.sub(r"^\[兑换\s*-\s*|\]$", "", bracket.strip())
        out_rows.append(
            {
                "id": c.get("debugName") or c.get("id"),
                "type": TYPE_ZH.get(c.get("missionType"), c.get("missionType")),
                "t": title_zh.strip() or c.get("title", ""),
                "te": c.get("title", ""),
                "rz": reward_zh,
                "rewards": rewards,
                "req": req,
                "systems": c.get("availableSystems") or c.get("systems") or [],
            }
        )
    out_rows.sort(key=lambda r: (r["type"], r["te"]))
    return {"version": merged.get("version"), "contracts": out_rows}


def build(merged_path, names_path, out=OUT):
    """merged-*.json + 汉化名 → wikelo.json（算好再在更新边界里写）；返回兑换个数"""
    data = make_data(merged_path, names_path)
    _write(out, data)
    return len(data["contracts"])


def _write(out, data):
    """写 wikelo.json（游戏数据库的源）：write_json 临时文件再换名（换名撞上占用会重试）；
    在更新边界里写（updating 在外、BUILD_LOCK 在内），出口重建一次库"""
    from .. import gamedata
    from ..core.paths import write_json
    from .build_crafting import BUILD_LOCK

    with gamedata.updating(), BUILD_LOCK:
        write_json(out, data, separators=(",", ":"))


def load():
    """全部兑换（wikelo.json 的 contracts 同形，按源顺序；材料中文名已去掉末尾的反斜杠）。同一内容版本内是同一个列表；
    库不可用当成没有兑换"""
    from .. import gamedata

    try:
        return gamedata.wikelo.contracts()
    except gamedata.GamedataError:
        return []


def _same(a, b):
    fa, fb = _fold(a), _fold(b)
    return bool(fa and fb) and (
        fa == fb or (len(fb) >= 4 and fb in fa) or (len(fa) >= 4 and fa in fb)
    )


def uses(name_en="", name_zh=""):
    """这样东西（英文名/中文名）在哪些兑换里要用：[(兑换, 需要的数量, 单位)]"""
    from .. import gamedata

    fe, fz = _fold(name_en), _fold(name_zh)
    try:  # 先按折叠名相等：库里按比较键筛（norm_n / norm_z），再照原条件核一遍（中文名去掉反斜杠后为空的不算）
        pairs = gamedata.wikelo.requiring(
            fe if name_en else None, fz if name_zh else None
        )
    except gamedata.GamedataError:
        return []
    hits = [
        (c, r["q"], r["u"])
        for c, r in pairs
        if (name_en and _fold(r["n"]) == fe)
        or (name_zh and r["z"] and _fold(r["z"]) == fz)
    ]
    if not hits:  # 名字被 OCR 截断时放宽成包含
        for c in load():
            for r in c["req"]:
                if (name_en and _same(r["n"], name_en)) or (
                    name_zh and r["z"] and _same(r["z"], name_zh)
                ):
                    hits.append((c, r["q"], r["u"]))
    return hits


def search(text):
    """按兑换名/奖励名/材料名搜兑换"""
    t = _fold(text)
    if not t:
        return load()
    out = []
    for c in load():
        hay = _fold(
            " ".join(
                [
                    c["t"],
                    c["te"],
                    c["rz"],
                    *c["rewards"],
                    *(r["n"] + r["z"] for r in c["req"]),
                ]
            )
        )
        if t in hay:
            out.append(c)
    return out


def req_label(r):
    return f"{r['z']}（{r['n']}）" if r["z"] else r["n"]


def print_spots(name):
    """打印机打印的物品在哪打（print_spots.json，由数据构建脚本从游戏数据生成，2026-10-27；读库）→ [地点]，不分大小写"""
    from .. import gamedata

    try:
        return gamedata.wikelo.print_places((name or "").strip().lower())
    except gamedata.GamedataError:
        return []


def source_note(name):
    n = note_for(name)
    if n:
        return n[1]
    w = [x for x in print_spots(name) if isinstance(x, str) and x]
    if (
        name in SOURCES
    ):  # 手写说明（如 DCHS-05 宝库）+ 有打印地点也写上（二审 2026-10-27）
        return SOURCES[name] + ("；打印：" + "；".join(w) if w else "")
    if w:
        return "打印：" + "；".join(w)
    if (
        (name or "").upper().startswith("DCHS-")
    ):  # 负责人 2026-10-27：DCHS 计算板是派罗争夺区打印的（数据包里没有地点时的兜底）
        return "派罗争夺区（Contested Zone）内打印"
    return ""


def describe(c, where=None):
    """一个兑换的完整说明；where(英文名) 返回去哪弄的一行说明（可选）"""
    reward = c["rz"] or "、".join(c["rewards"][:4]) or c["te"]
    lines = [f"【{c['t']}】{c['type']}｜换：{reward}"]
    # 同类材料（比如 9 种重组样本各 5 个）合成一行，免得刷屏
    groups = []
    for r in c["req"]:
        key = (r["z"], r["q"], r["u"]) if note_for(r["n"]) else (r["n"],)
        if groups and groups[-1][0] == key:
            groups[-1][1].append(r)
        else:
            groups.append((key, [r]))
    for _, rs in groups:
        r = rs[0]
        q = f"{r['q']:g} {r['u']}" if r["q"] else "若干"
        tip = where(r["n"]) if where else ""
        if len(rs) > 1:
            label = f"{r['z']}（{'、'.join(x['n'] for x in rs)}）"
            lines.append(f"  · {label} 各 × {q}" + (f"｜{tip}" if tip else ""))
        else:
            lines.append(f"  · {req_label(r)} × {q}" + (f"｜{tip}" if tip else ""))
    return "\n".join(lines)


def uses_text(name_en, name_zh=""):
    hits = uses(name_en, name_zh)
    if not hits:
        return ""
    parts = [f"{c['t']}（{q:g}{'' if u == '个' else ' ' + u}）" for c, q, u in hits[:5]]
    more = f" 等 {len(hits)} 个" if len(hits) > 5 else ""
    return "维科洛兑换要用：" + "，".join(parts) + more
