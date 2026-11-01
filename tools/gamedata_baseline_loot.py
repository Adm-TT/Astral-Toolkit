"""掉落查询迁移（游戏数据层批 4）前后的行为基线：一组固定查询跑一遍 crafting/loot.py，结果存成 JSON；迁移后再跑一次逐字比对

用法（在项目根目录）：.venv\\Scripts\\python.exe -X utf8 tools\\gamedata_baseline_loot.py --out <输出.json>
  全程断网（loot._get、core.net.read 一律抛 OSError），明细只从本机 loot_details.zip / data/loot/ 缓存读；
  前后两次必须用同一份 data/（含 loot/、loot_details.zip）。不写 userdata。
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# (name_en, name_zh)
FIND = [
    ("MedPen (Hemozal)", ""),
    ("", "医疗笔（血红扎）"),
    ("Medpen", ""),
    ("Citadel Core Base", ""),  # 同名多实体，wiki 类名带 alt（_ai_exclusive）
    ("", "要塞 胸甲 基础"),
    ("Citadel Arms Base", ""),
    ("FSK-8 Combat Knife", ""),  # 同名多实体：_gungame
    ('FSK-8 "Bloodline" Combat Knife', ""),
    ("Karna Rifle", ""),
    ("Omarof (16x Telescopic)", ""),
    ("EXO-8 Helmet (Used)", ""),
    ("Citade", ""),  # 英文 6 字符前缀
    ("itadel", ""),  # 英文 ≥5 子串
    ("Citad", ""),  # 5 字符：只够子串
    ("", "战术匕首"),  # 中文 ≥3 子串
    ("", "血色"),  # 中文 2 字符：不够部分匹配
    ("ATLS GEO Module", ""),  # wiki 里有、掉落里没有
    ("Cave", ""),
    ("Parallax", ""),
    ("AdrenaPen (Demexatrine)", ""),
    ("Janalite", ""),
    ("", ""),
    ("%", ""),
    ("_", ""),
    ("a_b%c", "百分号%"),
    ("xyz不存在", "不存在的东西"),
]
INSTANCE = [
    ("Carinite", ""),
    ("", "科力晶"),
    ("Carinite (Pure)", ""),
    ("", "纯科力晶"),
    ("Janalite", ""),
    ("", "加纳石"),
    ("Jaclium (Ore)", ""),
    ("", "杰金"),
    ("Saldynium", ""),
    ("", "烁迪银矿石"),
]
SHIP = [
    ("Quantanium", ""),
    ("Pressurized Ice", ""),
    ("", "量子矿"),
    ("Quartz (Raw)", ""),
]
DETAILS = 20


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
    from sc_mining.core import net
    from sc_mining.crafting import loot

    def no_net(*a, **kw):
        raise OSError("基线：断网")

    loot._get = no_net
    net.read = no_net


def _safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001 —— 基线要把异常也记下来
        return {"raised": f"{type(e).__name__}: {e}"}


def collect():
    import zipfile

    from sc_mining.core.paths import DATA, file_stamp
    from sc_mining.crafting import loot

    _offline()
    out = {}
    for en, zh in FIND:
        out[f"find({en!r}, {zh!r})"] = _safe(loot.find, en, zh)
    for en, zh in FIND + INSTANCE + SHIP:
        out[f"info({en!r}, {zh!r}, online=False)"] = _safe(
            loot.info, en, zh, online=False
        )
        out[f"text({en!r}, {zh!r})"] = _safe(loot.text, en, zh)
    for key in loot.INSTANCE_ORES:
        out[f"mine_info({key!r}, online=False)"] = _safe(
            loot.mine_info, key, online=False
        )
    for en, zh in FIND + INSTANCE + SHIP:
        out[f"instance_ore({en!r}, {zh!r})"] = _safe(loot.instance_ore, en, zh)
        out[f"ship_mineral({en!r}, {zh!r})"] = _safe(loot.ship_mineral, en, zh)
    try:
        with zipfile.ZipFile(loot.DETAILS) as z:
            uuids = sorted(n[:-5] for n in z.namelist() if n.endswith(".json"))[
                :DETAILS
            ]
    except Exception:
        uuids = []
    for u in uuids:
        try:
            out[f"summary(detail({u!r}))"] = loot.summary(loot.detail(u, online=False))
        except loot.Pending:
            out[f"summary(detail({u!r}))"] = "pending"
        except Exception as e:  # noqa: BLE001
            out[f"summary(detail({u!r}))"] = {"raised": f"{type(e).__name__}: {e}"}
    # detail() 用的版本：迁移前取自 load_index，迁移后取自库里的 loot_index_meta；两边都记（只在 meta 段，不进 results）
    meta = {
        "load_index_version": (loot.load_index(False) or {}).get("version"),
        "details_version": loot.details_version(),
    }
    try:
        from sc_mining import gamedata

        topic = getattr(gamedata, "loot", None)
        if topic is not None:
            meta["index_meta"] = topic.index_meta()
    except Exception as e:  # noqa: BLE001
        meta["index_meta"] = f"{type(e).__name__}: {e}"
    stamps = {p.name: file_stamp(p) for p in sorted(DATA.glob("*.json"))}
    stamps["loot_details.zip"] = file_stamp(loot.DETAILS)
    return {"git": _git_head(), "data_stamps": stamps, "meta": meta, "results": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description="掉落查询迁移前后的行为基线")
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
