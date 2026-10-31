"""解包核对：物品属性（data/item_stats.json，来自 star-citizen.wiki）和掉落索引（data/loot_index.json）里的物品，
在本机解包（DataCore 导出 JSON）里能不能找到、尺寸/耐久对不对得上（2026-10-27）。只读，打印结果。
用法：python tools/unpack_items_check.py <records 目录>"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _scan(paths):
    out = {}
    for p in paths:
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        rid = d.get("_RecordId_")
        if not rid:
            continue
        v = d.get("_RecordValue_") or {}
        size = health = None
        for c in v.get("Components") or []:
            if not c:
                continue
            t = c.get("_Type_")
            if t == "SAttachableComponentParams":
                size = ((c.get("AttachDef") or {}).get("Size"))
            elif t == "SHealthComponentParams":
                health = c.get("Health")
        out[rid.lower()] = (d.get("_RecordName_", ""), size, health)
    return out


def main(rec):
    files = [os.path.join(d, f) for d, _, fs in os.walk(os.path.join(rec, "entities")) for f in fs if f.endswith(".json")]
    idx = {}
    with ProcessPoolExecutor(30) as ex:
        for part in ex.map(_scan, [files[i::60] for i in range(60)]):
            idx.update(part)
    stats = json.loads((ROOT / "data" / "item_stats.json").read_text(encoding="utf-8"))["items"]
    miss, size_bad, hp_bad = [], [], []
    for uid, it in stats.items():
        g = idx.get(uid.lower())
        if not g:
            miss.append(it.get("n"))
            continue
        if it.get("size") is not None and g[1] is not None and it["size"] != g[1]:
            size_bad.append((it.get("n"), it["size"], g[1]))
        hp = (((it.get("s") or {}).get("durability") or {}).get("health"))
        if hp is not None and g[2] is not None and abs(hp - g[2]) > 0.5:
            hp_bad.append((it.get("n"), hp, g[2]))
    loot = json.loads((ROOT / "data" / "loot_index.json").read_text(encoding="utf-8"))["rows"]
    lmiss = [r[1] for r in loot if r[0].lower() not in idx]
    print(f"物品属性 {len(stats)} 件：解包里找不到 {len(miss)}，尺寸不同 {len(size_bad)}，耐久不同 {len(hp_bad)}")
    print("  找不到（前 10）：", miss[:10])
    print("  尺寸不同（前 10）：", size_bad[:10])
    print("  耐久不同（前 10）：", hp_bad[:10])
    print(f"掉落索引 {len(loot)} 件：解包里找不到 {len(lmiss)}（前 10）：", lmiss[:10])


if __name__ == "__main__":
    main(sys.argv[1])
