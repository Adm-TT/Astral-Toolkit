"""解包核对：飞船截面（CS）→ 对照 data/ship_signatures.json（2026-10-27）。
截面 = 飞船记录里的 crossSection（三个方向）× 出厂装甲的截面系数（SCItemVehicleArmorParams.signalCrossSection），从小到大排。
红外、电磁上限要按部件和用电模型算，暂时沿用原数据（erkul）。
用法：python tools/unpack_ships.py <records 目录> [--write]   不带 --write 只打印差别"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def armor_index(rec):
    """装甲类名（小写）→ 截面系数"""
    out = {}
    for f in (rec / "entities/scitem/ships/armor").rglob("*.json"):
        d = _load(f)
        if not d:
            continue
        for c in d["_RecordValue_"].get("Components") or []:
            if c and c.get("_Type_") == "SCItemVehicleArmorParams":
                m = c.get("signalCrossSection")
                if isinstance(m, (int, float)):
                    out[d["_RecordName_"].split(".", 1)[-1].lower()] = float(m)
    return out


def ship_cs(rec):
    arm = armor_index(rec)
    out = {}
    for f in (rec / "entities/spaceships").glob("*.json"):
        d = _load(f)
        if not d:
            continue
        comps = [c for c in d["_RecordValue_"].get("Components") or [] if c]
        sig = next((c for c in comps if c.get("_Type_") == "SSCSignatureSystemParams"), None)
        cs = ((((sig or {}).get("radarProperties") or {}).get("crossSectionParams") or {}).get("crossSection")) or None
        if not cs:
            continue
        mult = 1.0
        lo = next((c for c in comps if c.get("_Type_") == "SEntityComponentDefaultLoadoutParams"), None)
        for e in (((lo or {}).get("loadout") or {}).get("entries") or []):
            name = (e.get("entityClassName") or "").lower()
            if not name:                                    # 新格式：直接引用装甲记录文件
                m = re.search(r"/([^/]+)\.json$", str(e.get("entityClassReference") or ""))
                name = m.group(1).lower() if m else ""
            if name in arm:
                mult = arm[name]
                break
        out[f.stem.lower()] = sorted(round(cs[k] * mult) for k in ("x", "y", "z"))
    return out


def main(rec, write=False):
    rec = Path(rec)
    game = ship_cs(rec)
    p = ROOT / "data" / "ship_signatures.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    diff, missing = [], []
    for s in data["ships"]:
        g = game.get(s["id"].lower())
        if not g:
            missing.append(s["id"])
            continue
        if any(abs(a - b) > max(2, 0.01 * b) for a, b in zip(g, s["cs"])):
            diff.append((s["id"], s["cs"], g))
        if write:
            s["cs"] = g
    print(f"解包 {len(game)} 条飞船记录；AT 表 {len(data['ships'])} 条：截面不一样 {len(diff)}，解包里找不到 {len(missing)}")
    for x in diff[:40]:
        print("  ", x)
    if missing:
        print("  找不到：", missing[:20])
    if write and diff:
        data["note"] = data["note"] + "；cs 2026-10-27 起按解包（crossSection × 出厂装甲截面系数）"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print("已写入", p)
    return diff, missing


if __name__ == "__main__":
    main(sys.argv[1], "--write" in sys.argv)
