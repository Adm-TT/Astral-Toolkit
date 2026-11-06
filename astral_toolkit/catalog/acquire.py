"""物品详情「怎么弄到」的组合规则（IQ-C2，架构稿 §5.1：商店 / 掉落信息的组合规则归 catalog）：
买不到时推荐哪几件同款、卖给商店最高的那家、要不要查掉落、算不算「哪都没有」，
以及物品查询 / F8 用的详情字典的骨架和各块的样子。

原 crafting/acquire.info 里不夹着取数据的规则搬到这里；查商店、物品查询、掉落、维科洛、蓝图、当前位置留在旧文件。
还夹着取数据、留在 crafting/acquire 的规则：买点给最近 3 处还是最便宜 3 处（_buy_rows，按条件才去查）、
名字找物品 id 的先后（resolve）、维科洛材料来源那一句（material_source / loot_source）；
随搬目录那批（crafting/shops 这些的取数据归位）一起处理，见待做。
catalog 不读文件、不联网、不碰全局缓存（和 catalog/shops.py、catalog/loot.py 一样）。
"""

import re

# 推荐同款时不推这些配件（电池、弹匣…），除非要找的这件本身就是配件
ACCESSORY = frozenset(
    {"battery", "magazine", "mag", "cap", "ammo", "canister", "charge"}
)


def _words(s):
    return set(re.findall(r"[a-z]+", (s or "").lower()))


def pick_variants(name, candidates):
    """买不到时推荐的同款：candidates 是 shops.variants 给的同系列能买到的几件 [(id, 名字, 类别)]（原型排前面），
    去掉配件（这件本身是配件的除外），最多 2 件。
    name：商店数据里有这件时是商店里的名字，没有时是传进来的英文名（没有英文名用中文名），见 name_and_category"""
    extra_ok = _words(name) & ACCESSORY
    return [v for v in candidates if not ((_words(v[1]) & ACCESSORY) - extra_ok)][:2]


def name_and_category(record, item_id, name_en, name_zh):
    """商店数据里的名字和类别。record 是商店数据里这件的 [名字, 类别]；没有 id、或商店数据里没有这件：
    用传进来的英文名（没有英文名用中文名），类别空"""
    if item_id is None:
        return name_en or name_zh, ""
    name, category = record or [name_en or name_zh, ""]
    return name, category


def is_nowhere(hit, ships, how):
    """「哪都没有」：物品查询精确命中、但商店和掉落数据里都没有（只有汉化包里有名字），也不随船自带、没有别的来源说明"""
    return bool(hit) and not hit["has_data"] and not ships and not how


def shows_loot(show_loot, hit):
    """要不要查掉落：物品查询精确命中、但掉落数据里没有这件时不查（不去模糊找别的东西的掉落）"""
    return show_loot and not (hit and not hit["loot"])


def desc_and_aka(entry):
    """物品查询那一条的描述（wiki 的游戏官方中文说明）和别名；没有这条返回 ("", [])"""
    if not entry:
        return "", []
    return entry.get("desc") or "", list(entry.get("aka") or [])


def here_summary(here):
    """当前位置那一行：{label, minutes}（多少分钟前开过库存 / 记下的位置）；不知道在哪返回 None"""
    if not here:
        return None
    return {"label": here["label"], "minutes": int(here["age"] // 60)}


def sell_summary(sell):
    """卖给商店最高的那家（sell 已按价格从高到低排好的 (价格, 商店, 地点)）；没人收返回 None"""
    if not sell:
        return None
    p, shop, place = sell[0]
    return {"price": p, "shop": shop, "place": place}


def craft_summary(bp, key, name):
    """「哪都没有」但有制造蓝图时显示的蓝图：key、显示名由制造模块算好传进来"""
    return {
        "key": key,
        "name": name,
        "unlocked": bool(bp["d"]),
        "missions": [t for t, *_ in bp["src"][:3]],
        "nsrc": bp["nsrc"],
    }


def wikelo_rows(uses, limit=8):
    """维科洛兑换里用到这件的合同：uses 是 (合同, 数量, 单位)，最多 limit 条；奖励没写就拿前两样奖励"""
    return [
        {
            "title": c["t"],
            "q": q,
            "u": u,
            "reward": c["rz"] or "、".join(c["rewards"][:2]),
        }
        for c, q, u in uses[:limit]
    ]


def empty_facts(name, zh, category, item_id, nowhere, ships, how):
    """详情字典的骨架：各块先空着，按查到的往里填（键的顺序和以前一样）"""
    return {
        "name": name,
        "zh": zh,
        "category": category,
        "id": item_id,
        "here": None,
        "buyable": False,
        "buy": [],
        "buy_total": 0,
        "variants": [],
        "sell": None,
        "loot": None,
        "wikelo": [],
        "nowhere": nowhere,
        "craft": None,
        "desc": "",
        "aka": [],
        "ships": ships,
        "how": how,
    }
