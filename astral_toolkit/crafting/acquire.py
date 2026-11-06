"""一件东西怎么弄到：商店买（按离你远近推荐 3 处）→ 买不到就推荐能买到的原型/同系列 → 掉落 → 维科洛用途

游戏里 F8 识别、物品查询、维科洛材料来源都用这里。这里只管查数据（商店、物品查询、掉落、维科洛、蓝图、当前位置）；
怎么挑、怎么拼成详情字典在 catalog/acquire.py（IQ-C2 拆开）。命令行「哪买」2026-11-06 删了，
它用的整段文字版（text / buy_lines）也跟着删了。
"""

import re as _re

from ..catalog import acquire as _rules
from ..contracts.textkeys import fold_en_loose
from . import shops


def _buy_rows(item_id, here, top=3):
    if here:
        rows = shops.nearest(item_id, here, top)
        if rows and rows[0][0] != float("inf"):
            from ..navigation.position import fmt_distance

            return [
                {"dist": fmt_distance(d), "price": p, "shop": shop, "place": place}
                for d, p, shop, place in rows
            ]
    buy, _ = shops.where(item_id)
    return [
        {"dist": "", "price": p, "shop": shop, "place": place}
        for p, shop, place in buy[:top]
    ]


def resolve(name_en="", name_zh="", item_id=None):
    """名字 → 商店数据里的物品 id。顺序：英文名完全一样 → 中文名（汉化包对照表）→ 英文名最像的（OCR 认错一两个字母）"""
    if item_id is not None or not (name_en or name_zh):
        return item_id
    if name_en:
        hits = shops.find(name_en, limit=3)
        exact = [h for h in hits if fold_en_loose(h[1]) == fold_en_loose(name_en)]
        if exact:
            return exact[0][0]
    if name_zh:
        hits = shops.find(name_zh, limit=3)
        if hits:
            return hits[0][0]
    if name_en:
        close = shops.find_close(name_en)
        if close:
            return close[0]
        if not name_zh:
            hits = shops.find(name_en, limit=3)
            return hits[0][0] if hits else None
    return None


def ships_with(name):
    """自带这个部件出厂的船（ship_items.json，由数据构建脚本从游戏数据生成，2026-10-27；读库）→ [船中文名]"""
    from .. import gamedata
    from ..contracts.textkeys import fold_en as _fold_en

    try:
        return gamedata.itemstats.ships_with(_fold_en(name))
    except gamedata.GamedataError:
        return []


def info(
    name_en="", name_zh="", item_id=None, show_loot=True, exact=False, loot_online=True
):
    """{name, category, buyable, here, buy, buy_total, variants, sell, loot, wikelo, nowhere, craft}
    exact=True：从物品查询搜索结果点进来的，英文名是准的，不再按中文名去模糊找（以前会找成别的东西）；
    nowhere：商店和掉落数据里都没有（只有汉化包里有名字）；craft：这种东西有制造蓝图时的蓝图。
    这里只查数据；挑哪几件同款、算不算「哪都没有」、要不要查掉落、各块怎么拼，见 catalog/acquire.py"""
    from ..navigation.position import current

    here = None
    try:
        here = current()
    except Exception:
        pass
    hit = None
    if exact and name_en:
        from .itemsearch import lookup

        hit = lookup(name_en)
    if hit:
        if item_id is None:
            item_id = hit["shop"]
    else:
        item_id = resolve(name_en, name_zh, item_id)
    items = shops.load(auto_update=False)["items"]
    name, category = _rules.name_and_category(
        items.get(str(item_id)) if item_id is not None else None,
        item_id,
        name_en,
        name_zh,
    )
    ships = ships_with(name_en or name) or ships_with(name)
    try:
        from .wikelo import source_note

        how = source_note(name_en or name) or source_note(name)
    except Exception:
        how = ""
    out = _rules.empty_facts(
        name, name_zh, category, item_id, _rules.is_nowhere(hit, ships, how), ships, how
    )
    if hit:
        entry = hit
    else:
        from .itemsearch import lookup

        entry = lookup(name)
    out["desc"], out["aka"] = _rules.desc_and_aka(
        entry
    )  # 描述：wiki 的游戏官方中文说明（1.6.49）
    if out["nowhere"]:
        try:
            from .crafting import for_item, bp_key, display_name

            bp = for_item(name_en, name_zh)
            if bp:
                out["craft"] = _rules.craft_summary(bp, bp_key(bp), display_name(bp))
        except Exception:
            pass
    out["here"] = _rules.here_summary(here)
    if item_id is not None and shops.buyable(item_id):
        out["buyable"] = True
        out["buy_total"] = len(shops.where(item_id)[0])
        out["buy"] = _buy_rows(item_id, here)
    elif name:
        for iid, vname, _ in _rules.pick_variants(name, shops.variants(name, limit=6)):
            out["variants"].append(
                {
                    "id": iid,
                    "name": vname,
                    "total": len(shops.where(iid)[0]),
                    "buy": _buy_rows(iid, here),
                }
            )
    if item_id is not None:
        out["sell"] = _rules.sell_summary(shops.where(item_id)[1])
    if _rules.shows_loot(show_loot, hit):
        try:
            from .loot import info as loot_info

            out["loot"] = loot_info(name_en or name, name_zh, online=loot_online)
        except Exception as e:
            out["loot"] = {"error": f"掉落数据出错：{e}"}
    try:
        from .wikelo import uses

        out["wikelo"] = _rules.wikelo_rows(uses(name_en or name, name_zh))
    except Exception:
        pass
    return out


def material_source(name_en):
    """维科洛材料去哪弄：商店能买就给最便宜的店；是矿就给最好的矿点"""
    from ..crafting import shops
    from ..crafting.wikelo import source_note

    note = source_note(name_en)
    if note:
        return note
    tip = shops.where_by_name(name_en)
    if tip:
        return tip
    try:
        from ..mining.locations import where as mine_where, zh_name

        base = _re.sub(r"\s*\(.*?\)", "", name_en).strip()
        rows = mine_where(base)
        if rows:
            pct, loc = rows[0]
            return f"挖矿：{zh_name(loc)} {pct:.0f}%" + (
                "（要精炼成纯净的）" if "Pure" in name_en else ""
            )
    except Exception:
        pass
    return loot_source(name_en)


def loot_source(name_en, name_zh=""):
    """开箱掉落一句话（scl.miao.network 的掉落表）：概率最高的箱子在哪些地方；没有掉落返回空"""
    try:
        from ..crafting.loot import info

        d = info(
            name_en, name_zh, top=2, online=False
        )  # 本机没有明细就算没有，不在页面里逐个材料联网等（细查 2026-10-28）
    except Exception:
        return ""
    if not d or not d.get("groups"):
        return ""
    g = d["groups"][0]
    regions = "、".join(g["regions"][:3]) + (
        "等" if len(g["regions"]) > 3 or d.get("more") else ""
    )
    if d.get("mine"):  # 副本专属矿：不开箱，只能开采
        return (
            d["note"].split("：")[0]
            + f"，只能开采：{regions}"
            + (f"（{g['box']}）" if g["box"] else "")
        )
    if g.get("placed"):  # 不在箱子里，直接刷在场景里（争夺区奖励室架子上的舰船组件…）
        return f"场景里刷出：{regions}（最高约 {g['p']:.0%}）"
    box = g["box"].split(" · ")[0]
    box = "" if _re.fullmatch(r"\d+.*", box or "") else box
    return (
        f"开箱：{regions}"
        + (f"（{box} 箱" if box else "（")
        + f"，单箱最高约 {g['p']:.0%}）"
    )
