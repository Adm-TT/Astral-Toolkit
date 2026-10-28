"""解包第四项：物品清单 + 物品属性（2026-10-28，不再靠 star-citizen.wiki 的 API）

从本机解包的 DataCore 记录（entities/scitem/**）直接出两份文件，格式和以前 wiki 版一样，程序里不用改：
  data/wiki_items.json  物品清单 [{n 英文名, t 类型, s 尺寸, mfr 厂商, cls 游戏类名, d 中文描述}]（itemsearch / loot / localization 用）
  data/item_stats.json  物品属性 {uuid: {n, size, grade, cls, type, sub, mass, ver, mfr, s{各属性段}}}（制造页「属性统计」itemstats.PROPS 用）
只取程序用得到的字段（耐久、护盾、武器伤害 / 射速、护甲减伤、温度 / 辐射、冷却 / 发电、量子驱动、雷达辅助瞄准、牵引光束、打捞模块、采矿激光）。

用法：python tools\\unpack_items.py            → 解包并和现有 data/ 里的（wiki 版或上次）对比，不写
      python tools\\unpack_items.py --write    → 写入 data/wiki_items.json、data/item_stats.json
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from unpack_crafting import REC, Loc, dl, rec, game_version, manufacturer, attach_def  # noqa: E402
from sc_mining.localization import read_ini  # noqa: E402

ENT = REC / "entities"
OUT_LIST = ROOT / "data" / "wiki_items.json"
OUT_STATS = ROOT / "data" / "item_stats.json"
GRADE = {1: "A", 2: "B", 3: "C", 4: "D"}
DMG_KEYS = ("DamagePhysical", "DamageEnergy", "DamageDistortion", "DamageThermal", "DamageBiochemical", "DamageStun")
RES_KEYS = {"PhysicalResistance": "physical", "EnergyResistance": "energy", "DistortionResistance": "distortion",
            "ThermalResistance": "thermal", "BiochemicalResistance": "biochemical", "StunResistance": "stun"}
PERSONAL = ("WeaponPersonal",)
SKIP_TYPES = {"Char_Hair_Color", "Char_Skin_Color", "Char_Head_Eyes", "Char_Head", "Char_Head_Hair", "Char_Body", "Char_Head_Eyebrow",
              "Char_Head_Eyelash", "Char_Head_Beard", "Char_Eyes_Color"}


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _dmg(d):
    """伤害表 {DamagePhysical: …} → 总伤害 和 分项列表"""
    d = d or {}
    parts = [{"name": k[6:].lower(), "damage": round(d[k], 4)} for k in DMG_KEYS if _num(d.get(k))]
    return round(sum(p["damage"] for p in parts), 4), parts


def _resist(dr):
    out = {}
    for k, name in RES_KEYS.items():
        e = (dr or {}).get(k) or {}
        if _num(e.get("Multiplier")) is not None:
            out[name] = {"multiplier": e["Multiplier"], "threshold": e.get("Threshold", 0)}
    return out


def fire_info(fa, depth=0):
    """一个开火动作 → {rpm, pellets, damage_multiplier, ammo_cost, mode}；序列 / 蓄力 / 条件 / 并行动作往里找真正的发射参数"""
    if not isinstance(fa, dict) or depth > 4:
        return None
    t = fa.get("_Type_", "")
    if "sequenceEntries" in fa:                                   # 序列：第一项的间隔（RPM）+ 里面的动作
        ents = dl(fa.get("sequenceEntries"))
        inner = fire_info((ents[0] if ents else {}).get("weaponAction"), depth + 1) or {}
        if ents and _num(ents[0].get("delay")) and ents[0]["delay"] > 0:
            inner["rpm"] = ents[0]["delay"] if ents[0].get("unit") == "RPM" else round(60 / ents[0]["delay"], 2)
        return inner or None
    if "conditionalWeaponActions" in fa:                          # 条件动作：先看默认动作，再看各条件分支
        r = fire_info(fa.get("defaultWeaponAction"), depth + 1)
        if r:
            return r
        for c in dl(fa.get("conditionalWeaponActions")):
            r = fire_info(c.get("weaponAction"), depth + 1)
            if r:
                return r
        return None
    if "weaponActions" in fa:
        for c in dl(fa.get("weaponActions")):
            r = fire_info(c, depth + 1)
            if r:
                return r
        return None
    if "maxChargeModifier" in fa:                                 # 蓄力：满蓄伤害倍率，射速 = 60 / 蓄力时间
        inner = fire_info(fa.get("weaponAction"), depth + 1) or {}
        lp = fa.get("launchParams") or {}
        mc = fa.get("maxChargeModifier") or {}
        inner.setdefault("pellets", lp.get("pelletCount"))
        inner.setdefault("ammo_cost", lp.get("ammoCost"))
        inner["damage_multiplier"] = (inner.get("damage_multiplier") or lp.get("damageMultiplier") or 1) * (mc.get("damageMultiplier") or 1)
        if _num(fa.get("chargeTime")) and fa["chargeTime"] > 0:
            inner["rpm"] = round(60 / fa["chargeTime"], 2)
        inner.setdefault("mode", fa.get("name"))
        return inner
    if "launchParams" in fa:
        lp = fa.get("launchParams") or {}
        return {"mode": fa.get("name"), "rpm": fa.get("fireRate") or None, "pellets": lp.get("pelletCount"),
                "damage_multiplier": lp.get("damageMultiplier"), "ammo_cost": lp.get("ammoCost"), "action": t}
    if "damagePerSecond" in fa and "maxForce" not in fa:
        total, parts = _dmg(fa.get("damagePerSecond"))
        return {"mode": fa.get("name"), "dps": total, "damages": parts, "action": t}
    return None


def _extract(d):
    """一个实体记录 → 原始字段（在子进程里做，不解析文本）；不是物品返回 None"""
    v = d.get("_RecordValue_") or {}
    comps = {}
    for c in dl(v.get("Components")):
        comps.setdefault(c.get("_Type_"), c)
    att = comps.get("SAttachableComponentParams")
    if not att or not isinstance(att.get("AttachDef"), dict):
        return None
    a = att["AttachDef"]
    lz = a.get("Localization") or {}
    r = {"id": d.get("_RecordId_"), "cn": (d.get("_RecordName_") or "").split(".", 1)[-1],
         "type": a.get("Type"), "sub": a.get("SubType"), "size": a.get("Size"), "grade": a.get("Grade"),
         "mfr_path": a.get("Manufacturer"), "name_key": lz.get("Name"), "desc_key": lz.get("Description"), "s": {}}
    s = r["s"]
    ph = ((comps.get("SEntityPhysicsControllerParams") or {}).get("PhysType") or {})
    r["mass"] = _num(ph.get("Mass"))
    h = comps.get("SHealthComponentParams")
    if h and _num(h.get("Health")) is not None:
        s["durability"] = {"health": h["Health"], "repairable": h.get("IsRepairable"), "salvageable": h.get("IsSalvagable"),
                           "resistance": {k: e["multiplier"] for k, e in _resist(h.get("DamageResistances")).items()}}
    di = comps.get("SDistortionParams")
    if di:
        s["distortion"] = {"max": di.get("Maximum"), "decay_rate": di.get("DecayRate"), "decay_delay": di.get("DecayDelay"),
                           "warning_ratio": di.get("WarningRatio")}
    ir = comps.get("ItemResourceComponentParams")
    if ir:
        sig = ir.get("signatureParams") or {}
        em, irs = (sig.get("EMSignature") or {}).get("nominalSignature"), (sig.get("IRSignature") or {}).get("nominalSignature")
        if _num(em) is not None or _num(irs) is not None:
            s["emission"] = {"em": em, "ir": irs}
        for st in dl(ir.get("states")):
            for de in dl(st.get("deltas")):
                g = (de.get("generation") or {})
                amt = g.get("resourceAmountPerSecond") or {}
                if g.get("resource") == "Power" and _num(amt.get("units")) is not None:
                    s.setdefault("power_plant", {})["power_segment_generation"] = amt["units"]
                if g.get("resource") == "Coolant" and _num(amt.get("standardResourceUnits")) is not None:
                    s.setdefault("cooler", {})["coolant_segment_generation"] = amt["standardResourceUnits"]
            break                                             # 只看第一个状态（Online）
    sh = comps.get("SCItemShieldGeneratorParams")
    if sh:
        s["shield"] = {"max_health": sh.get("MaxShieldHealth"), "regen_rate": sh.get("MaxShieldRegen"), "decay_ratio": sh.get("DecayRatio"),
                       "regen_delay": {"downed": sh.get("DownedRegenDelay"), "damage": sh.get("DamagedRegenDelay")}}
    qd = comps.get("SCItemQuantumDriveParams")
    if qd:
        def jump(p):
            p = p or {}
            return {"drive_speed": p.get("driveSpeed"), "cooldown_time": p.get("cooldownTime"), "spool_up_time": p.get("spoolUpTime"),
                    "stage_one_accel_rate": p.get("stageOneAccelRate"), "stage_two_accel_rate": p.get("stageTwoAccelRate"),
                    "engage_speed": p.get("engageSpeed")}
        s["quantum_drive"] = {"quantum_fuel_requirement": qd.get("quantumFuelRequirement"), "jump_range": qd.get("jumpRange"),
                              "disconnect_range": qd.get("disconnectRange"), "standard_jump": jump(qd.get("params")),
                              "spline_jump": jump(qd.get("splineJumpParams"))}
    rd = comps.get("SCItemRadarComponentParams")
    if rd:
        aa = rd.get("aimAssist") or {}
        s["radar"] = {"cooldown": (rd.get("pingProperties") or {}).get("cooldownTime"),
                      "aim_assist": {"distance_min_assignment": aa.get("distanceMinAssignment"),
                                     "distance_max_assignment": aa.get("distanceMaxAssignment")}}
    w = comps.get("SCItemWeaponComponentParams")
    if w:
        fas = dl(w.get("fireActions"))
        fa = fas[0] if fas else {}
        if "maxForce" in fa:                                   # 牵引光束
            s["tractor_beam"] = {"force": {"min": fa.get("minForce"), "max": fa.get("maxForce"), "max_volume": fa.get("maxVolume")},
                                 "range": {"min": fa.get("minDistance"), "max": fa.get("maxDistance"),
                                           "full_strength_distance": fa.get("fullStrengthDistance")}, "max_angle": fa.get("maxAngle")}
        elif "damagePerSecond" in fa and comps.get("SEntityComponentMiningLaserParams"):   # 采矿激光
            total, parts = _dmg(fa.get("damagePerSecond"))
            ml = comps["SEntityComponentMiningLaserParams"]
            mods = {k: m.get("value") for k, m in (ml.get("miningLaserModifiers") or {}).items()
                    if isinstance(m, dict) and _num(m.get("value")) is not None}
            s["mining_laser"] = {"laser_power": {"min": round(total * (ml.get("throttleMinimum") or 0), 4), "max": total},
                                 "optimal_range": fa.get("fullDamageRange"), "maximum_range": fa.get("zeroDamageRange"),
                                 "throttle_minimum": ml.get("throttleMinimum"), "modifiers": mods}
        else:                                                  # 发射物武器：射速 + 弹药记录里的伤害；光束武器：每秒伤害
            fi = next((x for x in (fire_info(f) for f in fas) if x), None)
            if fi and "dps" in fi:
                r["beam"] = {"dps": fi["dps"], "damages": fi["damages"], "mode": fi.get("mode")}
            elif fi:
                fi["modes"] = [f.get("name") for f in fas]
                r["fire"] = fi
                r["mag_path"] = w.get("ammoContainerRecord")
    ac = comps.get("SAmmoContainerComponentParams")
    if ac:
        r["ammo_path"] = ac.get("ammoParamsRecord")
        r["ammo_count"] = ac.get("maxAmmoCount")
    mod = comps.get("EntityComponentAttachableModifierParams")
    if mod:
        for m in dl(mod.get("modifiers")):
            for mm in [m] + dl(m.get("modifiers")):
                wm = mm.get("weaponModifier") or {}
                sm = wm.get("salvageModifier") or (wm.get("weaponStats") or {}).get("salvageModifier") or {}
                if _num(sm.get("salvageSpeedMultiplier")) is not None:
                    s["weapon_modifier"] = {"salvage": {"salvage_speed_multiplier": sm["salvageSpeedMultiplier"],
                                                        "radius_multiplier": sm.get("radiusMultiplier"),
                                                        "extraction_efficiency": sm.get("extractionEfficiency")}}
    cl = comps.get("SCItemClothingParams")
    if cl:
        tr, rr = cl.get("TemperatureResistance") or {}, cl.get("RadiationResistance") or {}
        s["temperature_resistance"] = {"min": tr.get("MinResistance"), "max": tr.get("MaxResistance")}
        s["radiation_resistance"] = {"maximum_radiation_capacity": rr.get("MaximumRadiationCapacity"),
                                     "radiation_dissipation_rate": rr.get("RadiationDissipationRate")}
        s["gforce_resistance"] = {"value": (cl.get("Flight") or {}).get("gForceResistance")}
    sa = comps.get("SCItemSuitArmorParams")
    if sa:
        sig = {x.get("signatureType", "").lower(): x.get("signatureEmission") for x in dl(sa.get("signatureParams"))}
        s["suit_armor"] = {"signature": sig}
        r["armor_res_path"] = sa.get("damageResistance")
    elif cl:
        s["clothing"] = {}
    return r


def _scan(paths):
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            r = _extract(d)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if r:
            r["path"] = os.path.relpath(p, REC).replace("\\", "/")
            out.append(r)
    return out


def scan():
    files = [os.path.join(d, f) for d, _, fs in os.walk(ENT) for f in fs if f.endswith(".json")]
    n = max(1, min(60, len(files) // 200))
    rows = []
    with ProcessPoolExecutor(min(30, os.cpu_count() or 4)) as ex:
        for part in ex.map(_scan, [files[i::n] for i in range(n)]):
            rows.extend(part)
    return rows


# ---------------------------------------------------------------- 主进程：文本、厂商、弹药

_ammo_cache = {}


def ammo_damage(path):
    """弹药记录 → (单发总伤害, 分项)；没有返回 (None, [])"""
    if not path:
        return None, []
    if path not in _ammo_cache:
        a = rec(path)
        pp = ((a or {}).get("_RecordValue_") or {}).get("projectileParams") or {}
        total, parts = _dmg(pp.get("damage")) if pp.get("damage") else (None, [])
        det = (((pp.get("detonationParams") or {}).get("explosionParams")) or {}).get("damage")
        if det:
            t2, p2 = _dmg(det)
            total = (total or 0) + t2
            parts = parts + [{"name": x["name"], "damage": x["damage"], "type": "detonation"} for x in p2]
        _ammo_cache[path] = (total, parts)
    return _ammo_cache[path]


def mag_ammo(mag_path):
    """弹匣实体 → 它的弹药记录路径和容量"""
    m = rec(mag_path)
    for c in dl(((m or {}).get("_RecordValue_") or {}).get("Components")):
        if c.get("_Type_") == "SAmmoContainerComponentParams":
            return c.get("ammoParamsRecord"), c.get("maxAmmoCount")
    return None, None


def clean_desc(t):
    """描述：和 wiki 版一样原样保留（开头的「制造商 / 物品类型 / 功率」属性行物品页也显示），去掉标记，最多 500 字"""
    t = (t or "").replace("\\n", "\n").replace("\r", "")
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return "" if t.startswith("<=") or t.startswith("(PH)") else t[:500]


def desc_class(t):
    m = re.search(r"(?:^|\\n|\n)\s*Class:\s*([A-Za-z]+)", t or "")
    return m.group(1) if m else None


def build():
    t0 = time.time()
    rows = scan()
    loc = Loc()
    zh_ini = ROOT / "data" / "loc" / "global_zh.ini"
    zh = {k.lower(): v for k, v in read_ini(zh_ini).items()} if zh_ini.exists() else {}
    ver = game_version()
    print(f"扫描 {len(rows)} 件带 AttachDef 的实体，{time.time() - t0:.0f}s", flush=True)
    stats, listing, seen = {}, [], {}
    mfr_cache = {}
    for r in rows:
        name = loc.text(r["name_key"])
        if not name or (re.fullmatch(r"[a-z0-9_]+", name) and "_" in name) or name.upper().startswith("[PH]"):
            continue
        if (r["type"] or "").startswith("NOITEM") or (r["type"] or "") in SKIP_TYPES:    # 载具、捏脸这类不是物品
            continue
        en_desc = loc.ini.get((r["desc_key"] or "@")[1:].lower(), "")
        zh_desc = zh.get((r["desc_key"] or "@")[1:].lower(), "")
        mp = r.get("mfr_path") or ("prefix:" + r["cn"].split("_", 1)[0].lower())     # 没填厂商的按类名前缀推，键要带前缀（老大审查 2026-10-28）
        if mp not in mfr_cache:
            mfr_cache[mp] = manufacturer(loc, {"_RecordName_": "x." + r["cn"], "_RecordValue_": {"Components": [
                {"_Type_": "SAttachableComponentParams", "AttachDef": {"Manufacturer": r.get("mfr_path") or ""}}]}})
        mfr = mfr_cache[mp]
        s = r["s"]
        if r.get("fire"):                                       # 发射物武器：伤害在弹药记录里
            ap, cnt = r.get("ammo_path"), r.get("ammo_count")
            if not ap and r.get("mag_path"):
                ap, cnt = mag_ammo(r["mag_path"])
            total, parts = ammo_damage(ap)
            f = r["fire"]
            key = "personal_weapon" if r["type"] in PERSONAL else "vehicle_weapon"
            s[key] = {"damage_per_shot": round(total * (f.get("damage_multiplier") or 1) * (f.get("pellets") or 1), 4) if total is not None else None,
                      "pellets_per_shot": f.get("pellets"), "rpm": f.get("rpm"), "capacity": cnt, "mode": f.get("mode"),
                      "modes": f.get("modes"), "damages": parts}
        if r.get("beam"):
            key = "personal_weapon" if r["type"] in PERSONAL else "vehicle_weapon"
            s[key] = {"damage_per_second": r["beam"]["dps"], "damages": r["beam"]["damages"]}
        if r.get("armor_res_path"):
            dr = ((rec(r["armor_res_path"]) or {}).get("_RecordValue_") or {})
            res = _resist(dr.get("damageResistance"))
            imp = (dr.get("impactForceResistance") or {}).get("impactForceResistance")
            if imp is not None:
                res["impact"] = imp
            s["suit_armor"]["damage_resistance"] = res
        it = {"n": name, "size": r["size"], "grade": GRADE.get(r["grade"]), "cls": desc_class(en_desc), "type": r["type"],
              "sub": r["sub"], "mass": r["mass"], "ver": ver, "mfr": mfr, "cn": r["cn"].lower(), "s": s}
        stats[r["id"]] = it
        e = {"n": name, "t": r["type"] or "", "s": r["size"], "mfr": mfr or "", "cls": r["cn"].lower(),
             "d": clean_desc(zh_desc) or clean_desc(en_desc)}
        k = name.lower()
        if k in seen:
            seen[k].setdefault("alt", []).append(e["cls"])
            if not seen[k]["d"] and e["d"]:
                seen[k]["d"] = e["d"]
        else:
            seen[k] = e
            listing.append(e)
    listing.sort(key=lambda e: e["n"].lower())
    want = set()
    try:                                                        # 先看自己解包的蓝图（本次解包刚出的，不会漏新蓝图）
        from sc_mining.build_crafting import unpacked
        own = unpacked()
        if own:
            for b in dl(json.loads(own[0].read_text(encoding="utf-8")).get("blueprints")):
                u = (b.get("productEntityClass") or {}).get("uuid") if isinstance(b.get("productEntityClass"), dict) else b.get("productEntityClass")
                if isinstance(u, str):
                    want.add(u)
    except Exception as e:
        print("读解包蓝图失败：", e)
    if not want:
        craft = ROOT / "data" / "crafting.json"
        try:
            want = {b.get("u") for b in json.loads(craft.read_text(encoding="utf-8")).get("blueprints") or []}
        except (OSError, ValueError):
            want = set()
    if want:                                                    # 只留可制造成品（制造页用）；没有蓝图表就全留
        stats = {u: v for u, v in stats.items() if u in want}
        print(f"属性表只留可制造成品 {len(stats)} 件（蓝图 {len(want)} 个）")
    print(f"有名字的物品 {len(stats)} 件（清单去重后 {len(listing)}），用时 {time.time() - t0:.0f}s")
    return ver, stats, listing


# ---------------------------------------------------------------- 对比

def compare(stats, listing):
    from sc_mining import itemstats
    old = json.loads(OUT_STATS.read_text(encoding="utf-8")) if OUT_STATS.exists() else {"items": {}}
    oi = old.get("items") or {}
    print(f"\n== 物品属性：旧表（{old.get('source')} {old.get('version')}）{len(oi)} 件；新表 {len(stats)} 件")
    miss = [v["n"] for u, v in oi.items() if u not in stats]
    print(f"旧表有、新表没有：{len(miss)} {miss[:10]}")
    both = [u for u in oi if u in stats]
    for fld in ("n", "size", "grade", "cls", "type", "sub", "mfr", "mass"):
        diff = [(oi[u]["n"], oi[u].get(fld), stats[u].get(fld)) for u in both if oi[u].get(fld) != stats[u].get(fld)
                and not (fld == "mass" and isinstance(oi[u].get(fld), (int, float)) and isinstance(stats[u].get(fld), (int, float))
                         and abs(oi[u][fld] - stats[u][fld]) < 0.5)]
        print(f"  {fld} 不同 {len(diff)}：{diff[:6]}")
    for key, (fn, _unit) in itemstats.PROPS.items():
        bad, have_old, have_new = [], 0, 0
        for u in both:
            try:
                a = fn(oi[u].get("s") or {})
            except Exception:
                a = None
            try:
                b = fn(stats[u].get("s") or {})
            except Exception:
                b = None
            have_old += a is not None
            have_new += b is not None
            if a is not None and b is not None and abs(a - b) > max(0.01, abs(a) * 0.005):
                bad.append((oi[u]["n"], a, b))
            elif a is not None and b is None:
                bad.append((oi[u]["n"], a, None))
        print(f"  {key}: 旧有 {have_old} 新有 {have_new}，不一样 / 新表缺 {len(bad)}：{bad[:5]}")
        if key in ("weapon_damage", "weapon_firerate"):
            for b in bad:
                print("      ", b)
    ol = json.loads(OUT_LIST.read_text(encoding="utf-8")) if OUT_LIST.exists() else {"items": []}
    on = {e["n"].lower(): e for e in ol.get("items") or []}
    nn = {e["n"].lower(): e for e in listing}
    print(f"\n== 物品清单：旧 {len(on)} 新 {len(nn)}；只在旧 {len(set(on) - set(nn))} {sorted(set(on) - set(nn))[:12]}；只在新 {len(set(nn) - set(on))} {sorted(set(nn) - set(on))[:12]}")
    tdiff = [(k, on[k]["t"], nn[k]["t"]) for k in on if k in nn and on[k]["t"] != nn[k]["t"]]
    print(f"  类型不同 {len(tdiff)}：{tdiff[:8]}")
    nd = sum(1 for e in listing if e["d"])
    print(f"  新表有描述 {nd}，旧表有描述 {sum(1 for e in on.values() if e.get('d'))}")


def main(argv):
    ver, stats, listing = build()
    if "--write" in argv:
        try:
            on = len(json.loads(OUT_LIST.read_text(encoding="utf-8")).get("items") or [])
            os_ = len(json.loads(OUT_STATS.read_text(encoding="utf-8")).get("items") or {})
        except (OSError, ValueError):
            on = os_ = 0
        if (on and len(listing) < on * 0.9) or (os_ and len(stats) < os_ * 0.9):
            sys.exit(f"❌ 新表比旧表少太多（清单 {len(listing)}/{on}，属性 {len(stats)}/{os_}）：解包可能不完整，不写")
        today = time.strftime("%Y-%m-%d")
        OUT_STATS.write_text(json.dumps({"version": ver, "source": "unpack", "fetched": today, "items": stats},
                                        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        OUT_LIST.write_text(json.dumps({"version": ver, "source": "unpack", "fetched": today, "items": listing},
                                       ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"写入 {OUT_STATS.name}（{OUT_STATS.stat().st_size // 1024} KB）、{OUT_LIST.name}（{OUT_LIST.stat().st_size // 1024} KB），版本 {ver}")
    else:
        compare(stats, listing)


if __name__ == "__main__":
    main(sys.argv[1:])

