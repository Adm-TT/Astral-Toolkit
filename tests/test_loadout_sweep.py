"""所有合法配装全量验算：每条船、每个矿头、每种模组组合（约 5000 套），外加 MOLE 随机混搭和接口存取"""
import itertools
import math
import random
import time


def test_every_loadout(monkeypatch, tmp_path):
    from sc_mining import settings, laser
    from sc_mining.data import SHIPS, HEADS, MODULES, GADGETS
    from sc_mining.app import services
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")

    def mult(*ps):
        out = 1.0
        for p in ps:
            out *= 1 + (p or 0) / 100
        return out

    from sc_mining.app import services

    def mult(*ps):
        out = 1.0
        for p in ps: out *= 1 + (p or 0) / 100
        return out

    ROCKS = [(m, r, i) for m in (500, 3000, 8000, 20000, 60000) for r in (0, 15, 35, 60, 90) for i in (0, 15, 60)]
    mods = list(MODULES)
    n_loadouts = n_calcs = 0
    problems = []
    t0 = time.time()
    # 1) 每条船、每个能装的矿头、每一种模组组合（含空槽、可重复），逐个验算
    for ship, spec in SHIPS.items():
        heads = [spec["fixed"]] if spec.get("fixed") else [k for k, h in HEADS.items() if h["size"] == spec["size"] and not h.get("ship")]
        for hk in heads:
            h = HEADS[hk]
            for n in range(h["slots"] + 1):
                for combo in itertools.combinations_with_replacement(mods, n):
                    lo = {"heads": [[hk, list(combo)]] * spec["heads"], "crew": 1}
                    clean = laser.clean_loadout(ship, lo)
                    n_loadouts += 1
                    if clean["heads"][0] != [hk, list(combo)]:
                        problems.append(("被错改", ship, hk, combo, clean)); continue
                    hs = laser.HeadSetup(hk, list(combo))
                    want = h["pmax"] * mult(*(MODULES[m].get("power") for m in combo))
                    if abs(hs.max_power() - want) > 1e-6:
                        problems.append(("功率算错", ship, hk, combo, hs.max_power(), want))
                    for (m, r, i) in ROCKS[:: (1 if n_loadouts % 50 == 0 else 15)]:
                        for g in (None, *GADGETS):
                            p = laser.evaluate([hs], g, m, r, i)
                            n_calcs += 1
                            # 手算：有效抗性 = 抗性 × 矿头修正 × 模组修正 × 工具修正，限制在 0~0.99
                            gres = GADGETS[g].get("res") if g else None
                            eff = min(max(r / 100 * mult(h["res"], *(MODULES[x].get("res") for x in combo), gres), 0), 0.99)
                            delivered = want * (1 - eff)
                            if abs(p.delivered - delivered) > 1e-6 or not math.isfinite(p.ratio) or p.ratio < 0:
                                problems.append(("输出算错", ship, hk, combo, g, m, r, p.delivered, delivered)); break
                            if p.breakable and not (0 < p.throttle <= 1):
                                problems.append(("建议功率越界", ship, hk, combo, g, m, r, p.throttle))
    # 2) 模组塞超了 / 装错尺寸 / 魔像换矿头 / 人数超了：都要被纠正
    bad = [("prospector", {"heads": [["helix_ii", []]]}), ("mole", {"heads": [["helix_i", []]] * 3}),
           ("golem", {"heads": [["lancet_mh1", ["rieger"] * 5]], "crew": 9}), ("mole", {"heads": [["helix_ii", ["xx", "rieger"]]], "crew": 7}),
           ("prospector", {"heads": [["pitman", []]]}), ("mole", None), ("prospector", {}), ("golem", {"heads": []})]
    for ship, lo in bad:
        c = laser.clean_loadout(ship, lo); n_loadouts += 1
        spec = SHIPS[ship]
        ok = len(c["heads"]) == spec["heads"] and 1 <= c["crew"] <= spec["crew_max"] and all(
            HEADS[k]["size"] == spec["size"] and len(m) <= HEADS[k]["slots"] and all(x in MODULES for x in m)
            and (not spec.get("fixed") or k == spec["fixed"]) and (not HEADS[k].get("ship") or HEADS[k]["ship"] == ship) for k, m in c["heads"])
        if not ok: problems.append(("没纠正", ship, lo, c))
    # 3) MOLE 三个矿头随机混搭 + 1~3 人，跑完整推荐（包括多矿头组合、贴工具）
    random.seed(1)
    s2 = [k for k, h in HEADS.items() if h["size"] == 2]
    for _ in range(400):
        heads = []
        for _ in range(3):
            k = random.choice(s2); heads.append([k, random.choices(mods, k=random.randint(0, HEADS[k]["slots"]))])
        crew = random.randint(1, 3)
        settings.update(mining_ship="mole", mining_loadouts={"mole": {"heads": heads, "crew": crew}})
        n_loadouts += 1
        for (m, r, i) in random.sample(ROCKS, 6):
            plans = laser.recommend(m, r, i, top=5); n_calcs += 1
            if not plans or any(len(p.heads) > crew for p in plans):
                problems.append(("MOLE 推荐不对", heads, crew, m, r, len(plans)))
            best = plans[0]
            # 排第一的方案如果破不开，那所有组合都破不开
            if not best.breakable and any(p.breakable for p in laser.recommend(m, r, i, top=999)):
                problems.append(("排序不对", heads, crew, m, r))
    # 4) 通过窗口接口改配装 → 读回来一致
    for ship in SHIPS:
        for _ in range(20):
            spec = SHIPS[ship]
            pool = [spec["fixed"]] if spec.get("fixed") else [k for k, h in HEADS.items() if h["size"] == spec["size"] and not h.get("ship")]
            heads = []
            for _ in range(spec["heads"]):
                k = random.choice(pool); heads.append([k, random.choices(mods, k=random.randint(0, HEADS[k]["slots"]))])
            lo = {"heads": heads, "crew": random.randint(1, spec["crew_max"])}
            g = services.set_mining_gear(ship=ship, loadout=lo); n_loadouts += 1
            got = next(s for s in g["ships"] if s["key"] == ship)["loadout"]
            if got != lo or g["ship"] != ship or not g["chosen"]:
                problems.append(("保存读回不一致", ship, lo, got))
            if [h.key for h in laser.loadout()] != [k for k, _ in heads]:
                problems.append(("扫描没用上新配装", ship))
    assert not problems, problems[:10]
    assert n_loadouts > 5000
