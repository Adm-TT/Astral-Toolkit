"""解包数据 → 采矿数据库（2026-10-27）：从 StarBreaker 导出的 DataCore JSON（records 目录）整理出
矿物元素、岩石成分、雷达信号、每个地点刷什么矿（概率、成团块数）、品质分布。用法：
  python tools/unpack_mining.py <records 目录> <输出 json> [data/mining_rocks.json]
第三个参数：顺便生成 AT 用的雷达石头表（每个地点刷哪几种石头、一团几块）
只读游戏导出的文件，不碰用户数据"""
import json
import re
import sys
from pathlib import Path


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def ref_name(s):
    """file://./../../libs/foundry/records/x/y/z.json → x/y/z"""
    if not s or not isinstance(s, str):
        return None
    m = re.search(r"records/(.+)\.json$", s.replace("\\", "/"))
    return m.group(1).lower() if m else None


def main(root, out):
    root = Path(root)
    rec = lambda rel: load(root / (rel + ".json"))["_RecordValue_"]  # noqa: E731, F841
    db = {"elements": {}, "compositions": {}, "rocks": {}, "presets": {}, "clusters": {}, "locations": {}, "quality": {}}
    for f in sorted((root / "mining/mineableelements").glob("*.json")):
        v = load(f)["_RecordValue_"]
        db["elements"][f.stem] = {"resource": (v.get("resourceType") or {}).get("_RecordName_", "").split(".")[-1],
                                  "instability": v.get("elementInstability"), "resistance": v.get("elementResistance"),
                                  "window_mid": v.get("elementOptimalWindowMidpoint"),
                                  "window_rand": v.get("elementOptimalWindowMidpointRandomness"),
                                  "window_thin": v.get("elementOptimalWindowThinness"),
                                  "explosion": v.get("elementExplosionMultiplier"), "cluster": v.get("elementClusterFactor")}
    for f in sorted((root / "mining/rockcompositionpresets").rglob("*.json")):
        v = load(f)["_RecordValue_"]
        key = f.relative_to(root).with_suffix("").as_posix().lower()
        db["compositions"][key] = {"deposit": v.get("depositName"), "min_distinct": v.get("minimumDistinctElements"),
                                   "parts": [{"element": Path(ref_name(p.get("mineableElement")) or "").name,
                                              "min": p.get("minPercentage"), "max": p.get("maxPercentage"),
                                              "prob": p.get("probability"), "quality_scale": p.get("qualityScale"),
                                              "curve": p.get("curveExponent")} for p in v.get("compositionArray") or []]}
    for f in sorted((root / "entities/mineable").rglob("*.json")):
        v = load(f)["_RecordValue_"]
        sig, comp = None, None
        for c in v.get("Components") or []:
            t = (c or {}).get("_Type_")
            if t == "SSCSignatureSystemParams":
                s = (((c.get("radarProperties") or {}).get("baseSignatureParams") or {}).get("signatures")) or []
                sig = [x for x in s]
            elif t == "MineableParams":
                comp = ref_name(c.get("composition"))
        db["rocks"][f.relative_to(root).with_suffix("").as_posix().lower()] = {"signatures": sig, "composition": comp}
    for f in sorted((root / "harvestable/harvestablepresets").rglob("*.json")):
        v = load(f)["_RecordValue_"]
        ent = ref_name(v.get("entityClass"))
        if ent:
            db["presets"][f.relative_to(root).with_suffix("").as_posix().lower()] = {"entity": ent}
    for f in sorted((root / "harvestable/clusteringpresets").rglob("*.json")):
        v = load(f)["_RecordValue_"]
        db["clusters"][f.relative_to(root).with_suffix("").as_posix().lower()] = {
            "p_cluster": v.get("probabilityOfClustering"),
            "sizes": [{"p": c.get("relativeProbability"), "min": c.get("minSize"), "max": c.get("maxSize")}
                      for c in v.get("clusterParamsArray") or []]}
    for f in sorted((root / "harvestable/providerpresets").rglob("*.json")):
        v = load(f)["_RecordValue_"]
        groups = []
        for g in v.get("harvestableGroups") or []:
            items = []
            for h in g.get("harvestables") or []:
                items.append({"preset": ref_name(h.get("harvestable")), "entity": ref_name(h.get("harvestableEntityClass")),
                              "p": h.get("relativeProbability"), "cluster": ref_name(h.get("clustering"))})
            groups.append({"name": g.get("groupName"), "p": g.get("groupProbability"), "items": items})
        db["locations"][f.stem.lower()] = {"path": f.relative_to(root).as_posix(), "groups": groups}
    for f in sorted((root / "crafting/qualitydistribution").rglob("*.json")):
        v = load(f)["_RecordValue_"]
        dist = v.get("qualityDistribution")
        entries = []
        if dist:
            entries.append({"location": None, **{k: dist.get(k) for k in ("min", "max", "mean", "stddev")}})
        for e in ((v.get("locationOverride") or {}).get("locationOverrideList") or []):
            d = e.get("qualityDistribution") or {}
            entries.append({"location": Path(ref_name(e.get("location")) or "").name, **{k: d.get(k) for k in ("min", "max", "mean", "stddev")}})
        db["quality"][f.stem.lower()] = entries
    Path(out).write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: len(v) for k, v in db.items()})
    return db


def check_rocks(r, scminer):
    """检查：船挖矿 26 种以上、信号和 AT 的表一致、每个地点的石头都在 SCMiner 这个地点的矿物里（派罗星团合并表除外）"""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from sc_mining.mining.data import SIGNATURES
    bad = []
    if len(r["ores"]) < 26:
        bad.append(f"船挖矿只有 {len(r['ores'])} 种")
    bad += [f"{o} 信号 {v['sig']} ≠ AT {SIGNATURES[o]}" for o, v in r["ores"].items() if o in SIGNATURES and SIGNATURES[o] != v["sig"]]
    for name, tab in r["areas"].items():
        if name not in scminer:                       # SCMiner 没有的地点（派罗拉格朗日点、深空小行星）不比
            continue
        miss = [o for o in tab if o not in scminer[name]]
        if miss:
            bad.append(f"{name}：{'、'.join(miss)} 不在 SCMiner 表里")
    if len(r["areas"]) < 40:
        bad.append(f"地点只有 {len(r['areas'])} 个")
    return bad


# ---------------------------------------------------------------- 给 AT 用的「雷达石头表」data/mining_rocks.json
TIERS = ("common", "uncommon", "rare", "epic", "legendary")
ORE_NAME = {"aluminum": "Aluminum", "quantainium": "Quantainium", "stileron": "Stileron"}
# 星图 / SCMiner 地点名 ← 游戏里的刷矿表（providerpresets）。星球卫星按游戏内部编号；小行星带直接对应
FIXED = {"hpp_stanton1": "Hurston", "hpp_stanton1a": "Arial", "hpp_stanton1b": "Aberdeen", "hpp_stanton1c": "Magda",
         "hpp_stanton1d": "Ita", "hpp_stanton2a": "Cellin", "hpp_stanton2b": "Daymar", "hpp_stanton2c": "Yela",
         "hpp_stanton3a": "Lyria", "hpp_stanton3b": "Wala", "hpp_stanton4": "microTech", "hpp_stanton4a": "Calliope",
         "hpp_stanton4b": "Clio", "hpp_stanton4c": "Euterpe", "hpp_stanton2c_belt": "Yela Asteroid Belt",
         "hpp_aaronhalo": "Aaron Halo", "hpp_nyx_keegerbelt": "Keeger Belt", "hpp_nyx_glaciemring": "Glaciem Ring",
         "hpp_pyro1": "Pyro I", "hpp_pyro2": "Pyro II (Monox)", "hpp_pyro3": "Pyro III (Bloom)", "hpp_pyro4": "Pyro IV",
         "hpp_pyro5a": "Pyro V-a (Ignis)", "hpp_pyro5b": "Pyro V-b (Vatra)", "hpp_pyro5c": "Pyro V-c (Adir)",
         "hpp_pyro5d": "Pyro V-d (Fairo)", "hpp_pyro5e": "Pyro V-e (Fuego)", "hpp_pyro5f": "Pyro V-f (Vuur)",
         "hpp_pyro6": "Pyro VI (Terminus)"}
# 下面这些「哪里用哪张刷矿表」是 2026-10-27 解物件容器（socpak）按刷矿表 GUID 找到的：
# 斯坦顿拉格朗日点的子云 childcloud_s<星>_l<点>_* → hpp_lagrange_a～f（s1 赫斯顿 HUR、s2 十字军 CRU、s3 弧光 ARC、s4 微科 MIC）
LAGRANGE = {"hpp_lagrange_a": ["HUR-L1", "HUR-L4"], "hpp_lagrange_b": ["CRU-L4", "ARC-L5", "MIC-L3"],
            "hpp_lagrange_c": ["HUR-L5", "CRU-L3", "MIC-L1", "MIC-L2", "MIC-L5"],
            "hpp_lagrange_d": ["CRU-L5", "ARC-L3", "MIC-L4"], "hpp_lagrange_e": ["HUR-L3", "CRU-L1", "CRU-L2"],
            "hpp_lagrange_f": ["HUR-L2", "ARC-L1", "ARC-L2", "ARC-L4"]}
# 派罗拉格朗日点的子云：派1、派2 → 暖带 01，派3 → 暖带 02，派5 → 冷带 01，派6 → 冷带 02（派4 没有）；
# 每颗星的 L1、L2 旁边还有几团「模块化星团」（深空小行星表）
PYRO_LAGRANGE = {1: "hpp_pyro_warm01", 2: "hpp_pyro_warm01", 3: "hpp_pyro_warm02", 5: "hpp_pyro_cool01", 6: "hpp_pyro_cool02"}
DEEP = "Deep Space Asteroids"        # 派罗 15 个「小行星群」、86 个远矿站都用 hpp_pyro_deepspaceasteroids


def _ship_rocks(db, loc):
    """一个刷矿表里飞船能挖的石头：{矿名: (相对概率, 稀有度, 成团规则名)}"""
    out = {}
    for g in db["locations"][loc]["groups"]:
        if "ship" not in (g["name"] or "").lower():
            continue
        for it in g["items"]:
            ent = (db["presets"].get(it["preset"] or "") or {}).get("entity") or it["entity"] or ""
            m = re.match(r".*mineablerock_(?:asteroid|surface)(\w+?)_(\w+)$", ent)
            if not m or m.group(1) not in TIERS:
                continue
            ore = ORE_NAME.get(m.group(2), m.group(2).capitalize())
            p, tier, cl = out.get(ore, (0.0, m.group(1), it["cluster"]))
            out[ore] = (p + (it["p"] or 0), tier, cl)
    return out


def _pct(rocks):
    tot = sum(p for p, _, _ in rocks.values()) or 1
    return {ore: round(100 * p / tot, 1) for ore, (p, _, _) in sorted(rocks.items(), key=lambda kv: -kv[1][0])}


def _element_ore(db, element):
    """成分里的元素 → AT 用的英文矿名（Raw_Hephaestanite / RawSilicon / Ore_Aluminum → Hephaestanite / Silicon / Aluminum）"""
    res = (db["elements"].get(element) or {}).get("resource") or ""
    return re.sub(r"^(Ore_|Raw_|Raw)", "", res) or None


def build_rocks(db, scminer=None):
    """→ {"tiers": {稀有度: 成团规则}, "ores": {矿: {"sig", "tier"}}, "areas": {地点名: {矿: 百分比}},
    "contains": {主矿: [这种石头里会出的矿]}}。contains：扫描面板矿名没认出时，按品质档位只在这几种里补（2026-10-27：
    火神石石头只出火神石、石英、硅，「?? 510」是硅；510 这一档拉兰石、萨达里克斯也有）"""
    tiers, ores, areas, contains = {}, {}, {}, {}
    for loc in db["locations"]:
        for ore, (p, tier, cl) in _ship_rocks(db, loc).items():
            c = db["clusters"].get(cl or "")
            if c and tier not in tiers:
                tiers[tier] = {"p_cluster": c["p_cluster"], "sizes": [[s["p"], s["min"], s["max"]] for s in c["sizes"]]}
    for k, r in db["rocks"].items():
        m = re.match(r".*mineablerock_(?:asteroid|surface)(\w+?)_(\w+)$", k)
        if not m or m.group(1) not in TIERS:
            continue
        sig = max((s for s in (r["signatures"] or []) if s), default=None)
        if sig and m.group(2).isalpha() and m.group(2) != "template":      # 不要模板、破岩站（_rcd_）这些特殊石头
            main = ORE_NAME.get(m.group(2), m.group(2).capitalize())
            ores[main] = {"sig": int(sig), "tier": m.group(1)}
            comp = db["compositions"].get((r.get("composition") or "").lower()) or {}
            got = {_element_ore(db, p["element"]) for p in comp.get("parts") or []} - {None}
            if got:
                contains.setdefault(main, set()).update(got)
    for loc, name in FIXED.items():
        if loc in db["locations"]:
            areas[name] = _pct(_ship_rocks(db, loc))
    has = db["locations"]
    if "hpp_pyro_akirocluster" in has:
        areas["Akiro Cluster"] = _pct(_ship_rocks(db, "hpp_pyro_akirocluster"))
    deep = _ship_rocks(db, "hpp_pyro_deepspaceasteroids") if "hpp_pyro_deepspaceasteroids" in has else {}
    if deep:
        areas[DEEP] = _pct(deep)
    for loc, names in LAGRANGE.items():
        if loc in has:
            for name in names:
                areas[name] = _pct(_ship_rocks(db, loc))
    for k, loc in PYRO_LAGRANGE.items():
        if loc not in has:
            continue
        base = _ship_rocks(db, loc)
        for m in range(1, 6):
            rocks = base
            if m in (1, 2) and deep:                   # L1、L2 旁边的模块化星团：两张表各算一半
                ta = sum(p for p, _, _ in base.values()) or 1
                tb = sum(p for p, _, _ in deep.values()) or 1
                rocks = {o: (p / ta, t, c) for o, (p, t, c) in base.items()}
                for o, (p, t, c) in deep.items():
                    q = rocks.get(o, (0.0, t, c))
                    rocks[o] = (q[0] + p / tb, t, c)
            areas[f"PYR{k}-L{m}"] = _pct(rocks)
    return {"tiers": tiers, "ores": ores, "areas": areas, "contains": {k: sorted(v) for k, v in sorted(contains.items())}}


if __name__ == "__main__":
    db = main(sys.argv[1], sys.argv[2])
    if len(sys.argv) > 3:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from sc_mining.mining.locations import LOCATIONS
        sc = {row["name"]: row["minerals"] for row in LOCATIONS}
        rocks = build_rocks(db, sc)
        bad = check_rocks(rocks, sc)
        if bad:
            print("❌ 检查没通过，不写文件：\n  " + "\n  ".join(bad))
            sys.exit(1)
        Path(sys.argv[3]).write_text(json.dumps(rocks, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"✅ 雷达石头表：{len(rocks['ores'])} 种矿、{len(rocks['areas'])} 个地点 → {sys.argv[3]}")
