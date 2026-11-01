"""游戏数据层批 3（制造 / 维科洛 / 物品属性）迁移前后的行为基线：固定查询跑一遍现有接口，结果存成 JSON，迁移后再跑一次逐字比对

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\gamedata_baseline_craft.py --out <输出.json>
  查询写死在下面：蓝图全量 dict 与编号、搜索 / 按物品 / 按编号、矿的用途和统计、蓝图说明与属性、维科洛兑换、
  打印点、物品属性、出厂配件、目标清单的材料需求。抽样的名字从数据里按固定规则挑（前后两次数据相同，挑出来的一样）。
  只读 data/，不联网、不写 userdata。
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SEARCHES = ["Powerplant", "头盔", "karna", "Helix", "主发电机", "S2", "xyz不存在", ""]
MINERALS = ["Quantainium", "Tin", "Taranite", "Iron", "Hephaestanite", "Medpen"]
WIKELO_USES = [
    ("Medpen", ""),
    ("", "医疗笔"),
    ("Wikelo Favor", ""),
    ("Vanduul Meta", ""),  # 截断名：走包含规则
    ("Irradiated Valakkar", ""),
    ("xyz不存在", ""),
]
WIKELO_SEARCH = ["头盔", "Polaris", "favor", "", "不存在的东西"]


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


def collect():
    from collections import Counter

    from sc_mining.core.paths import DATA, file_stamp
    from sc_mining.crafting import acquire, crafting, goals, itemstats, wikelo

    out = {}
    bps = crafting.blueprints()
    out["blueprints"] = bps
    keys = [crafting.bp_key(b) for b in bps]
    out["bp_key all"] = keys
    out["blueprints same objects"] = all(
        a is b for a, b in zip(bps, crafting.blueprints())
    )
    out["variant_note all"] = [crafting.variant_note(b) for b in bps]
    dups = sorted(n for n, c in Counter(b["n"] for b in bps).items() if c > 1)[:4]
    for n in dups:
        for k in (n, f"{n}#1", f"{n}#2", f"{n}#9"):
            b = crafting.by_key(k)
            out[f"by_key({k!r})"] = None if b is None else crafting.bp_key(b)
    out["by_key('不存在')"] = crafting.by_key("不存在")
    for q in SEARCHES:
        out[f"search({q!r})"] = [crafting.bp_key(b) for b in crafting.search(q)]
    out["search('a', limit=200)"] = [
        crafting.bp_key(b) for b in crafting.search("a", limit=200)
    ]
    picks = [bps[i] for i in (0, 1, 50, 300, 800, len(bps) - 1)]
    picks += [b for b in bps if b["t"] is None][:2] + [b for b in bps if b["z"] == ""][
        :2
    ]
    for b in picks:
        k = crafting.bp_key(b)
        out[f"for_item(n of {k})"] = crafting.bp_key(
            crafting.for_item(b["n"]) or {"n": ""}
        )
        out[f"for_item(zh of {k})"] = (
            None
            if crafting.for_item("", b["z"]) is None
            else crafting.bp_key(crafting.for_item("", b["z"]))
        )
        out[f"header({k})"] = crafting.header(b)
        out[f"describe({k})"] = crafting.describe(b, with_locations=False)
        out[f"stats({k}, {{}})"] = crafting.stats(b, {})
        out[f"category_zh({k})"] = crafting.category_zh(b)
    out["for_item('', '')"] = crafting.for_item("", "")
    out["for_item('xyz', 'xyz')"] = crafting.for_item("xyz", "xyz")
    for m in MINERALS:
        out[f"uses({m!r})"] = [
            (crafting.bp_key(b), q, mq) for b, q, mq in crafting.uses(m)
        ]
        out[f"mat_summary({m!r})"] = crafting.mat_summary(m)
        out[f"mat_summary({m!r}, 600)"] = crafting.mat_summary(m, 600)
        out[f"uses_report({m!r})"] = crafting.uses_report(m)
        r = crafting.browse(mat=m, limit=1000)
        out[f"browse(mat={m!r})"] = {
            **{k: v for k, v in r.items() if k != "rows"},
            "rows": [crafting.bp_key(b) for b in r["rows"]],
        }
    r = crafting.browse(limit=2000)
    out["browse()"] = {
        **{k: v for k, v in r.items() if k != "rows"},
        "rows": [crafting.bp_key(b) for b in r["rows"]],
    }
    out["quality_hints"] = crafting.quality_hints(
        [("Quantainium", 30, 650), ("Tin", 20, 910), ("Iron", 10, 300)]
    )

    cs = wikelo.load()
    out["wikelo.load()"] = cs
    for en, zh in WIKELO_USES:
        out[f"wikelo.uses({en!r}, {zh!r})"] = [
            (c["id"], q, u) for c, q, u in wikelo.uses(en, zh)
        ]
        out[f"wikelo.uses_text({en!r}, {zh!r})"] = wikelo.uses_text(en, zh)
    for q in WIKELO_SEARCH:
        out[f"wikelo.search({q!r})"] = [c["id"] for c in wikelo.search(q)]
    for c in cs[:5]:
        out[f"wikelo.describe({c['id']})"] = wikelo.describe(c)
    req_names = sorted({r["n"] for c in cs for r in c["req"]})
    out["wikelo.source_note(all req)"] = {n: wikelo.source_note(n) for n in req_names}
    ps = json.loads((DATA / "print_spots.json").read_text(encoding="utf-8"))["items"]
    for n in sorted(ps):
        out[f"print_spots({n!r})"] = wikelo.print_spots(n)
        out[f"print_spots({n.upper()!r})"] = wikelo.print_spots(n.upper())
        out[f"print_spots(' '+{n!r}+' ')"] = wikelo.print_spots(f" {n} ")
    out["print_spots('不存在')"] = wikelo.print_spots("不存在")
    out["print_spots(None)"] = wikelo.print_spots(None)

    st = json.loads((DATA / "item_stats.json").read_text(encoding="utf-8"))["items"]
    uuids = [
        bps[0]["u"],
        bps[300]["u"],
        sorted(st)[0],
        sorted(st)[-1],
        "",
        None,
        "不存在",
    ]
    for u in uuids:
        out[f"itemstats.item({u!r})"] = itemstats.item(u)
        out[f"itemstats.tags({u!r})"] = itemstats.tags(u)
        out[f"itemstats.base_value({u!r}, health)"] = itemstats.base_value(
            u, "health_maxhealth"
        )
    out["itemstats.version()"] = itemstats.version()
    out["itemstats base_value all props first 40"] = [
        (u, k, itemstats.base_value(u, k))
        for u in sorted(st)[:40]
        for k in itemstats.PROPS
    ]

    si = json.loads((DATA / "ship_items.json").read_text(encoding="utf-8"))["items"]
    names = sorted(si)
    for n in names[:5] + names[-3:]:
        out[f"ships_with({n!r})"] = acquire.ships_with(n)
        out[f"ships_with(upper {n!r})"] = acquire.ships_with(n.upper())
    out["ships_with('不存在')"] = acquire.ships_with("不存在")
    out["ships_with(None)"] = acquire.ships_with(None)

    for c in cs[:3]:
        out[f"goals.requirements(wikelo {c['id']})"] = goals.requirements(
            {"kind": "wikelo", "ref": c["id"], "times": 2}
        )
    for k in keys[:2] + [k for k in keys if "#2" in k][:2]:
        out[f"goals.requirements(craft {k})"] = goals.requirements(
            {"kind": "craft", "ref": k, "times": 3}
        )
    stamps = {p.name: file_stamp(p) for p in sorted(DATA.glob("*.json"))}
    return {"git": _git_head(), "data_stamps": stamps, "results": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description="游戏数据层批 3 的行为基线")
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
