"""解包：制造蓝图 + 任务 / 维科洛兑换（2026-10-28，老大定：不再等 scmdb，自己从游戏文件出）。

用法：.venv\\Scripts\\python.exe -X utf8 tools\\unpack_crafting.py [--compare]
读：E:\\Game3\\unpack\\dcb_json（unpack_all 导出的 Game2.dcb JSON）+ 游戏英文文本 p4k_out\\Data\\Localization\\english\\global.ini
写：data\\unpack\\crafting_blueprints-<版本>.json、merged-<版本>.json —— 和 scmdb 一样的格式（只写我们用到的字段），
    所以 sc_mining.crafting.build_crafting.build / wikelo.build 不用改，照旧生成 data\\crafting.json、data\\wikelo.json。
    版本号来自游戏 build_manifest.id（4.10.2-live.12913470 这种写法），文件名里带 -live. 让 latest_live 认得出。
--compare：和本机已有的 scmdb 同版本文件逐条对照，列出蓝图数、材料、数量、品质、来源的差别（发数据包前人看一遍）。
只发整理出的数字，不发游戏原文件。
"""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sc_mining.update.localization import read_ini  # noqa: E402

WORK = Path(os.environ.get("AT_UNPACK_DIR", r"E:\Game3\unpack"))
GAME = Path(os.environ.get("SC_GAME_DIR", r"D:\StarCitizen\LIVE"))
REC = WORK / "dcb_json" / "libs" / "foundry" / "records"
EN_INI = WORK / "p4k_out" / "Data" / "Localization" / "english" / "global.ini"
OUT_DIR = ROOT / "data" / "unpack"          # 和 scmdb 下载的分开放（同版本文件名一样）
SCMDB_DIR = ROOT / "data" / "scmdb"

_cache = {}


def dl(xs):
    """列表里只要字典项（导出的 JSON 里常有 null）"""
    return [x for x in (xs or []) if isinstance(x, dict)]


def rec(path):
    """按 file://./../../libs/foundry/records/xxx.json 或 records 下的相对路径读记录（带缓存）"""
    if not path:
        return None
    p = re.sub(r"^file://\./(\.\./)*libs/foundry/records/", "", path).replace("\\", "/")
    if p in _cache:
        return _cache[p]
    f = REC / p
    try:
        _cache[p] = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _cache[p] = None
    return _cache[p]


def relpath(path):
    return re.sub(r"^file://\./(\.\./)*libs/foundry/records/", "", path or "").replace("\\", "/")


class Loc:
    def __init__(self):
        self.ini = {k.lower(): v for k, v in read_ini(EN_INI).items()} if EN_INI.exists() else {}

    def zh_en(self, key):
        """汉化包里这条文本的英文部分（「奎里努斯科技 Quirinus Tech」→ Quirinus Tech）；没有英文就给中文"""
        if not key or not key.startswith("@"):
            return ""
        if not hasattr(self, "_zh"):
            zh_ini = ROOT / "data" / "loc" / "global_zh.ini"
            self._zh = {k.lower(): v for k, v in read_ini(zh_ini).items()} if zh_ini.exists() else {}
        v = re.sub(r"<[^>]+>", "", self._zh.get(key[1:].lower(), "")).split("\\n")[0].strip()
        m = re.search(r"[A-Za-z][A-Za-z0-9 &'.\-]+$", v)
        return (m.group(0).strip() if m and len(m.group(0).strip()) > 2 else v) or ""

    def text(self, key, default=""):
        if not key or not key.startswith("@"):
            return default
        v = self.ini.get(key[1:].lower())
        if v is None or key in ("@LOC_PLACEHOLDER", "@LOC_UNINITIALIZED", "@LOC_EMPTY"):
            return default
        v = re.sub(r"<[^>]+>", "", v).split("\\n")[0].strip()
        return v or default


def game_version():
    """4.10.2-live.12913470：和 scmdb 的版本写法一样（latest_live 按 -live. 认正式服）"""
    try:
        b = json.loads((GAME / "build_manifest.id").read_text(encoding="utf-8")).get("Data") or {}
        ver = re.search(r"\d+\.\d+\.\d+", b.get("Branch", "") + " " + b.get("Version", ""))
        branch = "live" if "live" in GAME.name.lower() or "live" in b.get("Branch", "").lower() else GAME.name.lower()
        return f"{ver.group(0) if ver else '0.0.0'}-{branch}.{b.get('RequestedP4ChangeNum', '0')}"
    except Exception as e:
        raise SystemExit(f"❌ 读不到游戏版本（{GAME / 'build_manifest.id'}）：{e}")


# ---------------------------------------------------------------- 实体：名字、厂商、尺寸

def attach_def(entity):
    for c in dl((entity or {}).get("_RecordValue_", {}).get("Components")):
        if isinstance(c, dict) and "AttachDef" in c:
            return c["AttachDef"]
    return {}


def entity_name(loc, entity):
    """物品 / 载具的英文名"""
    if not entity:
        return ""
    a = attach_def(entity)
    name = loc.text((a.get("Localization") or {}).get("Name"))
    if name:
        return name
    for c in dl(entity["_RecordValue_"].get("Components")):        # 载具：VehicleComponentParams.vehicleName
        if isinstance(c, dict):
            for k in ("vehicleName", "Name"):
                if isinstance(c.get(k), str) and c[k].startswith("@"):
                    n = loc.text(c[k])
                    if n:
                        return n
    return ""


def manufacturer(loc, entity):
    """厂商英文名：记录里的 Localization.Name → 「manufacturer_name<代码>」文本 → 代码 → 文件名大写（VOLT 这种记录里只有占位符）"""
    a = attach_def(entity)
    path = a.get("Manufacturer")
    if not path and entity:                         # 头盔这类没填厂商的：按实体名前缀找厂商记录（kap_… → kap.json）
        prefix = entity["_RecordName_"].split(".", 1)[-1].split("_", 1)[0].lower()
        path = _mfr_by_code().get(prefix)
    m = rec(path)
    if not m:
        return None
    v = m.get("_RecordValue_", {})
    code = (v.get("Code") or "").strip()
    key = (v.get("Localization") or {}).get("Name") or (f"@manufacturer_name{code}" if code else "")
    return loc.text(key) or loc.zh_en(key) or code or Path(relpath(path)).stem.upper() or None


_mfr_index = {}


def _mfr_by_code():
    """{文件名（厂商代码小写）: 记录路径}"""
    if not _mfr_index:
        for f in (REC / "scitemmanufacturer").rglob("*.json"):
            _mfr_index.setdefault(f.stem.lower().split(".")[-1], str(f.relative_to(REC)).replace("\\", "/"))
    return _mfr_index


# ---------------------------------------------------------------- 资源表

def resources(loc):
    """{记录名 ResourceType.X: (英文显示名, 文本键)}"""
    db = rec("resourcetypedatabase/resourcetypedatabase.json")
    out = {}

    def walk(g):
        for r in dl(g.get("resources")):
            out[r["_RecordName_"]] = (loc.text(r.get("displayName")) or r["_RecordName_"].split(".", 1)[-1], r.get("displayName"))
        for s in dl(g.get("groups")):
            walk(s)
    for g in dl(db["_RecordValue_"].get("groups")):
        walk(g)
    return out


# ---------------------------------------------------------------- 蓝图

def blueprints(loc, res):
    gp = rec("crafting/globalparams/craftingglobalparams.json")["_RecordValue_"]
    defaults = {relpath(p) for p in (gp.get("defaultBlueprintSelection") or {}).get("blueprintRecords") or []}
    dis = rec("crafting/blueprints/dismantle/globalgenericdismantle.json")["_RecordValue_"]["blueprint"]["processSpecificData"]
    dt = dis.get("dismantleTime") or {}
    dismantle = {"efficiency": dis.get("efficiency"), "dismantleTimeSeconds": int(_seconds(dt)),
                 "blacklistedResources": [{"guid": r["_RecordId_"], "name": res.get(r["_RecordName_"], ("",))[0]}
                                          for r in gp.get("dismantleBlacklistResources") or []]}
    props, out, used_res, used_items = {}, [], set(), set()
    base = REC / "crafting" / "blueprints" / "crafting"
    for f in sorted(base.rglob("*.json")):
        parts = tuple(x for x in f.relative_to(base).parts if x != "$templates")     # 模板文件夹里的也是能造的蓝图（scmdb 也收）
        r = json.loads(f.read_text(encoding="utf-8"))
        v = r["_RecordValue_"]["blueprint"]
        if v.get("_Type_") != "CraftingBlueprint":
            continue
        ent = rec((v.get("processSpecificData") or {}).get("entityClass"))
        a = attach_def(ent)
        gear = parts[0]
        typ = parts[1] if len(parts) > 2 else None
        sub = parts[2] if len(parts) > 3 else None
        tag = r["_RecordName_"].split(".", 1)[-1]
        if gear == "vehiclegear":                       # 和 scmdb 一样的分类：文件夹没分的按实体类型 / 标签
            et, low = a.get("Type") or "", tag.lower()
            if not typ:
                typ = "miningmodule" if et == "MiningModifier" else "orepod" if "pod" in low else "salvage" if et == "SalvageModifier" else None
            if typ == "weapons":
                m = re.search(r"(laser|tachyon|neutron|ballistic|distortion|plasma|electron)", low)
                sub = m.group(1) if m else sub
            if not sub:
                m = re.search(r"_(active|passive|small|medium|large)(?:_|$)", low)
                if m:
                    sub = m.group(1)
                elif typ not in ("orepod", "miningmodule") and a.get("Size") is not None:
                    sub = f"size{a['Size']}"
        tiers = []
        for t in dl(v.get("tiers")):
            costs = ((t.get("recipe") or {}).get("costs") or {})
            slots = []
            for s in dl((costs.get("mandatoryCost") or {}).get("options")):
                name = loc.text((s.get("nameInfo") or {}).get("displayName")) or _title((s.get("nameInfo") or {}).get("debugName", ""))
                opts, mods = [], []
                for o in dl(s.get("options")):
                    if o.get("_Type_") == "CraftingCost_Resource":
                        rn = res.get((o.get("resource") or {}).get("_RecordName_"), ("",))[0]
                        used_res.add(rn)
                        opts.append({"type": "resource", "quantity": (o.get("quantity") or {}).get("standardCargoUnits"),
                                     "minQuality": o.get("minQuality", 0), "resourceName": rn})
                    elif o.get("_Type_") == "CraftingCost_Item":
                        iname = entity_name(loc, rec(o.get("entityClass")))
                        used_items.add(iname)
                        opts.append({"type": "item", "quantity": o.get("quantity"), "minQuality": o.get("minQuality", 0),
                                     "modifiers": None, "itemName": iname})
                for ctx in dl(s.get("context")):
                    for m in ((ctx.get("gameplayPropertyModifiers") or {}).get("gameplayPropertyModifiers") or []):
                        prec = rec(m.get("gameplayPropertyRecord"))
                        key = Path(relpath(m.get("gameplayPropertyRecord"))).stem.removeprefix("gpp_")
                        pname = loc.text((prec or {}).get("_RecordValue_", {}).get("propertyName")) or _title(key.split("_", 1)[-1])
                        props.setdefault(key, {"name": pname, "unit": None, "category": key.split("_", 1)[0]})
                        for vr in dl(m.get("valueRanges")):
                            if not isinstance(vr, dict):
                                continue
                            d = {"startQuality": vr.get("startQuality"), "endQuality": vr.get("endQuality"),
                                 "modifierAtStart": vr.get("modifierAtStart", vr.get("additiveModifierAtStart")),
                                 "modifierAtEnd": vr.get("modifierAtEnd", vr.get("additiveModifierAtEnd")),
                                 "propertyName": pname, "propertyKey": key}
                            if "Additive" in vr.get("_Type_", ""):
                                d["additive"] = True
                            mods.append(d)
                slots.append({"name": name, "options": opts, "modifiers": mods or None})
            tiers.append({"craftTimeSeconds": int(_seconds(costs.get("craftTime") or {})), "slots": slots})
        item = dict(guid=r["_RecordId_"], tag=tag, productEntityClass=(ent or {}).get("_RecordId_", ""),
                    gear=gear, type=typ, subtype=sub, tiers=tiers, productName=entity_name(loc, ent) or None, manufacturer=manufacturer(loc, ent))
        if str(f.relative_to(REC)).replace("\\", "/") in defaults:
            item["isDefault"] = True
        out.append(item)
    return out, dismantle, props, sorted(used_res), sorted(used_items)


def _seconds(t):
    return (t.get("days") or 0) * 86400 + (t.get("hours") or 0) * 3600 + (t.get("minutes") or 0) * 60 + (t.get("seconds") or 0)


def _title(s):
    return " ".join(w.capitalize() for w in re.split(r"[\s_]+", s.strip()) if w)


# ---------------------------------------------------------------- 蓝图池、任务

def blueprint_pools():
    pools = {}
    for f in (REC / "crafting" / "blueprintrewards").rglob("*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        pools[r["_RecordId_"]] = {"name": r["_RecordName_"].split(".", 1)[-1], "blueprints": [
            {"blueprintRecord": (rec(b.get("blueprintRecord")) or {}).get("_RecordId_", ""), "weight": b.get("weight", 1)}
            for b in r["_RecordValue_"].get("blueprintRewards") or []]}
    return pools


def _hauling(loc, res, orders, pools):
    """模板里的 HaulingOrder_* 和任务覆盖里的 HaulingOrderContent_* → scmdb 的 haulingOrders 行"""
    out = []
    for h in dl((orders)):
        t = h.get("_Type_", "")
        if "Resource" in t and h.get("resource"):
            name, key = res.get(h["resource"].get("_RecordName_"), (h["resource"].get("_RecordName_", ""), None))
            pools.setdefault(name, {"name": name, "nameKey": key})
            out.append({"resource": name, "minSCU": h.get("minSCU"), "maxSCU": h.get("maxSCU")})
        elif "EntityClass" in t or "MissionItem" in t:
            ents = [h.get("entityClass")] if h.get("entityClass") else list(h.get("entityClasses") or [])
            for e in ents:
                er = rec(e)
                name = entity_name(loc, er)
                pools.setdefault(name, {"name": name, "nameKey": (attach_def(er).get("Localization") or {}).get("Name")})
                out.append({"resource": name, "minAmount": h.get("minAmount"), "maxAmount": h.get("maxAmount")})
        elif "Or" in t:
            for sub in dl(h.get("options") or h.get("haulingOrders")):
                out += _hauling(loc, res, [sub] if isinstance(sub, dict) and "_Type_" in sub else (sub.get("haulingOrders") or []), pools)
    return out


def contracts(loc, res):
    """所有任务生成器里的任务（含子任务）→ scmdb 的 contracts 行（只放我们用到的字段）"""
    pools, rows = {}, []
    systems_of = lambda pre: sorted({_sys(p.get("locationAvailable")) for p in pre or [] if p.get("_Type_") == "ContractPrerequisite_Location"} - {""})  # noqa: E731

    def sysname(s):
        return {"stanton": "Stanton", "pyro": "Pyro", "nyx": "Nyx"}.get(s, s.capitalize())

    def walk(c, gen, gen_sys, depth=0):
        tpl = rec(c.get("template")) or {}
        tv = tpl.get("_RecordValue_", {})
        params = [(c.get("paramOverrides") or {}), (gen.get("contractParams") or {})]
        strs = {}
        for p in reversed(params):                           # 任务自己的覆盖优先于生成器的
            for s in dl(p.get("stringParamOverrides")):
                strs[s.get("param")] = s.get("value")
        title_key = strs.get("Title") or ((tv.get("contractDisplayInfo") or {}).get("displayString") or [""])[0]
        mt_path = next((p.get("missionTypeOverride") for p in params if p.get("missionTypeOverride")), None) \
            or (tv.get("contractDisplayInfo") or {}).get("type")
        mtype = rec(mt_path) or {}
        mt_name_key = mtype.get("_RecordValue_", {}).get("LocalisedTypeName")
        who, who_key = "", ""
        hauling = []
        for tok in dl(tv.get("objectiveTokens")):
            hauling += _hauling(loc, res, (tok.get("objectiveHandler") or {}).get("haulingOrders"), pools)
        override = []
        for p in params:
            for pr in dl(p.get("propertyOverrides")):
                if (pr.get("value") or {}).get("_Type_") == "MissionPropertyValue_HaulingOrders":
                    override += _hauling(loc, res, pr["value"].get("haulingOrderContent"), pools)
        if override:
            hauling = override
        items, bps, fac = [], [], ""
        for r in ((c.get("contractResults") or {}).get("contractResults") or []):
            t = r.get("_Type_", "")
            if t == "ContractResult_Item":
                items.append({"name": entity_name(loc, rec(r.get("entityClass"))), "amount": r.get("amount"), "groups": []})
            elif t == "ContractResult_ItemsWeighting":
                groups = []
                structure = []
                for w in dl(r.get("itemAwardStructure")):
                    if w.get("_Type_") == "ItemAwardWeightingsParams":      # 引用奖励记录（维科洛「很饿」的 IAE 帽子衣服）
                        structure += dl(((rec(w.get("awardsRecord")) or {}).get("_RecordValue_") or {}).get("itemAwardStructure"))
                    else:
                        structure.append(w)
                for w in structure:
                    groups.append({"weight": w.get("weighting"), "items": [
                        {"name": entity_name(loc, rec(a.get("entityClass"))), "amount": a.get("amountToAward")} for a in w.get("awards") or []]})
                items.append({"name": "", "groups": groups})
            elif t == "BlueprintRewards":
                pool = rec(r.get("blueprintPool")) or {}
                bps.append({"blueprintPool": pool.get("_RecordId_", ""), "chance": r.get("chance", 1)})
            elif t == "ContractResult_LegacyReputation" and not fac:
                fac = (r.get("contractResultReputationAmounts") or {}).get("factionReputation") or ""
        if not who and fac:
            fv = (rec(fac) or {}).get("_RecordValue_", {})
            who_key = fv.get("displayName") or ""
            who = loc.text(who_key) or _title(Path(relpath(fac)).stem.removeprefix("factionreputation_"))
        rep_who, rep_key = who, who_key
        if not rep_who and strs.get("Contractor"):           # 生成器 / 任务的 Contractor 文本参数（@Hockrow_from 这种，2026-10-28 补）
            rep_who, rep_key = loc.text(strs["Contractor"]), strs["Contractor"]
        who, who_key = "", ""
        org_rec = None
        if True:                                      # Contractor 属性指定的组织：只作最后的候补（维科洛那组写的是别的组织）
            for props in [p.get("propertyOverrides") or [] for p in params] + [tv.get("contractProperties") or []]:
                for p in props:
                    val = p.get("value") or {}
                    if p.get("extendedTextToken") == "Contractor" and val.get("_Type_") == "MissionPropertyValue_Organization":   # 只认「发布方」那一项
                        for cond in dl(val.get("matchConditions")):
                            for o in cond.get("organizations") or []:
                                org = rec(o if isinstance(o, str) else (o or {}).get("_RecordPath_"))
                                ov = (org or {}).get("_RecordValue_", {})
                                if org and org_rec is None:
                                    org_rec = ov
                                fv = (rec(ov.get("factionReputation")) or {}).get("_RecordValue_", {})     # 组织 → 声望阵营 → 显示名
                                k = fv.get("displayName") or ov.get("displayName") or ov.get("name") or ""
                                if loc.text(k):
                                    who, who_key = loc.text(k), k
                                    break
                        if who:
                            break
                if who:
                    break
        org_who, org_key = who, who_key
        who, who_key = rep_who, rep_key
        systems = sorted(set(gen_sys) | set(systems_of(c.get("additionalPrerequisites"))))
        title_text = loc.text(title_key)
        m_tok = re.fullmatch(r"~mission\(Contractor\|(\w+)\)", title_text.strip())
        if m_tok and org_rec:                                 # 「~mission(Contractor|RecoverItemTitle)」：组织说法表里按标签名取（2026-10-28 补）
            for v in dl(((org_rec.get("stringVariants") or {}).get("variants"))):
                if _tag_name((v.get("tag") or {}).get("_RecordId_")) == m_tok.group(1) and loc.text(v.get("string")):
                    title_key, title_text = v.get("string"), loc.text(v.get("string"))
                    break
        rows.append({"id": c.get("id"), "debugName": c.get("debugName"), "template": Path(relpath(c.get("template"))).stem,
                     "title": title_text, "titleLocKey": title_key if title_key and title_key.startswith("@") else None,
                     "missionType": loc.text(mt_name_key) or mtype.get("_RecordName_", "").split(".", 1)[-1], "missionTypeKey": mt_name_key,
                     "contractorName": who, "contractorNameKey": who_key, "_org": (org_who, org_key), "systems": [sysname(s) for s in systems],
                     "haulingOrders": hauling, "itemRewards": items, "blueprintRewards": bps})
        for sc in dl(c.get("subContracts")):
            if isinstance(sc, dict) and sc.get("template"):
                walk(sc, gen, gen_sys, depth + 1)

    for f in sorted((REC / "contracts" / "contractgenerator").rglob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        for gen in dl(r["_RecordValue_"].get("generators")):
            if gen.get("notForRelease"):
                continue
            gen_sys = systems_of((gen.get("defaultAvailability") or {}).get("prerequisites"))
            start = len(rows)
            for key, val in gen.items():                 # contracts、introContracts、PVPBountyContract…：所有任务列表
                if not isinstance(val, list):
                    continue
                for c in dl(val):
                    if c.get("_Type_") in ("Contract", "CareerContract") and c.get("template") and not c.get("notForRelease"):
                        walk(c, gen, gen_sys)
            # 发布方：同一个生成器里没写明的（没有声望结果的那几条维科洛兑换），按这组里最多的那个
            whos = [x["contractorName"] for x in rows[start:] if x["contractorName"]]
            if whos:
                top = max(set(whos), key=whos.count)
                for x in rows[start:]:
                    if not x["contractorName"]:
                        x["contractorName"] = top
                        x["contractorNameKey"] = next((y["contractorNameKey"] for y in rows[start:] if y["contractorName"] == top), "")
            for x in rows[start:]:
                if not x["contractorName"]:
                    x["contractorName"], x["contractorNameKey"] = x["_org"]
                del x["_org"]
            syss = [tuple(x["systems"]) for x in rows[start:] if x["systems"]]
            for x in rows[start:]:
                if not x["systems"]:
                    x["systems"] = list(max(set(syss), key=syss.count)) if syss else (["Stanton"] if "wikelo" in x["contractorName"].lower() else [])
    return rows, pools


_tags = {}


def _tag_name(tag_id):
    """标签库：记录 id → 标签名（OpenBountyTitle、RecoverItemTitle…）"""
    if not _tags:
        def walk(o):
            if isinstance(o, dict):
                if o.get("_Type_") == "Tag" and o.get("_RecordId_"):
                    _tags[o["_RecordId_"]] = o.get("tagName")
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(rec("tagdatabase/tagdatabase.tagdatabase.json"))
    return _tags.get(tag_id)


def _sys(path):
    m = re.search(r"starmap/pu/system/([a-z0-9]+)/", relpath(path).lower())
    return m.group(1) if m else ""


# ---------------------------------------------------------------- 主流程

def build(ver=None):
    loc = Loc()
    if not loc.ini:
        raise SystemExit(f"没有游戏英文文本：{EN_INI}（先跑 tools\\unpack_all.py）")
    res = resources(loc)
    ver = ver or game_version()
    bps, dismantle, props, used_res, used_items = blueprints(loc, res)
    bp_out = {"version": ver, "meta": {"totalBlueprints": len(bps), "totalProducts": len({b["productEntityClass"] for b in bps}),
                                        "totalResources": len(used_res), "totalItems": len(used_items)},
              "dismantle": dismantle, "properties": props, "resources": used_res, "items": used_items, "blueprints": bps}
    rows, pools = contracts(loc, res)
    merged = {"version": ver, "source": "unpack", "resourcePools": pools, "blueprintPools": blueprint_pools(), "contracts": rows}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    f1, f2 = OUT_DIR / f"crafting_blueprints-{ver}.json", OUT_DIR / f"merged-{ver}.json"
    f1.write_text(json.dumps(bp_out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    f2.write_text(json.dumps(merged, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"蓝图 {len(bps)} 份（{len(props)} 种属性、{len(used_res)} 种资源、{len(used_items)} 种材料物品）；"
          f"任务 {len(rows)} 个（维科洛 {sum(1 for r in rows if 'wikelo' in r['contractorName'].lower())} 个，带蓝图奖励 {sum(1 for r in rows if r['blueprintRewards'])} 个）")
    print(f"→ {f1}\n→ {f2}")
    return f1, f2


def compare(f1, f2):
    """和本机 scmdb 同版本（或最新正式服）文件对照"""
    from sc_mining.crafting.build_crafting import latest_live
    cands = list(SCMDB_DIR.glob("crafting_blueprints-*.json"))
    old = latest_live(cands)
    if not old:
        print("本机没有 scmdb 的蓝图文件，没法对照")
        return
    a = json.loads(old.read_text(encoding="utf-8"))
    b = json.loads(f1.read_text(encoding="utf-8"))
    print(f"\n==== 对照 scmdb {a['version']} ↔ 解包 {b['version']}")
    am, bm = {x["guid"]: x for x in a["blueprints"]}, {x["guid"]: x for x in b["blueprints"]}
    print(f"蓝图数 scmdb {len(am)} / 解包 {len(bm)}；scmdb 有解包没有 {len(set(am) - set(bm))}，解包有 scmdb 没有 {len(set(bm) - set(am))}")
    for g in list(set(am) - set(bm))[:10]:
        print("  只在 scmdb：", am[g]["tag"])
    for g in list(set(bm) - set(am))[:10]:
        print("  只在解包：", bm[g]["tag"])
    diff = defaultdict(list)
    for g in set(am) & set(bm):
        x, y = am[g], bm[g]
        for k in ("productName", "manufacturer", "gear", "type", "subtype", "productEntityClass"):
            if (x.get(k) or None) != (y.get(k) or None):
                diff[k].append((x["tag"], x.get(k), y.get(k)))
        if bool(x.get("isDefault")) != bool(y.get("isDefault")):
            diff["isDefault"].append((x["tag"], x.get("isDefault"), y.get("isDefault")))
        tx, ty = x["tiers"][0], y["tiers"][0]
        if tx["craftTimeSeconds"] != ty["craftTimeSeconds"]:
            diff["craftTime"].append((x["tag"], tx["craftTimeSeconds"], ty["craftTimeSeconds"]))
        sx = [(s["name"], [(o["type"], o.get("resourceName") or o.get("itemName"), round(float(o["quantity"] or 0), 4), o["minQuality"]) for o in s["options"]],
               sorted((m["propertyKey"], m["startQuality"], m["endQuality"], m["modifierAtStart"], m["modifierAtEnd"], bool(m.get("additive"))) for m in (s.get("modifiers") or [])))
              for s in tx["slots"]]
        sy = [(s["name"], [(o["type"], o.get("resourceName") or o.get("itemName"), round(float(o["quantity"] or 0), 4), o["minQuality"]) for o in s["options"]],
               sorted((m["propertyKey"], m["startQuality"], m["endQuality"], m["modifierAtStart"], m["modifierAtEnd"], bool(m.get("additive"))) for m in (s.get("modifiers") or [])))
              for s in ty["slots"]]
        if sx != sy:
            diff["slots"].append((x["tag"], sx, sy))
    for k, v in diff.items():
        print(f"{k} 不一样：{len(v)} 份")
        for row in v[:5]:
            print("   ", json.dumps(row, ensure_ascii=False)[:400])
    # 任务：维科洛兑换对照
    oldm = old.with_name(old.name.replace("crafting_blueprints-", "merged-"))
    if oldm.exists():
        ma = json.loads(oldm.read_text(encoding="utf-8"))
        mb = json.loads(f2.read_text(encoding="utf-8"))
        wa = {c["debugName"]: c for c in ma["contracts"] if "wikelo" in (c.get("contractorName") or "").lower()}
        wb = {c["debugName"]: c for c in mb["contracts"] if "wikelo" in (c.get("contractorName") or "").lower()}   # 解包里叫 Wikelo Emporium
        print(f"\n维科洛兑换 scmdb {len(wa)} / 解包 {len(wb)}；只在 scmdb {sorted(set(wa) - set(wb))[:8]}；只在解包 {sorted(set(wb) - set(wa))[:8]}")
        n = 0
        for k in sorted(set(wa) & set(wb)):
            ra = sorted((h["resource"] if h["resource"] not in ma["resourcePools"] else ma["resourcePools"][h["resource"]]["name"], h.get("minSCU") or h.get("minAmount") or h.get("maxAmount")) for h in wa[k].get("haulingOrders") or [])
            rb = sorted((h["resource"], h.get("minSCU") or h.get("minAmount") or h.get("maxAmount")) for h in wb[k].get("haulingOrders") or [])
            if ra != rb and n < 8:
                n += 1
                print(f"  {k}: scmdb {ra} ↔ 解包 {rb}")
        print(f"维科洛材料不一样的：{n}{'+' if n >= 8 else ''} 个")
        sa = {c["debugName"] for c in ma["contracts"] if c.get("blueprintRewards")}
        sb = {c["debugName"] for c in mb["contracts"] if c.get("blueprintRewards")}
        print(f"带蓝图奖励的任务 scmdb {len(sa)} / 解包 {len(sb)}；只在 scmdb {len(sa - sb)}（{sorted(sa - sb)[:5]}）；只在解包 {len(sb - sa)}（{sorted(sb - sa)[:5]}）")


def _is_ours(p):
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("source") == "unpack" or "-unpack" in p.name
    except Exception:
        return False


if __name__ == "__main__":
    f1, f2 = build()
    if "--compare" in sys.argv:
        compare(f1, f2)
