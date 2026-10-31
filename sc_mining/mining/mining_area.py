"""玩家现在在哪个产矿区（2026-10-27 用户要求「位置和矿种对得上号」）

雷达信号只看数值时，几种稀有矿挨得很近（金 3585、贝沙电气石 3600、硼砂 3570），读错一位、块数不对就跳到隔壁的矿；
还会在根本不刷船挖矿的空旷太空报出矿名（用户反馈：尼克斯太空扫到贝沙电气石）。
这里按实时位置（右上角 r_DisplayInfo）判断所在的产矿区，矿表用 SCMiner「Ore by Location」（locations.py）：
- 星球 / 卫星地表 → 那颗星的矿表
- 尼克斯：基格带（绕恒星半径 48.0 Gm 的环）、冰川环带（15.0 Gm）
- 派罗：阿克罗团（星图里的 14 个星团附近，或右上角地点代号是 AsteroidCluster_Pyro…）
- 斯坦顿：亚伦光环（halo.py 的带）、拉格朗日点矿带（ARC-L1 这些点附近）
- 派罗、尼克斯里离所有矿带和星球都远的太空 → 不刷船挖矿
认不出（斯坦顿的空旷太空、没有矿表的星球）返回 None：调用方不过滤，和以前一样
"""
import json
import math
import re

NO_ORE = "此处不刷船挖矿"
RING_HALF_GM = 0.3          # 环带半宽（按恒星距离）：±0.3 Gm
RING_Z_M = 50_000_000       # 离环面上下 50,000 km 以内
CLUSTER_KM = 50_000         # 派罗星团标记点 5 万 km 以内算在星团里（星团之间至少隔 42 万 km，不会串）
LPOINT_KM = 20_000          # 斯坦顿拉格朗日点 20,000 km 以内算在那片矿带
NYX_RINGS = (("Keeger Belt", 48.0), ("Glaciem Ring", 15.0))
_ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4", "V": "5", "VI": "6"}


def _table(name):
    from .locations import LOCATIONS
    return next((r for r in LOCATIONS if r["name"] == name), None)


def _body_tables():
    """星图里的星球名（Pyro1、Fairo、Microtech…）→ SCMiner 矿表那一行"""
    from .locations import LOCATIONS
    out = {}
    for r in LOCATIONS:
        if r["kind"] not in ("Planet", "Moon"):
            continue
        name = r["name"]
        keys = {name.lower()}
        m = re.search(r"\(([^)]+)\)", name)
        if m:
            keys.add(m.group(1).lower())                         # Pyro V-d (Fairo) → fairo
        m = re.match(r"Pyro ([IV]+)\b", name)
        if m and m.group(1) in _ROMAN:
            keys.add(f"pyro{_ROMAN[m.group(1)]}")                # Pyro IV → pyro4
        for k in keys:
            out[k] = r
    return out


_ROCKS = {}


def rocks_table():
    """解包出来的雷达石头表 data/mining_rocks.json（2026-10-27 起，tools/unpack_mining.py 生成，随数据包更新）：
    {"tiers": 稀有度 → 一团几块, "ores": 矿 → 信号、稀有度, "areas": 地点 → {石头种类: 百分比}}；没有这个文件返回 {}"""
    from ..core.paths import DATA, cached_json
    t = cached_json(DATA / "mining_rocks.json", default={})      # 文件换了（更新数据）就重读，不用重启
    return t if isinstance(t, dict) else {}


def rocks_stamp():
    """石头表的版本（文件修改时间）：雷达结果按它判断要不要重新发"""
    from ..core.paths import DATA, file_stamp
    return file_stamp(DATA / "mining_rocks.json")


def _result(row, system=None):
    if row is None:
        return None
    from .locations import _ZH
    zh = _ZH.get(row["name"], row["name"]).split("（")[0]          # 悬浮窗写短名：基格小行星带、法伊罗、ARC-L1
    out = {"name": row["name"], "zh": zh, "system": row["system"], "minerals": dict(row["minerals"])}
    # 雷达信号是按「石头种类」给的：这里刷哪几种石头（SCMiner 的矿物表把石头里夹带的少量矿也算进去了，
    # 基格带会多出硼砂、金这些——那里根本没有硼砂石、金石，2026-10-27 解包发现）
    rocks = (rocks_table().get("areas") or {}).get(row["name"])
    if rocks:
        out["rocks"] = dict(rocks)
    return out


def _no_ore(system):
    return {"name": "", "zh": NO_ORE, "system": system, "minerals": {}, "rocks": {}}


def area(g, system, body=None, ground=None, location="", zone=""):
    """g：星系坐标（米）；system：星系；body / ground：locate 给的最近星球、是否在地表附近；
    location / zone：右上角那两段文字。→ {"name", "zh", "system", "minerals"} 或 None（认不出）"""
    text = f"{location} {zone}".lower()
    if ground and body:
        return _result(_body_tables().get(str(body).lower()))
    if system == "Nyx":
        if "keeger" in text:
            return _result(_table("Keeger Belt"))
        if "glaciem" in text:
            return _result(_table("Glaciem Ring"))
        if g:
            r = math.hypot(g[0], g[1]) / 1e9
            for name, radius in NYX_RINGS:
                if abs(r - radius) <= RING_HALF_GM and abs(g[2]) <= RING_Z_M:
                    return _result(_table(name))
        return _no_ore("Nyx") if g and not ground else None
    if system == "Pyro":
        flat = text.replace(" ", "_")
        if "akiro" in flat:
            return _named("Akiro Cluster")
        # 派罗「小行星群 FSN-704」这些和远矿站：游戏里用的是深空小行星表（2026-10-27 解物件容器，以前当成阿克罗团）
        if re.search(r"asteroidcluster_pyro|ab_mine_pyro|miningbase_pyro", flat):
            return _named(DEEP)
        if g:
            hit = _pyro_spot(g)
            if hit is _KNOWN_SPOT_NO_TABLE:   # 在挖矿点附近、但这里的石头表缺了：不知道刷什么，不能说「不刷」（Codex 2026-10-27）
                return None
            if hit is not None:
                return hit
            t6 = _body_xyz("Terminus") or _body_xyz("Pyro6")
            if t6 and math.dist(g, t6) <= 2_000_000_000:     # 派6 附近有一圈矿（物件容器引用了耶拉环带的刷矿表），范围还没解出来：不过滤
                return None
            spots = _spots_raw()
            clusters = [p for p in _starmap_points() if p.get("sys") == "Pyro" and p.get("t") == "AsteroidBelt"]
            if not spots and not clusters:   # 旧星图、没有挖矿点数据：不知道星团在哪，不能说「不刷」（Codex 2026-10-27 补审）
                return None
            for p in clusters:
                if math.dist(g, (p["x"], p["y"], p["z"])) <= CLUSTER_KM * 1000:
                    return _named(DEEP)
        return _no_ore("Pyro") if g and not ground else None
    if system == "Stanton" and g and not ground:
        yela = _body_xyz("Yela")
        if yela and YELA_RING[0] * 0.95 <= math.dist(g, yela) <= YELA_RING[1] * 1.05:
            return _result(_table("Yela Asteroid Belt"))       # 耶拉环带：星图记录里的环 482,000～782,000 km（解包）
        from ..navigation import halo
        try:
            if halo.where(g).get("band"):
                return _result(_table("Aaron Halo"))
        except Exception:
            pass
        from ..navigation.navigate import load
        best = None
        for p in load().get("points") or []:
            if p["sys"] == "Stanton" and p["t"] == "Lagrange Point":
                d = math.dist(g, (p["x"], p["y"], p["z"]))
                if d <= LPOINT_KM * 1000 and (best is None or d < best[0]):
                    best = (d, p["n"].replace(" ", "-"))            # ARC L1 → ARC-L1
        if best:
            return _result(_table(best[1]))
    return None


DEEP = "Deep Space Asteroids"
YELA_RING = (482_000_000, 782_000_000)       # 米
SPOT_KM = 20_000                  # 远矿站、拉格朗日点：20,000 km 以内算在那里（远矿站的量子到达半径 18,000 km）
_AREA_ZH = {DEEP: "小行星群"}      # 汉化组对「小行星群 FSN-704」的叫法；派罗拉格朗日点用星图点的中文名


def _named(name, system=None):
    """按石头表里的地点名给结果：AT 的 SCMiner 表里有就用那一行，没有（派罗拉格朗日点、深空小行星）就只用石头表"""
    row = _table(name)
    if row is not None:
        return _result(row)
    rocks = (rocks_table().get("areas") or {}).get(name)
    if not rocks:
        return None
    zh = _AREA_ZH.get(name, "")
    m = re.match(r"PYR(\d)-L(\d)$", name)
    if m and not zh:
        from ..navigation.navigate import point_zh
        p = next((q for q in _starmap_points() if q.get("i") == f"P{m.group(1)}_L{m.group(2)}"), None)
        zh = (point_zh(p) if p else "") or f"PYR{m.group(1)} L{m.group(2)}"
    return {"name": name, "zh": zh or name, "system": system or "Pyro", "minerals": dict(rocks), "rocks": dict(rocks)}


def _body_xyz(name):
    try:
        from ..navigation.navigate import load
        b = load()["bodies"].get(name)
        return (b["x"], b["y"], b["z"]) if b else None
    except Exception:
        return None


def _starmap_points():
    try:
        from ..navigation.navigate import load
        return load().get("points") or []
    except Exception:
        return []


def _spots_raw():
    try:
        from ..core.paths import DATA
        return json.loads((DATA / "mining_spots.json").read_text(encoding="utf-8"))
    except Exception:
        return []


_KNOWN_SPOT_NO_TABLE = object()     # 找到了挖矿点 / L 点，但石头表里没有它


def _pyro_spot(g):
    """派罗：在远矿站 / 小行星群 / 拉格朗日点附近 → 那里的产矿区；在附近但缺表 → _KNOWN_SPOT_NO_TABLE；都不在 → None"""
    for s in _spots_raw():
        if s.get("sys") == "Pyro" and s.get("area") and math.dist(g, (s["x"], s["y"], s["z"])) <= (
                CLUSTER_KM if s.get("kind") == "cluster" else SPOT_KM) * 1000:
            return _named(s["area"]) or _KNOWN_SPOT_NO_TABLE
    for p in _starmap_points():
        if p.get("sys") == "Pyro" and p.get("t") == "Lagrange Point" and \
                math.dist(g, (p["x"], p["y"], p["z"])) <= SPOT_KM * 1000:
            m = re.match(r"P(\d)_L(\d)$", p.get("i") or "")
            if m:
                return _named(f"PYR{m.group(1)}-L{m.group(2)}") or _KNOWN_SPOT_NO_TABLE
    return None


def area_for_spot(spot, g):
    """导航「挖矿点」：这个点刷哪几种石头 {矿: %}（没有就 None）"""
    if spot.get("area"):
        return (rocks_table().get("areas") or {}).get(spot["area"])
    if spot.get("lagrange"):
        m = re.match(r"P(\d)_L(\d)$", spot["lagrange"])
        name = f"PYR{m.group(1)}-L{m.group(2)}" if m else str(spot["lagrange"]).replace(" ", "-")
        return (rocks_table().get("areas") or {}).get(name)
    a = area(g, spot.get("sys"))
    return (a or {}).get("rocks") or None


def filter_text(a):
    """悬浮窗上的地点小注：（基格带）"""
    return f"（{a['zh']}）" if a and a.get("zh") else ""
