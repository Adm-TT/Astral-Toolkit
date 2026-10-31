"""库存的存放地点：游戏里能存东西的地方（空间站、城市、星门、L 点休息站），按「星系 / 星球 / 站点」排好。

- 地点列表来自商店数据里各终端所在的地方（UEX，随天枢一起发的 shops.json），中文名用汉化包，
  和导航、顶上的「位置」是同一套名字（炽天使空间站、18区、新巴贝奇……）
- 库存里记的是地点的中文名（label；同名的后面加星系，比如「派罗星门（斯坦顿）」），老版本打开也看得懂
- 以前手打的位置：中文名、英文名、去掉空格大小写后对得上的算这个地点；对不上的归「未归类」
- 游戏里最后打开库存的地方（游戏日志）就是入库默认的地点
"""

import re
from collections import Counter
from functools import lru_cache

SYS_ORDER = ("Stanton", "Pyro", "Nyx")
SYS_ZH = {"Stanton": "斯坦顿", "Pyro": "派罗", "Nyx": "尼克斯"}
KIND_ORDER = ("城市", "空间站", "休息站", "星门")

# 汉化包里叫法不一样、或者玩家常用别的叫法的
_NAME_ZH = {
    "Checkmate Station": "死局空间站",
    "Green Imperial Housing Exchange": "六角湾",
}
_ALIASES = {
    "Green Imperial Housing Exchange": ("Grim HEX", "GrimHEX", "Grim Hex Station"),
    "Area 18": ("A18", "Area18 仓库"),
    "Checkmate Station": ("Checkmate",),
    "Everus Harbor": ("Everus",),
    "Baijini Point": ("Baijini",),
    "Port Tressler": ("Tressler",),
    "Seraphim Station": ("Seraphim",),
}
# 商店数据读不到时的保底（星系, 星球, 卫星, 名字, 城市?）
_FALLBACK = (
    ("Stanton", "ArcCorp", "", "Area 18", True),
    ("Stanton", "ArcCorp", "", "Baijini Point", False),
    ("Stanton", "Crusader", "", "Orison", True),
    ("Stanton", "Crusader", "", "Seraphim Station", False),
    ("Stanton", "Crusader", "Yela", "Green Imperial Housing Exchange", False),
    ("Stanton", "Hurston", "", "Lorville", True),
    ("Stanton", "Hurston", "", "Everus Harbor", False),
    ("Stanton", "MicroTech", "", "New Babbage", True),
    ("Stanton", "MicroTech", "", "Port Tressler", False),
    ("Stanton", "", "", "Pyro Gateway (Stanton)", False),
    ("Stanton", "", "", "Nyx Gateway (Stanton)", False),
    ("Stanton", "", "", "Terra Gateway (Stanton)", False),
    ("Pyro", "Monox", "", "Checkmate Station", False),
    ("Pyro", "Bloom", "", "Orbituary", False),
    ("Pyro", "Terminus", "", "Ruin Station", False),
    ("Pyro", "Pyro V", "", "Gaslight", False),
    ("Pyro", "Pyro V", "", "Rat's Nest", False),
    ("Pyro", "Pyro IV", "", "Endgame", False),
    ("Pyro", "Terminus", "", "Dudley & Daughters", False),
    ("Pyro", "", "", "Stanton Gateway (Pyro)", False),
    ("Nyx", "Delamar", "", "Levski", True),
    ("Nyx", "", "", "Stanton Gateway (Nyx)", False),
)


def norm(text):
    """比较地点名用：去掉空格、标点、大小写（中文照留）"""
    return re.sub(r"[\W_]+", "", str(text or "").lower())


def body_zh(name):
    """星球 / 卫星英文名 → 中文（Pyro V → 派罗 V，MicroTech → 微科星）"""
    if not name:
        return ""
    from ..navigation.navigate import BODY_ZH

    if name in BODY_ZH:
        return BODY_ZH[name]
    low = {k.lower(): v for k, v in BODY_ZH.items()}
    m = re.fullmatch(r"(?i)pyro\s+(i{1,3}|iv|v|vi)", name.strip())
    if m:
        n = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}[m.group(1).lower()]
        return low.get(f"pyro{n}", name)
    return low.get(name.lower(), name)


def _kind(en, city):
    if city:
        return "城市"
    if "gateway" in en.lower():
        return "星门"
    if re.match(r"(?i)(ARC|CRU|HUR|MIC)-L\d", en):
        return "休息站"
    return "空间站"


def _raw_places():
    """[(星系, 星球, 卫星, 英文名, 是城市)]：商店终端所在的空间站和城市"""
    try:
        from . import shops

        rows = shops.load(auto_update=False).get("rows") or []
    except Exception:
        rows = []
    out, seen = [], set()
    for r in rows:
        f = r[6] if len(r) > 6 else None
        if not f:
            continue
        system, planet, orbit, moon, station, city = (list(f) + [""] * 6)[:6]
        name = station or city
        if not name or system not in SYS_ZH or (system, name) in seen:
            continue
        seen.add((system, name))
        if (
            not planet
            and orbit
            and orbit != name
            and "gateway" not in orbit.lower()
            and "lagrange" not in orbit.lower()
        ):
            planet = orbit  # 列夫斯基：挂在德拉玛（Delamar）上
        out.append((system, planet or "", moon or "", name, bool(city)))
    return out or list(_FALLBACK)


@lru_cache(maxsize=1)
def places():
    """所有地点：[{label, zh, en, sys, sys_zh, planet_zh, moon_zh, path, kind, keys}]，按星系、星球排好"""
    from ..navigation.navigate import poi_zh

    items = []
    for system, planet, moon, en, city in _raw_places():
        zh = _NAME_ZH.get(en) or poi_zh(en) or en
        items.append(
            {
                "en": en,
                "zh": zh,
                "sys": system,
                "sys_zh": SYS_ZH[system],
                "planet": planet,
                "planet_zh": body_zh(planet),
                "moon_zh": body_zh(moon),
                "kind": _kind(en, city),
            }
        )
    dup = Counter(p["zh"] for p in items)
    for p in items:
        p["label"] = p["zh"] if dup[p["zh"]] == 1 else f"{p['zh']}（{p['sys_zh']}）"
        p["path"] = " / ".join(
            x for x in (p["sys_zh"], p["planet_zh"], p["moon_zh"], p["zh"]) if x
        )
        base = re.sub(r"\s*\(.*?\)\s*", " ", p["en"]).strip()
        keys = {
            p["label"],
            p["zh"],
            p["en"],
            base,
            re.sub(r"(?i)\s+station$", "", base),
            *_ALIASES.get(p["en"], ()),
        }
        m = re.match(r"(?i)((?:ARC|CRU|HUR|MIC)-L\d)", p["en"])
        if m:
            keys.add(m.group(1))  # ARC-L1
            keys.add(re.sub(r"\s*\S+站$", "", p["zh"]))  # 弧 L1
        p["keys"] = sorted(norm(k) for k in keys if k)
    order = {s: i for i, s in enumerate(SYS_ORDER)}
    items.sort(
        key=lambda p: (
            order.get(p["sys"], 9),
            not p["planet"],
            p["planet"].lower(),
            p["moon_zh"],
            KIND_ORDER.index(p["kind"]),
            p["en"].lower(),
        )
    )
    return tuple(items)


@lru_cache(maxsize=1)
def _index():
    idx = {}
    for p in places():
        for k in p["keys"]:
            idx.setdefault(k, []).append(p)
    return idx


def match(text, system=None):
    """以前手打的位置 / 游戏日志里的地点名 → 地点；对不上（或者同名分不清哪个星系）返回 None"""
    hits = _index().get(norm(text)) or []
    hits = list({id(p): p for p in hits}.values())
    if len(hits) > 1 and system:
        hits = [p for p in hits if p["sys"] == system] or hits
    return hits[0] if len(hits) == 1 else None


def by_label(label):
    return next((p for p in places() if p["label"] == label), None)


def public(p):
    """给窗口用的（不带内部的 keys）"""
    return {k: p[k] for k in ("label", "zh", "en", "sys_zh", "path", "kind")}


def current_place():
    """游戏里最后打开库存的地方：{label, path, kind, minutes, custom}；在列表外的地方（前哨等）custom=True；不知道返回 None"""
    try:
        from ..navigation.position import current

        here = current()
    except Exception:
        here = None
    if not here or not here.get("label"):
        return None
    p = match(here["label"], here.get("sys"))
    out = (
        public(p)
        if p
        else {
            "label": here["label"],
            "zh": here["label"],
            "en": "",
            "sys_zh": SYS_ZH.get(here.get("sys"), ""),
            "path": here["label"],
            "kind": "其他",
        }
    )
    out.update(minutes=int(here.get("age", 0) // 60), custom=not p)
    return out


def check_name(name):
    """自己起的地点名（船、前哨……）：去掉两头空格；不能空、不能只有数字（以前把数量 38 填进了位置）、最长 30 个字"""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise ValueError("需填写地点名称")
    if re.fullmatch(r"[\d.,\s]+", name):
        raise ValueError("地点名称不能只含数字")
    if len(name) > 30:
        raise ValueError("地点名称过长（最多 30 个字）")
    if "｜" in name:
        raise ValueError("地点名称不能包含「｜」")
    return name


# ---------------------------------------------------------------- 仓位（1.6.40）：一个地点下面自己分的格子，库存里记成「地点｜仓位」

BIN_SEP = "｜"
MAIN_BIN = "总仓"  # 不分仓位的就在总仓（库存里只记地点名）


def split_loc(location):
    """「新巴贝奇｜待卖」→ (新巴贝奇, 待卖)；「新巴贝奇」→ (新巴贝奇, 总仓)"""
    place, sep, b = str(location or "").partition(BIN_SEP)
    return place, (b if sep and b else MAIN_BIN)


def join_loc(place, b=None):
    return place if not b or b == MAIN_BIN else f"{place}{BIN_SEP}{b}"


def check_bin(name):
    """仓位名：去掉两头空格；不能空、不能叫「总仓」、不能有「｜」、最长 20 个字"""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise ValueError("需填写仓位名称")
    if name == MAIN_BIN:
        raise ValueError("「总仓」为默认仓位，需使用其他名称")
    if BIN_SEP in name or "|" in name:
        raise ValueError("仓位名称不能包含「｜」")
    if len(name) > 20:
        raise ValueError("仓位名称过长（最多 20 个字）")
    return name
