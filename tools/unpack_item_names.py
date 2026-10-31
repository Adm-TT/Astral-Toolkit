"""解包：汉化包里只写了中文名的物品（勋章、计算板、钥匙卡、摆件…）→ 从游戏英文文本补英文名（2026-10-27）。
老大 F8 反馈：这些东西说明框只有中文名，AT 只靠「中文\\n英文」的对照表找，全都查不到、还会把说明文字当名字。

用法：.venv\\Scripts\\python.exe -X utf8 tools\\unpack_item_names.py
读：E:\\Game3\\unpack\\p4k_out\\Data\\Localization\\english\\global.ini（unpack_all 解出来的游戏英文文本）+ data\\loc\\global_zh.ini（汉化包）
写：data\\zh_only_names.json  {中文名: 英文名}（随数据包发给玩家；trade/names.table() 合进对照表）。只发名字，不发游戏原文件。
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sc_mining.update.localization import read_ini  # noqa: E402

EN_INI = pathlib.Path(r"E:\Game3\unpack\p4k_out\Data\Localization\english\global.ini")
ZH_INI = ROOT / "data" / "loc" / "global_zh.ini"
OUT = ROOT / "data" / "zh_only_names.json"
CJK = "\u4e00-\u9fff"
# item_name_*：一般物品；item_Mining_*：采矿模组 / 激光器 / 小工具 / 耗材（2026-10-28 老大 F8 反馈：FLTR-XL 模组查不到——
# 汉化包里它只有中文名「FLTR-XL 模组」，第二行是「[-24%废料|-5%提取功率]」属性）
KEY = re.compile(r"^item_(?:name_?|mining_)(?P<cls>.+?)$", re.I)


def known_items():
    """商店、掉落、wiki 物品表里真有的英文名（折叠过的）：「无→None」「红色→Red」「导弹→MISSILES」这种界面词不收（独立审查 2026-10-27）"""
    from sc_mining.trade.names import _known_names, _fold_en
    out = set(_known_names())
    try:
        from sc_mining.crafting.itemsearch import wiki_items
        out |= {_fold_en(w["n"]) for w in wiki_items() if w.get("n")}
    except Exception:
        pass
    return out


def build(en_ini, zh_ini, known=None):
    en = {k.lower(): v for k, v in en_ini.items()}
    out, skipped = {}, 0
    from sc_mining.trade.names import _fold_en
    known = known_items() if known is None else known
    for k, v in zh_ini.items():
        kl = k.lower()
        m = KEY.match(kl)
        if not m or kl.endswith(("_short", "_shop")) or "desc" in kl:
            continue
        v = re.sub(r"<[^>]+>", "", v).strip()
        attr = "\\n[" in v                                # 「名字\n[属性|属性]」（采矿模组 / 激光器）：属性行不是名字
        if attr:
            v = v.split("\\n[")[0].strip()
        if "\\n" in v or not re.search(f"[{CJK}]", v) or re.search(r"[A-Za-z]{3,}\s*$", v) and re.search(f"[{CJK}].*[A-Za-z]{{3,}}", v) \
                or attr and re.search(f"[{CJK}].*[A-Za-z]{{3,}}", v):
            continue                       # 已经带英文（「中文\nEnglish」「中文English」「里格-C3 模组Rieger-C3」）：原来的对照表管
        e = re.sub(r"<[^>]+>", "", en.get(kl, "")).split("\\n")[0].strip()
        if not e or re.search(f"[{CJK}]", e) or e.startswith("@") or len(e) < 2 or len(e) > 80:
            skipped += 1
            continue
        zh = v.strip(' "“”')
        if len(zh) > 40 or zh.startswith("[") or "@" in zh or "@" in e or len(re.sub(r"\s+", "", zh)) < 3:
            continue
        if _fold_en(e) not in known:
            skipped += 1
            continue
        out.setdefault(zh, e)
    return out, skipped


def main():
    if not EN_INI.exists():
        raise SystemExit(f"没有游戏英文文本：{EN_INI}（先跑 tools\\unpack_all.py）")
    out, skipped = build(read_ini(EN_INI), read_ini(ZH_INI))
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"只有中文名的物品：补上英文名 {len(out)} 条，跳过 {skipped} 条（英文文本里没有 / 商店掉落都没有这个物品）→ {OUT}")


if __name__ == "__main__":
    main()
