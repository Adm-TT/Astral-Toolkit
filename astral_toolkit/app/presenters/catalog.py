"""物品查询的展示（IQ-B5）：用例取好的东西 → 窗口物品查询页的 JSON（字段、中文分类、出错文字和以前逐字一样）。
只排版，不取数据；原来写在 tasks/trade.py 的 item_search / item_info / item_loot 里。"""

from typing import Any, Iterable

from ...catalog.results import ItemInfo, LootLookup
from ...core.i18n import shop_cat_zh

WIKI_TYPE_ZH = {
    "WeaponPersonal": "单兵武器",
    "WeaponGun": "舰炮",
    "MissileLauncher": "导弹架",
    "Missile": "导弹",
    "Turret": "炮塔",
    "Char_Armor_Helmet": "头盔",
    "Char_Armor_Torso": "胸甲",
    "Char_Armor_Arms": "臂甲",
    "Char_Armor_Legs": "腿甲",
    "Char_Armor_Backpack": "背包",
    "Char_Armor_Undersuit": "基底服",
    "Char_Clothing_Torso_0": "上衣",
    "Char_Clothing_Torso_1": "外套",
    "Char_Clothing_Legs": "裤子",
    "Char_Clothing_Feet": "鞋",
    "Char_Clothing_Hat": "帽子",
    "Char_Clothing_Hands": "手套",
    "WeaponAttachment": "附件",
    "Shield": "护盾生成器",
    "PowerPlant": "发电机",
    "Cooler": "冷却器",
    "QuantumDrive": "量子驱动器",
    "Radar": "雷达",
    "WeaponMining": "采矿激光器",
    "MiningModifier": "采矿模组",
    "Container": "货柜",
    "TractorBeam": "牵引光束",
    "FuelTank": "燃料箱",
    "FuelIntake": "燃料进气口",
    "Thruster": "推进器",
    "Armor": "舰船装甲",
    "UtilityTurret": "工具炮塔",
    "RemovableChip": "钥匙卡",
    "FPS_Consumable": "消耗品",
    "Food": "食物",
    "Drink": "饮料",
    "Commodity": "商品",
}


def _wiki_cat(r):
    """只在 wiki 清单里的物品：类型 + 尺寸当分类显示（「导弹架 S5」）"""
    if not r.get("wtype"):
        return ""
    t = WIKI_TYPE_ZH.get(r["wtype"], r["wtype"])
    return (
        f"{t} S{r['wsize']}"
        if r.get("wsize") not in (None, 0, 1)
        or (
            r.get("wsize") == 1
            and r["wtype"]
            in (
                "WeaponGun",
                "MissileLauncher",
                "Shield",
                "PowerPlant",
                "Cooler",
                "QuantumDrive",
                "Radar",
                "WeaponMining",
            )
        )
        else t
    )


def present_search_results(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """搜索列表每一行 → {id, name, zh, category, src}。src：shop 商店有数据 / loot 只在掉落数据里 /
    wiki 只在 wiki 清单里 / loc 都没有（只有汉化包里有名字）"""
    return [
        {
            "id": r["shop"],
            "name": r["en"],
            "zh": r["zh"],
            "category": shop_cat_zh(r["cat"]) or _wiki_cat(r),
            "src": "shop"
            if r["shop"] is not None
            else "loot"
            if r["loot"]
            else "wiki"
            if r.get("wiki")
            else "loc",
        }
        for r in rows
    ]


def distance_text(m):
    """买点离你多远 → 文字（目录迁移收尾从 navigation/position.fmt_distance 搬来）：不在一个星系「要跳星系」、
    1000 公里内「就在附近」、10 亿米内按千公里、再远按 Gm"""
    if m >= 1e15:
        return "要跳星系"
    if m < 1e6:
        return "就在附近"
    if m < 1e9:
        return f"{m / 1e6:,.0f} 千公里"
    return f"{m / 1e9:,.1f} Gm"


def _buy_row(r):
    """买点一行：用例给的 dist_m（米；None 是不知道你在哪）换成 dist 文字，键和先后跟以前一样（dist、price、shop、place）"""
    m = r.get("dist_m")
    return {
        "dist": "" if m is None else distance_text(m),
        "price": r["price"],
        "shop": r["shop"],
        "place": r["place"],
    }


def present_item_info(info: ItemInfo) -> dict[str, Any]:
    """物品卡片：facts 照抄一份（不改用例给的字典），换上中文名；有分类才换成中文分类；买点（含同系列的）的距离
    写成文字；最后加目标提示。窗口物品查询页和 F8 卡片都是这一份"""
    d = dict(info.facts)
    d["zh"] = info.zh
    if d.get("category"):
        d["category"] = shop_cat_zh(d["category"])
    if d.get("buy"):
        d["buy"] = [_buy_row(r) for r in d["buy"]]
    if d.get("variants"):
        d["variants"] = [
            {**v, "buy": [_buy_row(r) for r in v["buy"]]} if v.get("buy") else v
            for v in d["variants"]
        ]
    d["goal"] = info.goal
    return d


def present_item_loot(result: LootLookup) -> dict[str, Any]:
    """掉落那一块：{"loot": 原样}；取的时候出错 → {"loot": {"error": "掉落数据出错：…"}}"""
    if result.error is not None:
        return {"loot": {"error": f"掉落数据出错：{result.error}"}}
    return {"loot": result.loot}
