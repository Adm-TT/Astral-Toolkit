"""解包核对：导航星图（data/starmap.json，来自 starmap.space）里的星球、拉格朗日点、星团等太空坐标，
和解包的星系物件容器（<系>system.xml）算出来的位置比（2026-10-27）。只读，打印差别。
用法：python tools/unpack_starmap_check.py <oc_x 目录（解开的 socpak）> [--write]
--write：把对不上的点按解包坐标写进 data/starmap_fixes.json（导航读星图时用它改正）"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from unpack_spots import placements   # noqa: E402


def main(oc):
    oc = Path(oc)
    pos = {}
    for sysname in ("stanton", "pyro", "nyx"):
        x = next(iter(sorted(oc.glob(f"*{sysname}system*/{sysname}system.xml"))), None)
        if x:
            for ent, g, _, _ in placements(x):
                pos[(sysname, ent.lower())] = g
    if not pos:                               # 目录给错 / 解包没做：一个星系都没读到，不能拿空结果去写 starmap_fixes.json
        sys.exit(f"❌ {oc} 里一个 <星系>system.xml 都没找到（或里面没有物件），不核对、不写")
    data = json.loads((ROOT / "data" / "starmap.json").read_text(encoding="utf-8"))
    rows = [(p["sys"], (p.get("i") or p.get("n") or "").lower(), (p["x"], p["y"], p["z"]), p.get("n")) for p in data["points"]]
    rows += [(b["sys"], name.lower(), (b["x"], b["y"], b["z"]), name) for name, b in data["bodies"].items()]
    ok, far, missing, fixes = 0, [], [], {}
    for s, key, xyz, name in rows:
        g = pos.get((s.lower(), key))
        if g is None:
            missing.append(name)
            continue
        d = math.dist(g, xyz) / 1000
        if d <= 1:
            ok += 1
        else:
            far.append((name, round(d)))
            fixes[name] = [round(v, 1) for v in g]
    far.sort(key=lambda r: -r[1])
    print(f"星图 {len(rows)} 个太空点：一致（≤1 km）{ok}，不一致 {len(far)}，解包里没对上名字 {len(missing)}")
    print("  不一致（最大的 15 个，km）：", far[:15])
    print("  没对上名字（前 20）：", missing[:20])
    return fixes


if __name__ == "__main__":
    fixes = main(sys.argv[1])
    if "--write" in sys.argv:
        (ROOT / "data" / "starmap_fixes.json").write_text(json.dumps(fixes, ensure_ascii=False), encoding="utf-8")
        print(f"已写入 data/starmap_fixes.json：{len(fixes)} 个")
