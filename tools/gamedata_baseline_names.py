"""名字对照（trade/names、trade/gamekey、core/i18n 护栏）迁移前后的行为基线：固定查询跑一遍现有接口，存成 JSON 逐字比对

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\gamedata_baseline_names.py --out <输出.json>
  查询列表写死在下面；旧写法、涂装名运行时从 data/ 里的源文件取第一条。
  只读 data/，不联网、不写 userdata。输出格式同 tools/gamedata_baseline.py（_git_head 从它 import）。
迁移专用：批 6 合并、真实数据 before / after 比对通过后，由游戏数据层收口批次删掉（或并进 gamedata_baseline.py）。
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gamedata_baseline import _git_head  # noqa: E402

TABLE_KEYS = ["视差步枪", "医疗笔", "荣誉勋章", "锡", "铁"]
TO_ENGLISH = [
    "视差步枪",
    "科力晶（单个矿块）",
    "医疗",
    "头盔",
    "步枪",
    "铁",
    "荣誉",
    "abc",
]
CANONICAL = [
    ("冷冻舱（刻度）", ""),
    ("", "Hofstede-S2 Mining Laser"),
    ("塔兰导电石Taranite", ""),
    ("峰期", ""),
]
ZH_FOR = ["Medpen", "Quantanium"]
SUGGEST = ["医疗", "lawson"]
GAMEKEY = ["Medpen", "Lawson Mining Laser", "zzz"]


def collect():
    from sc_mining.core import i18n
    from sc_mining.core.paths import DATA, cached_json, file_stamp
    from sc_mining.trade import gamekey, names

    out = {}
    table = names.table()
    pairs = list(table.items())
    out["names.table() len"] = len(pairs)
    out["names.table() sha256"] = hashlib.sha256(
        json.dumps(pairs, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    out["names.table() first30"] = pairs[:30]
    out["names.table() last30"] = pairs[-30:]
    for k in TABLE_KEYS:
        out[f"names.table()[{k!r}]"] = table.get(k)
    for q in TO_ENGLISH:
        out[f"names.to_english({q!r})"] = names.to_english(q)
    out["names.to_english('步枪', limit=2)"] = names.to_english("步枪", limit=2)
    for zh, en in CANONICAL:
        out[f"names.canonical({zh!r}, {en!r})"] = names.canonical(zh, en)
    for en in ZH_FOR:
        out[f"names.zh_for({en!r})"] = names.zh_for(en)
    for q in SUGGEST:
        out[f"names.suggest({q!r})"] = names.suggest(q)

    queries = list(GAMEKEY)
    aliases = cached_json(DATA / "name_aliases.json", default={}) or {}
    if aliases:
        queries.append(next(iter(aliases)))  # 旧写法：文件第一条
    wiki = (cached_json(DATA / "wiki_items.json", default={}) or {}).get("items") or []
    paint = next((w.get("n") for w in wiki if w.get("t") == "Paints"), None)
    if paint:
        queries.append(paint)  # 只在 wiki 里的涂装
    for q in queries:
        out[f"gamekey.resolve({q!r})"] = gamekey.resolve(q)

    out["i18n.mineral_en('桂石原矿')"] = i18n.mineral_en("桂石原矿")
    out["i18n.mineral_zh('Quantanium')"] = i18n.mineral_zh("Quantanium")
    out["i18n.station_zh('MIC-L5')"] = i18n.station_zh("MIC-L5")
    out["i18n.gear_label('Hofstede-S2')"] = i18n.gear_label("Hofstede-S2")
    out["i18n.shop_cat_zh('Arms')"] = i18n.shop_cat_zh("Arms")
    stamps = {p.name: file_stamp(p) for p in sorted(DATA.glob("*.json"))}
    return {"git": _git_head(), "data_stamps": stamps, "results": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description="名字对照迁移前后的行为基线")
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
