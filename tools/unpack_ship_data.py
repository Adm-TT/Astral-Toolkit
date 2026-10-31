"""解包：飞船 / 地面载具数据包（2026-10-27 老大要：默认配置 + 基本参数 + 信号截面，带去做新产品；AT 用它补「随船自带」来源）。

用法：.venv\\Scripts\\python.exe -X utf8 tools\\unpack_ship_data.py [输出目录]
读（都是 unpack_all 解出来的）：
  E:\\Game3\\unpack\\dcb_json\\libs\\foundry\\records\\   游戏数据库（飞船、部件、厂商、货舱容器）
  E:\\Game3\\unpack\\vehicles_xml\\                       飞船定义（质量、船体部件血量；CryXmlB 转出来的）
  E:\\Game3\\unpack\\p4k_out\\Data\\Localization\\english\\global.ini   游戏英文文本
  data\\loc\\global_zh.ini                                汉化包（中文名一律用汉化组的）
写：
  <输出目录>\\ships.json        全量（每条船：基本参数、船体、装甲、截面、默认配置树）
  <输出目录>\\ships.csv         飞船总表（一船一行）
  <输出目录>\\loadouts.csv      默认配置明细（一船一挂点一行）
  <输出目录>\\README.md         字段说明、数据版本、算法
  data\\ship_items.json         给 AT：部件英文名 → 自带这个部件的船（中文名）
只发整理出的数字和名字，不发游戏原文件、模型、贴图。
"""
import csv
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sc_mining.update.localization import read_ini  # noqa: E402

WORK = Path(r"E:\Game3\unpack")
REC = WORK / "dcb_json" / "libs" / "foundry" / "records"
VXML = WORK / "vehicles_xml"
EN_INI = WORK / "p4k_out" / "Data" / "Localization" / "english" / "global.ini"
ZH_INI = ROOT / "data" / "loc" / "global_zh.ini"
OUT_DEFAULT = Path(r"E:\Game3\飞船数据")
GAME = Path(r"D:\StarCitizen\LIVE")

# 不是玩家能拥有的版本：AI、模板、展示、教程、剧情、残骸……（文件名里带这些的不收）
NOT_PLAYER = re.compile(r"(_ai(_|$)|_pu_ai|template|_display|_test|tutorial|unmanned|_ea_|derelict|wreck|boarded|"
                        r"_s42|cinematic|_dummy|_prop|hijacked|_npc|_fleetweek|_showdown|_pir$|_crim$|_civ$|_sec_|_bis\d|"
                        r"_hangar|_destructible|_spawn|_mission|_drone|_tow$|_exec_|_lowpoly|_nointerior|_noint|_fake|"
                        r"_temp|_tier_\d|_prison|_tsg|_fw_\d+|^eaobjective|^probe_)", re.I)
# 默认配置里不收的部件类型（界面、门、灯、座位、控制器这些不算「配置」）
SKIP_TYPES = {"Display", "Door", "DoorController", "Light", "LightController", "Seat", "SeatAccess", "SeatDashboard", "Usable",
              "Relay", "AirTrafficController", "DockingCollar", "LandingSystem", "SelfDestruct", "CommsController",
              "EnergyController", "CoolerController", "ShieldController", "WeaponController", "MiningController",
              "FuelController", "CapacitorAssignmentController", "FlightController", "Paints", "Elevator", "Button",
              "Interactable", "SalvageController", "TractorBeamController", "Ping", "TurretBase_Controller",
              "AttachedPart", "Transponder", "Scanner", "Misc", "Container_Interior", "ManneuverThruster", "MainThruster",
              "Lightgroup", "StatusScreen", "Sensor", "InventoryContainer", "VehicleController", "WheeledController",
              "Player", "Decal", "Flair_Wall", "Flair_Floor", "Flair_Surface", "Holder", "Bed", "Armor_Interior",
              "DockingAnimator", "ControlPanel", "Room", "WeaponPersonal", "RoomConnector", "Cargo_Interior"}
DAMAGE_KEYS = ("Physical", "Energy", "Distortion", "Thermal", "Biochemical", "Stun")


def load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def comp(v, t):
    return next((c for c in (v or {}).get("Components") or [] if c and c.get("_Type_") == t), None)


def ref_path(ref):
    """「file://./../../libs/foundry/records/x/y.json」→ 记录文件路径"""
    m = re.search(r"libs/foundry/records/(.+?\.json)", str(ref or ""))
    return REC / m.group(1) if m else None


def find_key(o, name):
    """深层找第一个叫 name 的键（不是字典 / 列表的值）"""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == name and not isinstance(v, (dict, list)):
                return v
            r = find_key(v, name)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_key(v, name)
            if r is not None:
                return r
    return None


class Loc:
    """「@vehicle_NameMISC_Prospector」→ 中文（汉化组）/ 英文（游戏英文文本）"""

    def __init__(self):
        self.zh = {k.lower(): v for k, v in read_ini(ZH_INI).items()}
        self.en = {k.lower(): v for k, v in read_ini(EN_INI).items()} if EN_INI.exists() else {}

    @staticmethod
    def _clean(v):
        return re.sub(r"<[^>]+>", "", v or "").strip()

    def en_of(self, key):
        k = (key or "").lstrip("@").lower()
        v = self._clean(self.en.get(k, ""))
        return v.split("\\n")[0].strip() if v and not v.startswith("@") and k not in ("loc_empty", "loc_placeholder") else ""

    def zh_of(self, key):
        """汉化组的写法有「中文\\nEnglish」「English\\n中文」「中文English」：只取中文那部分；汉化组没翻的返回空"""
        k = (key or "").lstrip("@").lower()
        v = self._clean(self.zh.get(k, ""))
        if not v or k in ("loc_empty", "loc_placeholder"):
            return ""
        parts = [p.strip() for p in v.split("\\n") if p.strip()]
        cjk = [p for p in parts if re.search(r"[\u4e00-\u9fff]", p)]
        if not cjk:
            return ""
        zh = cjk[0]
        en = self.en_of(key)
        if en and zh.endswith(en) and len(zh) > len(en):          # 「勘探者Prospector」→ 勘探者
            zh = zh[: -len(en)].strip()
        # 汉化组在中文后面接了英文（「5CA 阿库拉Akura」「刀轴 MH2 型采矿激光器Arbor MH2」）：去掉中文后面紧贴的英文尾巴
        m = re.fullmatch(r"(.*[\u4e00-\u9fff）)」”])\s*([A-Za-z][A-Za-z0-9 \-'\".()/&]*)", zh)
        if m and re.search(r"[A-Za-z]{3,}", m.group(2)) and re.search(r"[a-z]", m.group(2)):   # 「南船座 SRV」「自由枪骑兵 MAX」的型号码留着
            zh = m.group(1).strip()
        return zh


def build_item_index():
    files = list((REC / "entities" / "scitem").rglob("*.json"))

    def one(f):
        d = load(f)
        if not d:
            return None
        v = d.get("_RecordValue_") or {}
        att = comp(v, "SAttachableComponentParams") or {}
        ad = att.get("AttachDef") or {}
        return d.get("_RecordName_", "").split(".", 1)[-1].lower(), f.stem.lower(), {
            "file": f, "type": ad.get("Type") or "", "sub": ad.get("SubType") or "", "size": ad.get("Size"),
            "grade": ad.get("Grade"), "name_key": ((ad.get("Localization") or {}).get("Name") or ""),
            "mfr": ad.get("Manufacturer")}
    idx = {}
    with ThreadPoolExecutor(32) as ex:
        for r in ex.map(one, files):
            if r:
                idx.setdefault(r[0], r[2])
                idx.setdefault(r[1], r[2])
    return idx


def manufacturers(loc):
    out = {}
    for f in (REC / "scitemmanufacturer").glob("*.json"):
        d = load(f)
        v = (d or {}).get("_RecordValue_") or {}
        name_key = ((v.get("Localization") or {}).get("Name")) or ""
        out[f.resolve()] = {"code": v.get("Code") or "", "en": loc.en_of(name_key), "zh": loc.zh_of(name_key)}
    return out


def container_scu(c):
    """货舱容器记录 → SCU。封闭式（箱子、矿袋）直接写 capacity；开放式货舱格只给内部尺寸（米），
    按 1 SCU = 1.25 米见方的格子数（德雷克黑弯刀主货舱 5×6.25×2.5 → 4×5×2 = 40）"""
    it = c.get("inventoryType") or {}
    if it.get("_Type_") == "InventoryOpenContainerType":
        dim = c.get("interiorDimensions") or {}
        try:
            n = 1
            for k in ("x", "y", "z"):
                n *= int(float(dim.get(k) or 0) / 1.25 + 1e-6)
            return n or None
        except (TypeError, ValueError):
            return None
    return find_key(it, "standardCargoUnits")


def _vxml_file(name):
    name = Path(str(name or "")).name
    if not name:
        return None
    if not name.lower().endswith(".xml"):
        name += ".xml"
    return next((p for p in VXML.rglob("*.xml") if p.name.lower() == name.lower()), None)


def vehicle_xml(path, mod=""):
    """飞船定义 XML → (质量 kg, [(部件名, 血量)])。mod：改装版名字（VehicleComponentParams.modification，比如 MAX、
    Interdiction）：有补丁文件（Modifications/MISC_Freelancer_MAX）就用补丁文件里的部件；没有就按 <Elem idRef name value> 改属性
    （独立核对 2026-10-27：自由枪骑兵 MAX 质量 341,408 在补丁文件里，以前只读了基础版 219,396）"""
    f = _vxml_file(path)
    if not f:
        return None, []
    try:
        root = ET.parse(f).getroot()
    except ET.ParseError:
        return None, []
    base = _mass_parts(root)
    if mod:
        m = next((x for x in root.iter("Modification") if (x.get("name") or "").lower() == mod.lower()), None)
        if m is not None:
            pf = _vxml_file(m.get("patchFile"))
            if pf:
                try:
                    mass, parts = _mass_parts(ET.parse(pf).getroot())
                    # 补丁文件多数只改飞控 / 部分部件：没写质量、没写部件血量的就沿用基础版（野马 Beta、旋风 AA 等）
                    return (mass if mass is not None else base[0]), (parts or base[1])
                except ET.ParseError:
                    pass
            else:
                ids = {e.get("id"): e for e in root.iter() if e.get("id")}
                for e in m.iter("Elem"):
                    tgt = ids.get(e.get("idRef"))
                    if tgt is not None and e.get("name"):
                        tgt.set(e.get("name"), e.get("value") or "")
                mass, parts = _mass_parts(root)
                return (mass if mass is not None else base[0]), (parts or base[1])
    return base


def _num(v):
    """游戏文件里的数字偶尔夹着看不见的字符（短剑勇士版的质量后面有 U+202C）"""
    t = "".join(ch for ch in str(v or "") if ch.isdigit() or ch in ".-eE")
    try:
        return float(t)
    except ValueError:
        return None


def _mass_parts(root):
    mass = None
    parts = []
    for p in root.iter("Part"):
        if mass is None and p.get("mass"):
            mass = _num(p.get("mass"))
        hp = _num(p.get("damageMax")) if p.get("damageMax") else None
        if hp is not None:
            parts.append((p.get("name"), hp))
    return mass, parts


class Ships:
    def __init__(self):
        t = time.time()
        self.loc = Loc()
        self.items = build_item_index()
        self.mfr = manufacturers(self.loc)
        self._detail = {}
        print(f"部件索引 {len(self.items)} 条、厂商 {len(self.mfr)} 家（{time.time() - t:.1f} 秒）")

    def mfr_of(self, ref):
        p = ref_path(ref)
        return self.mfr.get(p.resolve()) if p else None

    def item(self, cls):
        """部件类名 → 名字、类型、尺寸、关键数值（缓存）"""
        cls = (cls or "").lower()
        if cls in self._detail:
            return self._detail[cls]
        it = self.items.get(cls)
        if not it:
            self._detail[cls] = None
            return None
        v = (load(it["file"]) or {}).get("_RecordValue_") or {}
        d = {"class": cls, "type": it["type"], "subtype": it["sub"], "size": it["size"], "grade": it["grade"],
             "name_en": self.loc.en_of(it["name_key"]), "name_zh": self.loc.zh_of(it["name_key"]),
             "manufacturer": (self.mfr_of(it["mfr"]) or {}).get("code") or ""}
        sh = comp(v, "SCItemShieldGeneratorParams")
        if sh:
            d["shield_hp"], d["shield_regen"] = sh.get("MaxShieldHealth"), sh.get("MaxShieldRegen")
        if it["type"] in ("FuelTank", "QuantumFuelTank", "ExternalFuelTank"):
            d["fuel_scu"] = find_key([c for c in v.get("Components") or [] if c and "capacity" in c], "standardCargoUnits")
        ifcs = comp(v, "IFCSParams")
        if ifcs:
            d["speed"] = {"scm": ifcs.get("scmSpeed"), "boost_forward": ifcs.get("boostSpeedForward"), "max": ifcs.get("maxSpeed")}
        qd = comp(v, "SCItemQuantumDriveParams")
        if qd:
            d["qt_speed_mps"] = (qd.get("params") or {}).get("driveSpeed")
        arm = comp(v, "SCItemVehicleArmorParams")
        if arm:
            dm = arm.get("damageMultiplier") or {}
            d["armor"] = {"signal_ir": arm.get("signalInfrared"), "signal_em": arm.get("signalElectromagnetic"),
                          "signal_cs": arm.get("signalCrossSection"),
                          "damage_multiplier": {k.lower(): dm.get("Damage" + k) for k in DAMAGE_KEYS}}
        inv = comp(v, "SCItemInventoryContainerComponentParams")
        if inv:
            c = ((load(ref_path(inv.get("containerParams")) or "") or {}).get("_RecordValue_")) or {}
            scu = container_scu(c)
            if scu:
                d["cargo_scu"] = scu
        elif it["type"] == "Container":
            scu = find_key([c for c in v.get("Components") or [] if c and "capacity" in c], "standardCargoUnits")
            if scu:
                d["cargo_scu"] = scu
        self._detail[cls] = d
        return d

    def own_loadout(self, cls):
        """部件记录自己带的默认配置条目（货舱门 → 货舱格，2026-10-27 星座仙女座的货舱就挂在这里）"""
        it = self.items.get(cls)
        if not it:
            return []
        v = (load(it["file"]) or {}).get("_RecordValue_") or {}
        lo = comp(v, "SEntityComponentDefaultLoadoutParams") or {}
        return ((lo.get("loadout") or {}).get("entries")) or []

    def loadout(self, entries, depth=0, stack=()):
        out = []
        if depth > 8:
            return out
        for e in entries or []:
            cls = (e.get("entityClassName") or "").lower()
            if not cls and e.get("entityClassReference"):
                m = re.search(r"/([^/]+)\.json", str(e["entityClassReference"]))
                cls = m.group(1).lower() if m else ""
            sub_ = ((e.get("loadout") or {}).get("entries"))
            if not sub_ and cls and cls not in stack:
                sub_ = self.own_loadout(cls)
            kids = self.loadout(sub_, depth + 1, stack + (cls,))
            it = self.item(cls) if cls else None
            if not it:
                out += kids
                continue
            node = {"port": e.get("itemPortName"), **it}
            if kids:
                node["children"] = kids
            out.append(node)
        return out

    def ship(self, f, kind):
        d = load(f)
        v = (d or {}).get("_RecordValue_") or {}
        vc = comp(v, "VehicleComponentParams")
        if not vc or not vc.get("vehicleName"):
            return None
        ad = (comp(v, "SAttachableComponentParams") or {}).get("AttachDef") or {}
        sig = comp(v, "SSCSignatureSystemParams") or {}
        cs = ((((sig.get("radarProperties") or {}).get("crossSectionParams")) or {}).get("crossSection")) or {}
        lo = comp(v, "SEntityComponentDefaultLoadoutParams") or {}
        tree = self.loadout(((lo.get("loadout") or {}).get("entries")))
        flat = list(walk(tree))
        mass, parts = vehicle_xml(vc.get("vehicleDefinition"), vc.get("modification") or "")
        stem = f.stem.lower()  # noqa: F841
        armor = next((n for n in flat if n["type"] == "Armor"), None)
        cs_mult = ((armor or {}).get("armor") or {}).get("signal_cs") or 1.0
        fc = next((n for n in flat if n.get("speed")), None)
        m = self.mfr_of(vc.get("manufacturer")) or {}
        ship = {
            "class": f.stem.lower(), "kind": kind,
            "name_en": self.loc.en_of(vc["vehicleName"]), "name_zh": self.loc.zh_of(vc["vehicleName"]),
            "manufacturer": m,
            "career": {"en": self.loc.en_of(vc.get("vehicleCareer")), "zh": self.loc.zh_of(vc.get("vehicleCareer"))},
            "role": {"en": self.loc.en_of(vc.get("vehicleRole")), "zh": self.loc.zh_of(vc.get("vehicleRole"))},
            "size": ad.get("Size"), "crew": vc.get("crewSize"), "mass_kg": mass,
            "hull": {"hp_total": round(sum(h for _, h in parts)), "parts": [{"name": n, "hp": h} for n, h in parts]},
            "cross_section_raw": [cs.get(k) for k in ("x", "y", "z")] if cs else None,
            "cross_section": sorted(round(cs[k] * cs_mult) for k in ("x", "y", "z")) if cs else None,
            "armor": {"class": armor["class"], **armor.get("armor", {})} if armor else None,
            "shield_generators": sum(1 for n in flat if n.get("shield_hp")) or None,
            "shield_hp_each": max((n.get("shield_hp") or 0 for n in flat), default=0) or None,
            "shield_hp_all": round(sum(n.get("shield_hp") or 0 for n in flat)) or None,
            "shield_regen_all": round(sum(n.get("shield_regen") or 0 for n in flat)) or None,
            "cargo_scu": round(sum(n.get("cargo_scu") or 0 for n in flat if not is_pod(n) and not is_personal(n)), 2) or None,
            "personal_storage_scu": round(sum(n.get("cargo_scu") or 0 for n in flat if is_personal(n)), 2) or None,
            "mining_pod_scu": round(sum(n.get("cargo_scu") or 0 for n in flat if is_pod(n)), 2) or None,
            "fuel_hydrogen_scu": round(sum(n.get("fuel_scu") or 0 for n in flat if n["type"] == "FuelTank"), 2) or None,
            "fuel_quantum_scu": round(sum(n.get("fuel_scu") or 0 for n in flat if n["type"] == "QuantumFuelTank"), 2) or None,
            "speed": (fc or {}).get("speed"),
            "loadout": prune(tree),
        }
        return ship


def is_personal(n):
    """不是货舱格、也不是矿袋的小容器（座位旁储物、格斗机的库存格）：不算货舱（独立核对 2026-10-27：Gladius 0.65 是库存）"""
    return not is_pod(n) and n["type"] != "CargoGrid"


def is_pod(n):
    """采矿船的矿石吊舱（矿袋）：不算货舱"""
    return n["type"] == "Container" and ("mining" in (n.get("port") or "") or "shipmining" in n["class"])


def orphan_grids(S, ships):
    """货舱格记录没被任何配置引用（游牧者、锤头鲨……挂法在模型文件里，数据库里查不到）：
    名字「<船类名>_cargogrid_*」或「<前缀>_cargogrid_<型号>」能唯一对上一条还没有货舱的船，才把容量算给它，并注明"""
    used = set()
    for sh in ships:
        for n in walk(sh["loadout"]):
            used.add(n["class"])
    # 被门、模块（报复者前后舱模块的升降梯门）自带配置引用的货舱格：有正经挂法，只是这条船默认没装，不算孤儿
    for k, it in S.items.items():
        if it["type"] in ("Door", "Module", "Container", "Usable") and it["file"].stem.lower() == k:
            for e in S.own_loadout(k):
                ref = (e.get("entityClassName") or "").lower() or \
                    (re.search(r"/([^/]+)\.json", str(e.get("entityClassReference") or "")) or [None, ""])[1].lower()
                if "cargogrid" in ref:
                    used.add(ref)
    classes = {sh["class"]: sh for sh in ships}
    got = {}
    for k, it in S.items.items():
        if "cargogrid" not in k or it["file"].stem.lower() != k or "template" in k or k in used:
            continue
        m = re.match(r"(.+?)_cargogrid(?:_(.+))?$", k)
        if not m:
            continue
        pre, rest = m.group(1), (m.group(2) or "")
        if any(u.startswith(pre + "_cargogrid") for u in used):     # 同系列的货舱格有正经挂法（报复者的模块）：这一个也不按名字归
            continue
        if rest and f"{pre}_{rest}" in classes:                     # 完整后缀先对：anvl_hornet_cargogrid_f7c_mk2 → anvl_hornet_f7c_mk2
            cands = {f"{pre}_{rest}"}
        else:
            cands = {c for c in classes if c == pre} | {f"{pre}_{t}" for t in rest.split("_") if f"{pre}_{t}" in classes}
        if len(cands) != 1:
            continue
        c = S.item(k)
        if c and c.get("cargo_scu"):
            got.setdefault(cands.pop(), []).append((k, c["cargo_scu"]))
    for cls, grids in got.items():
        sh = classes[cls]
        if sh["cargo_scu"]:
            continue
        sh["cargo_scu"] = round(sum(v for _, v in grids), 2)
        sh["cargo_note"] = "货舱格没挂在默认配置里，按名字归属：" + "、".join(k for k, _ in grids)


def walk(tree, path=()):
    for n in tree:
        yield n
        yield from walk(n.get("children") or [], path + (n["port"],))


def prune(tree):
    """默认配置里只留「配置」：武器、导弹、护盾、发电机、冷却器、量子引擎、雷达、油箱、装甲、货舱、采矿/打捞头……"""
    out = []
    for n in tree:
        kids = prune(n.get("children") or [])
        keep = n["type"] not in SKIP_TYPES and not n["type"].endswith("Controller")
        if keep:
            m = {k: v for k, v in n.items() if k != "children" and v not in (None, "")}
            if kids:
                m["children"] = kids
            out.append(m)
        else:
            out += kids
    return out


def flat_rows(tree, path=""):
    for n in tree:
        p = f"{path}/{n['port']}" if path else n["port"]
        yield p, n
        yield from flat_rows(n.get("children") or [], p)


README = """# 星际公民 飞船数据包

- 游戏版本：{game}（正式服）
- 生成时间：{made}
- 来源：我们自己解包的游戏文件（StarBreaker 0.3.2），不是第三方网站
- 条数：{n}（飞船 {sp}、地面载具 {gr}）。已去掉 AI、模板、展示、任务专用版。同名的其他版本（皮肤版、金标版、特别版）不单列，记在 other_classes 里
- 中文名一律用汉化组的译名（玩家汉化包）；汉化组没翻的保留英文

## 文件

| 文件 | 内容 |
|---|---|
| ships.json | 全量：每条船的基本参数、船体、装甲、信号截面、默认配置树 |
| ships.csv | 飞船总表，一船一行（Excel 直接打开，UTF-8 带 BOM） |
| loadouts.csv | 默认配置明细，一船一挂点一行（port_path 用 / 表示嵌套：武器架/武器） |

## ships.json 字段

| 字段 | 说明 |
|---|---|
| class | 游戏内部类名（唯一标识） |
| kind | spaceship 飞船 / ground 地面载具 |
| name_zh / name_en | 中文名（汉化组）/ 英文名（游戏英文文本） |
| manufacturer | 厂商：code 代码、zh、en |
| career / role | 职业（战斗、工业…）/ 定位（轻型采矿、重型战斗…），各有 zh、en |
| size | 尺寸等级（1 最小） |
| crew | 船员数（游戏记录的 crewSize） |
| mass_kg | 质量，千克（飞船定义里根部件的 mass；改装版按游戏的改装补丁算，比如自由枪骑兵 MAX）。已知和星际 wiki 不一致：大力神 C2、货轮 C（游戏定义文件里就是这个数，wiki 的来源不明） |
| hull.hp_total / hull.parts | 船体各部件血量（damageMax）之和 / 每个部件的血量 |
| shield_generators | 默认配置里护盾发生器个数 |
| shield_hp_each / shield_hp_all / shield_regen_all | 单个发生器的护盾值 / 全部发生器之和 / 全部的每秒回复之和（4.x 的数值，比 3.x 大很多是正常的）。注意：游戏里同时开着的发生器可能少于装着的（星际 wiki 对勘探者、秃鹫只算 2 个，第 3 个锁着），数据库里没有这个限制，所以给全部和单个，按需要自己乘 |
| cargo_scu | 货舱 SCU：只算货舱格（CargoGrid，1.25 米一格）。小战斗机的库存格不算 |
| cargo_note | 只在货舱格没挂在默认配置、按名字归属时出现（目前锤头鲨、游牧者、135c） |
| mining_pod_scu | 采矿船矿石吊舱（矿袋）SCU，不算货舱 |
| personal_storage_scu | 个人储物 / 库存格 SCU（座位旁储物、战斗机库存），不算货舱 |
| fuel_hydrogen_scu / fuel_quantum_scu | 氢油箱 / 量子油箱容量（SCU） |
| speed | 默认飞控的速度（米/秒）：scm 巡航、boost_forward 前向加速、max 最高 |
| cross_section_raw | 飞船记录里的截面（x、y、z 三个方向，未乘装甲） |
| cross_section | 截面乘出厂装甲的截面系数，从小到大排（AT 雷达用的就是这个） |
| armor | 出厂装甲：signal_ir 红外系数、signal_em 电磁系数、signal_cs 截面系数、damage_multiplier 各类伤害倍率（physical 实弹、energy 能量、distortion 扰流、thermal 热能、biochemical 生化、stun 眩晕） |
| loadout | 默认配置树。每个节点：port 挂点名、class 部件类名、name_zh/name_en、type/subtype 类型、size 尺寸、grade 等级、manufacturer 厂商代码；有的带数值（shield_hp、fuel_scu、cargo_scu、qt_speed_mps 量子速度米/秒、speed、armor）；children 是下一层（武器架里的武器、导弹架里的导弹、采矿臂里的采矿头） |
| other_classes | 同名的其他版本类名（主记录优先用 _gs 重做后的现行版本） |

## 算法和已知限制

- 默认配置只列「配置」：武器、导弹、护盾、发电机、冷却器、量子引擎、雷达、油箱、装甲、货舱、采矿/打捞头等。门、门控、灯、屏幕、面板、房间、座位、灭火器、各种控制器、推进器不列（推进器的数据在原始记录里，需要再加）。
- 速度：天蝎座蝎心的最高速度和星际 wiki 差约 6%（1,385 对 1,303），默认飞控记录里就是 1,385。
- 部件自己带的默认配置会展开（货舱门里的货舱格、炮塔里的武器）。
- 红外、电磁信号是运行时按用电和部件算的，这里只给装甲的系数，没有算总值。
- 发电机、冷却器的功率、热量数值没有导出（4.x 改成资源网络，算法另做）。
- 速度是默认飞控的标称值，不含加力燃料、大气阻力。
"""


def game_version():
    try:
        b = json.loads((GAME / "build_manifest.id").read_text(encoding="utf-8")).get("Data") or {}
        return f"{b.get('Branch', '')} {b.get('RequestedP4ChangeNum', '')}".strip()
    except Exception:
        return ""


def main(out_dir=OUT_DEFAULT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    S = Ships()
    ships, skipped = [], 0
    for kind, sub in (("spaceship", "spaceships"), ("ground", "groundvehicles")):
        for f in sorted((REC / "entities" / sub).glob("*.json")):
            if NOT_PLAYER.search(f.stem):
                skipped += 1
                continue
            s = S.ship(f, kind)
            if s:
                ships.append(s)
    orphan_grids(S, ships)
    # 同一个名字只留一条主记录（类名最短的那条，一般就是商店里卖的那版），其他版本（皮肤版、金标版、改了配置的特别版）
    # 记在 other_classes 里
    by_name = {}
    for s in ships:
        by_name.setdefault(s["name_en"], []).append(s)
    uniq = []
    for name, group in by_name.items():
        group.sort(key=lambda x: ("_gs" not in x["class"], len(x["class"]), x["class"]))
        main_ = group[0]
        main_["other_classes"] = [g["class"] for g in group[1:]]
        uniq.append(main_)
    uniq.sort(key=lambda x: (x["kind"], x["manufacturer"].get("code") or "", x["name_en"]))
    ver = game_version()
    meta = {"game": ver, "made": time.strftime("%Y-%m-%d %H:%M"), "source": "游戏解包（StarBreaker 0.3.2）",
            "count": len(uniq)}
    (out_dir / "ships.json").write_text(json.dumps({"meta": meta, "ships": uniq}, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["class", "kind", "name_zh", "name_en", "manufacturer", "career_zh", "role_zh", "size", "crew", "mass_kg",
            "hull_hp_total", "shield_generators", "shield_hp_each", "shield_hp_all", "shield_regen_all", "cargo_scu", "mining_pod_scu", "personal_storage_scu",
            "fuel_hydrogen_scu", "fuel_quantum_scu",
            "scm_speed", "boost_forward", "max_speed", "cs_min", "cs_mid", "cs_max", "armor_signal_ir", "armor_signal_em",
            "armor_signal_cs"]
    with open(out_dir / "ships.csv", "w", encoding="utf-8-sig", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(cols)
        for s in uniq:
            cs = s["cross_section"] or [None] * 3
            a = s["armor"] or {}
            sp = s["speed"] or {}
            w.writerow([s["class"], s["kind"], s["name_zh"], s["name_en"], s["manufacturer"].get("code"),
                        s["career"]["zh"] or s["career"]["en"], s["role"]["zh"] or s["role"]["en"], s["size"], s["crew"],
                        s["mass_kg"], s["hull"]["hp_total"], s["shield_generators"], s["shield_hp_each"], s["shield_hp_all"],
                        s["shield_regen_all"], s["cargo_scu"], s["mining_pod_scu"], s["personal_storage_scu"],
                        s["fuel_hydrogen_scu"], s["fuel_quantum_scu"], sp.get("scm"), sp.get("boost_forward"),
                        sp.get("max"), *cs, a.get("signal_ir"), a.get("signal_em"), a.get("signal_cs")])
    with open(out_dir / "loadouts.csv", "w", encoding="utf-8-sig", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["ship_class", "ship_zh", "ship_en", "port_path", "item_class", "item_zh", "item_en", "type", "subtype",
                    "size", "grade", "manufacturer"])
        for s in uniq:
            for p, n in flat_rows(s["loadout"]):
                w.writerow([s["class"], s["name_zh"], s["name_en"], p, n["class"], n.get("name_zh", ""), n.get("name_en", ""),
                            n["type"], n.get("subtype", ""), n.get("size", ""), n.get("grade", ""), n.get("manufacturer", "")])
    (out_dir / "README.md").write_text(README.format(game=ver, made=meta["made"], n=len(uniq),
                                                     sp=sum(1 for x in uniq if x["kind"] == "spaceship"),
                                                     gr=sum(1 for x in uniq if x["kind"] == "ground")), encoding="utf-8")
    # 给 AT：部件英文名 → 自带这个部件的船（中文名，汉化组没翻的用英文）
    by = {}
    for s in uniq:
        if s["kind"] != "spaceship" and s["kind"] != "ground":
            continue
        for _, n in flat_rows(s["loadout"]):
            if n.get("name_en"):
                by.setdefault(n["name_en"], set()).add(s["name_zh"] or s["name_en"])
    (ROOT / "data" / "ship_items.json").write_text(
        json.dumps({"game": ver, "items": {k: sorted(v) for k, v in sorted(by.items())}}, ensure_ascii=False,
                   separators=(",", ":")), encoding="utf-8")
    print(f"飞船 / 载具 {len(uniq)} 条（跳过 AI、模板、任务版等 {skipped} 个记录；同名的其他版本 {len(ships) - len(uniq)} 条记在 other_classes）→ {out_dir}")
    print(f"AT：{len(by)} 种部件有「随船自带」来源 → data\\ship_items.json")
    return uniq


if __name__ == "__main__":
    main(*(sys.argv[1:2] or []))
