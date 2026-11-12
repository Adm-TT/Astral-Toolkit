"""物品详情「怎么弄到」的组合规则（IQ-C2，架构稿 §5.1：商店 / 掉落信息的组合规则归 catalog）：
买不到时推荐哪几件同款、卖给商店最高的那家、要不要查掉落、算不算「哪都没有」，
以及物品查询 / F8 用的详情字典的骨架和各块的样子。

原 crafting/acquire.info 里不夹着取数据的规则搬到这里；查商店、物品查询、掉落、维科洛、蓝图、当前位置在
tasks/catalog_queries/acquire.py（目录迁移 Q3b 从 crafting/acquire 搬去）。
dev 拆分①（2026-11-09）：那边原来还夹着的几块规则也搬来了——买点用最近几处还是最便宜几处、各行的样子
（nearest_usable / near_rows / cheapest_rows）、名字找物品 id 时英文名完全一样的（exact_ids）、维科洛材料的矿点和
掉落事实（ore_base / mine_fact / loot_fact）。那边只剩按原来的先后取数据（先查最近、算不出才查全部；按条件才查下一样）。
维科洛材料那一句话在 app/presenters/wikelo.source_text。
catalog 不读文件、不联网、不碰全局缓存（和 catalog/shops.py、catalog/loot.py 一样）。
"""

import re

from ..contracts.textkeys import fold_en_loose

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


# ---------------------------------------------------------------- 买点（dev 拆分①从 tasks/catalog_queries/acquire._buy_rows 搬来）
def nearest_usable(rows):
    """shops.nearest 给的 [(距离米, 价格, 商店, 地点)] 能不能用：有、而且最近那处算得出距离（不在一个星系的是 inf）"""
    return bool(rows) and rows[0][0] != float("inf")


def near_rows(rows):
    """最近几处买点的样子：dist_m 是米，写成文字在 app/presenters/catalog.distance_text"""
    return [
        {"dist_m": d, "price": p, "shop": shop, "place": place}
        for d, p, shop, place in rows
    ]


def cheapest_rows(buy, top):
    """没有位置、或算不出距离时：最便宜 top 处（buy 已按价格从低到高排好的 (价格, 商店, 地点)），dist_m 是 None"""
    return [
        {"dist_m": None, "price": p, "shop": shop, "place": place}
        for p, shop, place in buy[:top]
    ]


# ---------------------------------------------------------------- 名字找物品 id（dev 拆分①从 resolve 搬来）
def exact_ids(hits, name_en):
    """shops.find 给的 [(id, 英文名, …)] 里英文名和 name_en 完全一样的那几件的 id，按原顺序（大小写、空格、l / I 认混
    不算不一样）；没有是 []。给列表不给单个：和原来「有就取第一个」一模一样，不拿 None 兼当「没有」"""
    want = fold_en_loose(name_en)
    return [h[0] for h in hits if fold_en_loose(h[1]) == want]


# ---------------------------------------------------------------- 维科洛材料去哪弄（dev 拆分①从 material_source / loot_source 搬来）
def ore_base(name_en):
    """矿名去掉括号那截（「Quantainium (Raw)」→「Quantainium」），按它查矿点"""
    return re.sub(r"\s*\(.*?\)", "", name_en).strip()


def mine_fact(pct, where, name_en):
    """最好的矿点的事实：where 是地点的中文名（取数据那边换好），pure：要的是纯净的（英文名带 Pure）"""
    return {"where": where, "pct": pct, "pure": "Pure" in name_en}


def loot_fact(d):
    """掉落表（loot.info 的结果）里概率最高那组的事实：{regions 地方、more 后面还有、mine 副本专属矿只能开采、
    note 掉落说明、box 箱子、placed 直接刷在场景里、p 单箱最高概率}；没有掉落给 None。
    regions、note、box、p 原样给：掉落数据缺字段时拼字那步出错、写空，和以前一样"""
    if not d or not d.get("groups"):
        return None
    g = d["groups"][0]
    return {
        "regions": g["regions"],
        "more": bool(d.get("more")),
        "mine": bool(d.get("mine")),
        "note": d.get("note"),
        "box": g["box"],
        "placed": bool(g.get("placed")),
        "p": g["p"],
    }
