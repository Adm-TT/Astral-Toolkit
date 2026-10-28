"""一件东西怎么弄到：商店买（按离你远近推荐 3 处）→ 买不到就推荐能买到的原型/同系列 → 掉落 → 维科洛用途

「哪买」命令和游戏里 F8 识别都用这里。
"""
import re

from . import shops


_ACCESSORY = {"battery", "magazine", "mag", "cap", "ammo", "canister", "charge"}


def _words(s):
    return set(re.findall(r"[a-z]+", (s or "").lower()))


def _variants(name):
    extra_ok = _words(name) & _ACCESSORY
    return [v for v in shops.variants(name, limit=6) if not ((_words(v[1]) & _ACCESSORY) - extra_ok)][:2]


def buy_lines(item_id, here, top=3):
    rows = shops.nearest(item_id, here, top) if here else []
    lines = []
    if rows and rows[0][0] != float("inf"):
        from .position import fmt_distance
        lines += [f"    {fmt_distance(d)}｜{p:,.0f} aUEC｜{shop}｜{place}" for d, p, shop, place in rows]
    else:
        buy, _ = shops.where(item_id)
        lines += [f"    {p:,.0f} aUEC｜{shop}｜{place}" for p, shop, place in buy[:top]]
    return lines


def text(name_en="", name_zh="", item_id=None, show_loot=True):
    """完整说明（多行）。item_id 是商店数据里的物品 id，没有就按名字找"""
    from .position import current
    lines = []
    here = None
    try:
        here = current()
    except Exception:
        pass
    if item_id is None and (name_en or name_zh):
        hits = shops.find(name_en or name_zh, limit=3)
        exact = [h for h in hits if shops._fold(h[1]) == shops._fold(name_en)] if name_en else hits[:1]
        if exact:
            item_id = exact[0][0]
    pos_note = ""
    if here:
        pos_note = f"（按离当前位置远近排：{here['label']}" + (f"，{int(here['age'] // 60)} 分钟前" if here['age'] > 600 else "") + "）"
    if item_id is not None and shops.buyable(item_id):
        buy, _ = shops.where(item_id)
        lines.append(f"  商店有卖（共 {len(buy)} 处）{pos_note or '（最便宜的在前；开过库存后会按远近排）'}：")
        lines += buy_lines(item_id, here)
    else:
        name = name_en or (shops.load(auto_update=False)["items"].get(str(item_id), [""])[0] if item_id else "")
        vs = _variants(name) if name else []
        if vs:
            lines.append("  这件是限定/特殊版本，商店买不到。能买到的同款：")
            for iid, vname, _ in vs:
                buy, _ = shops.where(iid)
                lines.append(f"  · {vname}（{len(buy)} 处有卖）{pos_note}")
                lines += buy_lines(iid, here)
        else:
            lines.append("  商店买不到，也没找到能买的同款")
    if item_id is not None:
        _, sell = shops.where(item_id)
        if sell:
            p, shop, place = sell[0]
            lines.append(f"  卖给商店最高：{p:,.0f} aUEC｜{shop}｜{place}")
    if show_loot:
        try:
            from .loot import text as loot_text
            t = loot_text(name_en, name_zh)
            if t:
                lines.append(t)
        except Exception as e:
            lines.append(f"  （掉落数据出错：{e}）")
    try:
        from .wikelo import uses_text
        w = uses_text(name_en, name_zh)
        if w:
            lines.append("  " + w)
    except Exception:
        pass
    return "\n".join(lines)


# ---------------------------------------------------------------- 窗口用的结构化版本

def _buy_rows(item_id, here, top=3):
    if here:
        rows = shops.nearest(item_id, here, top)
        if rows and rows[0][0] != float("inf"):
            from .position import fmt_distance
            return [{"dist": fmt_distance(d), "price": p, "shop": shop, "place": place} for d, p, shop, place in rows]
    buy, _ = shops.where(item_id)
    return [{"dist": "", "price": p, "shop": shop, "place": place} for p, shop, place in buy[:top]]


def resolve(name_en="", name_zh="", item_id=None):
    """名字 → 商店数据里的物品 id。顺序：英文名完全一样 → 中文名（汉化包对照表）→ 英文名最像的（OCR 认错一两个字母）"""
    if item_id is not None or not (name_en or name_zh):
        return item_id
    if name_en:
        hits = shops.find(name_en, limit=3)
        exact = [h for h in hits if shops._fold(h[1]) == shops._fold(name_en)]
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
    """自带这个部件出厂的船（data/ship_items.json，tools/unpack_ship_data.py 从解包生成，2026-10-27）→ [船中文名]"""
    import re
    from .paths import DATA, cached_json
    fold = lambda x: re.sub(r"[^a-z0-9]", "", (x or "").lower())
    table = cached_json(DATA / "ship_items.json", lambda d: {fold(k): v for k, v in (d.get("items") or {}).items()}, {})
    return list(table.get(fold(name)) or [])


def info(name_en="", name_zh="", item_id=None, show_loot=True, exact=False, loot_online=True):
    """{name, category, buyable, here, buy, buy_total, variants, sell, loot, wikelo, nowhere, craft}
    exact=True：从物品查询搜索结果点进来的，英文名是准的，不再按中文名去模糊找（以前会找成别的东西）；
    nowhere：商店和掉落数据里都没有（只有汉化包里有名字）；craft：这种东西有制造蓝图时的蓝图"""
    from .position import current
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
    name, category = (items.get(str(item_id)) or [name_en or name_zh, ""]) if item_id is not None else (name_en or name_zh, "")
    ships = ships_with(name_en or name) or ships_with(name)
    try:
        from .wikelo import source_note
        how = source_note(name_en or name) or source_note(name)
    except Exception:
        how = ""
    out = {"name": name, "zh": name_zh, "category": category, "id": item_id, "here": None,
           "buyable": False, "buy": [], "buy_total": 0, "variants": [], "sell": None, "loot": None, "wikelo": [],
           "nowhere": bool(hit) and not hit["has_data"] and not ships and not how, "craft": None, "desc": "", "aka": [],
           "ships": ships, "how": how}
    if not hit:
        from .itemsearch import lookup
        hit2 = lookup(name)
        if hit2:
            out["desc"], out["aka"] = hit2.get("desc") or "", list(hit2.get("aka") or [])
    else:
        out["desc"], out["aka"] = hit.get("desc") or "", list(hit.get("aka") or [])     # 描述：wiki 的游戏官方中文说明（1.6.49）
    if hit and not hit["loot"]:
        show_loot = False                              # 掉落数据里没有这件：不去模糊找别的东西的掉落
    if out["nowhere"]:
        try:
            from .crafting import for_item, bp_key, display_name
            bp = for_item(name_en, name_zh)
            if bp:
                out["craft"] = {"key": bp_key(bp), "name": display_name(bp), "unlocked": bool(bp["d"]),
                                "missions": [t for t, *_ in bp["src"][:3]], "nsrc": bp["nsrc"]}
        except Exception:
            pass
    if here:
        out["here"] = {"label": here["label"], "minutes": int(here["age"] // 60)}
    if item_id is not None and shops.buyable(item_id):
        out["buyable"] = True
        out["buy_total"] = len(shops.where(item_id)[0])
        out["buy"] = _buy_rows(item_id, here)
    elif name:
        for iid, vname, _ in _variants(name):
            out["variants"].append({"id": iid, "name": vname, "total": len(shops.where(iid)[0]),
                                    "buy": _buy_rows(iid, here)})
    if item_id is not None:
        _, sell = shops.where(item_id)
        if sell:
            p, shop, place = sell[0]
            out["sell"] = {"price": p, "shop": shop, "place": place}
    if show_loot:
        try:
            from .loot import info as loot_info
            out["loot"] = loot_info(name_en or name, name_zh, online=loot_online)
        except Exception as e:
            out["loot"] = {"error": f"掉落数据出错：{e}"}
    try:
        from .wikelo import uses
        out["wikelo"] = [{"title": c["t"], "q": q, "u": u, "reward": c["rz"] or "、".join(c["rewards"][:2])}
                         for c, q, u in uses(name_en or name, name_zh)[:8]]
    except Exception:
        pass
    return out
