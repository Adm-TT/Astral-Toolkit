"""地名翻译、中文名称对照表与标准化规则模块（Navigation: Names & Localization）

提供：
1. 星体、跳跃点、设施、类型、城区的中文与双语映射对照表（BODY_ZH、TYPE_ZH、QT_ZH、CITY_ZH 等）；
2. 汉化包地名动态更新对照（poi_zh）；
3. 地表洞穴、飞船残骸、前哨站等社区命名的规则式翻译（rule_zh）；
4. 地点与天体友好显示名称生成（label、body_label、point_zh）。
"""

import re

from .. import gamedata

# POI 接口里的星球名 → 星体接口里的名字
_POI_BODY = {"microTech": "Microtech", "Pyro V": "Pyro5"}

BODY_ZH = {
    "Hurston": "赫斯顿",
    "Arial": "艾瑞尔",
    "Aberdeen": "阿伯丁",
    "Magda": "玛格达",
    "Ita": "依塔",
    "Crusader": "十字军",
    "Cellin": "赛琳",
    "Daymar": "戴玛尔",
    "Yela": "耶拉",
    "ArcCorp": "弧光星",
    "Lyria": "莉瑞雅",
    "Wala": "瓦菈",
    "Microtech": "微科星",
    "Calliope": "卡利俄佩",
    "Clio": "克利俄",
    "Euterpe": "欧忒耳佩",
    "Pyro1": "派罗 I",
    "Monox": "殁氧星",
    "Bloom": "盛放星",
    "Pyro4": "派罗 IV",
    "Pyro5": "派罗 V",
    "Terminus": "端点星",
    "Ignis": "伊格尼斯",
    "Vatra": "瓦塔拉",
    "Adir": "阿迪尔",
    "Fairo": "法伊罗",
    "Fuego": "弗果",
    "Vuur": "伏尔",
    "Delamar": "德拉玛",
}

TYPE_ZH = {
    "Mining Spot": "挖矿点",
    "City": "城里",
    "Cave": "洞穴",
    "Wreck": "残骸",
    "Outpost": "前哨站",
    "Derelict Outpost": "废弃前哨",
    "Derelict Settlement": "废弃定居点",
    "Abandoned Outpost": "废弃前哨",
    "Underground Facility": "地下设施",
    "Security Outpost": "安保哨站",
    "Onyx Facility": "玛瑙设施",
    "Druglab": "毒品实验室",
    "Colonial Outpost": "殖民前哨",
    "Colonial Bunker": "殖民地堡",
    "Forward Operating Base": "前线基地",
    "Distribution Center": "物流中心",
    "Landing Zone": "主城",
    "LandingZone": "主城",
    "Spaceport": "太空港",
    "Orbital Station": "轨道站",
    "RestStop": "休息站",
    "Comm Array": "通讯阵列",
    "River": "河流",
    "Scrapyard": "废料场",
    "Racetrack": "赛道",
    "Racetrack (Community)": "赛道（玩家）",
    "Animal Area": "动物区",
    "Mission Area": "任务区",
    "Prison": "监狱",
    "Easteregg": "彩蛋",
    "Event": "活动",
    "Planetary Alignment Facility": "行星校准设施",
    "Orbital Laser Platform": "轨道激光平台",
    "Ground Activation Platform": "地面激活平台",
    "AsteroidBase": "小行星基地",
    "Asteroid Belt": "小行星带",
    "Object Container": "容器",
    "Location": "地点",
    "Unknown": "未知",
    "": "其他",
    "Waypoint": "路标",
}

QT_ZH = {1: "有信标", 0: "无信标"}

POINT_ZH = {
    "Lagrange Point": "拉格朗日点",
    "Jumppoint": "跳跃点",
    "Star": "恒星",
    "Naval Station": "海军站",
}

CITY_ZH = {
    "NewBabbage": "新巴贝奇",
    "Lorville": "罗威尔",
    "Area18": "18区",
    "Orison": "奥里森",
    "Levski": "列夫斯基",
}

SYS_ZH = {"Stanton": "斯坦顿", "Pyro": "派罗", "Nyx": "尼克斯"}

_RR = {"1": "HUR", "2": "CRU", "3": "ARC", "4": "MIC"}  # 斯坦顿几号星 → 空间站代码


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def poi_zh(name: str) -> str:
    """地点英文名 → 汉化包里的中文名（没有就返回空字符串）。查游戏数据库的地名表：places_extra_zh（从游戏数据对出的
    汉化名，汉化包里中文不带英文的地名，如采矿基地 #IGB-FXW）盖过 places_zh（二审 2026-10-27）；库不可用当作没有"""
    base = re.sub(
        r"\s*[\[(].*?[\])]\s*", " ", name
    ).strip()  # 去掉 "[F]" "(missing)" 之类的备注
    try:
        table = gamedata.places.poi_names()
    except gamedata.GamedataError:
        return ""
    return table.get(_norm(name)) or table.get(_norm(base)) or ""


# 洞穴、前哨这类社区起的名字（星图数据里约 1400 个，汉化包里没有）：按规则翻，编号原样保留
_RULE_HEAD = [
    (r"Rock ?Cave", "岩石洞穴"),
    (r"Sand ?Cave", "沙地洞穴"),
    (r"Acidic ?Cave", "酸性洞穴"),
    (r"Unknown ?Cave", "未知洞穴"),
    (r"Cave", "洞穴"),
    (r"River", "河流"),
    (r"Remote Outpost", "偏远前哨站"),
    (r"Abandoned Outpost", "废弃前哨站"),
    (r"Derelict ?Outpost", "废弃前哨站"),
    (r"Colonial Outpost XS", "小型殖民前哨站"),
    (r"Colonial Outpost", "殖民前哨站"),
    (r"Colonial Bunker", "殖民地地堡"),
    (r"Frontier Fighters Hideout", "边境战士藏身处"),
    (r"Comm Array", "通讯阵列"),
    (r"AsteroidArena", "小行星竞技场"),
    (r"Mining Tower", "采矿塔"),
    (r"Kopion Lab", "科皮翁实验室"),
    (r"Valakkar Apex Spawn Area", "瓦拉卡巨兽出没区"),
    (r"Crashed Satel+ite", "坠毁卫星"),
    (r"a Private Landing Pad", "私人停机坪"),
    (r"OC_EscortMissionMarkup-?", "护送任务点 "),
    (r"EscortMission", "护送任务点"),
    (r"Scrapyard", "废料场"),
]

_RULE_TAIL = [
    (r"[,\s]*[\[(]?\b(?:Fauna|F)\b[\])]?", "（有动物）"),
    (r"[,\s]*\(?\bUnoccupied\b\)?", "（无人）"),
    (r"[,\s]*\(?\bOccupied\b\)?", "（有人）"),
    (r"[,\s]*\bAbandoned\b", "（废弃）"),
    (r"[,\s]*\[Foot\]", "（步行）"),
    (r"\bSize\s*(\d)", r"规模 \1"),
]

_WRECK = re.compile(
    r"^(?P<ship>[A-Z][A-Za-z]+)(?:\s+(?P<tail>Derelict|Wreck))?(?P<rest>[\s#\dA-Z]*?)$"
)

# 星图里的飞船残骸只写了型号（汉化包 vehicle_Name… 里的叫法，去掉厂商）
_SHIP_ZH = {
    "starfarer": "星际远航者",
    "cutlass": "弯刀",
    "caterpillar": "毛虫",
    "freelancer": "自由枪骑兵",
    "constellation": "星座",
    "reclaimer": "回收者",
    "hull": "货轮",
    "prospector": "勘探者",
    "mole": "鼹鼠",
}

_SEGMENT = [  # 尼克斯小行星带的分段（星图里是内部名字；冰川环带、基格小行星带是汉化组的，「区段」这些自译，2026-10-27）
    (r"Glaciemring_Segment_Wtn-(\d+)", "冰川环带 区段 Wtn-{0}"),
    (
        r"Glaciemring_Segment_Mission_Genrl_(\d+)_(\d+)_Fstreamable",
        "冰川环带 任务区段 {0}-{1}",
    ),
    (r"Glaciemring_Segment_Levski", "冰川环带 列夫斯基区段"),
    (r"keeger_segment_mission_genrl_(\d+)_(\d+)", "基格小行星带 任务区段 {0}-{1}"),
    (r"keeger_segment_outlaw_(\d+)", "基格小行星带 法外区段 {0}"),
    (r"keeger_segment_social_(\d+)", "基格小行星带 社交区段 {0}"),
]


def rule_zh(name: str) -> str:
    """按规则翻：Rock Cave #12, Fauna → 岩石洞穴 #12（有动物）；RL_col_m_drlct_otpst_occ_001 → 废弃前哨站（有人）001；
    Caterpillar Derelict 03 S1 → 毛虫残骸 03 S1。翻不了返回空"""
    n = (name or "").strip()
    for pat, zh in _SEGMENT:
        m = re.fullmatch(pat, n, re.I)
        if m:
            return zh.format(*m.groups())
    m = re.match(
        r"(?:RL_)?(?:Stanton|Pyro)\w*?_(acidic|sand|rock)\d*_(occu|unoc)_", n, re.I
    )
    if m:  # 洞穴的内部名字：Stanton2b_sand01_occu_001_… → 沙地洞穴（有人）
        kind = {"acidic": "酸性洞穴", "sand": "沙地洞穴", "rock": "岩石洞穴"}[
            m[1].lower()
        ]
        return f"{kind}（{'有人' if m[2].lower() == 'occu' else '无人'}）"
    if re.fullmatch(r"RL_Pyro\d_Rock Cave", n, re.I):
        return "岩石洞穴"
    m = re.fullmatch(
        r"(Caterpillar|Constellation|Freelancer|Starfarer|Cutlass) ([A-D]) Wreck\s*(.*)",
        n,
    )
    if m and _SHIP_ZH.get(
        m[1].lower()
    ):  # 「Caterpillar A Wreck 4HJ-027/158」→ 毛虫残骸 A 4HJ-027/158
        return f"{_SHIP_ZH[m[1].lower()]}残骸 {m[2]} {m[3]}".strip()
    m = re.match(r"RL_(?:Pyro\d_)?col_[ms]_drlct_otpst_(occ|unoc)_(\d+)$", n, re.I)
    if m:
        return f"废弃前哨站（{'有人' if m.group(1).lower() == 'occ' else '无人'}）{m.group(2)}"
    for pat, zh in _RULE_HEAD:
        m = re.match(rf"^{pat}\b\s*", n, re.I) or re.match(rf"^{pat}", n, re.I)
        if m:
            rest = n[m.end() :]
            for tp, tz in _RULE_TAIL:
                rest = re.sub(tp, tz, rest, flags=re.I)
            rest = re.sub(
                r"\s*/\s*(Derelict ?Outpost)", " / 废弃前哨站", rest, flags=re.I
            )
            rest = re.sub(r"）\s*,\s*", "） ", re.sub(r"^\s*,\s*", " ", rest))
            return (
                zh + (" " if rest and not rest.startswith(("（", " ")) else "") + rest
            ).strip()
    m = _WRECK.match(n)
    if m:
        ship = _SHIP_ZH.get(m.group("ship").lower())
        if ship:
            return f"{ship}{'残骸' if m.group('tail') else ''}{m.group('rest') or ''}".strip()
    return ""


def point_zh(p: dict) -> str:
    """星图里的星球、恒星、拉格朗日点、跳跃点 → 中文名（2026-10-27：派罗的拉格朗日点以前显示成 PYR1 L1 这种代号）"""
    from .position import ini_name, place_name

    t, i, name = p.get("t"), p.get("i") or "", p.get("n") or ""
    if t in ("Planet", "Star"):
        return (
            BODY_ZH.get(name)
            or ini_name(i)
            or ini_name(i.replace("star", "_Star"))
            or ""
        )
    if t == "Lagrange Point":
        m = re.match(r"(?:P|Pyro)(\d)_L(\d)$", i)
        if m:  # 派罗：建在点上的空间站，没有就是点本身（派1 PYR1 L1）
            return place_name(f"RR_P{m.group(1)}_L{m.group(2)}")
        m = re.match(r"Stanton(\d)_L(\d)$", i)
        if m:  # 斯坦顿：弧 L1 广袤森林站
            code = _RR.get(m.group(1))
            return (code and ini_name(f"RR_{code}_L{m.group(2)}")) or ini_name(
                f"Stanton{m.group(1)}_L{m.group(2)}"
            )
        return ""
    if t == "Jumppoint":  # Pyro-Stanton Jump Point → 派罗 - 斯坦顿 跳跃点
        words = [
            w
            for w in re.findall(r"[A-Za-z]+", name)
            if w.lower() not in ("jump", "point", "jumppoint")
        ]
        if len(words) == 1:
            words = [p.get("sys") or "", words[0]]
        if len(words) == 2:
            return ini_name(f"{words[0]}_JumpPoint_{words[1]}")
    return ""


def label(p: dict) -> str:
    """地点显示名：中文名（英文名）。中文名依次查：汉化包对照表 → 星球/拉格朗日点/跳跃点的正式译名 → 洞穴、前哨这类按规则翻"""
    if p.get("t") == "Waypoint":
        return p["n"]
    zh = p.get("zh") or poi_zh(p["n"]) or point_zh(p) or rule_zh(p["n"])
    if zh:  # 汉化包里的名字自带英文「死局空间站 (Checkmate)」：不再重复写一遍
        zh = (
            re.sub(r"\s*[(（]" + re.escape(p["n"]) + r"[)）]\s*$", "", zh, flags=re.I)
            or zh
        )
    return f"{zh}（{p['n']}）" if zh and zh != p["n"] else p["n"]


def body_label(name: str) -> str:
    """星体/区域友好显示名称"""
    if name.startswith("@"):  # 太空路标：b = "@星系"
        return f"{SYS_ZH.get(name[1:], name[1:])}星系 太空"
    zh = BODY_ZH.get(name)
    return f"{zh}（{name}）" if zh else name
