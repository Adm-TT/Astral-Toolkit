"""中英对照：读屏识别到的中文名 → 英文名（计算核心统一用英文）

对照表来自 sc_glossary.json（由 sc_glossary/build_glossary.py 从汉化包生成）
"""

import json
from difflib import get_close_matches  # noqa: F401
from functools import lru_cache
from pathlib import Path

GLOSSARY = Path(__file__).resolve().parent.parent / "sc_glossary.json"

# 实测的 HUD 小字形近误认（OCR 结果 → 正确字），来自 2K 截图实测
CONFUSABLE = {
    **dict.fromkeys("速感康联颜医肤展胰碳硬喷唇源", "原"),
    "护": "矿",
    "桂": "柱",
    "于": "子",
    "特": "物",
    **dict.fromkeys("恒植提姐超加", "量"),
    # 金字旁的矿名字很小（勘探者面板约 10px），右半边常认错：铜 → 钥/销/确/網/相/明，锡 → 锯/继（2026-10-23 实测）
    **dict.fromkeys("钥销确確網网相明钢铡", "铜"),
    **dict.fromkeys("锯继锦锄", "锡"),
    # 雪地上的白字对比度低：钨 → 韩，砬 → 位/脑/敬（2026-10-23 Wala 地面实测）
    "韩": "钨",
    **dict.fromkeys("位脑敬", "砬"),
}


@lru_cache
def _tables(ship_only: bool):
    data = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    zh2en, en2zh = {}, {}
    for m in data["minerals"]:
        en2zh[m["en"]] = m["zh"]
        if ship_only and m["category"] != "ship" and m["en"] != "Inert Materials":
            continue
        for key in ("zh", "zh_refined", "zh_raw"):
            if m[key]:
                zh2en[m[key]] = m["en"]
    return zh2en, en2zh


def mineral_en(
    zh: str, fuzzy: bool = True, ship_only: bool = True, prefer: str | None = None
):
    """中文矿名 → 英文。OCR 错一两个字时用模糊匹配兜底；认不出返回 None。
    ship_only：只在船挖矿物里找（避免"桂石原矿"被配成手挖的"钻石原矿"）"""
    zh2en, _ = _tables(ship_only)
    zh = zh.strip().replace(" ", "")
    if not zh or zh in ("矿石", "原矿", "矿", "石"):  # 只剩后缀、矿名本身没认出来：不猜
        return None
    if zh in zh2en:
        return zh2en[zh]
    if fuzzy and len(zh) >= 2:
        zh = "".join(CONFUSABLE.get(c, c) for c in zh)
        if zh in zh2en:
            return zh2en[zh]
        best, best_sc, pref_sc = None, 0.0, 0.0
        for cand in zh2en:
            sc = _similarity(zh, cand)
            if prefer and zh2en[cand] == prefer:
                pref_sc = max(pref_sc, sc)
            if sc > best_sc:
                best, best_sc = cand, sc
        if prefer and pref_sc >= 0.45 and pref_sc >= best_sc - 0.03:
            return prefer  # 几个矿名一样像（都是「x石原矿」）：按石头本身的矿算
        if best_sc >= 0.45:
            return zh2en[best]
    return None


def _similarity(a: str, b: str) -> float:
    """OCR 容错相似度：整体相似度 + 同位置相同字符 + 长度一致 + 结尾一致
    HUD 字很小，常把形近字认错（柱→桂、子→于、物→特），但字数和"原矿/矿石"结尾通常是对的"""
    from difflib import SequenceMatcher

    ratio = SequenceMatcher(None, a, b).ratio()
    n = max(len(a), len(b))
    left = sum(x == y for x, y in zip(a, b))
    right = sum(
        x == y for x, y in zip(reversed(a), reversed(b))
    )  # 漏掉开头字时按结尾对齐
    pos = max(left, right) / n
    suffix = 0
    while suffix < min(len(a), len(b)) and a[-1 - suffix] == b[-1 - suffix]:
        suffix += 1
    return (
        0.55 * ratio
        + 0.3 * pos
        + (0.1 if len(a) == len(b) else 0)
        + 0.05 * min(suffix, 3)
    )


def mineral_zh(en: str):
    return _tables(False)[1].get(en, en)


# ---------------------------------------------------------------- 精炼方式、站点、城市的中文名


@lru_cache
def _maps():
    data = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    methods = {r["en"]: r["zh"] for r in data["refining_methods"]}
    places = {r["en"]: r["zh"] for r in data["locations"]}
    return methods, places


def method_zh(en: str) -> str:
    return _maps()[0].get(en, en)


def station_zh(en: str) -> str:
    """精炼站中文名，带上英文代号方便对照（如 "微 L5 现代伊卡洛斯站 (MIC-L5)"）"""
    zh = _maps()[1].get(en)
    return f"{zh} ({en})" if zh and zh != en else en


# ---------------------------------------------------------------- 矿头、模组、手持工具的名字（2026-10-26 用户定格式）


@lru_cache
def _gear_zh():
    """英文名（小写）→ 汉化包里的中文名去掉型号和后缀：「霍夫斯泰德-S2 型采矿激光器」→「霍夫斯泰德」"""
    import re

    data = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    out = {}
    for r in data.get("equipment", []):
        zh = r.get("zh") or ""
        for suf in ("型采矿激光器", "采矿激光器", "模组"):
            zh = zh.replace(suf, "")
        m = re.match(r"[一-鿿·]+", zh.strip())
        if m and r.get("en"):
            out.setdefault(r["en"].lower(), m.group(0))
    return out


def gear_label(en: str) -> str:
    """矿头、模组、手持工具统一写成「中文 English」：霍夫斯泰德 Hofstede-S2、里格 Rieger-C3、萨比尔 Sabir。
    汉化包里没有中文名的（XTR-L、FLTR）只写英文"""
    zh = _gear_zh().get((en or "").lower())
    return f"{zh} {en}" if zh else (en or "")


def gear_zh_of_item(en: str) -> str:
    """物品英文全名「Hofstede-S2 Mining Laser」「Rieger-C3 Module」「Sabir」→ 不带型号的中文名「霍夫斯泰德」；不是采矿装备返回空。
    物品查询、蓝图里的采矿装备用它，和配置区写法一致（2026-10-26）"""
    import re

    s = (en or "").strip()
    base = re.sub(r"\s+(Mining Laser|Module)$", "", s, flags=re.I)
    if base == s and s.lower() not in {
        "sabir",
        "optimax",
        "boremax",
        "okunis",
        "waveshift",
        "stalwart",
    }:
        return ""
    return _gear_zh().get(base.lower(), "")


# 商店分类（UEX 的英文分类）→ 游戏里的叫法（汉化包 item_Type…）。护甲三件用物品名里的「臂甲 / 胸甲 / 腿甲」、模组用「采矿模组」，
# 和汉化包的物品名一致；物品查询里只在 wiki 有记录的物品（tasks.trade.WIKI_TYPE_ZH）用同一套词
SHOP_CAT_ZH = {
    "Jackets": "夹克",
    "Footwear": "鞋子",
    "Legwear": "裤子",
    "Helmets": "头盔",
    "Shirts": "衬衫",
    "Arms": "臂甲",
    "Legs": "腿甲",
    "Torso": "胸甲",
    "Undersuits": "基底服",
    "Guns": "舰炮",
    "Personal Weapons": "单兵武器",
    "Hats": "帽子",
    "Attachments": "附件",
    "Foods": "食物",
    "Gloves": "手套",
    "Radar": "雷达",
    "Coolers": "冷却器",
    "Missiles": "导弹",
    "Flight Blade": "飞行刀片",
    "Quantum Drives": "量子驱动器",
    "Drinks": "饮料",
    "Power Plants": "发电机",
    "Shield Generators": "护盾生成器",
    "Miscellaneous": "杂项",
    "Backpacks": "背包",
    "Mining Modules": "采矿模组",
    "Mobiglas": "mobiGlas",
    "Liveries": "涂装",
    "Missile Racks": "导弹架",
    "Turrets": "炮塔",
    "Mining Laser Heads": "采矿激光器",
    "Decorations": "装饰",
    "Container": "货柜",
    "Module": "模块",
    "Bomb Racks": "炸弹架",
    "Consumables": "消耗品",
    "External Fuel Tanks": "外部燃料箱",
    "Tractor Beams": "牵引光束",
    "Docking Collars": "对接口",
    "Gadgets": "工具",
    "Scraper Beams": "刮削光束",
    "Salvage Beams": "打捞光束",
    "Bombs": "炸弹",
    "Jump Modules": "跳跃模块",
    "Surface": "表面",
    "Fabricator": "制造机",
}


def shop_cat_zh(cat: str) -> str:
    """商店分类的中文；表里没有的照原样"""
    return SHOP_CAT_ZH.get(cat or "", cat or "")
