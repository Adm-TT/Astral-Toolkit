"""游戏数据层批 5（采矿）迁移前后的行为基线：一组固定查询跑一遍采矿接口，结果存成 JSON；迁移后再跑一次逐字比对

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\gamedata_baseline_mining.py --out <输出.json>
  查询写死在 collect() 里：产矿区判断、挖矿点的石头、石头表、一团几块、石头里的矿、飞船信号、矿价和精炼站加成。
  全程断网（UEX 和 core.net.read 换成抛 OSError）；不写 userdata；库过时会在 data/gamedata 下重建一次。
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NYX_POINTS = [
    (-4634409388.2, -47775658122.7, -42640.1),  # 基格带实测
    (15.0e9, 0.0, 1e6),  # 冰川环带
    (30e9, 0.0, 0.0),  # 空旷
]
TEXTS = [
    "keeger",
    "glaciem",
    "akiro",
    "AsteroidCluster_Pyro_FSN704",
    "ab_mine_pyro_01",
    "miningbase_pyro_02",
]
BAGS = [{"Quantainium": 10}, {"Gold": 5, "Copper": 20}, {"Bexalite": 3, "Iron": 40}]
ORES = ["Quantainium", "Gold", "Bexalite", "Iron", "Copper"]
CS_EXTRA = [(5000, 20000, None), (5000, None, 20000), (20000, 1, 1), (0, None, None)]


def _git_head():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return ""


def _offline():
    from astral_toolkit.core import net
    from astral_toolkit.navigation import starmap
    from astral_toolkit.update import uex

    def no_net(*a, **k):
        raise OSError("基线工具不联网")

    uex._get = no_net
    net.read = no_net
    starmap.read = no_net  # starmap 是 from ..core.net import read 按名字引的，只改 net.read 拦不住（收口 2）


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _area_all(out, spots, points):
    from astral_toolkit.mining import mining_area as M

    for g in NYX_POINTS:
        out[f"area({g}, Nyx)"] = M.area(g, "Nyx")
    for t in TEXTS:
        for sys_ in ("Nyx", "Pyro"):
            out[f"area(location={t!r}, {sys_})"] = M.area(
                (1.0, 2.0, 3.0), sys_, location=t
            )
    for body in ("Fairo", "Pyro4", "Delamar"):
        for sys_ in ("Pyro", "Nyx"):
            out[f"area(ground {body}, {sys_})"] = M.area(
                (0.0, 0.0, 0.0), sys_, body=body, ground=True
            )
    pyro = [s for s in spots if s.get("sys") == "Pyro"]
    out["area(每个派罗挖矿点及偏移)"] = [
        [M.area((s["x"] + d, s["y"], s["z"]), "Pyro") for d in (0.0, 1e6, 3e7)]
        for s in pyro
    ]
    lpts = [p for p in points if p.get("t") == "Lagrange Point"]
    out["area(每个派罗拉格朗日点 + 1e6)"] = [
        M.area((p["x"] + 1e6, p["y"], p["z"]), "Pyro")
        for p in lpts
        if p.get("sys") == "Pyro"
    ]
    out["area(每个派罗星团点)"] = [
        M.area((p["x"], p["y"], p["z"]), "Pyro")
        for p in points
        if p.get("sys") == "Pyro" and p.get("t") == "AsteroidBelt"
    ]
    out["area(每个斯坦顿拉格朗日点 + 1e6)"] = [
        M.area((p["x"] + 1e6, p["y"], p["z"]), "Stanton")
        for p in lpts
        if p.get("sys") == "Stanton"
    ]
    return lpts


def collect():
    _offline()
    from astral_toolkit.core.paths import DATA, file_stamp
    from astral_toolkit.mining import data, locations, mining_area as M
    from astral_toolkit.mining import parse, refinery, shipsig, signals
    from astral_toolkit.navigation import navigate

    out = {}
    spots = _json(DATA / "mining_spots.json")
    star = navigate.load()
    points = star.get("points") or []
    lpts = _area_all(out, spots, points)
    bodies = star.get("bodies") or {}
    term = bodies.get("Terminus") or bodies.get("Pyro6")
    if term:
        out["area(Terminus 附近 1e9)"] = M.area(
            (term["x"] + 1e9, term["y"], term["z"]), "Pyro"
        )
    yela = bodies.get("Yela")
    if yela:
        for d in (4e8, 6e8, 9e8):
            out[f"area(Yela + {d})"] = M.area(
                (yela["x"] + d, yela["y"], yela["z"]), "Stanton"
            )
    out["area(亚伦光环)"] = M.area((20.3e9, 0.0, 0.0), "Stanton")
    out["area(斯坦顿空旷)"] = M.area((1e11, 1e11, 0.0), "Stanton")

    out["area_for_spot(每个挖矿点)"] = [
        M.area_for_spot(s, (s["x"], s["y"], s["z"])) for s in spots
    ]
    out["area_for_spot(每个拉格朗日点)"] = [
        M.area_for_spot(
            {"lagrange": p.get("i") or p["n"], "sys": p["sys"]},
            (p["x"], p["y"], p["z"]),
        )
        for p in lpts
    ]
    t = M.rocks_table()
    out["rocks_table 键"] = sorted(t)
    for k in ("tiers", "ores", "areas", "contains"):
        out[f"rocks_table[{k}]"] = json.dumps(t.get(k) or {}, sort_keys=True)
    out["cluster_weight"] = {
        m: [signals.cluster_weight(m, n) for n in range(1, 8)]
        for m in (t.get("ores") or {})
    }
    out["_rock_contains"] = {
        r: parse._rock_contains(r) for r in [*(t.get("contains") or {}), "不存在的石头"]
    }

    ships = shipsig.ships()
    out["ships"] = ships
    for s in ships:
        for a in s["cs"]:
            for f in (1.0, 0.88, 1.12):
                c = a * f
                key = f"{s.get('id')}|{a}|{f}"
                out[f"match({key})"] = shipsig.match(c)
                out[f"describe({key})"] = shipsig.describe(c)
    for cs, em, ir in CS_EXTRA:
        out[f"match({cs}, {em}, {ir})"] = shipsig.match(cs, em, ir)
        out[f"describe({cs}, {em}, {ir})"] = shipsig.describe(cs, em, ir)

    out["CITY_PRICES"] = data.CITY_PRICES
    out["REFINERIES"] = data.REFINERIES
    out["best_price"] = {m: data.best_price(m) for m in data.CITY_PRICES}
    for i, bag in enumerate(BAGS):
        out[f"best_stations(bag{i})"] = refinery.best_stations(bag)
    for m in ORES:
        out[f"locations.report({m})"] = locations.report(m)
    out["navigate.mining_spots()"] = [
        (p["n"], p.get("rocks")) for p in navigate.mining_spots()
    ]
    stamps = {p.name: file_stamp(p) for p in sorted(DATA.glob("*.json"))}
    return {"git": _git_head(), "data_stamps": stamps, "results": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description="游戏数据层批 5（采矿）迁移前后的行为基线")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    a = ap.parse_args(argv)
    res = collect()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(
        json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(f"基线写到 {a.out}：{len(res['results'])} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
