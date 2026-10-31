"""解包：导航星图整表（2026-10-28，老大定：不等 starmap.space）。

用法：.venv\\Scripts\\python.exe -X utf8 tools\\unpack_starmap.py [--write]
读：E:\\Game3\\unpack\\oc_x（unpack_all 解开的星系 / 星球物件容器）、dcb 的星图记录、游戏英文文本、现有 data\\starmap.json
写（--write）：data\\starmap.json（同一格式，source 写 unpack）；不带 --write 只打印对照结果

从游戏文件出的：
  points  太空点（恒星、星球、拉格朗日点、跳跃点、小行星带…）：名字、类型、星系坐标
  bodies  星球 / 卫星：星系坐标 x y z、半径 r、自转周期 rot（小时 / 圈）、流送格 grid
  pois    星球表面 / 轨道上带星图记录的地点：名字、类型、星球坐标（公里，星球文件自己的坐标系——和 starmap.space 的一致，微科 50 个点逐一核过）
游戏文件里没有、沿用现有 starmap.json 的：
  bodies.adj  自转相位（2020-01-01 时星球转到几度）：starmap.space 是逐个星球实测的；以后由 AT 自动校准（玩家在已知地点时反推）
  bodies.om   轨道标记 OM 距离：游戏代码算的，文件里没有；没有旧值的星球按 1.428·r + 11590 估（和实测差 0.3% 以内）
  pois 里玩家补充的点（洞穴、河流、残骸编号、彩蛋…）：没有星图记录，原样保留，标 src=community
"""
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict  # noqa: F401
from pathlib import Path

import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from unpack_spots import placements, starmap_records  # noqa: E402
from sc_mining.update.localization import read_ini  # noqa: E402

WORK = Path(os.environ.get("AT_UNPACK_DIR", r"E:\Game3\unpack"))
OCX = WORK / "oc_x"
REC = WORK / "dcb_json" / "libs" / "foundry" / "records"
EN_INI = WORK / "p4k_out" / "Data" / "Localization" / "english" / "global.ini"
OUT = ROOT / "data" / "starmap.json"
SYSTEMS = (("Stanton", "stanton"), ("Pyro", "pyro"), ("Nyx", "nyx"))
# 星图记录类型 → starmap.space 的叫法（导航按这些字分类）
TYPE_MAP = {"Star": "Star", "Planet": "Planet", "Moon": "Planet", "LagrangePoint": "Lagrange Point", "JumpPoint": "Jumppoint",
            "Manmade_VisibleOnInteraction": "Orbital Station", "Asteroid_ValidQT": "AsteroidBelt",
            "Asteroid": "AsteroidBelt", "AsteroidField": "AsteroidBelt", "Outpost": "Outpost", "LandingZone": "Landing Zone",
            "Manmade": "Orbital Station", "PointOfInterest": "Point of Interest", "Anomaly": "Anomaly", "Cave": "Cave",
            "Derelict": "Wreck", "NavPoint": "Nav Point"}
OM_SLOPE, OM_OFFSET = 1.428, 11590
SKIP_ALL = ("*",)       # system_tree 第一遍：什么外部容器都不钻


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def object_types():
    """星图记录类型 id → 名字（Star、Planet、Moon、Outpost…）"""
    out = {}
    j = json.loads((REC / "starmap" / "starmapobjecttypes.json").read_text(encoding="utf-8"))

    def walk(o):
        if isinstance(o, dict):
            if o.get("_Type_") == "StarMapObjectType" and o.get("_RecordId_"):
                out[o["_RecordId_"].lower()] = o.get("name") or ""
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(j)
    return out


_type_qt = {}


def type_qt():
    """类型 id → 能不能作为量子目的地（validQuantumTravelDestination）"""
    if not _type_qt:
        j = json.loads((REC / "starmap" / "starmapobjecttypes.json").read_text(encoding="utf-8"))

        def walk(o):
            if isinstance(o, dict):
                if o.get("_Type_") == "StarMapObjectType" and o.get("_RecordId_"):
                    _type_qt[o["_RecordId_"].lower()] = bool(o.get("validQuantumTravelDestination"))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(j)
    return _type_qt


def records():
    """记录 id → {key, qt, hide, rec, type}"""
    types = object_types()
    out = starmap_records(REC / "starmap" / "pu")
    for f in (REC / "starmap" / "pu").rglob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rid = d.get("_RecordId_", "").lower()
        if rid in out:
            t = ((d.get("_RecordValue_") or {}).get("type") or {}).get("_RecordId_", "")
            out[rid]["type"] = types.get(t.lower(), "")
            q = (d.get("_RecordValue_") or {}).get("quantumTravelData") or {}
            out[rid]["qt"] = bool(q) and type_qt().get(t.lower(), True)
    return out


def planet_params(oc_file):
    """星球文件里的半径、自转周期、流送格（米、小时 / 圈、米）"""
    name = Path(oc_file).stem
    for d in OCX.glob(f"*__{name}"):
        x = d / f"{name}.xml"
        if x.exists():
            head = x.read_text(encoding="utf-8", errors="ignore")          # 派罗的星球文件 planetRadius 在 1 MB 之后，整份读
            r = re.search(r'planetRadius="([\d.]+)"', head)
            s = re.search(r'planetRotationSpeed="([\d.]+)"', head)
            g = re.search(r'gridRadius="([\d.]+)"', head)
            return {"r": float(r.group(1)) if r else None, "rot": float(s.group(1)) if s else None,
                    "grid": float(g.group(1)) if g else None, "xml": x}
    return None


def external_xml(oc):
    """子容器文件名 Data/objectcontainers/pu/system/stanton/aaronhalo.socpak → oc_x 里解开的 xml（unpack_all 的命名：去掉 pu/system，用 __ 连）"""
    parts = re.sub(r"(?i)^data/objectcontainers/pu/", "", oc.replace("\\", "/")).split("/")
    if parts and parts[0].lower() == "system":
        parts = parts[1:]
    stem = Path(parts[-1]).stem
    d = OCX / "__".join(parts[:-1] + [stem])
    x = d / f"{stem}.xml"
    return x if x.exists() else None


def system_tree(xml_path, skip_ents=()):
    """系统文件：[(entityName, 星系坐标, 记录 id, 容器文件名, 所在星球容器的 entityName 或 None, 是不是轨道容器, 星球坐标系里的位置)]
    星球坐标系 = 星球容器自己的坐标系（不含星球容器的朝向），和星球文件、starmap.space 的地面点同一坐标系。
    外部子容器（小行星带、拉格朗日点云）有解开的 xml 就钻进去；skip_ents 里的（星球 / 卫星，另外按星球文件处理）不钻"""
    from unpack_spots import qmul, qrot
    out = []

    def walk(el, base, rot, body, lbase, lrot, depth):
        for ch in el.findall("./ChildObjectContainers/Child"):
            pos = tuple(float(v) for v in (ch.get("pos") or "0,0,0").split(","))
            r = tuple(float(v) for v in (ch.get("rot") or "1,0,0,0").split(","))
            off = qrot(rot, pos)
            g = tuple(base[i] + off[i] for i in range(3))
            loff = qrot(lrot, pos)
            lg = tuple(lbase[i] + loff[i] for i in range(3))
            ent, rec, oc = ch.get("entityName") or "", (ch.get("starMapRecord") or "").lower(), ch.get("name") or ""
            is_ooc = ch.get("class") == "OrbitingObjectContainer"
            out.append((ent, g, rec, oc, body, is_ooc, lg))
            nrot = qmul(rot, r)
            if is_ooc:                                   # 进了一个轨道容器（星球 / 卫星 / 拉格朗日点）：下面的点按它自己的坐标系记
                nb, nlb, nlr = ent, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)
            else:
                nb, nlb, nlr = body, lg, qmul(lrot, r)
            walk(ch, g, nrot, nb, nlb, nlr, depth)
            if "*" not in skip_ents and ent not in skip_ents and depth < 2 and not ch.findall("./ChildObjectContainers/Child"):
                x = external_xml(oc)
                if x:
                    try:
                        walk(ET.parse(x).getroot(), g, nrot, nb, nlb, nlr, depth + 1)
                    except ET.ParseError:
                        pass
    walk(ET.parse(xml_path).getroot(), (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), None, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), 0)
    return out


def build(old):
    ini = {k.lower(): v.split("\\n")[0].strip() for k, v in read_ini(EN_INI).items()}
    recs = records()
    old_bodies = old.get("bodies") or {}
    old_names = {norm(n): n for n in old_bodies} | {norm(p["n"]): p["n"] for p in old.get("points") or []}

    def name_of(rec):
        r = recs.get(rec) or {}
        n = ini.get(r.get("key", ""), "")
        return old_names.get(norm(n), n)          # 和现有表拼法一致（Microtech / microTech）

    points, bodies, pois = [], {}, []
    stats = Counter()
    for sys_name, sys_key in SYSTEMS:
        x = OCX / f"{sys_key}__{sys_key}system" / f"{sys_key}system.xml"
        if not x.exists():
            print(f"没有 {x}，跳过 {sys_name}")
            continue
        rows = system_tree(x, skip_ents={ent for ent, g, rec, oc, _, is_ooc, _lg in system_tree(x, skip_ents=set(SKIP_ALL))
                                          if is_ooc and ((recs.get(rec) or {}).get("type") in ("Planet", "Moon") or (planet_params(oc) or {}).get("r")
                                                         or name_of(rec) in old_bodies
                                                         or any(o["sys"] == sys_name and math.dist((o["x"], o["y"], o["z"]), g) < 50000 for o in old_bodies.values()))})
        # 星球 / 卫星：有星图记录且类型是 Planet / Moon 的轨道容器
        for ent, g, rec, oc, _, is_ooc, _lg in rows:
            r = recs.get(rec)
            if not r and is_ooc:                      # 没有星图记录的轨道容器，旧表按位置当星球的（德拉马 = 列夫斯基那块小行星）：照旧表
                hit = next((n for n, o in old_bodies.items() if o["sys"] == sys_name and math.dist((o["x"], o["y"], o["z"]), g) < 50000), None)
                if hit and hit not in bodies:
                    bodies[hit] = {**old_bodies[hit], "x": round(g[0], 1), "y": round(g[1], 1), "z": round(g[2], 1), "_ent": ent, "_xml": None}
                continue
            if not r or (not is_ooc and name_of(rec) not in old_bodies):
                continue
            t = r.get("type", "")
            p = planet_params(oc) or {}
            if t in ("Planet", "Moon") or p.get("r") or name_of(rec) in old_bodies:   # 德拉马：记录类型是 Asteroid，旧表当星球（r 65000、不自转）
                name = name_of(rec)
                ob = old_bodies.get(name) or {}
                if not p.get("r"):
                    stats["星球文件缺参数"] += 1
                radius = p.get("r") or ob.get("r") or 0
                bodies[name] = {"sys": sys_name, "x": round(g[0], 1), "y": round(g[1], 1), "z": round(g[2], 1),
                                "rot": p.get("rot") if p.get("rot") is not None else ob.get("rot", 0.0),
                                "adj": ob.get("adj", 0.0), "r": radius,
                                "om": ob.get("om") or round(OM_SLOPE * radius + OM_OFFSET),
                                "grid": p.get("grid") or ob.get("grid") or radius * 2, "_ent": ent, "_xml": p.get("xml")}
                if "adj" not in ob:
                    bodies[name]["adj_unknown"] = True
                if not ob.get("om"):
                    bodies[name]["om_est"] = True
        # 太空点：系统里带星图记录、不在星球容器之下的
        body_of = {b["_ent"]: n for n, b in bodies.items()}
        for ent, g, rec, oc, body, is_ooc, lg in rows:
            r = recs.get(rec)
            lagrange = is_ooc and re.search(r"(?i)_L\d$", ent)
            jump = is_ooc and re.search(r"(?i)jumppoint", oc)
            if r and r["hide"] and not (lagrange or jump):
                continue
            if lagrange:                                            # 拉格朗日点容器：记录是隐藏的，名字按 starmap.space 的写法（ARC L1）
                m = re.search(r"(?i)(\d+)_L(\d)$", ent)
                code = {"Stanton": {"1": "HUR", "2": "CRU", "3": "ARC", "4": "MIC"}}.get(sys_name, {}).get(m.group(1), f"{sys_name[:3].upper()}{m.group(1)}") if m else ""
                t, name = "Lagrange Point", f"{code} L{m.group(2)}" if m else ent
            elif r:
                t = TYPE_MAP.get(r.get("type", ""), r.get("type", ""))
                name = f"{sys_name} Star" if t == "Star" else name_of(rec)
            elif jump:                                                # 跳跃点：记录是隐藏的；名字沿用旧表（按位置），没有就用实体名
                t, name = "Jumppoint", ent
            elif is_ooc and re.search(r"(?i)segment|cluster|asteroid|belt|halo", ent + oc) and body not in body_of:
                t, name = "AsteroidBelt", ent                         # 小行星带段：starmap.space 也是直接用实体名
            else:
                continue
            if not name:
                stats["太空点没名字"] += 1
                continue
            if body in body_of and ent not in body_of:  # 星球容器之下的（轨道站、小行星基地、通讯阵列…）：按星球坐标记成地面点
                pois.append({"b": body_of[body], "n": ini.get(r["key"], "") if r else name, "t": t, "x": round(lg[0] / 1000, 3),
                             "y": round(lg[1] / 1000, 3), "z": round(lg[2] / 1000, 3), "qt": 1 if (r and r["qt"]) else 0})
                continue
            points.append({"n": name, "i": ent, "sys": sys_name, "t": t, "x": round(g[0], 1), "y": round(g[1], 1), "z": round(g[2], 1)})
    # 星球表面 / 轨道上的点：星球自己的文件
    for name, b in bodies.items():
        if not b.get("_xml"):
            continue
        seen = set()
        for ent, g, rec, oc in placements(b["_xml"]):
            r = recs.get(rec)
            if not r or r["hide"]:
                continue
            n = ini.get(r["key"], "")
            if not n or (norm(n), round(g[0])) in seen:
                continue
            seen.add((norm(n), round(g[0])))
            pois.append({"b": name, "n": n, "t": TYPE_MAP.get(r.get("type", ""), r.get("type", "")),
                         "x": round(g[0] / 1000, 3), "y": round(g[1] / 1000, 3), "z": round(g[2] / 1000, 3), "qt": 1 if r["qt"] else 0})
    for b in bodies.values():
        b.pop("_ent", None)
        b.pop("_xml", None)
    return points, bodies, pois, stats


def adopt_old(old, points, bodies):
    """同一位置（1 km 内）的太空点 / 星球沿用旧表的名字和类型（ARC-L1、Pyro1 这种叫法导航代码和玩家都认）"""
    op = [(p, (p["x"], p["y"], p["z"])) for p in old.get("points") or []]
    renamed = Counter()
    for p in points:
        near = [o for o, xyz in op if o["sys"] == p["sys"] and math.dist(xyz, (p["x"], p["y"], p["z"])) < 1000]
        # 同一位置有好几个点（恒星和亚伦环（Aaron Halo）都在原点）：先认记录编号一样的（2026-10-30）
        hit = next((o for o in near if p.get("i") and o.get("i") == p.get("i")), near[0] if near else None)
        if hit:
            if hit["n"] != p["n"]:
                renamed[(p["n"], hit["n"])] += 1
            p["n"], p["t"] = hit["n"], hit["t"]
    ob = old.get("bodies") or {}
    for name in list(bodies):
        b = bodies[name]
        hit = next((n for n, o in ob.items() if o["sys"] == b["sys"] and math.dist((o["x"], o["y"], o["z"]), (b["x"], b["y"], b["z"])) < 1000), None)
        if hit and hit != name:
            bodies[hit] = bodies.pop(name)
            o = ob[hit]
            bodies[hit].update({"adj": o.get("adj", 0.0), "om": o.get("om") or bodies[hit]["om"]})
            for k in ("r", "rot", "grid"):               # 星球文件里没有的（尼克斯三颗没 planetRadius）用旧表的
                if not bodies[hit].get(k) and o.get(k):
                    bodies[hit][k] = o[k]
            if o.get("om"):
                bodies[hit]["om"] = o["om"]
            bodies[hit].pop("adj_unknown", None)
            if o.get("om"):
                bodies[hit].pop("om_est", None)
            renamed[(name, hit)] += 1
    return renamed


def merge(old, points, bodies, pois):
    """旧表里有、解包没有的地面点（玩家补充的）原样保留"""
    have = {(norm(p["b"]), norm(p["n"])) for p in pois}
    extra = []
    for p in old.get("pois") or []:
        if (norm(p["b"]), norm(p["n"])) not in have and p["b"] in bodies:
            q = dict(p)
            q["src"] = "community"
            extra.append(q)
    have_p = {(p["sys"], norm(p["n"])) for p in points}
    for p in old.get("points") or []:
        if (p["sys"], norm(p["n"])) not in have_p and p["t"] not in ("AsteroidBelt",) \
                and not any(q["sys"] == p["sys"] and math.dist((q["x"], q["y"], q["z"]), (p["x"], p["y"], p["z"])) < 1000 for q in points):
            q = dict(p)
            q["src"] = "community"
            points.append(q)                             # 太空点单独补进 points（别混进地面点）
    return pois + extra, extra


def compare(old, points, bodies, pois, extra):
    print(f"\n==== 对照现有 starmap.json（{old.get('source')} {old.get('fetched')}）")
    op = {(p['sys'], norm(p['n'])): p for p in old.get("points") or []}
    np_ = {(p['sys'], norm(p['n'])): p for p in points}
    print(f"太空点 旧 {len(op)} / 新 {len(np_)}；只在旧 {len(set(op) - set(np_))} {sorted(k[1] for k in set(op) - set(np_))[:8]}；只在新 {len(set(np_) - set(op))} {sorted(k[1] for k in set(np_) - set(op))[:8]}")
    far = [(k[1], round(math.dist((op[k]['x'], op[k]['y'], op[k]['z']), (np_[k]['x'], np_[k]['y'], np_[k]['z'])) / 1000)) for k in set(op) & set(np_)]
    far = [f for f in far if f[1] > 1]
    print(f"  坐标差 >1 km 的 {len(far)}：{sorted(far, key=lambda f: -f[1])[:8]}")
    tdiff = [(k[1], op[k]['t'], np_[k]['t']) for k in set(op) & set(np_) if op[k]['t'] != np_[k]['t']]
    print(f"  类型不同的 {len(tdiff)}：{Counter((a, b) for _, a, b in tdiff).most_common(6)}")
    ob = old.get("bodies") or {}
    print(f"星球 旧 {len(ob)} / 新 {len(bodies)}；只在旧 {sorted(set(ob) - set(bodies))}；只在新 {sorted(set(bodies) - set(ob))}")
    for n in sorted(set(ob) & set(bodies)):
        a, b = ob[n], bodies[n]
        d = {k: (a.get(k), b.get(k)) for k in ("r", "rot", "grid") if a.get(k) != b.get(k)}
        dist = math.dist((a['x'], a['y'], a['z']), (b['x'], b['y'], b['z'])) / 1000
        if d or dist > 1:
            print(f"  {n}: 参数不同 {d}{'，坐标差 %.0f km' % dist if dist > 1 else ''}")
    print(f"  adj 未知的 {sum(1 for b in bodies.values() if b.get('adj_unknown'))}，om 估算的 {sum(1 for b in bodies.values() if b.get('om_est'))}")
    opois = old.get("pois") or []
    okeys = {(norm(p['b']), norm(p['n'])): p for p in opois}
    nkeys = {(norm(p['b']), norm(p['n'])): p for p in pois if not p.get("src")}
    both = set(okeys) & set(nkeys)
    far = [(k, round(math.dist((okeys[k]['x'], okeys[k]['y'], okeys[k]['z']), (nkeys[k]['x'], nkeys[k]['y'], nkeys[k]['z'])), 2)) for k in both]
    far = [f for f in far if f[1] > 1]
    print(f"地面点 旧 {len(opois)} / 解包 {len(nkeys)}；两边都有 {len(both)}（坐标差 >1 km 的 {len(far)} {far[:5]}）；只在解包 {len(set(nkeys) - set(okeys))}；旧表独有、保留 {len(extra)}")
    print(f"  只在解包的例子：{[nkeys[k]['n'] + '@' + nkeys[k]['b'] for k in sorted(set(nkeys) - set(okeys))[:10]]}")
    print(f"  qt 不同的：{sum(1 for k in both if (okeys[k].get('qt') or 0) != nkeys[k]['qt'])}")
    print(f"  新表类型：{Counter(p['t'] for p in pois).most_common(12)}")


def main():
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    points, bodies, pois, stats = build(old)
    renamed = adopt_old(old, points, bodies)
    for p in pois:                                       # 星球改名了，地面点跟着改
        for (a, b) in renamed:
            if p["b"] == a:
                p["b"] = b
    if renamed:
        print("按位置沿用旧名：", dict(list(renamed.items())[:12]), "…共", len(renamed))
    pois, extra = merge(old, points, bodies, pois)
    # 作者电脑上 AT 自动校准出的自转相位（userdata\rotation_calib.json）：合进星图发给玩家（2026-10-28）
    try:
        from sc_mining.core.paths import USER
        cal = json.loads((USER / "rotation_calib.json").read_text(encoding="utf-8"))
        n_cal = 0
        for name, c in (cal.items() if isinstance(cal, dict) else []):
            if name in bodies and isinstance(c, dict) and isinstance(c.get("adj"), (int, float)):
                if isinstance(c.get("rot"), (int, float)) and abs(c["rot"] - (bodies[name].get("rot") or 0)) > 1e-6:
                    print(f"  {name} 校准时的自转周期 {c['rot']} 和现在的 {bodies[name].get('rot')} 不一样，这条校准值不用")
                    continue
                if abs(((bodies[name]["adj"] - c["adj"] + 180) % 360) - 180) > 0.01:
                    print(f"  自转相位用本机校准值：{name} {bodies[name]['adj']:.3f}° → {c['adj']:.3f}°（{c.get('at', '')}）")
                bodies[name]["adj"] = c["adj"]
                bodies[name]["adj_src"] = "calib"
                n_cal += 1
        if n_cal:
            print(f"自转相位：{n_cal} 颗用 AT 校准值")
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    print(f"太空点 {len(points)}，星球 {len(bodies)}，地面点 {len(pois)}（解包 {len(pois) - len(extra)} + 保留 {len(extra)}）{dict(stats) if stats else ''}")
    compare(old, points, bodies, pois, extra)
    if "--write" in sys.argv:
        ob, op, oo = len(old.get("bodies") or {}), len(old.get("points") or []), len(old.get("pois") or [])
        if (ob and len(bodies) < ob * 0.9) or (op and len(points) < op * 0.9) or (oo and len(pois) < oo * 0.9):
            sys.exit(f"❌ 新星图比旧表少太多（星球 {len(bodies)}/{ob}，太空点 {len(points)}/{op}，地面点 {len(pois)}/{oo}）：解包可能不完整，不写")
        import datetime
        data = {"source": "unpack", "fetched": old.get("fetched"), "unpacked": datetime.date.today().isoformat(),
                "bodies": bodies, "pois": pois, "points": points}
        OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"→ {OUT}")


if __name__ == "__main__":
    main()
