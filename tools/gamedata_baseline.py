"""游戏数据层迁移前的行为基线：把一组固定查询跑一遍现有接口，结果存成 JSON；迁移后再跑一次逐字比对

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\gamedata_baseline.py --out <输出.json>
  查询列表写死在 QUERIES 里：物品搜索、商店买卖点、最近买点、掉落查找、中英对照表抽样、游戏类名解析。
  只读 data/ 里的 JSON，不联网、不写 userdata。
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEARCHES = [
    "视差步枪",
    "parallax",
    "Medpen",
    "头盔",
    "劳森",
    "P4-AR",
    "Hurston",
    "xyz不存在",
]
LOOKUPS = ["Lawson Mining Laser", "medpen"]
LOOT_NAMES = ["Medpen", "AdrenaPen (Demexatrine)", "Parallax"]
GAMEKEY_NAMES = ["Medpen", "Lawson Mining Laser"]
SHOP_ITEMS = 20  # shops.load()["items"] 按 id 排序取前几个
NEAREST_ITEMS = 5


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


def _new_babbage_point(data):
    """用商店数据里第一家新巴贝奇商店的位置当“我在这”，不依赖导航模块的常量"""
    from astral_toolkit.crafting import shops

    for r in data["rows"]:
        if len(r) > 6 and r[6] and r[6][5] == "New Babbage":
            return shops.shop_point(r[6])
    return None


def collect():
    from astral_toolkit.core.paths import DATA, file_stamp
    from astral_toolkit.crafting import itemsearch, loot, shops
    from astral_toolkit.trade import gamekey, names

    out = {}
    for q in SEARCHES:
        out[f"itemsearch.find({q!r}, limit=30)"] = itemsearch.find(q, limit=30)
    for q in LOOKUPS:
        e = itemsearch.lookup(q)
        out[f"itemsearch.lookup({q!r})"] = (
            None
            if e is None
            else {k: (sorted(v) if isinstance(v, set) else v) for k, v in e.items()}
        )
    data = shops.load(auto_update=False)
    ids = sorted(int(i) for i in (data.get("items") or {}))
    for iid in ids[:SHOP_ITEMS]:
        out[f"shops.where({iid})"] = shops.where(iid)
    here = _new_babbage_point(data)
    out["here"] = here
    for iid in ids[:NEAREST_ITEMS]:
        out[f"shops.nearest({iid}, here, n=3)"] = shops.nearest(iid, here, n=3)
    for q in LOOT_NAMES:
        out[f"loot.find(name_en={q!r})"] = loot.find(name_en=q)
    table = names.table()
    out["names.table() len"] = len(table)
    out["names.table() first50"] = sorted(table.items())[:50]
    for q in GAMEKEY_NAMES:
        out[f"gamekey.resolve({q!r})"] = gamekey.resolve(q)
    stamps = {p.name: file_stamp(p) for p in sorted(DATA.glob("*.json"))}
    return {"git": _git_head(), "data_stamps": stamps, "results": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description="游戏数据层迁移前的行为基线")
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
