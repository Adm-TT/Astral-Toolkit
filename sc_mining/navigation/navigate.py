"""地表导航：去没有量子信标的地点（洞穴、残骸、自定义路标……），思路同 starmap.space

用法：游戏控制台输入 r_DisplayInfo 2，右上角会显示坐标；天枢读这几行（displayinfo.py）
→ 算出你在哪个星球、经纬度 → 告诉你朝哪个方位飞、还有多远。

坐标换算照搬 starmap.space 的公式（星球自转相位从 2020-01-01 UTC 起算），
星球/地点数据来自 starmap.space 的公开接口，缓存在 starmap.json。
方位：0°=北（OM-1 方向），90°=东，应该和游戏头盔指南针一致（待游戏内确认）。
"""
import json
import math
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
from ..core.paths import DATA, USER, write_json
CACHE = DATA / "starmap.json"
WAYPOINTS = USER / "waypoints.json"      # 自定义路标，放 userdata，更新不会覆盖
API = "https://starmap.space/api/v3/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36", "Accept": "application/json", "Referer": "https://starmap.space/"}
EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)
R2D = 180 / math.pi

# POI 接口里的星球名 → 星体接口里的名字
_POI_BODY = {"microTech": "Microtech", "Pyro V": "Pyro5"}

BODY_ZH = {
    "Hurston": "赫斯顿", "Arial": "艾瑞尔", "Aberdeen": "阿伯丁", "Magda": "玛格达", "Ita": "依塔",
    "Crusader": "十字军", "Cellin": "赛琳", "Daymar": "戴玛尔", "Yela": "耶拉",
    "ArcCorp": "弧光星", "Lyria": "莉瑞雅", "Wala": "瓦菈",
    "Microtech": "微科星", "Calliope": "卡利俄佩", "Clio": "克利俄", "Euterpe": "欧忒耳佩",
    "Pyro1": "派罗 I", "Monox": "殁氧星", "Bloom": "盛放星", "Pyro4": "派罗 IV", "Pyro5": "派罗 V",
    "Terminus": "端点星", "Ignis": "伊格尼斯", "Vatra": "瓦塔拉", "Adir": "阿迪尔", "Fairo": "法伊罗",
    "Fuego": "弗果", "Vuur": "伏尔", "Delamar": "德拉玛",
}

TYPE_ZH = {
    "Mining Spot": "挖矿点", "City": "城里",
    "Cave": "洞穴", "Wreck": "残骸", "Outpost": "前哨站", "Derelict Outpost": "废弃前哨",
    "Derelict Settlement": "废弃定居点", "Abandoned Outpost": "废弃前哨", "Underground Facility": "地下设施",
    "Security Outpost": "安保哨站", "Onyx Facility": "玛瑙设施", "Druglab": "毒品实验室",
    "Colonial Outpost": "殖民前哨", "Colonial Bunker": "殖民地堡", "Forward Operating Base": "前线基地",
    "Distribution Center": "物流中心", "Landing Zone": "主城", "LandingZone": "主城", "Spaceport": "太空港",
    "Orbital Station": "轨道站", "RestStop": "休息站", "Comm Array": "通讯阵列", "River": "河流",
    "Scrapyard": "废料场", "Racetrack": "赛道", "Racetrack (Community)": "赛道（玩家）", "Animal Area": "动物区",
    "Mission Area": "任务区", "Prison": "监狱", "Easteregg": "彩蛋", "Event": "活动",
    "Planetary Alignment Facility": "行星校准设施", "Orbital Laser Platform": "轨道激光平台",
    "Ground Activation Platform": "地面激活平台", "AsteroidBase": "小行星基地", "Asteroid Belt": "小行星带",
    "Object Container": "容器", "Location": "地点", "Unknown": "未知", "": "其他", "Waypoint": "路标",
}
QT_ZH = {1: "有信标", 0: "无信标"}

_places_zh = None


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def poi_zh(name):
    """地点英文名 → 汉化包里的中文名（没有就返回空字符串）"""
    global _places_zh
    files = ("places_zh.json", "places_extra_zh.json")      # 后读的优先：解包对出的汉化名（extra）盖过旧表（二审 2026-10-27）
    stamp = []
    for f in files:
        try:
            stamp.append((DATA / f).stat().st_mtime_ns)
        except OSError:
            stamp.append(0)
    if _places_zh is None or _places_zh[0] != stamp:      # 更新数据后不用重启
        table = {}
        # places_extra_zh.json（tools/unpack_place_names.py，2026-10-27）：汉化包里中文不带英文的地名（采矿基地 #IGB-FXW…）
        for f in files:
            try:
                d = json.loads((DATA / f).read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    table.update({k: v for k, v in d.items() if isinstance(v, str) and v})
            except Exception:
                pass
        _places_zh = (stamp, table)                         # 填好了再挂上：别的线程不会拿到半张表
    base = re.sub(r"\s*[\[(].*?[\])]\s*", " ", name).strip()      # 去掉 "[F]" "(missing)" 之类的备注
    table = _places_zh[1]
    return table.get(_norm(name)) or table.get(_norm(base)) or ""


def label(p):
    """地点显示名：中文名（英文名）。中文名依次查：汉化包对照表 → 星球/拉格朗日点/跳跃点的正式译名 → 洞穴、前哨这类按规则翻"""
    if p.get("t") == "Waypoint":
        return p["n"]
    zh = p.get("zh") or poi_zh(p["n"]) or point_zh(p) or rule_zh(p["n"])
    if zh:                                   # 汉化包里的名字自带英文「死局空间站 (Checkmate)」：不再重复写一遍
        zh = re.sub(r"\s*[(（]" + re.escape(p["n"]) + r"[)）]\s*$", "", zh, flags=re.I) or zh
    return f"{zh}（{p['n']}）" if zh and zh != p["n"] else p["n"]


_RR = {"1": "HUR", "2": "CRU", "3": "ARC", "4": "MIC"}           # 斯坦顿几号星 → 空间站代码


def point_zh(p):
    """星图里的星球、恒星、拉格朗日点、跳跃点 → 中文名（2026-10-27：派罗的拉格朗日点以前显示成 PYR1 L1 这种代号）"""
    from .position import ini_name, place_name
    t, i, name = p.get("t"), p.get("i") or "", p.get("n") or ""
    if t in ("Planet", "Star"):
        return BODY_ZH.get(name) or ini_name(i) or ini_name(i.replace("star", "_Star")) or ""
    if t == "Lagrange Point":
        m = re.match(r"(?:P|Pyro)(\d)_L(\d)$", i)
        if m:                                                      # 派罗：建在点上的空间站，没有就是点本身（派1 PYR1 L1）
            return place_name(f"RR_P{m.group(1)}_L{m.group(2)}")
        m = re.match(r"Stanton(\d)_L(\d)$", i)
        if m:                                                      # 斯坦顿：弧 L1 广袤森林站
            code = _RR.get(m.group(1))
            return (code and ini_name(f"RR_{code}_L{m.group(2)}")) or ini_name(f"Stanton{m.group(1)}_L{m.group(2)}")
        return ""
    if t == "Jumppoint":                                            # Pyro-Stanton Jump Point → 派罗 - 斯坦顿 跳跃点
        words = [w for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in ("jump", "point", "jumppoint")]
        if len(words) == 1:
            words = [p.get("sys") or "", words[0]]
        if len(words) == 2:
            return ini_name(f"{words[0]}_JumpPoint_{words[1]}")
    return ""


# 洞穴、前哨这类社区起的名字（星图数据里约 1400 个，汉化包里没有）：按规则翻，编号原样保留
_RULE_HEAD = [
    (r"Rock ?Cave", "岩石洞穴"), (r"Sand ?Cave", "沙地洞穴"), (r"Acidic ?Cave", "酸性洞穴"), (r"Unknown ?Cave", "未知洞穴"),
    (r"Cave", "洞穴"), (r"River", "河流"), (r"Remote Outpost", "偏远前哨站"), (r"Abandoned Outpost", "废弃前哨站"),
    (r"Derelict ?Outpost", "废弃前哨站"), (r"Colonial Outpost XS", "小型殖民前哨站"), (r"Colonial Outpost", "殖民前哨站"),
    (r"Colonial Bunker", "殖民地地堡"), (r"Frontier Fighters Hideout", "边境战士藏身处"), (r"Comm Array", "通讯阵列"),
    (r"AsteroidArena", "小行星竞技场"), (r"Mining Tower", "采矿塔"), (r"Kopion Lab", "科皮翁实验室"),
    (r"Valakkar Apex Spawn Area", "瓦拉卡巨兽出没区"), (r"Crashed Satel+ite", "坠毁卫星"), (r"a Private Landing Pad", "私人停机坪"),
    (r"OC_EscortMissionMarkup-?", "护送任务点 "), (r"EscortMission", "护送任务点"), (r"Scrapyard", "废料场"),
]
_RULE_TAIL = [
    (r"[,\s]*[\[(]?\b(?:Fauna|F)\b[\])]?", "（有动物）"), (r"[,\s]*\(?\bUnoccupied\b\)?", "（无人）"),
    (r"[,\s]*\(?\bOccupied\b\)?", "（有人）"), (r"[,\s]*\bAbandoned\b", "（废弃）"), (r"[,\s]*\[Foot\]", "（步行）"),
    (r"\bSize\s*(\d)", r"规模 \1"),
]
_WRECK = re.compile(r"^(?P<ship>[A-Z][A-Za-z]+)(?:\s+(?P<tail>Derelict|Wreck))?(?P<rest>[\s#\dA-Z]*?)$")


# 星图里的飞船残骸只写了型号（汉化包 vehicle_Name… 里的叫法，去掉厂商）
_SHIP_ZH = {"starfarer": "星际远航者", "cutlass": "弯刀", "caterpillar": "毛虫", "freelancer": "自由枪骑兵",
            "constellation": "星座", "reclaimer": "回收者", "hull": "货轮", "prospector": "勘探者", "mole": "鼹鼠"}


_SEGMENT = [   # 尼克斯小行星带的分段（星图里是内部名字；冰川环带、基格小行星带是汉化组的，「区段」这些自译，2026-10-27）
    (r"Glaciemring_Segment_Wtn-(\d+)", "冰川环带 区段 Wtn-{0}"),
    (r"Glaciemring_Segment_Mission_Genrl_(\d+)_(\d+)_Fstreamable", "冰川环带 任务区段 {0}-{1}"),
    (r"Glaciemring_Segment_Levski", "冰川环带 列夫斯基区段"),
    (r"keeger_segment_mission_genrl_(\d+)_(\d+)", "基格小行星带 任务区段 {0}-{1}"),
    (r"keeger_segment_outlaw_(\d+)", "基格小行星带 法外区段 {0}"),
    (r"keeger_segment_social_(\d+)", "基格小行星带 社交区段 {0}"),
]


def rule_zh(name):
    """按规则翻：Rock Cave #12, Fauna → 岩石洞穴 #12（有动物）；RL_col_m_drlct_otpst_occ_001 → 废弃前哨站（有人）001；
    Caterpillar Derelict 03 S1 → 毛虫残骸 03 S1。翻不了返回空"""
    n = (name or "").strip()
    for pat, zh in _SEGMENT:
        m = re.fullmatch(pat, n, re.I)
        if m:
            return zh.format(*m.groups())
    m = re.match(r"(?:RL_)?(?:Stanton|Pyro)\w*?_(acidic|sand|rock)\d*_(occu|unoc)_", n, re.I)
    if m:                                               # 洞穴的内部名字：Stanton2b_sand01_occu_001_… → 沙地洞穴（有人）
        kind = {"acidic": "酸性洞穴", "sand": "沙地洞穴", "rock": "岩石洞穴"}[m[1].lower()]
        return f"{kind}（{'有人' if m[2].lower() == 'occu' else '无人'}）"
    if re.fullmatch(r"RL_Pyro\d_Rock Cave", n, re.I):
        return "岩石洞穴"
    m = re.fullmatch(r"(Caterpillar|Constellation|Freelancer|Starfarer|Cutlass) ([A-D]) Wreck\s*(.*)", n)
    if m and _SHIP_ZH.get(m[1].lower()):                # 「Caterpillar A Wreck 4HJ-027/158」→ 毛虫残骸 A 4HJ-027/158
        return f"{_SHIP_ZH[m[1].lower()]}残骸 {m[2]} {m[3]}".strip()
    m = re.match(r"RL_(?:Pyro\d_)?col_[ms]_drlct_otpst_(occ|unoc)_(\d+)$", n, re.I)
    if m:
        return f"废弃前哨站（{'有人' if m.group(1).lower() == 'occ' else '无人'}）{m.group(2)}"
    for pat, zh in _RULE_HEAD:
        m = re.match(rf"^{pat}\b\s*", n, re.I) or re.match(rf"^{pat}", n, re.I)
        if m:
            rest = n[m.end():]
            for tp, tz in _RULE_TAIL:
                rest = re.sub(tp, tz, rest, flags=re.I)
            rest = re.sub(r"\s*/\s*(Derelict ?Outpost)", " / 废弃前哨站", rest, flags=re.I)
            rest = re.sub(r"）\s*,\s*", "） ", re.sub(r"^\s*,\s*", " ", rest))
            return (zh + (" " if rest and not rest.startswith(("（", " ")) else "") + rest).strip()
    m = _WRECK.match(n)
    if m:
        ship = _SHIP_ZH.get(m.group("ship").lower())
        if ship:
            return f"{ship}{'残骸' if m.group('tail') else ''}{m.group('rest') or ''}".strip()
    return ""


SYS_ZH = {"Stanton": "斯坦顿", "Pyro": "派罗", "Nyx": "尼克斯"}


def body_label(name):
    if name.startswith("@"):                 # 太空路标：b = "@星系"
        return f"{SYS_ZH.get(name[1:], name[1:])}星系 太空"
    zh = BODY_ZH.get(name)
    return f"{zh}（{name}）" if zh else name


# ---------------------------------------------------------------- 数据

def _fetch(path, tries=3):
    """下载一个接口；失败自动重试（隔 2、5 秒），最后一次的原因翻成中文抛出去"""
    import time
    import urllib.error
    import urllib.request
    from ..core.net import read
    last = None
    for n in range(tries):
        try:
            body = read(urllib.request.Request(API + path, headers=UA), timeout=60)
            try:
                return json.loads(body)
            except ValueError:
                head = body[:200].decode("utf-8", "replace").lower()
                last = RuntimeError("starmap.space 返回的不是数据" + ("（被网站防护拦截，稍后重试）" if "<html" in head else ""))
        except urllib.error.HTTPError as e:
            last = RuntimeError(f"starmap.space 拒绝了请求（HTTP {e.code}"
                                + ("，被网站防护拦截，过一会再试" if e.code in (403, 429, 503) else "") + "）")
        except Exception as e:
            reason = str(getattr(e, "reason", e))
            last = RuntimeError("无法连接 starmap.space（" + ("超时" if "timed out" in reason.lower() else reason) + "）")
        if n < tries - 1:
            time.sleep((2, 5)[min(n, 1)])
    raise last


def compact(oc, pois):
    """把 starmap 接口的原始数据压缩成程序用的格式"""
    bodies = {}
    for x in oc:
        if x.get("Type") != "Planet" or not float(x.get("BodyRadius") or 0) or x.get("System") not in (
                "Stanton", "Pyro", "Nyx"):
            continue
        name = x.get("ObjectContainer") or x.get("Planet")
        bodies[name] = dict(sys=x["System"], x=float(x["XCoord"]), y=float(x["YCoord"]), z=float(x["ZCoord"]),
                            rot=float(x["RotationSpeedX"] or 0), adj=float(x["RotationAdjustmentX"] or 0),
                            r=float(x["BodyRadius"]), om=float(x["OrbitalMarkerRadius"] or 0),
                            grid=float(x["GRIDRadius"] or 0))
    # 所有星体/拉格朗日点/跳跃点的位置（商店「离我多远」用）
    points = []
    for x in oc:
        if x.get("System") not in ("Stanton", "Pyro", "Nyx"):
            continue
        try:
            points.append(dict(n=x.get("ObjectContainer") or x.get("Planet") or "", i=x.get("InternalName") or "",
                               sys=x["System"], t=x.get("Type") or "", x=float(x["XCoord"]), y=float(x["YCoord"]),
                               z=float(x["ZCoord"])))
        except (TypeError, ValueError, KeyError):
            pass
    out = []
    for p in pois:
        b = _POI_BODY.get(p.get("Planet"), p.get("Planet"))
        if b not in bodies:
            continue
        qt = p.get("QTMarker")
        out.append(dict(b=b, n=(p.get("PoiName") or "").strip(), t=(p.get("Type") or "").strip(),
                        x=round(float(p["XCoord"]), 3), y=round(float(p["YCoord"]), 3),
                        z=round(float(p["ZCoord"]), 3), qt=None if qt in (None, "") else int(qt)))
    return dict(source="starmap.space", fetched=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                bodies=bodies, pois=out, points=points)


def update():
    """从 starmap.space 下载最新的星球和地点数据"""
    print("下载 starmap.space 星图数据（星球 + 约 2000 个地点）…")
    data = compact(_fetch("oc/index.php"), _fetch("pois/index.php"))
    if len(data.get("bodies", [])) < 10 or len(data.get("pois", [])) < 300:
        raise RuntimeError(f"starmap.space 返回的数据不完整（{len(data.get('bodies', []))} 个星球、"
                           f"{len(data.get('pois', []))} 个地点），保留原来的星图")
    tmp = CACHE.with_suffix(".tmp")          # 先写临时文件再换上：导航正在读的时候不会读到半个文件
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(CACHE)
    global _data
    _data = None                             # 下次用时读新的
    n_no = sum(1 for p in data["pois"] if p["qt"] != 1)
    print(f"星图数据已更新：{len(data['bodies'])} 个星球/卫星，{len(data['pois'])} 个地点（其中 {n_no} 个没有确认的量子信标）")
    return data


_data = None
_data_stamp = None


def _files_stamp():
    """星图和坐标改正文件的修改时间：数据包换了文件，下次 load() 就重读（不用重启）"""
    def mt(f):
        try:
            return f.stat().st_mtime_ns
        except OSError:
            return None
    return mt(CACHE), mt(DATA / "starmap_fixes.json")


def load():
    global _data, _data_stamp
    stamp = _files_stamp()
    if _data is None or (_data_stamp is not None and stamp != _data_stamp and stamp[0] is not None):
        if not CACHE.exists():
            print("第一次使用导航，需要先下载星图数据。")
            update()
            stamp = _files_stamp()
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        _apply_fixes(data)
        for name, b in (data.get("bodies") or {}).items():
            b["name"] = name                      # 自转相位校准按名字存（rotation_deg 只拿到星球那个 dict）
        _data, _data_stamp = data, stamp
    return _data


def _apply_fixes(data):
    """解包核对出来的星图坐标改正（data/starmap_fixes.json：{点名: [x, y, z] 米}）：starmap.space 个别点的坐标不对
    （2026-10-27：QV 碎岩站 BRK-304 差了 53 万 km，和 BRK-204 重了）。文件坏了 / 条目不对就跳过，保留原坐标"""
    try:
        fixes = json.loads((DATA / "starmap_fixes.json").read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(fixes, dict):
        return
    good = {}
    for name, f in fixes.items():
        if isinstance(f, (list, tuple)) and len(f) == 3 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in f):
            good[name] = [float(v) for v in f]
    for p in data.get("points") or []:
        f = good.get(p.get("n"))
        if f:
            p["x"], p["y"], p["z"] = f


def waypoints():
    """路标表（查询用：读不到就当没有，搜索 / 导航照常）"""
    try:
        return _waypoints_strict()
    except RuntimeError:
        return []


def _waypoints_strict():
    """路标表（改写前用）：文件读不到（被占着）或坏了就抛错，别当成空表——不然接下来存一个路标会把整份覆盖掉（细查 2026-10-28）"""
    try:
        rows = json.loads(WAYPOINTS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RuntimeError(f"路标文件暂时读不到：{e}")
    except ValueError as e:
        raise RuntimeError(f"路标文件损坏（userdata 里的 waypoints.json）：{e}")
    return rows if isinstance(rows, list) else []


def add_waypoint(name, body, local_xyz):
    """新建/覆盖一个路标；local_xyz 是星球自转坐标系里的千米坐标"""
    wps = [w for w in _waypoints_strict() if w["n"] != name]
    wps.append(dict(b=body, n=name, t="Waypoint", x=round(local_xyz[0], 3), y=round(local_xyz[1], 3),
                    z=round(local_xyz[2], 3), qt=0, saved=datetime.now().strftime("%Y-%m-%d %H:%M")))
    write_json(WAYPOINTS, wps, indent=1)


# ---------------------------------------------------------------- 太空路标（不在星球附近：记星系里的绝对坐标）
# 星球在自转，星球上的点要记「相对星球」的坐标；太空里没有自转，星系坐标本身就是固定的，直接记下来就行。

POINT_ZH = {"Lagrange Point": "拉格朗日点", "Jumppoint": "跳跃点", "Star": "恒星", "Naval Station": "海军站"}


def is_space(p):
    return bool(p and p.get("space"))


def add_space_waypoint(name, system, g):
    """g：游戏右上角读到的星系坐标（米）；存成千米"""
    wps = [w for w in _waypoints_strict() if w["n"] != name]
    wps.append(dict(b="@" + system, sys=system, space=True, n=name, t="Waypoint",
                    x=round(g[0] / 1000, 3), y=round(g[1] / 1000, 3), z=round(g[2] / 1000, 3), qt=0,
                    saved=datetime.now().strftime("%Y-%m-%d %H:%M")))
    write_json(WAYPOINTS, wps, indent=1)


SYS_WORD = re.compile(r"(stanton|pyro|nyx)", re.I)
_solar_ids = {}


SOLAR_FILE = "solar_ids_v2.json"     # 1.0.3 起只记有把握的；旧的 solar_ids.json 可能记过坐标猜错的星系，不再读（文件留着不动）


def _solar_map():
    """SolarSystem_<编号> → 星系：从右上角学来的，存 userdata/solar_ids.json（每个星系一个固定编号）"""
    if not _solar_ids:
        try:
            _solar_ids.update(json.loads((USER / SOLAR_FILE).read_text(encoding="utf-8")))
        except Exception:
            pass
        _solar_ids.setdefault("_loaded", True)
    return _solar_ids


def _learn_solar(solar_id, system):
    m = _solar_map()
    if solar_id and system and m.get(solar_id) != system:
        m[solar_id] = system
        try:
            write_json(USER / SOLAR_FILE, {k: v for k, v in m.items() if k != "_loaded"}, indent=1)
        except OSError:
            pass


BELT_SYS = {"keeger": "Nyx", "glaciem": "Nyx", "akiro": "Pyro", "aaron": "Stanton"}   # 区域名里的矿带名 → 星系


def system_info(g, data=None, zone="", location="", solar_id=""):
    """星系坐标（米）在哪个星系 → (星系, 有没有把握)。三个星系各自有自己的坐标系（同一个坐标在派罗和尼克斯都可能有东西），
    所以优先看右上角给的线索：地点 / 区域名里带的星系名或矿带名 → SolarSystem 编号（学过的）→ 区域名对得上哪个星系的地点，
    这些算有把握；都没有才按「离哪个星球或地点最近」猜（没把握：不能拿来排除矿种，也不记进编号表）"""
    data = data or load()
    found = ""
    for text in (location, zone):                 # 地点 / 区域名里明写的星系名最准，先看（和编号表对不上时以它为准、顺手改正编号表）
        m = SYS_WORD.search(text or "")
        if m:
            found = m.group(1).capitalize()
            break
    if not found:
        low = f"{location} {zone}".lower()
        found = next((sysname for word, sysname in BELT_SYS.items() if word in low), "")
    if found:
        _learn_solar(solar_id, found)
        return found, True
    if solar_id and _solar_map().get(solar_id):
        return _solar_map()[solar_id], True
    if zone:
        key = re.sub(r"[^a-z0-9]", "", zone.lower())
        for p in data.get("points") or []:
            pk = re.sub(r"[^a-z0-9]", "", (p.get("i") or p.get("n") or "").lower())
            if pk and (key.startswith(pk) or pk.startswith(key)) and len(pk) >= 6:
                found = p["sys"]
                break
        if not found:
            for name, b in data["bodies"].items():
                if re.sub(r"[^a-z0-9]", "", name.lower()) in key and len(name) >= 4:
                    found = b["sys"]
                    break
    if found:
        _learn_solar(solar_id, found)
        return found, True
    cands = [(math.dist(g, (b["x"], b["y"], b["z"])), b["sys"]) for b in data["bodies"].values()]
    cands += [(math.dist(g, (p["x"], p["y"], p["z"])), p["sys"]) for p in data.get("points") or []]
    return min(cands)[1], False


def system_of(g, data=None, zone="", location="", solar_id=""):
    """只要星系名（导航、显示用；没把握时也给最可能的那个）"""
    return system_info(g, data, zone=zone, location=location, solar_id=solar_id)[0]


def space_landmarks(system, data=None):
    """这个星系里能当参照、能量子跳过去的东西：[(名字, 坐标千米)]——星球/卫星、拉格朗日点、跳跃点、恒星"""
    data = data or load()
    out = [(body_label(n), (b["x"] / 1000, b["y"] / 1000, b["z"] / 1000))
           for n, b in data["bodies"].items() if b["sys"] == system]
    for p in data.get("points", []):
        if p["sys"] == system and p["t"] in POINT_ZH:
            out.append((f"{p['n']}（{POINT_ZH[p['t']]}）", (p["x"] / 1000, p["y"] / 1000, p["z"] / 1000)))
    return out


def _angle(u, v):
    nu, nv = math.hypot(*u), math.hypot(*v)
    if not nu or not nv:
        return 0.0
    c = sum(a * b for a, b in zip(u, v)) / nu / nv
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def space_guide(g, target, data=None):
    """当前星系坐标（米）→ 太空路标：距离、先量子跳到哪、对准哪个标记再偏几度"""
    data = data or load()
    here_sys = system_of(g, data)
    here = tuple(v / 1000 for v in g)
    t = (target["x"], target["y"], target["z"])
    out = {"system": here_sys, "target_system": target["sys"], "same_system": here_sys == target["sys"]}
    if not out["same_system"]:
        return out
    marks = space_landmarks(target["sys"], data)
    d = math.dist(here, t)
    out["direct"] = d
    out["arrived"] = d < 1
    # 先量子跳：离目标最近的参照物（比现在离目标更近才有意义）
    near = min(marks, key=lambda m: math.dist(m[1], t)) if marks else None
    if near and math.dist(near[1], t) < d * 0.5 and d > 100:
        out["qt"] = {"name": near[0], "km": math.dist(near[1], t)}
    # 方向：在游戏里能看到标记的参照物里，挑和目标方向夹角最小的
    vt = tuple(b - a for a, b in zip(here, t))
    best = None
    for name, pos_ in marks:
        if math.dist(here, pos_) < 1:
            continue
        ang = _angle(vt, tuple(b - a for a, b in zip(here, pos_)))
        if best is None or ang < best[1]:
            best = (name, ang, math.dist(here, pos_) > d)
    if best:
        out["aim"] = {"name": best[0], "angle": best[1], "beyond": best[2]}
    return out


# ---------------------------------------------------------------- 按机头指方向（太空、星球上都能用）
# 游戏右上角第一行「CamDir: 俯仰 横滚 偏航」：镜头朝向，单位度，在星系坐标系里（不跟星球自转）。
# 旋转顺序 Rz(偏航)·Ry(横滚)·Rx(俯仰)，镜头没转时朝 +y、头顶朝 +z（社区工具 sc-locator 的结论，作者注明是实测出来的）。
# 有了朝向就能说「右转 30°、抬头 10°」，不用管东南西北——太空里本来就没有。
# 注意：CamDir 是镜头不是飞船，驾驶舱里转头看（自由视角）时它也会跟着变。


def cam_axes(pitch, roll, yaw):
    """镜头的 (前方, 头顶) 单位向量"""
    p, r, y = (math.radians(a) for a in (pitch, roll, yaw))
    sp, cp, sr, cr, sy, cy = math.sin(p), math.cos(p), math.sin(r), math.cos(r), math.sin(y), math.cos(y)
    forward = (sr * sp * cy - cp * sy, sr * sp * sy + cp * cy, cr * sp)
    up = (cp * sr * cy + sp * sy, cp * sr * sy - sp * cy, cp * cr)
    return forward, up


def target_global(target, data=None, when=None, ref=None):
    """目标在星系坐标系里的位置（米）：太空路标直接就是；星球上的点要按星球现在转到哪算。
    ref=(玩家星系坐标, locate() 的结果, 那一帧的时间)：同一颗星球上时，把「游戏给的局部坐标和推算的差」也补上，
    屏幕记号、机头转向和罗盘、距离用同一个基准（Codex 2026-10-27：差 500 m 时城里会指偏）"""
    if is_space(target):
        return (target["x"] * 1000, target["y"] * 1000, target["z"] * 1000)
    data = data or load()

    def _t(w):
        return datetime.fromtimestamp(w, timezone.utc) if isinstance(w, (int, float)) else w
    b = data["bodies"][target["b"]]
    out = to_global(b, pos(target), _t(when))
    if ref:
        g0, h0, w0 = ref
        if g0 and h0 and h0.get("body") == target["b"]:
            c = tuple(a - e for a, e in zip(g0, to_global(b, pos(h0), _t(w0))))
            if math.dist(c, (0, 0, 0)) < 60_000:            # 校准差超过 locate 允许的范围就不用
                out = tuple(a + e for a, e in zip(out, c))
    return out


def steer(g, cam, target_g):
    """当前位置 g、镜头朝向 cam=(俯仰,横滚,偏航)、目标 target_g（都是星系坐标，米）
    → {"turn": 右转多少度（负数是左转）, "pitch": 抬头多少度（负数是低头）, "off": 机头偏离目标多少度}"""
    f, u = cam_axes(*cam)
    r = (f[1] * u[2] - f[2] * u[1], f[2] * u[0] - f[0] * u[2], f[0] * u[1] - f[1] * u[0])   # 右边 = 前 × 上
    d = tuple(b - a for a, b in zip(g, target_g))
    x, y, z = (sum(a * b for a, b in zip(d, axis)) for axis in (r, f, u))
    return {"turn": math.degrees(math.atan2(x, y)), "pitch": math.degrees(math.atan2(z, math.hypot(x, y))),
            "off": _angle(d, f)}


def project(g, cam, fov, target_g, w, h, vertical=True):
    """目标在屏幕上的哪个位置（导航记号，2026-10-27）。g 当前位置、target_g 目标（星系坐标，米），cam=(俯仰,横滚,偏航)，
    fov 视角（度；vertical=True 当成上下方向的视角，引擎惯例）、w×h 游戏画面像素。
    → {"on": 在画面里, "x","y": 像素（on 时）, "angle": 屏幕上的方向（度，0 = 右、90 = 上；画面外时用来贴边画箭头）,
       "behind": 在身后, "off": 视线偏离目标多少度, "dist": 米}"""
    f, u = cam_axes(*cam)
    r = (f[1] * u[2] - f[2] * u[1], f[2] * u[0] - f[0] * u[2], f[0] * u[1] - f[1] * u[0])
    d = tuple(b - a for a, b in zip(g, target_g))
    x, y, z = (sum(a * b for a, b in zip(d, axis)) for axis in (r, f, u))
    half = math.radians(max(10.0, min(170.0, fov or 70.0))) / 2
    if vertical:
        ty = math.tan(half)
        tx = ty * w / h
    else:
        tx = math.tan(half)
        ty = tx * h / w
    out = {"on": False, "behind": y <= 0, "off": _angle(d, f), "dist": math.dist(g, target_g),
           "angle": math.degrees(math.atan2(z, x)) if abs(x) + abs(z) > 1e-9 else -90.0}
    if y > 1e-9:
        nx, ny = x / y / tx, z / y / ty
        if abs(nx) <= 1 and abs(ny) <= 1:
            out.update(on=True, x=w / 2 + nx * w / 2, y=h / 2 - ny * h / 2)
    return out


def dist_text(m):
    """记号旁边的距离：1,234 m / 12.3 km / 1,234 km / 12.3 Gm"""
    if m < 1000:
        return f"{m:,.0f} m"
    if m < 100_000:
        return f"{m / 1000:,.1f} km"
    if m < 1e9:
        return f"{m / 1000:,.0f} km"
    return f"{m / 1e9:,.1f} Gm"


def steer_text(s, walk=False):
    """walk=True：城里走路，只说左右转（上下楼另有提示），不说机头、直飞"""
    if walk:
        t = s["turn"]
        if abs(t) < 5:
            return "✅ 面向目标，往前走"
        return ("掉头 · " if abs(t) > 120 else "") + f"{'右' if t > 0 else '左'}转 {abs(t):.0f}°"
    if s["off"] < 3:
        return "✅ 机头正对目标，直飞"
    parts = []
    t, p = s["turn"], s["pitch"]
    if abs(t) >= 2:
        parts.append(("掉头 · " if abs(t) > 120 else "") + f"{'右' if t > 0 else '左'}转 {abs(t):.0f}°")
    if abs(p) >= 2:
        parts.append(f"{'抬头' if p > 0 else '低头'} {abs(p):.0f}°")
    return "机头：" + "，".join(parts)


def space_text(g, target, data=None):
    """悬浮窗 / 命令行用的一两行"""
    s = space_guide(g, target, data)
    if not s["same_system"]:
        return f"目标在 {s['target_system']} 星系，当前在 {s['system']}：先跳过去"
    if s["arrived"]:
        return f"✅ 已经到了（{s['direct'] * 1000:,.0f} m 内），找找周围"
    line = f"直线 {s['direct']:,.1f} km"
    if s.get("aim"):
        a = s["aim"]
        line += (f"｜对准「{a['name']}」的标记" + ("" if a["angle"] < 3 else f"，再偏 {a['angle']:.0f}°"))
    if s.get("qt"):
        line += f"\n太远了：先量子跳到 {s['qt']['name']}（离目标 {s['qt']['km']:,.0f} km）"
    return line


# ---------------------------------------------------------------- 一键定位（太空路标）
# 玩家社区的通用做法（Star-Citizen-Navigation、Project Jericho、starmap.space 教程）：反复 /showlocation 拿精确坐标，
# 用前后两次坐标得出「实际飞的方向」，和「指向目标的方向」比夹角 = 偏离角；再看距离近了还是远了。不读屏、不靠机头朝向。

def fix_guide(fixes, target, data=None, prev_arrived=False):
    """fixes = [(时间秒, 星系坐标米), ...]，最新的在最后 → 距离、近了多少、偏离角、预计多久到。
    太空路标在星系坐标里算；星球上的路标在星球自转坐标里算（星球在转，地面的点跟着转，两次定位之间也要扣掉）"""
    data = data or load()
    t1, g1 = fixes[-1]
    if is_space(target):
        out = space_guide(g1, target, data)
        tgt = (target["x"], target["y"], target["z"])

        def frame(t, g):
            return tuple(v / 1000 for v in g)
    else:
        key = target["b"]
        b = data["bodies"][key]
        out = {"system": system_of(g1, data), "target_system": b["sys"]}
        out["same_system"] = out["system"] == out["target_system"]
        if not out["same_system"]:
            return out
        tgt = pos(target)

        def frame(t, g):
            return to_local(b, g, datetime.fromtimestamp(t, timezone.utc))
        out["direct"] = math.dist(frame(t1, g1), tgt)
        out["arrived"] = out["direct"] < 1
        if is_city(target):                                         # 城里：8 米内才算到（出 15 米才算离开），加上下楼层
            out["city"] = True
            out["arrived"] = city_arrived(out["direct"] * 1000, prev_arrived)
            out["close"] = not out["arrived"] and out["direct"] * 1000 < CITY_NEAR_M
            out["updown"] = (math.hypot(*tgt) - math.hypot(*frame(t1, g1))) * 1000
        if out["direct"] > max(1000, b["r"] / 1000 * 3):            # 离星球还远：先跳过去
            out["qt"] = {"name": body_label(key), "km": None}
    if not out["same_system"] or len(fixes) < 2:
        return out
    t0, g0 = fixes[-2]
    p0, p1 = frame(t0, g0), frame(t1, g1)
    out["moved"] = math.dist(p0, p1)
    out["delta"] = out["direct"] - math.dist(p0, tgt)            # 负数 = 近了
    if out["moved"] >= 0.02:                                       # 两次之间至少飞了 20 m 才算得出方向
        out["deviation"] = _angle(tuple(b_ - a for a, b_ in zip(p0, p1)), tuple(b_ - a for a, b_ in zip(p1, tgt)))
    dt = t1 - t0
    if dt > 0 and out["delta"] < -0.001:
        out["eta"] = out["direct"] / (-out["delta"] / dt)
    return out


def fix_text(f, key=""):
    """悬浮窗几行：距离和变化、偏离角（10° 内绿、20° 内黄、再大红）、多久到、先跳到哪"""
    if not f["same_system"]:
        return f"目标在 {SYS_ZH.get(f['target_system'], f['target_system'])}星系：先跳过去"
    if f["arrived"]:
        return f"✅ 已经到了（{f['direct'] * 1000:,.0f} m 内），找找周围"
    d = f["direct"]
    if f.get("close"):                                         # 城里 15 米内：不给偏离角（位置差一两米角度就乱跳）
        lines = [f"就在附近 {d * 1000:,.0f} m"]
        up = f.get("updown")
        if up is not None and abs(up) > CITY_FLOOR_M:
            lines.append(f"目标在{'上' if up > 0 else '下'}方 {abs(up):,.0f} 米：找电梯{'上' if up > 0 else '下'}楼")
        return "\n".join(lines)
    if f.get("city"):
        line = f"直线 {d * 1000:,.0f} m"
        if "delta" in f:
            line += f"（{'近了' if f['delta'] < 0 else '远了'} {abs(f['delta']) * 1000:,.0f} m）" if abs(f["delta"]) >= 0.002 else "（没变）"
    else:
        line = f"直线 {d:,.2f} km" if d < 100 else f"直线 {d:,.0f} km"
        if "delta" in f:
            line += f"（{'近了' if f['delta'] < 0 else '远了'} {abs(f['delta']):,.2f} km）" if abs(f["delta"]) >= 0.005 else "（没变）"
    lines = [line]
    up = f.get("updown")
    if up is not None and abs(up) > CITY_FLOOR_M:
        lines.append(f"目标在{'上' if up > 0 else '下'}方 {abs(up):,.0f} 米：找电梯{'上' if up > 0 else '下'}楼")
    if f.get("qt"):
        km = f["qt"].get("km")
        lines.append(f"太远了：先量子跳到 {f['qt']['name']}" + (f"（离目标 {km:,.0f} km）" if km else ""))
    if "deviation" in f:
        dev = f["deviation"]
        mark = "✅" if dev <= 10 else ("⚠️" if dev <= 20 else "❌")
        go = "走" if f.get("city") else "飞"
        lines.append(f"{mark} 偏离 {dev:.0f}°" + ("" if dev <= 10 else f"：转一点再{go}，再定位一次看变大还是变小")
                     + (f"（在往反方向{go}）" if dev > 120 else ""))
    else:
        go = "走一段" if f.get("city") else "直线飞一段"
        lines.append(f"朝目标方向{go}，再{f'按 {key}' if key else '输入 /showlocation'}，就能算出偏了几度")
    if f.get("eta"):
        e = f["eta"]
        lines.append(f"照这个速度约 {int(e // 60)} 分 {int(e % 60)} 秒到" if e < 3600 else f"照这个速度约 {e / 3600:.1f} 小时到")
    if f.get("aim") and "deviation" not in f:
        a = f["aim"]
        lines.append(f"参考：对准「{a['name']}」的标记" + ("" if a["angle"] < 3 else f"，再偏 {a['angle']:.0f}°"))
    return "\n".join(lines)


def delete_waypoint(name):
    wps = _waypoints_strict()
    left = [w for w in wps if w["n"] != name]
    write_json(WAYPOINTS, left, indent=1)
    return len(left) < len(wps)


# ---------------------------------------------------------------- 坐标换算

def rotation_deg(body, when=None):
    """星球当前自转角（度），starmap.space 的算法：2020-01-01 时的相位 adj + 转过的圈数。
    adj 游戏文件里没有，优先用 AT 自己校准的（calibration()，玩家在星球上右上角同时给了星系坐标和星球坐标时反推，2026-10-28）"""
    when = when or datetime.now(timezone.utc)
    days = (when - EPOCH).total_seconds() / 86400
    turn = (days / (body["rot"] / 24)) % 1 if body["rot"] else 0
    c = calibration().get(body.get("name") or "")
    adj = c["adj"] if c else body["adj"]
    return adj + turn * 360


# ---------------------------------------------------------------- 自转相位校准（2026-10-28）
# 右上角调试信息同时给了星系坐标（Zone: Root）和星球坐标（Zone: OOC_…），两者的方向差就是星球此刻转到的角度，
# 倒算回 2020-01-01 就是相位。每颗星球一次就够（0.05° 以内不动，误差换算到微科表面不到 1 km）。
# 存 userdata\rotation_calib.json：{星球: {adj, n 次数, at 时间, dz 高度残差 km}}；作者的校准值由 tools\unpack_starmap.py 合进星图发给玩家。
CALIB = USER / "rotation_calib.json"
CALIB_TOL = 0.05                       # 和现用相位差这么多度以上才算新校准
_calib = {"stamp": None, "data": {}}


def calibration():
    from ..core.paths import cached_json
    return cached_json(CALIB, lambda raw: {k: v for k, v in raw.items() if isinstance(v, dict) and isinstance(v.get("adj"), (int, float)) and math.isfinite(v["adj"])}, {})


def phase_from(body, g, local, when=None):
    """星系坐标 g（米）+ 同一时刻的星球坐标 local（千米）→ 这颗星球在 2020-01-01 的相位 adj（度）；
    高度对不上（两行不是同一时刻 / 认错数）返回 None"""
    v = (g[0] - body["x"], g[1] - body["y"])
    if math.hypot(*v) < 1000 or math.hypot(local[0], local[1]) < 1:
        return None
    dz = (g[2] - body["z"]) / 1000 - local[2]
    if abs(dz) > 1.0 or abs(math.hypot(*v) / 1000 - math.hypot(local[0], local[1])) > 1.0:
        return None
    a = math.atan2(local[1], local[0]) - math.atan2(v[1], v[0])        # to_local：local = R(a)·v，a = (360 − 自转角)
    rot_deg = (360 - a * R2D) % 360
    when = when or datetime.now(timezone.utc)
    days = (when - EPOCH).total_seconds() / 86400
    turn = (days / (body["rot"] / 24)) % 1 if body["rot"] else 0
    return (rot_deg - turn * 360) % 360


def _ang_diff(a, b):
    return abs((a - b + 180) % 360 - 180)


_calib_lock = threading.Lock()


def _calibrate(name, body, g, local, when):
    """locate() 里信得过的一次读数：和现用相位差 CALIB_TOL 以上就记下（连续两次一致才换，防认错数）"""
    adj = phase_from(body, g, local, when)
    if adj is None:
        return
    cal = calibration()
    cur = cal.get(name, {}).get("adj", body["adj"])
    if _ang_diff(adj, cur) < CALIB_TOL:
        return                                    # 和现用的一样（数据包里已是校准值）：不用写
    entry = {"adj": round(adj, 5), "n": cal.get(name, {}).get("n", 0) + 1, "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
             "was": round(cur, 5), "rot": body["rot"]}
    with _calib_lock:                             # 位置线程和导航接口都可能调 locate(record=True)
        pend = _calib.setdefault("pending", {})
        last = pend.get(name)
        now_s = time.time()
        if last is None or _ang_diff(last[0], adj) > CALIB_TOL or now_s - last[1] > 600:
            pend[name] = (adj, now_s)             # 第一次见：先记着，10 分钟内下一次读数一致再采用
            return
        pend.pop(name, None)
        try:
            raw = json.loads(CALIB.read_text(encoding="utf-8")) if CALIB.exists() else {}
            if not isinstance(raw, dict):
                raw = {}
        except OSError:
            raw = {}
        except ValueError:
            return False                          # 文件坏了：别把别的星球的记录一起覆盖掉，留给人看
        raw[name] = entry
        tmp = CALIB.with_name(f"rotation_calib.{threading.get_ident()}.tmp")
        try:
            CALIB.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(CALIB)
            from ..core.paths import clear_json_cache
            clear_json_cache(CALIB)               # 下次 calibration() 重读
            _offsets.pop(name, None)              # 相位换了，以前记的偏差作废
            print(f"自转相位校准：{name} {cur:.3f}° → {adj:.3f}°")
            return True
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    return False


def to_local(body, g, when=None):
    """星系坐标（米）→ 星球自转坐标系（千米），和 POI 数据同一坐标系"""
    dx, dy = body["x"] - g[0], body["y"] - g[1]
    a = (360 - rotation_deg(body, when)) / R2D
    c, s = math.cos(a), math.sin(a)
    return (-(dx * c - dy * s) / 1000, -(dx * s + dy * c) / 1000, (g[2] - body["z"]) / 1000)


def to_global(body, loc, when=None):
    """to_local 的逆运算（测试用）"""
    a = (360 - rotation_deg(body, when)) / R2D
    c, s = math.cos(a), math.sin(a)
    X, Y = loc[0] * 1000, loc[1] * 1000
    dx, dy = -(c * X + s * Y), -(-s * X + c * Y)
    return (body["x"] - dx, body["y"] - dy, loc[2] * 1000 + body["z"])


def latlon(p):
    """局部坐标（千米）→ (纬度, 经度, 到球心距离km)，经度定义和 starmap 的 POI 数据一致"""
    x, y, z = p
    r = math.sqrt(x * x + y * y + z * z) or 1e-9
    lon = (-math.atan2(x, y) * R2D + 270) % 360
    return math.asin(max(-1, min(1, z / r))) * R2D, (lon - 360 if lon > 180 else lon), r


def from_latlon(lat, lon, radius_km, height_m=0.0):
    """经纬度 + 高度 → 局部坐标（千米），latlon() 的逆运算"""
    r = radius_km + height_m / 1000
    th = -((lon - 270) / R2D)
    rho = r * math.cos(lat / R2D)
    return (rho * math.sin(th), rho * math.cos(th), r * math.sin(lat / R2D))


def bearing(a, b):
    """从 a 到 b 的初始方位角（0=北，顺时针），a、b 是局部坐标"""
    la1, lo1, _ = latlon(a)
    la2, lo2, _ = latlon(b)
    f1, f2, dl = la1 / R2D, la2 / R2D, (lo2 - lo1) / R2D
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return (math.atan2(y, x) * R2D) % 360


def surface_km(a, b, radius_km):
    """两点在地表投影之间的大圆距离"""
    la1, lo1, _ = latlon(a)
    la2, lo2, _ = latlon(b)
    f1, f2, dl = la1 / R2D, la2 / R2D, (lo2 - lo1) / R2D
    c = math.sin(f1) * math.sin(f2) + math.cos(f1) * math.cos(f2) * math.cos(dl)
    return radius_km * math.acos(max(-1, min(1, c)))


def direct_km(a, b):
    return math.dist(a, b)


def compass(deg):
    names = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    return names[int((deg + 22.5) // 45) % 8]


def zone_body(zone, data=None):
    """游戏右上角的 Zone 名（如 OOC_Stanton_4_Microtech）→ 星图里的星球名；认不出返回 None"""
    from .gridtext import fold
    data = data or load()
    z = fold(_norm(zone or ""))                  # 右上角认字常把 O 认成 0、l 认成 1：两边都归一再比
    hits = [name for name in data["bodies"] if _norm(name) and fold(_norm(name)) in z]
    return max(hits, key=len) if hits else None


# 星球 → [(时间, 游戏给的局部坐标 − 推算的)]。推算（星系坐标 + 自转角）和游戏有一个几乎不变的偏差；
# 记住它，哪次右上角那行没认出来，就用「推算 + 偏差」，位置不会在两种算法之间来回跳
_offsets = {}
OFFSET_KEEP = 600.0


def _note_offset(body, d):
    lst = _offsets.setdefault(body, [])
    lst.append((time.time(), d))
    del lst[:-7]


def _offset(body):
    import statistics
    lst = [d for t, d in _offsets.get(body, []) if time.time() - t < OFFSET_KEEP]
    if not lst:
        return None
    return tuple(statistics.median(v[i] for v in lst) for i in range(3))


def locate(g, when=None, data=None, local=None, zone=None, local_ok=None, use_offset=True, record=True):
    """判断坐标在哪个星球附近，返回 dict（body、局部坐标、经纬度、高度、src）；在深空返回最近星球 + inside=False
    local/zone：游戏右上角直接给的星球局部坐标（千米），星球对得上就用它（最准，站着不动时一点不变）：
      local_ok=True（和 CamPos 那行对上了）：相差 50 km 内都信；None（没法核对）：和推算的相差 5 km 内才信；
      False（两行对不上，有一行认错）：不用。
    不用的时候：推算的位置 + 之前记下的偏差。when：截图的时刻（星球在转，差 1 秒能差上百米）"""
    data = data or load()
    best = None
    for name, b in data["bodies"].items():
        d = math.dist(g, (b["x"], b["y"], b["z"]))
        limit = max(b["grid"], b["om"] * 1.5, b["r"] * 2)
        score = d - b["r"]
        if best is None or score < best[0]:
            best = (score, name, b, d <= limit)
    _, name, b, inside = best
    if record:                                         # record=False：只是看一眼（导航页每几秒问一次在哪），不记位置、不记偏差（复审 2026-10-27）
        _remember(g, name)
    if isinstance(when, (int, float)):
        when = datetime.fromtimestamp(when, timezone.utc)
    calc = to_local(b, g, when)
    loc, src = calc, "推算"
    off = _offset(name)
    same = bool(local and zone and zone_body(zone, data) == name)
    if same and local_ok and record:                  # 两行核对过的读数拿来校准自转相位（相位还不对时推算和游戏差得远，所以放在距离检查前面）
        try:
            if _calibrate(name, b, g, tuple(local), when):
                calc = to_local(b, g, when)           # 相位换了，推算重来
        except Exception:
            pass
    if same and local_ok is not False and math.dist(local, calc) < (50 if local_ok else 5):
        # 没法核对时再看一眼：和「推算 + 偏差」差太远（>1 km）多半是认错了一位数
        if local_ok or off is None or math.dist(local, tuple(c + o for c, o in zip(calc, off))) < 1.0:
            loc, src = tuple(local), "游戏"
            if record:
                _note_offset(name, tuple(a - c for a, c in zip(local, calc)))
    if src == "推算" and off is not None and use_offset:
        loc, src = tuple(c + o for c, o in zip(calc, off)), "推算+偏差"
    lat, lon, r = latlon(loc)
    return dict(body=name, inside=inside, x=loc[0], y=loc[1], z=loc[2], lat=lat, lon=lon,
                height_m=r * 1000 - b["r"], radius_km=b["r"] / 1000, src=src)


# ---------------------------------------------------------------- /showlocation 剪贴板

def parse_clip(text):
    """'Coordinates: x:-18930539540.1 y:-2610158765.2 z:295000.3' → (x, y, z)，星系坐标，单位米；不是坐标返回 None"""
    if not text or "Coordinates:" not in text:
        return None
    m = re.search(r"x:\s*(-?[\d.]+)\s+y:\s*(-?[\d.]+)\s+z:\s*(-?[\d.]+)", text)
    return tuple(float(v) for v in m.groups()) if m else None


def read_clipboard():
    """Windows 剪贴板文本（不依赖第三方库）"""
    if sys.platform != "win32":
        return ""
    import ctypes
    from ctypes import wintypes
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.GetClipboardData.restype = wintypes.HANDLE
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not u32.OpenClipboard(None):
        return ""
    try:
        h = u32.GetClipboardData(13)          # CF_UNICODETEXT
        if not h:
            return ""
        p = k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p) if p else ""
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


LAST = USER / "last_position.json"


def _remember(g, body):
    """记下最近一次读到的位置"""
    try:
        LAST.write_text(json.dumps({"t": time.time(), "x": g[0], "y": g[1], "z": g[2], "body": body}), encoding="utf-8")
    except Exception:
        pass


def orbital_markers(body):
    om = body["om"] / 1000
    pts = [(0, 0, om), (0, 0, -om), (0, om, 0), (0, -om, 0), (om, 0, 0), (-om, 0, 0)]
    return [dict(b=None, n=f"OM-{i + 1}", t="OM", x=p[0], y=p[1], z=p[2], qt=1) for i, p in enumerate(pts)]


def pos(p):
    return (p["x"], p["y"], p["z"])


def qt_points(body_name, data=None):
    """这个星球上能量子跳过去的点：轨道标记 OM-1~6 + 有信标的地点"""
    data = data or load()
    b = data["bodies"][body_name]
    return orbital_markers(b) + [p for p in data["pois"] if p["b"] == body_name and p["qt"] == 1]


def approaches(target, data=None, top=3):
    """离目标最近的几个量子点：[(直线km, 地表km, 从该点出发的方位, 点)]"""
    data = data or load()
    b = data["bodies"][target["b"]]
    rkm = b["r"] / 1000
    t = pos(target)
    rows = []
    for q in qt_points(target["b"], data):
        if q["n"] == target["n"] and q.get("t") == target.get("t"):
            continue
        rows.append((direct_km(pos(q), t), surface_km(pos(q), t, rkm), bearing(pos(q), t), q))
    rows.sort(key=lambda r: r[0])
    return rows[:top]


# ---------------------------------------------------------------- 报告

def plan_text(target, data=None):
    data = data or load()
    lines = [f"目的地：{label(target)}｜{body_label(target['b'])}｜{TYPE_ZH.get(target['t'], target['t'])}"
             f"｜{QT_ZH.get(target['qt'], '信标未确认')}"]
    lat, lon, r = latlon(pos(target))
    b = data["bodies"][target["b"]]
    lines.append(f"  位置：纬度 {lat:.3f}°，经度 {lon:.3f}°，海拔约 {r * 1000 - b['r']:,.0f} m")
    if target["qt"] == 1:
        lines.append("  这个地点有量子信标，直接在星图里选它量子跳过去就行。")
    lines.append("  推荐路线（先量子跳到下面的点，再按方位飞过去）：")
    for d3, ds, brg, q in approaches(target, data):
        kind = "轨道标记" if q["t"] == "OM" else "信标"
        lines.append(f"    {kind} {label(q)}：到目标 {ds:,.1f} km（直线 {d3:,.1f} km），"
                     f"出发后朝 {deg_text(brg)}°（{compass(brg)}）")
    return "\n".join(lines)


def nav_text(here, target, data=None):
    """当前位置 → 目标：方位、距离"""
    data = data or load()
    if not here["inside"] or here["body"] != target["b"]:
        return (f"当前在 {body_label(here['body'])} 附近，目标在 {body_label(target['b'])}。"
                f"先量子跳到 {body_label(target['b'])}，按上面的推荐路线走。")
    a, t = pos(here), pos(target)
    brg = bearing(a, t)
    ds = surface_km(a, t, here["radius_km"])
    d3 = direct_km(a, t)
    tgt_h = latlon(t)[2] * 1000 - here["radius_km"] * 1000
    dh = tgt_h - here["height_m"]
    line = f"→ 朝 {deg_text(brg)}°（{compass(brg)}）飞 {ds:,.1f} km（直线 {d3:,.1f} km）"
    if height_ok(here):
        line += f"｜当前高度 {here['height_m']:,.0f} m，目标 {tgt_h:,.0f} m（{'需上升' if dh > 0 else '需下降'} {abs(dh):,.0f} m）"
    if ds < 1:
        line += "\n  ✅ 已经到了（1 km 内），找找周围"
    else:
        best = approaches(target, data, top=1)
        if best and best[0][1] < ds * 0.5 and ds > 30:
            d3q, dsq, brgq, q = best[0]
            line += (f"\n  提示：直接飞太远，先量子跳到 {label(q)}（离目标 {dsq:,.1f} km），"
                     f"再朝 {deg_text(brgq)}° 飞更快")
    return line


def nearby(here, data=None, within_km=50):
    """离当前位置最近的已知地点（含路标）：(地表km, 地点) 或 None"""
    data = data or load()
    if not here["inside"]:
        return None
    a = pos(here)
    best = None
    for p in waypoints() + data["pois"]:
        if p["b"] != here["body"]:
            continue
        d = surface_km(a, pos(p), here["radius_km"])
        if best is None or d < best[0]:
            best = (d, p)
    return best if best and best[0] <= within_km else None


def near_text(here, data=None):
    hit = nearby(here, data)
    if not hit:
        return ""
    d, p = hit
    dist = f"{d * 1000:,.0f} m" if d < 1 else f"{d:,.1f} km"
    return f"附近：{label(p)}（{dist}）"


def here_text(here, data=None):
    if not here["inside"]:
        return f"深空中，最近的星球是 {body_label(here['body'])}"
    near = near_text(here, data)
    return (f"当前在 {body_label(here['body'])}：纬度 {here['lat']:.3f}°，经度 {here['lon']:.3f}°"
            + (f"，高度 {here['height_m']:,.0f} m" if height_ok(here) else "") + (f"｜{near}" if near else ""))


def height_ok(here):
    """高度能不能显示：比星图表面低 1 km 以上不可能是真地面（列夫斯基在德拉玛的钻孔里，星图半径不是这块的），不显示（审查 2026-10-30）"""
    return here.get("height_m") is not None and here["height_m"] >= -1000


# ---------------------------------------------------------------- 挖矿点（2026-10-27 解包：能量子过去、而且刷船挖矿的太空地点）

_spots = {}


def mining_spots(data=None):
    """导航里的「挖矿点」（太空目标，b = "@星系"，坐标千米）：
    - data/mining_spots.json（tools/unpack_spots.py 解物件容器生成）：派罗 15 个小行星群、86 个远矿站，冰川环带中转点、QV 碎岩站
    - 星图里有刷矿表的拉格朗日点（斯坦顿 20 个、派罗 25 个，data/mining_rocks.json 里有表的才算）
    每个点带 rocks：这里刷哪几种石头（搜「贝沙电气石」能搜到会刷它的点）"""
    from ..mining.mining_area import rocks_stamp, area_for_spot
    from ..core.paths import DATA
    p = DATA / "mining_spots.json"
    data = data or load()
    try:
        mt = p.stat().st_mtime_ns
    except OSError:
        mt = None
    stamp = (mt, rocks_stamp(), id(data), _data_stamp)        # 挖矿点文件、石头表、星图任何一个换了都重算（Codex 2026-10-27）
    if _spots.get("stamp") == stamp and "list" in _spots:
        return _spots["list"]
    out = []
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) if mt is not None else []
    except Exception:
        raw = []
    for r in raw:
        x, y, z = r["x"] / 1000, r["y"] / 1000, r["z"] / 1000
        out.append(dict(b="@" + r["sys"], sys=r["sys"], space=True, n=r.get("en") or r["id"], zh=r.get("zh") or "",
                        t="Mining Spot", x=round(x, 3), y=round(y, 3), z=round(z, 3), qt=1,
                        rocks=area_for_spot(r, (r["x"], r["y"], r["z"]))))
    for q in data.get("points") or []:
        if q.get("t") != "Lagrange Point":
            continue
        g = (q["x"], q["y"], q["z"])
        rocks = area_for_spot({"lagrange": (q.get("i") if q.get("sys") == "Pyro" else q.get("n")), "sys": q.get("sys")}, g)
        if rocks:
            out.append(dict(b="@" + q["sys"], sys=q["sys"], space=True, n=q["n"], zh=point_zh(q), t="Mining Spot",
                            x=round(q["x"] / 1000, 3), y=round(q["y"] / 1000, 3), z=round(q["z"] / 1000, 3), qt=1, rocks=rocks))
    _spots.update(stamp=stamp, list=out)
    return out


def space_points(data=None):
    """星图里的太空站、跳跃点（2026-10-28 解包星图后有了：拉格朗日点的站、派罗 / 尼克斯的门户站、INS Jericho）→ 导航的太空目标（b = "@星系"，千米）"""
    data = data or load()
    out = []
    for q in data.get("points") or []:
        if q.get("t") not in ("Orbital Station", "Naval Station", "Jumppoint"):
            continue
        out.append(dict(b="@" + q["sys"], sys=q["sys"], space=True, n=q["n"], zh=point_zh(q), t=q["t"],
                        x=round(q["x"] / 1000, 3), y=round(q["y"] / 1000, 3), z=round(q["z"] / 1000, 3), qt=1))
    return out


# ---------------------------------------------------------------- 搜索

def search(query, data=None, limit=15):
    """按中文名/英文名/星球名/类型搜地点；多个词都要命中。没信标的排前面"""
    data = data or load()
    words = [w for w in re.split(r"[\s,，]+", query.strip().lower()) if w]
    rows = []
    try:
        spots = mining_spots(data)
    except Exception:
        spots = []
    try:
        spots = spots + city_places()
    except Exception:
        pass
    try:
        spots = spots + space_points(data)
    except Exception:
        pass
    from ..core.i18n import mineral_zh
    for p in waypoints() + data["pois"] + spots:
        if p["b"] not in data["bodies"] and not is_space(p):
            continue
        rocks = " ".join(f"{o.lower()} {mineral_zh(o)}" for o in (p.get("rocks") or {}))       # 挖矿点：按会刷的矿也能搜到
        hay = " ".join([p["n"].lower(), p.get("zh", ""), rocks, poi_zh(p["n"]), p["b"].lower(), BODY_ZH.get(p["b"], ""),
                        p["t"].lower(), TYPE_ZH.get(p["t"], ""), "太空 space" if is_space(p) else "",
                        SYS_ZH.get(p.get("sys", ""), "").lower(), p.get("sys", "").lower(),
                        p.get("cat", ""), p.get("area", ""), p.get("city_zh", ""), p.get("city", "").lower()])
        if all(w in hay for w in words):
            exact = _norm(p["n"]) == _norm(query) or poi_zh(p["n"]) == query.strip()
            rows.append((not exact, p["t"] != "Waypoint", p["qt"] == 1, p["b"], p["n"], p))
    rows.sort(key=lambda r: r[:5])
    return [r[-1] for r in rows[:limit]], len(rows)


# ---------------------------------------------------------------- 城里导航（2026-10-27，先做新巴贝奇）

CITY_ARRIVE_M = 8            # 城里离目标几米以内算到了（星球上的点是 1 km）
CITY_LEAVE_M = 15            # 算到了以后，走开到这么远才算离开（实测 7–9 米来回跳，2026-10-27）
CITY_NEAR_M = 15             # 这么近就不给转向角度了：位置差一两米角度就乱跳，只说「就在附近」
CITY_FLOOR_M = 4             # 上下差这么多米以上才提示换楼层
CITY_ZH = {"NewBabbage": "新巴贝奇", "Lorville": "罗威尔", "Area18": "18区", "Orison": "奥里森", "Levski": "列夫斯基"}
_city = {}


def is_city(p):
    return bool(p) and p.get("t") == "City"


def city_places():
    """data/city_places.json（tools/unpack_city.py 解城市物件容器生成）→ 导航用的地点（星球坐标，千米）"""
    from ..core.paths import cached_json
    return cached_json(DATA / "city_places.json", _city_rows, [])


def _city_rows(raw):
    """city_places.json 原始条目 → 导航用的地点列表（只在文件变了时跑一次）"""
    if True:
        def txt(v):
            return v.strip() if isinstance(v, str) else ""
        out, ids, names = [], set(), {}
        for i, r in enumerate(raw if isinstance(raw, list) else []):
            space = isinstance(r, dict) and bool(r.get("space")) and bool(txt(r.get("sys")))
            if not isinstance(r, dict) or not (txt(r.get("body")) or space) or not txt(r.get("en")):
                continue                                   # 坏条目跳过，别的照常（Codex 2026-10-27）
            try:
                xyz = [float(r[k]) for k in ("x", "y", "z")]
            except (KeyError, TypeError, ValueError):
                continue
            if not all(math.isfinite(v) for v in xyz):
                continue
            pid = txt(r.get("src")) or f"#{i}"             # 同名地点（4 个 ASOP…）靠它区分，搜索、开始导航都用
            while pid in ids:
                pid += "+"
            ids.add(pid)
            zh = txt(r.get("zh"))
            if zh:                                         # 同一个城 / 站里中文名重名（空港两台取船终端）：后面的加 2、3
                nk = (txt(r.get("city")), zh)
                names[nk] = names.get(nk, 0) + 1
                if names[nk] > 1:
                    zh = f"{zh} {names[nk]}"
            city = txt(r.get("city"))
            kinds = [k for k in (r.get("kinds") or []) if isinstance(k, str)]
            up = r.get("up")
            q = dict(b=("@" + txt(r["sys"])) if space else txt(r["body"]), n=txt(r["en"]), zh=zh, t="City",
                     x=xyz[0], y=xyz[1], z=xyz[2], qt=0, id=pid, cat=txt(r.get("cat")), area=txt(r.get("area")), city=city,
                     city_zh=txt(r.get("site_zh")) or CITY_ZH.get(city, ""), site_en=txt(r.get("site_en")),
                     line=txt(r.get("line")), stop=txt(r.get("stop")), kinds=kinds)
            if space:                                  # 拉格朗日点、跳跃点的空间站：星系坐标（千米），不跟星球转
                q.update(space=True, sys=txt(r["sys"]))
            if isinstance(up, list) and len(up) == 3 and all(isinstance(v, (int, float)) for v in up):
                q["up"] = tuple(float(v) for v in up)    # 空间站的「上」（楼层提示用）
            out.append(q)
    return out


def city_metrics(here, target):
    """城里：直线距离（米）、目标比你高多少米（正数在上方）"""
    a, t = pos(here), pos(target)
    d = math.dist(a, t) * 1000
    if target.get("up"):                               # 空间站：按站自己的朝向分上下
        up = sum((x - y) * u for x, y, u in zip(t, a, target["up"])) * 1000
    else:
        up = (math.hypot(*t) - math.hypot(*a)) * 1000
    return d, up


def city_arrived(d, before=False):
    """到了没：进 8 米算到；已经算到了，走出 15 米才算离开"""
    return d < (CITY_LEAVE_M if before else CITY_ARRIVE_M)


def city_text(here, target, brg=None, arrived=None):
    a, t = pos(here), pos(target)
    brg = bearing(a, t) if brg is None else brg
    d, up = city_metrics(here, target)
    if city_arrived(d) if arrived is None else arrived:
        return f"✅ 到了（{d:,.0f} m 内）"
    if d < CITY_NEAR_M:
        out = f"就在附近 {d:,.0f} m"
    elif target.get("up"):                             # 空间站里南北没意义：只给距离，转向看机头 / 屏幕记号
        out = f"{d:,.0f} m"
    else:
        out = f"朝 {deg_text(brg)}°（{compass(brg)}） {d:,.0f} m"
    if up > CITY_FLOOR_M:
        out += f"\n目标在上方 {up:,.0f} 米：找电梯上楼"
    elif up < -CITY_FLOOR_M:
        out += f"\n目标在下方 {-up:,.0f} 米：找电梯下楼"
    return out


# ---------------------------------------------------------------- 找最近的医院 / 空港 / 买船（2026-10-27 老大定）

NEAR_KINDS = ("医院", "空港", "买船")
# 城里同一类有好几个点时，指向能直接办事的那个：医院 → 登记处，空港 → 取船终端（ASOP）；买船就是店本身
NEAR_PREFER = {"医院": ("Hospital Check-In", "Clinic Check-In"), "空港": ("Fleet Manager Terminal",)}
NEAR_ALIAS = {"空港": "取船"}           # 空间站里没有「空港」这个类，取船终端就是
# 在主城 / 空间站里能点的分类（2026-10-27 老大定），顺序就是按钮顺序
SITE_KINDS = ("取船", "交易", "货梯", "医院", "武器", "护甲", "服装", "部件", "吃喝", "精炼", "行政", "罚款", "租船", "买船", "地铁")
SITE_NEAR_M = 6000          # 离空间站最近的点这么近（米）算在站里
_amen = {}


def amenity_targets(kind, data=None):
    """城外有这类设施的地点（data/place_amenities.json，tools/unpack_amenities.py 从星图记录生成）→ 导航目标。
    休息站在星图里只有所在的拉格朗日点 / 跳跃点，就导航到那个点；城市用城里的点（city_places）"""
    from ..core.paths import cached_json
    data = data or load()
    rows = cached_json(DATA / "place_amenities.json", lambda r: r if isinstance(r, list) else [], [])
    pois = {}
    for q in data["pois"]:
        pois.setdefault(_norm(q["n"]), q)
    pts = {q["n"]: q for q in data.get("points") or []}
    pts_id = {q["i"]: q for q in data.get("points") or [] if q.get("i")}     # 星门站重名，按编号找（2026-10-30）
    inside = {q.get("city") for q in city_places()}
    out = []
    for r in rows:
        if not isinstance(r, dict) or kind not in (r.get("kinds") or []):
            continue
        if str(r.get("rec") or "").lower() in inside:   # 站里的点已经有了（tools/unpack_stations.py）：用站里的
            continue
        ref, zh, en = r.get("ref") or {}, (r.get("zh") or "").strip(), (r.get("en") or "").strip()
        if not en:
            continue
        if ref.get("poi"):
            q = pois.get(_norm(ref["poi"]))
            if q and q["b"] in data["bodies"]:
                out.append(q)
            elif ref.get("body") in data["bodies"] and isinstance(ref.get("local"), list) and len(ref["local"]) == 3:
                x, y, z = ref["local"]                    # 星图地点表里没有的轨道站（Everus Harbor）：相对星球的位置
                out.append(dict(b=ref["body"], n=en, zh=zh, t="Orbital Station", qt=1, x=x, y=y, z=z))
            continue
        src = (pts_id.get(ref.get("point_id")) or pts.get(ref.get("point")) if ref.get("point")
               else data["bodies"].get(ref.get("body") or ""))
        if src and src.get("sys"):
            out.append(dict(b="@" + src["sys"], sys=src["sys"], space=True, n=en, zh=zh, t="Orbital Station", qt=1,
                            x=src["x"] / 1000, y=src["y"] / 1000, z=src["z"] / 1000))
    return out


def city_targets(kind):
    """城里这类的点：有能直接办事的（登记处 / 取船终端）就只要这些（一个城可能有好几台，按远近挑），没有就这类全部"""
    by_city = {}
    alias = NEAR_ALIAS.get(kind, kind)
    for q in city_places():
        if q.get("cat") == kind or alias in (q.get("kinds") or ()):
            by_city.setdefault(q.get("city"), []).append(q)
    pref = NEAR_PREFER.get(kind)
    out = []
    for qs in by_city.values():
        good = [q for q in qs if pref and q["n"] in pref]
        out += good or qs
    return out


def site_at(g=None, here=None, when=None, data=None, system=""):
    """现在在哪个主城 / 空间站里 → {"site", "zh", "en", "kinds": [这里有的分类]}；不在就 None。
    星球上的（主城、绕星球轨道的站）：同一颗星球、离最近的点 20 km 内；拉格朗日点 / 跳跃点的站：离最近的点 SITE_NEAR_M 米内"""
    best = None
    pts = city_places()
    if here and here.get("inside"):
        for q in pts:
            if not q.get("space") and q["b"] == here.get("body"):
                d = math.dist(pos(q), pos(here)) * 1000
                if d < 20_000 and (best is None or d < best[0]):
                    best = (d, q)
    if best is None and g is not None:
        for q in pts:
            if q.get("space") and (not system or q.get("sys") == system):   # 别的星系同一个坐标也可能有站（二审 2026-10-27）
                d = math.dist(g, (q["x"] * 1000, q["y"] * 1000, q["z"] * 1000))
                if d < SITE_NEAR_M and (best is None or d < best[0]):
                    best = (d, q)
    if best is None:
        return None
    q = best[1]
    have = {k for p in pts if p.get("city") == q.get("city") for k in (p.get("kinds") or ())}
    return {"site": q.get("city"), "zh": q.get("city_zh") or "", "en": q.get("site_en") or q.get("city") or "",
            "kinds": [k for k in SITE_KINDS if k in have]}


def site_nearest(site, kind, g=None, when=None, data=None, here=None):
    """主城 / 空间站里这一类的点，近的在前 → [(距离米或 None, 点)]。
    here：locate() 的结果，同一颗星球上用它校准（和实时导航、屏幕记号同一个基准，二审 2026-10-27）"""
    data = data or load()
    out = []
    qs = [q for q in city_places() if q.get("city") == site and kind in (q.get("kinds") or ())]
    pref = NEAR_PREFER.get(kind)
    good = [q for q in qs if pref and q["n"] in pref]
    for q in good or qs:
        d = None
        if g is not None:
            try:
                d = math.dist(g, target_global(q, data, when, (g, here, when) if here else None))
            except Exception:
                d = None
        out.append((d is None, d or 0.0, label(q), d, q))
    out.sort(key=lambda r: r[:3])
    return [(d, q) for *_, d, q in out]


def station_text(g, target, data=None, when=None, arrived=None):
    """拉格朗日点 / 跳跃点空间站里（星系坐标）：距离 + 上下楼层；转向看机头一行和屏幕记号"""
    tg = target_global(target, data, when)
    d = math.dist(g, tg)
    if city_arrived(d) if arrived is None else arrived:
        return f"✅ 到了（{d:,.0f} m 内）"
    out = f"就在附近 {d:,.0f} m" if d < CITY_NEAR_M else f"{d:,.0f} m"
    up = sum((t - a) * u for t, a, u in zip(tg, g, target.get("up") or (0, 0, 0)))
    if up > CITY_FLOOR_M:
        out += f"\n目标在上方 {up:,.0f} 米：找电梯上楼"
    elif up < -CITY_FLOOR_M:
        out += f"\n目标在下方 {-up:,.0f} 米：找电梯下楼"
    return out


def target_system(p, data=None):
    data = data or load()
    if is_space(p):
        return p.get("sys") or ""
    b = data["bodies"].get(p.get("b"))
    return b["sys"] if b else ""


def nearest(kind, g=None, system="", when=None, data=None, here=None):
    """最近的医院 / 空港 / 买船。g：玩家星系坐标（米），不知道就给 None。
    → [(距离米或 None, 目标)]，近的在前；同星系的排在前面。城里：同一个城里只按城里的点算（不会跑去城外的站）"""
    data = data or load()
    cands = city_targets(kind) + amenity_targets(kind, data)
    site = site_at(g, here, when, data, system)
    if site:                                           # 已经在某个主城 / 空间站里：只要这里的
        inside = [q for q in city_targets(kind) if q.get("city") == site["site"]]
        if inside:
            cands = inside
    out = []
    for q in cands:
        d = None
        if g is not None:
            try:
                d = math.dist(g, target_global(q, data, when, (g, here, when) if here else None))
            except Exception:
                d = None
        same = not system or target_system(q, data) == system
        if not same:                                  # 每个星系各有自己的坐标系：跨星系的距离没意义（二审 2026-10-27）
            d = None
        out.append((not same, d is None, d or 0.0, label(q), d, q))
    out.sort(key=lambda r: r[:4])
    seen, res = set(), []
    for *_, d, q in out:
        k = (q.get("id") or q["n"], q.get("b"))
        if k not in seen:
            seen.add(k)
            res.append((d, q))
    return res


# ---------------------------------------------------------------- 城里分段路线：走到站台 → 坐地铁（可换乘一次）→ 出站走到目的地

METRO_MIN_M = 400            # 起点和目的地隔这么远（米）以上才考虑坐地铁
METRO_BOARD_M = 25           # 离上车的站台这么近：提示上车
LINE_ZH = {"loop": "微科地铁环线", "perim_line_a": "外环 A 线", "perim_line_b": "外环 B 线", "sp_line": "空港线",
           "com_line": "商业线", "cen_line": "中央线"}


def _metro_lines(city):
    """城里的地铁：{线: {站: 站台}}；只有一个站的线（另一头的站台没解出来）不算"""
    lines = {}
    for q in city_places():
        if q.get("city") == city and q.get("cat") == "地铁" and q.get("line") and q.get("stop"):
            lines.setdefault(q["line"], {}).setdefault(q["stop"], q)
    return {k: v for k, v in lines.items() if len(v) >= 2}


def city_route(here, target):
    """城里怎么去：[(动作, 站台, 线)]，动作 walk / ride / transfer；不用坐地铁（太近、没地铁、走路更快）返回 None"""
    if not is_city(target) or here.get("body") != target.get("b"):
        return None
    lines = _metro_lines(target.get("city"))
    stops = [(ln, q) for ln, st in lines.items() for q in st.values()]
    if not stops:
        return None
    a, t = pos(here), pos(target)
    direct = math.dist(a, t) * 1000
    if direct < METRO_MIN_M:
        return None
    l0, s0 = min(stops, key=lambda x: math.dist(a, pos(x[1])))
    l1, s1 = min(stops, key=lambda x: math.dist(t, pos(x[1])))
    if s0["stop"] == s1["stop"]:
        return None
    walk = (math.dist(a, pos(s0)) + math.dist(pos(s1), t)) * 1000
    if walk > direct * 0.8:                              # 走到站台再走出来，比直接走还远
        return None
    on = [ln for ln, st in lines.items() if s0["stop"] in st and s1["stop"] in st]
    if on:                                               # 一条线直达
        return [("walk", lines[on[0]][s0["stop"]], on[0]), ("ride", lines[on[0]][s1["stop"]], on[0])]
    for la, sa in lines.items():                         # 换乘一次：起点那条线和终点那条线有同一个站（罗威尔的地铁中心）
        if s0["stop"] not in sa:
            continue
        for lb, sb in lines.items():
            if lb == la or s1["stop"] not in sb:
                continue
            mid = set(sa) & set(sb)
            if mid:
                m = sorted(mid)[0]
                return [("walk", sa[s0["stop"]], la), ("ride", sa[m], la), ("transfer", sb[m], lb), ("ride", sb[s1["stop"]], lb)]
    return None


LINE_EN = {"loop": "MetroLoop", "perim_line_a": "Perimeter Line A", "perim_line_b": "Perimeter Line B", "sp_line": "Spaceport Line",
           "com_line": "Commerce Line", "cen_line": "Central Line"}


def _bi(zh, en):
    """导航双语（2026-10-27 老大定）：中文（English）；没中文或一样就只写英文"""
    zh, en = (zh or "").strip(), (en or "").strip()
    return f"{zh}（{en}）" if zh and en and zh != en else (zh or en)


def _line_name(ln):
    return _bi(LINE_ZH.get(ln, ""), LINE_EN.get(ln, ln))


def _stop_name(q):
    """站名：「地铁中心（Metro Center）」"""
    zh = q.get("zh") or ""
    zh = zh.replace("地铁站台 · ", "").split("（")[0] if "·" in zh else zh
    en = q["n"].split(" - ", 1)[1] if " - " in q["n"] else q["n"]
    return _bi(zh, en)


REROUTE_M = 150              # 比离这一段的目标最近时又远了这么多（米）：走偏了，重新规划
REROUTE_RIDE_M = 3000        # 坐车那几段：轨道会绕弯，放宽


def city_leg(here, target, plan=None, inner=""):
    """这一段该去哪：(该指向的点, 步骤文字[]）。不用坐地铁：指向目的地、没有步骤。
    plan：导航时传同一个 dict 进来——路线定下来按段往前走（到了一段的站台就进下一段），
    走偏了才重新规划；不然每帧重算，坐车坐到一半会跳回第一步（二审 2026-10-27）。
    绕星球轨道的空间站：按区域坐电梯分段（station_leg，inner 是右上角最里层 Zone 名）"""
    a = pos(here)
    if station_lifts().get(target.get("city") or ""):
        if here.get("body") != target.get("b"):
            return target, []
        return station_leg(a, target, plan, inner)
    if plan is None:
        route = city_route(here, target)
        i = 1 if route and math.dist(a, pos(route[0][1])) * 1000 < METRO_BOARD_M else 0
    else:
        key = (target.get("id") or target["n"], target.get("b"), here.get("body"))
        if plan.get("key") == key and "route" in plan:
            route, i = plan["route"], plan["i"]
            goal = route[i][1] if route and i < len(route) else target
            d = math.dist(a, pos(goal)) * 1000
            ride = bool(route) and i < len(route) and route[i][0] == "ride"
            if d > plan["best"] + (REROUTE_RIDE_M if ride else REROUTE_M):
                plan.clear()
            else:
                plan["best"] = min(plan["best"], d)
        if plan.get("key") != key or "route" not in plan:
            route = city_route(here, target)
            plan.clear()
            plan.update(key=key, route=route, i=0, best=float("inf"))
            i = 0
        while route and i < len(route) and math.dist(a, pos(route[i][1])) * 1000 < METRO_BOARD_M:
            i += 1                                      # 到了这一段的站台：下一段
            plan["best"] = float("inf")
        plan["i"] = i
        if plan["best"] == float("inf"):
            goal = route[i][1] if route and i < len(route) else target
            plan["best"] = math.dist(a, pos(goal)) * 1000
    if not route:
        return target, []
    goal = route[i][1] if i < len(route) else target
    steps, n = [], 0
    for act, q, ln in route:
        n += 1
        if act == "walk":
            steps.append(f"{n}. 步行到 {label(q)}")
        elif act == "ride":
            steps.append(f"{n}. 坐 {_line_name(ln)} 到 {_stop_name(q)} 下车")
        else:
            steps.append(f"{n}. 换乘 {_line_name(ln)}")
    steps.append(f"{n + 1}. 出站步行到 {label(target)}")
    steps = [("→ " if k == i else "   ") + s for k, s in enumerate(steps)]    # 当前这步用 →（悬浮窗的字体没有 ▶，画成方块，2026-10-28）
    return goal, steps


# ---------------------------------------------------------------- 空间站里分段路线：走到电梯门 → 坐电梯（可换乘一次）→ 出电梯走到目的地（2026-10-28）
# 数据：data/station_lifts.json（tools/unpack_lifts.py 解包生成）：每个站的区域、电梯线（每站的门）、机库电梯门、站里的点在哪个区域

LIFT_BOARD_M = 25            # 坐电梯：离下车的门这么近算到了（居住区各层的门上下只隔 16 米：以后加居住区目的地时这里要注意）
LIFT_SWITCH_M = 8            # 在电梯里直接换乘（一帧大厅都没读到）：离这一段的上车门这么近、又比离上一段下车门近，算换到了新轿厢
LIFT_SPOT_M = 10             # 读不到区域名时：离某个已知点（电梯门、站里的点）这么近，就当在那个点的区域
LIFT_OFF_N = 3               # 读不到区域名、连续这么多帧都在路线外的区域：重新规划
LIFT_WALK_M = 4              # 读不到区域名时：离上车的门这么近算进了电梯（各部电梯的门最近只隔 3 米，审查 2026-10-28）
LIFT_NEAR_M = 300            # 读不到区域名时按坐标认区域：离最近的已知点（电梯门、站里的点）这么近才算数
LIFT_FAR_M = 3000            # 离站里所有已知点都这么远：不在这个站里
HANGAR_LIFT_M = 250          # 在机库里：离机库电梯门这么近才算是这个机库的


def station_lifts():
    """rr_* 站记录名 → 这个站的区域 / 电梯 / 机库数据"""
    from ..core.paths import cached_json
    return cached_json(DATA / "station_lifts.json", _lift_rows, {})


def _lift_rows(raw):
    """station_lifts.json → {站: 数据}；结构不对的站整个跳过，别的照常（坏数据不能让导航线程抛错退出）"""
    def xyz(v):
        return isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)

    def ok(st):
        if isinstance(st, dict) and st.get("ok") is False:     # 解包自检没过（点和电梯门对不上）：不分段，照旧直线指
            return False
        if not (isinstance(st, dict) and isinstance(st.get("areas"), dict) and isinstance(st.get("places"), dict)
                and isinstance(st.get("lifts"), list) and isinstance(st.get("hangars"), list)):
            return False
        if not all(isinstance(a, str) and isinstance(v, dict) for a, v in st["areas"].items()):
            return False
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in st["places"].items()):
            return False

        def names(d):
            return isinstance(d.get("en"), str) and isinstance(d.get("zh"), str)
        for ln in st["lifts"]:
            if not (isinstance(ln, dict) and isinstance(ln.get("stops"), list) and names(ln)):
                return False
            for s in ln["stops"]:
                if not (isinstance(s, dict) and names(s) and isinstance(s.get("gates"), list) and all(xyz(g) for g in s["gates"])
                        and (s.get("area") is None or isinstance(s.get("area"), str))):
                    return False
        return all(isinstance(h, dict) and isinstance(h.get("size"), str) and all(xyz(h.get(k)) for k in ("door", "lift", "spawn"))
                   for h in st["hangars"])
    sts = raw.get("stations") if isinstance(raw, dict) else None
    return {k: v for k, v in sts.items() if ok(v)} if isinstance(sts, dict) else {}


def _zkey(s):
    return re.sub(r"[\s_\-]", "", s or "").lower()


ZONE_MARGIN = 0.04           # 区域名模糊比较：第一名和第二名差不到这么多就不认（ObjectContainer-000 / -001 只差一位）


def zone_kind(inner, st):
    """右上角最里层 Zone 名 → 站里的区域 id；"lift" = 在电梯轿厢里；"hangar" = 在机库里；认不出 None。
    轿厢、机库名字末尾的 _<数字> 是每次随机的编号，只看开头（字模认错一两个字母也算）；
    区域名两边都不去编号（rs_refin_occu_001、ObjectContainer-001 的编号是名字的一部分），先找一模一样的，再模糊比较"""
    from difflib import SequenceMatcher
    k = _zkey(inner)
    if not k:
        return None
    if k.startswith("transitcarriage") or SequenceMatcher(None, k[:15], "transitcarriage").ratio() >= 0.85:
        return "lift"
    if k.startswith("hangar") or (SequenceMatcher(None, k[:6], "hangar").ratio() >= 0.8 and ("front" in k or "reststop" in k)):
        return "hangar"
    names = [a for a, v in st["areas"].items() if v.get("zone")]
    exact = [a for a in names if _zkey(a) == k]
    if exact:
        return exact[0] if len(exact) == 1 else None
    sc = sorted(((SequenceMatcher(None, _zkey(a), k).ratio(), a) for a in names), reverse=True)
    if not sc or sc[0][0] < 0.85 or (len(sc) > 1 and sc[0][0] - sc[1][0] < ZONE_MARGIN):
        return None
    return sc[0][1]


def _hangar_size(inner):
    m = re.search(r"(small|medium|large)", _zkey(inner))
    return m[1].capitalize() if m else None


def _station_points(st, site):
    """站里已知的点 → [(位置千米, 区域)]：电梯门、机库（门、电梯门、出生点）、站里的导航点"""
    pts = [(tuple(g), s["area"]) for ln in st["lifts"] for s in ln["stops"] if s.get("area") for g in s["gates"]]
    pts += [(tuple(h[k]), "hangar") for h in st["hangars"] for k in ("door", "lift", "spawn")]
    pts += [(pos(q), st["places"][q["id"]]) for q in city_places() if q.get("city") == site and q["id"] in st["places"]]
    return pts


def _hangar_lift(st, a, size=None):
    """在机库里：自己这个机库的电梯门（离得最近的、尺寸对得上的，HANGAR_LIFT_M 内）"""
    hs = [h for h in st["hangars"] if not size or h["size"] == size]
    best = min(hs, key=lambda h: math.dist(a, h["lift"]), default=None)
    return tuple(best["lift"]) if best and math.dist(a, best["lift"]) * 1000 < HANGAR_LIFT_M else None


def _goal(target, xyz, en, zh, tag):
    """分段的目标点：坐标系、所属站都跟着最终目的地（指向、屏幕记号照常用）"""
    return dict(target, x=xyz[0], y=xyz[1], z=xyz[2], n=en, zh=zh, id=f"{target.get('id') or target['n']}#{tag}", cat="")


def station_route(st, a, cur, dest, target, size=None):
    """从区域 cur 到区域 dest 怎么坐电梯（最多两段）→ [段]，段 = dict(act=walk/ride, goal, line, stop, frm, to)；没路返回 None。
    a：现在的位置（千米）；目的地在同一个区域里返回 []"""
    if cur == dest:
        return []
    t = pos(target)

    def gates(stop, ref):
        if stop["area"] == "hangar":
            g = _hangar_lift(st, ref, size)
            return [g] if g else []
        return [tuple(g) for g in stop["gates"]]
    found, frontier = [], [(cur, [])]
    for _depth in range(2):
        nxt = []
        for area, path in frontier:
            for ln in st["lifts"]:
                for on in ln["stops"]:
                    if on.get("area") != area:
                        continue
                    for off in ln["stops"]:
                        if not off.get("area") or off["area"] == area or off["area"] == "hangar" or not off["gates"]:
                            continue
                        p2 = path + [(ln, on, off)]
                        (found if off["area"] == dest else nxt).append((off["area"], p2))
        if found:
            break
        frontier = nxt
    best = None
    for _area, path in found:                                 # 几条一样少换乘的：最后下车的门离目的地最近的那条（居住区按楼层）
        legs, ref, prev = [], a, None
        for ln, on, off in path:
            ga = gates(on, ref)
            if not ga:
                legs = None
                break
            g_on = min(ga, key=lambda g: math.dist(g, ref))
            g_off = min((tuple(g) for g in off["gates"]), key=lambda g: math.dist(g, t))
            board = _goal(target, g_on, ln["en"], ln["zh"], f"{len(legs)}")
            # on_gates：上车站所有的门（走哪扇都算）；prev_gates：上一段下车站的门（在电梯里直接换乘时比远近）
            legs.append(dict(act="walk", goal=board, line=ln, stop=off, frm=on["area"], to=on["area"], on_gates=ga, prev_gates=prev))
            prev = [tuple(g) for g in off["gates"]]
            legs.append(dict(act="ride", goal=_goal(target, g_off, off["en"], off["zh"], f"{len(legs)}"), line=ln, stop=off,
                             frm=on["area"], to=off["area"], board=board, gates=[tuple(g) for g in off["gates"]], on_gates=ga))
            ref = g_off
        if legs is not None:                                  # 下车门一样近（居住区各层都能下到大厅）：比第一段上车门离人多远
            cost = (round(math.dist(ref, t), 6), math.dist(a, pos(legs[0]["goal"])))
            if best is None or cost < best[0]:
                best = (cost, legs)
    return best[1] if best else None


def _lift_steps(legs, i, kind, target):
    """路线 → 步骤文字：「1. 去机库电梯」「2. 坐机库电梯到「大厅」」「3. 换站内电梯到「购物中心」」「4. 出电梯到 …」；当前这步标 →"""
    rows, cur = [], None
    for k, L in enumerate(legs):
        ln = L["line"]["zh"] or L["line"]["en"]
        st = L["stop"]["zh"] or L["stop"]["en"]
        if L["act"] == "walk" and k == 0:
            rows.append(f"去{ln}")
        elif L["act"] == "ride" and k == 1:
            rows.append(f"坐{ln}到「{st}」")
        elif L["act"] == "ride":
            rows.append(f"换{ln}到「{st}」")
        if k == i:
            cur = len(rows) - 1 if L["act"] == "ride" or k == 0 else len(rows)
    rows.append(f"出电梯到 {label(target)}")
    cur = len(rows) - 1 if cur is None else cur
    out = [("→ " if n == cur else "   ") + f"{n + 1}. {s}" for n, s in enumerate(rows)]
    if kind == "lift" and i < len(legs) and legs[i]["act"] == "ride":
        out.insert(cur + 1, f"   在电梯里选「{legs[i]['stop']['zh'] or legs[i]['stop']['en']}」")
    return out


def _car_no(inner):
    """轿厢 Zone 名末尾的编号（每部电梯的轿厢不一样）"""
    m = re.search(r"(\S+)\s*$", (inner or "").replace("_", " "))
    return m[1] if m else ""


def _car_changed(a, b):
    """两个轿厢编号明显不同（逐位比，差 3 位以上；允许字模认错一两位）"""
    if not a or not b:
        return True
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b)) > 2


def station_leg(a, target, plan=None, inner=""):
    """空间站里这一段该去哪：(该指向的点, 步骤文字[])；同一个区域、没数据、认不出在哪：指向目的地、没有步骤。
    a：现在的位置（千米，和目的地同一个坐标系）；inner：右上角最里层 Zone 名（displayinfo 的 inner_zone）。
    plan：导航时传同一个 dict——路线定下来按段往前走：
      走到电梯门：读得到区域名时进了电梯（区域名变成轿厢、并且已经出过上一部电梯）才算完成；读不到时离门 LIFT_WALK_M 米内；
      坐电梯：区域名变成下车的区域，或离下车站任一个门 25 米内（读得到区域名时要在电梯里）；没进电梯（区域名是上车的区域）时指针还指上车门。
    区域名对不上路线（走错了）才重新规划"""
    st = station_lifts().get(target.get("city") or "")
    dest = st and st["places"].get(target.get("id") or "")         # 按导航的 id（同名的店两处各一个：id 带 +）
    plan = {} if plan is None else plan
    if not dest:
        plan.clear()
        return target, []
    pts = _station_points(st, target.get("city"))
    near = min(((math.dist(a, p) * 1000, ar) for p, ar in pts), default=(float("inf"), None))
    if near[0] > LIFT_FAR_M:                                  # 不在这个站里
        plan.clear()
        return target, []
    kind = zone_kind(inner, st)
    key = (target.get("id") or target["n"], target.get("city"))
    legs = plan.get("legs") if plan.get("key") == key else None

    def near_m(gs):
        return min(math.dist(a, g) for g in gs) * 1000

    def advance(i):
        """到了这一段就往下推，返回推到第几段"""
        if kind and kind != "lift":
            plan["out"] = True
        while i < len(legs):
            L = legs[i]
            if L["act"] == "walk":
                d_on = near_m(L["on_gates"])
                if kind is None:                              # 读不到区域名：离任一扇上车门 4 米内，或已经到了下一段的下车门附近（比离上车门近）
                    nx = near_m(legs[i + 1]["gates"]) if i + 1 < len(legs) else float("inf")
                    done = d_on < LIFT_WALK_M or (nx < LIFT_BOARD_M and nx < d_on)
                elif kind == "lift":
                    # 进了电梯要在这段上车门 8 米内（误进别的电梯不算）；没出过上一部电梯时（一帧大厅都没读到）
                    # 还要轿厢编号跟上一部明显不同、离这段上车门比离上一段下车门近
                    done = d_on < LIFT_SWITCH_M and (plan["out"] or bool(L.get("prev_gates")) and d_on < near_m(L["prev_gates"])
                                                     and _car_changed(_car_no(inner), plan.get("car", "")))
                else:
                    done = False                              # 还没进电梯
            else:
                d = near_m(L["gates"])                        # 到站：离下车门 25 米内而且比离上车门近（居住区各层门只隔 16–23 米）
                done = ((kind in (None, "lift") and d < LIFT_BOARD_M and d < near_m(L["on_gates"]))
                        or (kind not in (None, "lift") and kind == L["to"]))
            if not done:
                break
            i += 1
            plan["out"] = kind != "lift"
        if kind == "lift" and i < len(legs) and legs[i]["act"] == "ride":
            plan["car"] = _car_no(inner)                      # 正坐着的这部电梯的轿厢编号（换乘时比）
        return i
    if legs is not None:
        i = advance(plan["i"])
        want = (legs[i]["frm"], legs[i]["to"]) if i < len(legs) else (dest,)
        if kind not in (None, "lift") and kind not in want:   # 区域名对不上路线：重新规划
            legs = None
        elif kind is None:                                    # 读不到区域名：按坐标纠正，都要连着 LIFT_OFF_N 帧（坐电梯路过、读空一帧不算）
            spot = near[1] if near[0] < LIFT_SPOT_M else None
            if math.dist(a, pos(target)) * 1000 < LIFT_BOARD_M or spot == dest:
                plan["off"] = 0
                plan["arr"] = plan.get("arr", 0) + 1          # 已经在目的地（的区域）
                if plan["arr"] >= LIFT_OFF_N:
                    i = len(legs)
            elif spot and spot not in {x for L in legs for x in (L["frm"], L["to"])} | {dest}:
                plan["arr"] = 0
                plan["off"] = plan.get("off", 0) + 1          # 在路线外的区域
                if plan["off"] >= LIFT_OFF_N:
                    legs = None
            else:
                plan["off"] = plan["arr"] = 0
        else:                                                 # 在电梯里、或读得出区域名：两个计数都从头数
            plan["off"] = plan["arr"] = 0
        if legs is not None:
            plan["i"] = i
    if legs is None:
        if kind == "lift":                                    # 在电梯里开始（或重新）规划：只有就在某扇门口才知道在哪，不然先直接指目的地，出了电梯再规划
            gates = [(math.dist(a, g) * 1000, s["area"]) for ln in st["lifts"] for s in ln["stops"] if s.get("area") for g in s["gates"]]
            gates += [(math.dist(a, h["lift"]) * 1000, "hangar") for h in st["hangars"]]
            g0 = min(gates, default=(float("inf"), None))
            cur = g0[1] if g0[0] < LIFT_SWITCH_M else None
        else:
            cur = kind if kind is not None else (near[1] if near[0] < LIFT_NEAR_M else None)
        legs = station_route(st, a, cur, dest, target, _hangar_size(inner)) if cur else None
        plan.clear()
        if legs is None:
            return target, []
        plan.update(key=key, legs=legs, i=0, out=True)              # 开始时就在电梯里：当它就是要坐的那部
        i = plan["i"] = advance(0)                                    # 规划完马上往下推（人已经在电梯里才开始导航）
    if not legs:
        return target, []
    if i >= len(legs):
        goal = target
    elif legs[i]["act"] == "ride" and kind not in (None, "lift") and kind == legs[i]["frm"]:
        goal = legs[i]["board"]                                # 还没进电梯：继续指上车的门
    else:
        goal = legs[i]["goal"]
    return goal, _lift_steps(legs, i, kind, target)


def deg_text(brg):
    """方位角显示成 000~359（359.6° 显示 000，不显示 360）"""
    return f"{round(brg) % 360:03d}"


def _short(here, target, brg=None, arrived=None):
    """悬浮窗那一行；brg：要显示的方位角（导航时做过防抖），不给就现算；arrived：城里到了没（导航时带缓冲）"""
    if not here["inside"] or here["body"] != target["b"]:
        return f"先量子跳到 {BODY_ZH.get(target['b'], target['b'])}"
    if is_city(target):
        return city_text(here, target, brg, arrived)
    a, t = pos(here), pos(target)
    brg = bearing(a, t) if brg is None else brg
    ds = surface_km(a, t, here["radius_km"])
    return f"朝 {deg_text(brg)}°（{compass(brg)}） {ds:,.1f} km" + ("\n✅ 到了" if ds < 1 else "")


def _read_position(timeout=None):
    """读一次游戏右上角的位置：(星系坐标, 读到的信息)；超时返回 (None, None)"""
    from .displayinfo import Reader
    r = Reader(every=1.0)
    end = time.time() + timeout if timeout else None
    while end is None or time.time() < end:
        g = r.poll(force=True)
        if g:
            return g, r.info
        time.sleep(1.0)
    return None, None


def track(target, data=None):
    """导航（命令行版）：每秒读一次右上角的位置，刷新方位和距离"""
    from ..app.overlay import hud
    from .displayinfo import Reader
    data = data or load()
    ov = hud()
    print("\n切回游戏就行。要先在游戏控制台（~ 键）输入 r_DisplayInfo 2，右上角显示坐标。")
    print("  按 Ctrl+C 结束导航。\n")
    head = f"→ {label(target)}"
    ov.set("导航", f"{head}\n等待位置…")
    reader = Reader(every=1.0)
    try:
        while True:
            g = reader.poll()
            if g:
                info = reader.info or {}
                here = locate(g, when=info.get("t"), data=data, local=info.get("local"),
                              zone=info.get("zone"), local_ok=info.get("local_ok"))
                print(time.strftime("%H:%M:%S"), here_text(here, data))
                print("  " + nav_text(here, target, data).replace("\n", "\n  "))
                near = near_text(here, data)
                ov.set("导航", f"{head}\n{_short(here, target)}" + (f"\n{near}" if near else ""))
            ov.sleep(0.2)
    finally:
        ov.clear("导航")


def where_am_i(data):
    """读一次位置并返回（读不到返回 None）"""
    print("切回游戏，读右上角的位置（要开着 r_DisplayInfo 2）…")
    g, info = _read_position(timeout=20)
    if not g:
        print("20 秒没读到：游戏控制台输入 r_DisplayInfo 2，右上角显示坐标后再试")
        return None
    here = locate(g, when=info.get("t"), data=data, local=info.get("local"), zone=info.get("zone"),
                  local_ok=info.get("local_ok"))
    print(here_text(here, data))
    return here


# ---------------------------------------------------------------- 菜单

def ask():
    data = load()
    print(f"星图数据：starmap.space（{data.get('fetched', '?')}）。菜单 5 可更新。")
    print("输入目的地（中文或英文，可加星球名或类型，例：戴玛尔 洞穴 / Kudre / 残骸 耶拉）")
    print("输入「路标」管理自定义路标；直接回车看自己在哪；输入 q 退出。\n")
    while True:
        try:
            q = input("目的地 > ").strip()
        except EOFError:
            return
        if q.lower() == "q":
            return
        if not q:
            where_am_i(data)
            continue
        if q in ("路标", "lubiao", "wp"):
            target = waypoint_menu(data)
            if not target:
                continue
        else:
            hits, total = search(q, data)
            if not hits:
                print("没找到，换个词试试（地名、星球名都行）\n")
                continue
            target = pick(hits, total)
            if not target:
                continue
        print()
        print(plan_text(target, data))
        try:
            track(target, data)
        except KeyboardInterrupt:
            print("\n（导航结束）\n")


def pick(hits, total=None):
    for i, p in enumerate(hits, 1):
        print(f"  {i:>2}. {label(p)}｜{body_label(p['b'])}｜{TYPE_ZH.get(p['t'], p['t'])}"
              f"｜{QT_ZH.get(p['qt'], '信标未确认')}")
    if total and total > len(hits):
        print(f"  …共 {total} 个，加个词缩小范围（比如星球名）")
    sel = input("选序号（回车返回）> ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(hits):
        return hits[int(sel) - 1]
    return None


def _find_body(text, data):
    t = text.strip().lower()
    for name in data["bodies"]:
        if t in (name.lower(), BODY_ZH.get(name, "\0")):
            return name
    cands = [n for n in data["bodies"] if t in n.lower() or t in BODY_ZH.get(n, "")]
    return cands[0] if len(cands) == 1 else None


def waypoint_menu(data):
    """自定义路标：输入坐标或用当前位置新建；返回要导航去的路标（或 None）"""
    while True:
        wps = [w for w in waypoints() if w["b"] in data["bodies"]]
        print("\n路标：" + ("还没有" if not wps else ""))
        for i, w in enumerate(wps, 1):
            lat, lon, r = latlon(pos(w))
            h = r * 1000 - data["bodies"][w["b"]]["r"]
            print(f"  {i:>2}. {w['n']}｜{body_label(w['b'])}｜纬度 {lat:.3f}° 经度 {lon:.3f}° 高度 {h:,.0f} m")
        print("  序号 = 导航过去｜+ = 用坐标新建｜* = 用当前位置新建｜- 序号 = 删除｜回车返回")
        cmd = input("路标 > ").strip()
        if not cmd:
            return None
        if cmd.isdigit() and 1 <= int(cmd) <= len(wps):
            return wps[int(cmd) - 1]
        if cmd.startswith("-") and cmd[1:].strip().isdigit() and 1 <= int(cmd[1:]) <= len(wps):
            name = wps[int(cmd[1:]) - 1]["n"]
            delete_waypoint(name)
            print(f"已删除：{name}")
        elif cmd == "+":
            print("格式：星球 纬度 经度 [高度米]，例：戴玛尔 54.54 38.01 500")
            parts = re.split(r"[\s,，]+", input("坐标 > ").strip())
            try:
                body = _find_body(parts[0], data)
                lat, lon = float(parts[1]), float(parts[2])
                h = float(parts[3]) if len(parts) > 3 else 0.0
                assert body and -90 <= lat <= 90 and -360 <= lon <= 360
            except Exception:
                print("没看懂，按格式再输一次")
                continue
            name = input("路标名字 > ").strip() or f"{BODY_ZH.get(body, body)} {lat:.2f},{lon:.2f}"
            add_waypoint(name, body, from_latlon(lat, lon, data["bodies"][body]["r"] / 1000, h))
            print(f"已添加：{name}")
        elif cmd == "*":
            here = where_am_i(data)
            if not here:
                continue
            if not here["inside"]:
                print("不在星球附近，没法在这里放路标")
                continue
            name = input("路标名字 > ").strip() or time.strftime("路标 %m-%d %H:%M")
            add_waypoint(name, here["body"], pos(here))
            print(f"已添加：{name}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        update()
    else:
        ask()
