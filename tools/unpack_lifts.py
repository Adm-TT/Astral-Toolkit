"""空间站站内导航数据（2026-10-28）：每个站的区域、电梯线、机库 → data/station_lifts.json。
  .venv\\Scripts\\python.exe -X utf8 tools\\unpack_lifts.py [解开的物件容器目录…] [--force]
  比旧的 station_lifts.json 少很多（站、机库、标上区域的点少 10% 以上）就不写；确认没问题加 --force 强行写。
要先跑过 unpack_city.py（用 data/city_places.json 里站内的点，给每个点标上所在区域）。
  区域：站里带区域标签的子容器，右上角最里层 Zone 行显示的就是它的 entityName（每个站写法不一样，按站存）。
  电梯：站总容器 rs_ext_*.soc 里的 TransitManager 实体，Destination 的 destinationPos、Gateway 的 gatewayPos 都相对 TransitManager 自己的位置。
  机库：门实体 InstancedHangarGateway_*（机库实例摆在门的位置和朝向上），机库里电梯门 / 出生点从机库自己的容器和记录里取。
坐标和 city_places 一样：拉格朗日点 / 跳跃点的站是星系坐标（千米），绕星球轨道的站是星球局部坐标（千米）。
只发整理出的坐标和名字，不发游戏文件。"""
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cryx  # noqa: E402
import unpack_city as U  # noqa: E402
import unpack_stations as S  # noqa: E402

ROOT = U.ROOT
RECORDS = Path(os.environ.get("AT_UNPACK_DIR", r"E:\Game3\unpack")) / "dcb_json" / "libs" / "foundry" / "records"
ZONE_TAG = "503443c0-b6d1-4539-b493-688117334ff1"         # 带这个标签的子容器 = 一个区域（右上角 Zone 行显示它的 entityName）
CH = re.compile(r'<Child [^>]*?name="([^"]+)"[^>]*?entityName="([^"]*)"[^>]*?tags="([^"]*)"[^>]*?guid="([^"]+)"[^>]*?pos="([^"]+)" rot="([^"]+)"')
# 区域容器名 → 汉化包键（区域的中英文名）
AREA_KEY = [(r"^rs_entry_", "area_name_lobby"), (r"^rs_comm_", "ui_dest_commercial"), (r"^rs_habs_", "ui_dest_habs"),
            (r"^rs_refin_", "ui_dest_refinery"), (r"cargo", "ui_dest_cargo")]
# 小站的大厅 / 购物中心容器没带区域标签（右上角 Zone 行这时显示什么没核实）：也当一个区域，认区域时只能按坐标
PSEUDO = re.compile(r"^(rs_entry_|rs_comm_|rs_refin_|rs_habs_|reststop_cargo_occu)")
EXTRA = {"hangar": "ui_interactor_hangar", "pad": "ui_interactor_generic_pad", "dock": ""}
DOCK = ("Docking Port", "对接口")                         # 汉化包只有「对接口 01」这种带编号的，去掉编号
# 电梯线：汉化组没翻，自译进对照表（AGENTS.md）
LINE_NAME = {"TransitManager_Internal": ("Station Lift", "站内电梯"), "TransitManager_Habs": ("Habs Lift", "居住区电梯"),
             "TransitManager_Spaceport-to-Hangars": ("Hangar Lift", "机库电梯")}
SIZES = ("Small", "Medium", "Large")
GATE_CHECK_M = 5             # 算出的门和门实体（Gateway 指向的实体）位置差这么多就打印出来
AREA_GATE_M = 300            # 站里的点离本区域任一电梯门都超过这么远：这个站的数据不可信，标 ok=False（导航不分段）


def V(s):
    return tuple(float(v) for v in s.split(","))


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def km(g):
    return [round(v / 1000, 6) for v in g]


def tr(key):
    """汉化包键 → (英文, 中文)；中文两个汉字中间的空格去掉（「大 厅」）"""
    L = U.loc()
    k = (key or "").lstrip("@").lower()
    zh = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", L["zh"].get(k, "")).strip()
    return L["en"].get(k, key or ""), zh


def tm_local(mp, mq, rel):
    """TransitManager 的 destinationPos / gatewayPos（在它自己的坐标系里）→ 站局部坐标（米）：先转它的朝向再加它的位置"""
    return add(mp, U.rot(mq, rel))


def worst_place_gate(places, pmap, lifts):
    """站里的点离本区域任一电梯门的最近距离，取最大的（米）；坐标都是千米"""
    area_gates = {}
    for ln in lifts:
        for s in ln["stops"]:
            if s.get("area") and s["area"] != "hangar":
                area_gates.setdefault(s["area"], []).extend(s["gates"])
    worst = 0.0
    for p in places:
        a = pmap.get(p["id"])
        if area_gates.get(a):
            worst = max(worst, min(math.dist((p["x"], p["y"], p["z"]), g) for g in area_gates[a]) * 1000)
    return worst


def hangar_local(cls, idx, records, cache={}):
    """机库门类 → (机库容器名, 机库里电梯门, 出生点)，都是机库局部坐标（米）；找不到返回 None"""
    if cls in cache:
        return cache[cls]
    out = None
    try:
        gj = records / "entities/scitem/doors/hangar" / (cls.lower() + ".json")
        inst = next(x["instance"] for x in json.loads(gj.read_text(encoding="utf-8"))["_RecordValue_"]["Components"] if "instance" in x)
        rec = json.loads((records / "instancedinterior/hangar" / Path(inst).name).read_text(encoding="utf-8"))
        comps = {x["_Type_"]: x for x in rec["_RecordValue_"]["Components"]}
        oc = Path(comps["SObjectContainerComponentParams"]["objectContainer"]).stem
        sp = comps["InstancedInteriorComponentParams"]["spawnTransform"]["Position"]
        lift = next(V(x.get("Pos")) for x in cryx.entities(idx[oc.lower()].with_suffix(".soc"))
                    if x.get("EntityClass") == "TransitDynamicDestination")
        out = (oc, lift, (sp["x"], sp["y"], sp["z"]))
    except Exception as e:                                   # noqa
        print(f"  ⚠ 机库 {cls}：{e}")
    cache[cls] = out
    return out


def build_station(top, idx, rev, body_of, bodies, records, places, hl):
    r = S.resolve(top, rev, body_of)
    if not r:
        return None
    frame, where, P, Q = r
    sysname = where if frame == "sys" else (bodies.get(where) or {}).get("sys", "")
    if sysname not in S.DONE_SYS:
        return None
    rec = S.rec_of(top)

    def G(lp):
        return add(P, U.rot(Q, lp))
    qinv = (Q[0], -Q[1], -Q[2], -Q[3])

    # ---- 区域：容器树里带区域标签的那层；每个子容器归到往上最近的区域
    nodes = []                                    # (容器名, entityName, 站局部位置, 朝向, 区域 entityName, guid)
    pseudo = set()                                # 没带区域标签、按容器名当区域的

    def walk(stem, lp, lq, zone, depth=0):
        f = idx.get(stem.lower())
        if not f or depth > 8:
            return
        for name, ent, tags, guid, p, q in CH.findall(f.read_text(encoding="utf-8", errors="ignore")):
            s = Path(name.replace("\\", "/")).stem
            gp, gq = add(lp, U.rot(lq, V(p))), U.qmul(lq, V(q))
            z = ent if ZONE_TAG in tags and ent else zone
            if z is None and PSEUDO.search(s):
                z = ent or s
                pseudo.add(z)
            nodes.append((s, ent, gp, gq, z, guid.lower()))
            walk(s, gp, gq, z, depth + 1)
    walk(top, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), None)
    zones, boxes = {}, {}
    for s, ent, gp, gq, z, guid in nodes:
        if z and (z == ent or z == s) and z not in zones:
            key = next((k for pat, k in AREA_KEY if re.search(pat, s)), "")
            en, zh = tr(key) if key else (s, "")
            zones[z] = {"en": en, "zh": zh}
    for s, ent, gp, gq, z, guid in nodes:                # 包围盒（站局部米）：子容器原点 + 里面的小物件
        if not z:
            continue
        for p in [gp] + [add(gp, U.rot(gq, lp)) for _n, lp in U.soc_entities(idx, s)[:400]]:
            b = boxes.get(z) or [list(p), list(p)]
            boxes[z] = [[min(b[0][i], p[i]) for i in range(3)], [max(b[1][i], p[i]) for i in range(3)]]
    if not zones:
        print(f"  ⚠ {top}：没找到区域")
        return None

    # ---- 电梯线
    by_guid = {g: (s, z) for s, ent, gp, gq, z, g in nodes}
    node_at = {g: (s, gp, gq) for s, ent, gp, gq, z, g in nodes}
    soc_ents = {}

    def gate_entity(path):
        """Gateway 指向的实体在站局部坐标里的位置：路径里最深的那层容器 + 里面 EntityCryGUID 对得上的实体；找不到 None"""
        hit = [node_at[p] for p in path if p in node_at]
        if not hit:
            return None
        s, gp, gq = hit[-1]
        if s not in soc_ents:
            f = idx.get(s.lower())
            soc = f.with_suffix(".soc") if f else None
            soc_ents[s] = {(x.get("EntityCryGUID") or "").lower(): V(x.get("Pos"))
                           for x in (cryx.entities(soc) if soc and soc.exists() else []) if x.get("Pos")}
        lp = soc_ents[s].get(path[-1])
        return add(gp, U.rot(gq, lp)) if lp else None
    n_bad_gate = 0
    ents = cryx.entities(idx[top.lower()].with_suffix(".soc"))
    lifts = []
    owners = {}                                   # 门所在、又不在区域里的容器（安全港、外部货运）→ 第一个用到它的站名
    for e in ents:
        if e.get("EntityClass") != "TransitManager":
            continue
        mp, mq = V(e.get("Pos")), V(e.get("Rotate") or "1,0,0,0")     # 门、站的位置在 TransitManager 自己的坐标系里：要套它的朝向
        name = e.get("Name") or ""
        en, zh = LINE_NAME.get(name, (name, ""))
        line = {"id": name, "en": en, "zh": zh, "stops": []}
        for d in e.iter("Destination"):
            s_en, s_zh = tr(d.get("nameIdentifier"))
            gates, area = [], None
            for g in d.findall("Gateway"):
                nd = by_guid.get((g.get("Entity") or "").split(",")[0].lower())
                if nd and nd[1]:
                    area = nd[1]
                elif nd and not area:
                    area = "pad" if "elev_atc" in nd[0] else "dock" if "docking" in nd[0] else None
                    if area is None:                  # 区域外的容器（货运甲板、安全港）：一个容器里有十几个站，按「容器#站」分开
                        area = f"{nd[0]}#{d.get('nameIdentifier')}"
                        owners.setdefault(area, (s_en, s_zh))
                path = [x.lower() for x in (g.get("Entity") or "").split(",") if x]
                lp = tm_local(mp, mq, V(g.get("gatewayPos")))
                chk = gate_entity(path)
                if chk is not None and math.dist(chk, lp) > GATE_CHECK_M:
                    n_bad_gate += 1
                    print(f"  ⚠ {top}：{name} {d.get('nameIdentifier')} 门和门实体差 {math.dist(chk, lp):.0f} m")
                gates.append(km(G(lp)))
            line["stops"].append({"key": d.get("nameIdentifier"), "en": s_en, "zh": s_zh, "area": area, "gates": gates})
        if e.find("EntityLinks") is not None and "hangar" in name.lower():     # 机库（实例）也是机库电梯的一站，门在 hangars 里
            h_en, h_zh = tr(EXTRA["hangar"])
            line["stops"].append({"key": "hangar", "en": h_en, "zh": h_zh, "area": "hangar", "gates": []})
        lifts.append(line)

    # ---- 机库门 + 机库里的电梯门、出生点
    hangars = []
    for e in ents:
        c = e.get("EntityClass", "")
        m = re.search(r"_(Small|Medium|Large)Front", c)
        if not c.startswith("InstancedHangarGateway") or not m:
            continue
        loc = hangar_local(c, idx, records)
        if not loc:
            continue
        oc, lift, spawn = loc
        hl.setdefault(m[1], {"lift": [round(v, 2) for v in lift], "spawn": [round(v, 2) for v in spawn]})
        gp, gq = V(e.get("Pos")), V(e.get("Rotate") or "1,0,0,0")
        hangars.append({"id": e.get("Name"), "size": m[1], "door": km(G(gp)),
                        "lift": km(G(add(gp, U.rot(gq, lift)))), "spawn": km(G(add(gp, U.rot(gq, spawn))))})

    # ---- 站里的点 → 区域：点所在容器只属于一个区域就用它，不然看包围盒（放宽 3 米，取最小的）
    stem_zone = {}
    for s, ent, gp, gq, z, guid in nodes:
        stem_zone.setdefault(s.lower(), set()).add(z)
    pmap = {}
    for p in places:
        if p.get("city") != rec:
            continue
        first = p["id"].rstrip("+").split("/")[0]
        zs = stem_zone.get(first.lower(), set())
        a = next(iter(zs)) if len(zs) == 1 else None
        if a is None:                          # 点就在这种容器里：归到这个容器里离它最近的那一站
            own = [(math.dist((p["x"], p["y"], p["z"]), g), s["area"]) for ln in lifts for s in ln["stops"]
                   if s.get("area") in owners and s["area"].split("#")[0] == first for g in s["gates"]]
            a = min(own)[1] if own else None
        if a is None:
            lp = U.rot(qinv, tuple(v * 1000 - o for v, o in zip((p["x"], p["y"], p["z"]), P)))
            hit = [z for z, b in boxes.items() if all(b[0][i] - 3 <= lp[i] <= b[1][i] + 3 for i in range(3))]
            a = min(hit, key=lambda z: math.prod(boxes[z][1][i] - boxes[z][0][i] + 1 for i in range(3))) if hit else None
        if a is None:                          # 货运电梯这类：容器名对不上（_000 / _001），离区域外那些站的门 30 米内就归它
            near = min(((math.dist((p["x"], p["y"], p["z"]), g) * 1000, s["area"]) for ln in lifts for s in ln["stops"]
                        if s.get("area") in owners for g in s["gates"]), default=(1e9, None))
            a = near[1] if near[0] < 30 else None
        if a:
            pmap[p["id"]] = a
        else:
            print(f"  ⚠ {top}：{p['zh']}（{p['id']}）认不出在哪个区域")
    areas = {z: dict(v, zone=z not in pseudo) for z, v in zones.items()}
    h_en, h_zh = tr(EXTRA["hangar"])
    p_en, p_zh = tr(EXTRA["pad"])
    areas.update(hangar={"en": h_en, "zh": h_zh}, pad={"en": p_en, "zh": p_zh}, dock={"en": DOCK[0], "zh": DOCK[1]})
    for stem, (en, zh) in owners.items():
        areas.setdefault(stem, {"en": en, "zh": zh})
    # ---- 自检：站里的点离本区域任一电梯门的最近距离（正常几十到一两百米；差一个整体旋转时是几千米）
    worst = worst_place_gate([p for p in places if p.get("city") == rec], pmap, lifts)
    ok = worst <= AREA_GATE_M
    print(f"  {rec}：点到本区域电梯门最近距离的最大值 {worst:,.0f} m，门和门实体差 >{GATE_CHECK_M} m 的 {n_bad_gate} 个"
          + ("" if ok else f"  ❌ 超过 {AREA_GATE_M} m，这个站标为不可用（导航不分段）"))
    out = {"station": top, "ok": ok, "worst_m": round(worst), "areas": areas, "lifts": lifts, "hangars": hangars, "places": pmap}
    if frame == "body":
        out["body"] = where
    else:
        out.update(sys=where, space=True)
    return rec, out


def main():
    dirs = [a for a in sys.argv[1:] if not a.startswith("-")] or [
        d for d in (r"E:\Game3\unpack\city_x", r"E:\Game3\unpack\oc_x", r"E:\Game3\unpack\loc_x", r"E:\Game3\unpack\stn_x") if Path(d).exists()]
    idx = U.index(dirs)
    rev = S.reverse_index(idx)
    sys.path.insert(0, str(ROOT))
    from sc_mining import navigate as N
    bodies = N.load()["bodies"]
    body_of = S.bodies_of(rev, bodies)
    # 站里的点用导航读进来的样子（同一个店容器在两个区域各摆一个时 src 一样，id 后面加 +）：点 → 区域按 id 存
    places = N._city_rows(json.loads((ROOT / "data" / "city_places.json").read_text(encoding="utf-8")))
    hl, stations = {}, {}
    for top in sorted(k for k in idx if S.TOP.match(k)):
        r = build_station(top, idx, rev, body_of, bodies, RECORDS, places, hl)
        if not r:
            continue
        rec, st = r
        if not rec:
            continue
        stations[rec] = st
        n_pl = sum(1 for p in places if p.get("city") == rec)
        print(f"  {rec}（{top}）区域 {sum(1 for a in st['areas'].values() if a.get('zone'))} 个、电梯线 {len(st['lifts'])} 条、"
              f"机库 {len(st['hangars'])} 个、点 {len(st['places'])}/{n_pl} 标上区域")
    if not stations:
        sys.exit("❌ 一个站都没做出来")
    dst = ROOT / "data" / "station_lifts.json"

    def counts(sts):
        return (len(sts), sum(len(s.get("hangars") or []) for s in sts.values()), sum(len(s.get("places") or {}) for s in sts.values()))
    new = counts(stations)
    try:
        old = counts(json.loads(dst.read_text(encoding="utf-8")).get("stations") or {})
    except (OSError, ValueError, AttributeError):
        old = (0, 0, 0)
    if "--force" not in sys.argv and (not new[1] or any(o and n < o * 0.9 for n, o in zip(new, old))):
        sys.exit(f"❌ 新数据比旧的少太多（站 {new[0]}/{old[0]}，机库 {new[1]}/{old[1]}，标上区域的点 {new[2]}/{old[2]}）：解包可能不完整，不写")
    from sc_mining.paths import write_json
    write_json(dst, {"version": 1, "hangar_lift_local": hl, "stations": stations}, ensure_ascii=False, indent=1)
    print(f"✅ 空间站电梯 {len(stations)} 个站 → {dst}")
    # 自译的电梯线名写进对照表（已经有的不重复写），老大在「改成」列改
    csv = ROOT / "翻译对照" / "自译对照_词表.csv"
    if csv.exists():
        import csv as _csv
        rows = list(_csv.reader(csv.open(encoding="utf-8-sig")))
        have = {r[0] for r in rows[1:] if r}
        new = [(en, zh) for en, zh in LINE_NAME.values() if en not in have]
        if new:
            with csv.open("a", encoding="utf-8", newline="") as f:          # 追加不能再写 BOM
                w = _csv.writer(f)
                for en, zh in new:
                    w.writerow([en, zh, "自译（站内电梯）", 1, ""])
            print(f"自译对照_词表.csv 加了 {len(new)} 个词")


if __name__ == "__main__":
    main()
