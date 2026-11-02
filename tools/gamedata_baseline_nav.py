"""游戏数据层批 2（导航）迁移前后的行为基线：一组固定查询跑一遍导航接口，结果存成 JSON；迁移后再跑一次逐字比对

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\gamedata_baseline_nav.py --out <输出.json>
  查询写死在 collect() 里：星图整份、按内部名 / 名字找点、地点代码转中文、地名对照、城市地点、空间站电梯、
  城外设施、挖矿点、太空站、搜索、最近的医院 / 空港 / 买船。时间写死，结果不随时钟变。
  只读 data/ 和汉化包，不联网；会读 userdata 的自转校准（迁移前后同一份，不影响比对），不写 userdata。
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WHEN = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
CODES = [
    "Stanton4_NewBabbage",
    "Stanton1_Lorville",
    "Stanton3_Area18",
    "Stanton2_Orison",
    "RR_ARC_L1",
    "RR_HUR_L2",
    "RR_CRU_L5",
    "RR_MIC_L1",
    "RR_P1_L1",
    "RR_P2_L4",
    "RR_P3",
    "RR_P6",
    "RR_P5_L2",
    "RR_JP_StantonPyro",
    "RR_JP_PyroNyx",
    "Delamar_Levski",
    "Stanton1_SomeNewPlace",
    "Pyro5d",
    "Stanton2b",
    "Nyx3",
]
DISPLAY = [
    "RR P2 L4 CLINIC(LZ:R P24)",
    "Stanton4 NewBabbage (LZ: Stanton4 NewBabbage)",
    "Pyro5d",
    "AsteroidCluster_MiningBase_Nyx_Glaciem_01",
    "Somewhere (LZ: Stanton1 Lorville)",
]
NAMES = ["PyroIII", "Pyro I", "pyrovi", "Delamar", "Stanton-Pyro Jump Point", "XYZ"]
SEARCHES = [
    "Lorville",
    "戴玛尔 洞穴",
    "Kudre",
    "残骸 耶拉",
    "贝沙电气石",
    "医院",
    "电梯",
    "rr_hur_l1",
    "挖矿点 派罗",
    "xyz不存在",
]
KINDS = ["医院", "空港", "买船"]
G_HERE = (
    -18_962_176_000.0,
    -2_664_959_000.0,
    0.0,
)  # 赫斯顿附近的星系坐标（米），只当固定参考点


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


def _pt(p):
    return (
        None
        if p is None
        else {k: p.get(k) for k in ("n", "i", "sys", "t", "x", "y", "z")}
    )


def collect():
    from sc_mining.core.paths import DATA, file_stamp
    from sc_mining.navigation import names, navigate, position, starmap, transit

    out = {}
    data = starmap.load()
    out["starmap.load()"] = data
    pts = data.get("points") or []
    out["find_point(internal=每个点的 i)"] = [
        _pt(position.find_point(internal=p["i"])) for p in pts if p.get("i")
    ]
    out["find_point(internal=每个点的 i 大写)"] = [
        _pt(position.find_point(internal=p["i"].upper())) for p in pts if p.get("i")
    ]
    out["find_point(name=每个点的 n)"] = [
        _pt(position.find_point(name=p["n"])) for p in pts if p.get("n")
    ]
    for q in NAMES:
        out[f"find_point(name={q!r})"] = _pt(position.find_point(name=q))
    for c in CODES:
        out[f"from_code({c!r})"] = _pt(position.from_code(c))
        out[f"place_name({c!r})"] = position.place_name(c)
        out[f"ini_name({c!r})"] = position.ini_name(c)
    for t in DISPLAY:
        out[f"display_label({t!r})"] = position.display_label(t)
    out["poi_zh(每个 poi)"] = {q["n"]: names.poi_zh(q["n"]) for q in data["pois"]}
    out["label(每个 point)"] = [names.label(p) for p in pts]
    out["label(前 300 个 poi)"] = [names.label(q) for q in data["pois"][:300]]
    out["city_places()"] = transit.city_places()
    out["station_lifts()"] = transit.station_lifts()
    for k in KINDS:
        out[f"amenity_targets({k!r})"] = transit.amenity_targets(k)
    for k in transit.SITE_KINDS:
        out[f"city_targets({k!r})"] = [q["id"] for q in transit.city_targets(k)]
    out["mining_spots()"] = navigate.mining_spots()
    out["space_points()"] = navigate.space_points()
    for q in SEARCHES:
        rows, n = navigate.search(q, limit=30)
        out[f"search({q!r})"] = [n, [(p["n"], p["b"], p["t"]) for p in rows]]
    for k in KINDS:
        out[f"nearest({k!r})"] = [
            (d, q.get("id") or q["n"], q.get("b")) for d, q in transit.nearest(k)
        ]
        out[f"nearest({k!r}, g, Stanton, when)"] = [
            (d, q.get("id") or q["n"], q.get("b"))
            for d, q in transit.nearest(k, G_HERE, "Stanton", WHEN)
        ]
    out["site_nearest('Lorville', '医院')"] = [
        (d, q["id"]) for d, q in transit.site_nearest("Lorville", "医院")
    ]
    out["_metro_lines('NewBabbage')"] = {
        ln: sorted(st) for ln, st in transit._metro_lines("NewBabbage").items()
    }
    stamps = {p.name: file_stamp(p) for p in sorted(DATA.glob("*.json"))}
    return {"git": _git_head(), "data_stamps": stamps, "results": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description="游戏数据层批 2（导航）迁移前后的行为基线")
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
