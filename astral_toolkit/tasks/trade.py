"""物品查询、交易市场与矿石精炼任务模块（Task: Trade, Market & Mineral Refining）

专职处理：
1. 全局跨模块聚合搜索（物品、地点、矿脉、蓝图制造、Wikelo兑换）；
2. 物品查询旧壳（IQ-B5：用例在 tasks/catalog.py、排版在 app/presenters/catalog.py）与商店导航定位；
3. 玩家市场行情查价与报价明细查询（UEX / 社区市场）；
4. 矿脉分布检索、小行星带导航与精炼厂加成查询。
"""

import re
import threading


# ---------------------------------------------------------------- 依赖：别的任务、悬浮窗
# 2026-10-30 重构阶段 1：直接调别的任务模块和 app.hud_state，不再经 services 转发、出错也不再回头找 services 兜底。
# 别的任务在函数里 import（任务之间互相引用，顶层 import 会循环），取模块属性，测试换掉的名字能打中。
from ..app.hud_state import _item_hud

# IQ 过渡：下面 item_search 旧壳排版用（库存联想、全局搜索还在调），删壳时一起删
from ..app.presenters import catalog as _present_catalog
from . import catalog as _catalog


def _nav_search(q=""):
    from . import navigation

    return navigation.nav_search(q=q)


def _craft_search(q=""):
    from . import goals

    return goals.craft_search(q=q)


def _wikelo_search(q=""):
    from . import goals

    return goals.wikelo_search(q=q)


def _goal_for(*names):
    from . import goals

    return goals._goal_for(*names)


def _goal_text(g, q=None, lots=None):
    from . import goals

    return goals._goal_text(g, q, lots)


def _nav_objects():
    from . import navigation as n_mod

    return n_mod._place_row, n_mod._places, n_mod._start_nav


def _get_last_hover():
    from . import hover

    return hover.last_hover()


nav_search = _nav_search
craft_search = _craft_search
wikelo_search = _wikelo_search


# ================================================================ 全局搜索


def search(q=""):
    """一个输入框搜所有东西：物品、地点、矿、蓝图、维科洛兑换"""
    q = (q or "").strip()
    out = {"items": [], "places": [], "minerals": [], "blueprints": [], "wikelo": []}
    if not q:
        return out
    try:
        out["minerals"] = mineral_search(q)
    except Exception:
        pass
    try:
        out["items"] = item_search(q)[:8]
    except Exception:
        pass
    try:
        out["places"] = _nav_search(q)["rows"][:6]
    except Exception:
        pass
    try:
        out["blueprints"] = _craft_search(q)[:6]
    except Exception:
        pass
    try:
        out["wikelo"] = _wikelo_search(q)[:5]
    except Exception:
        pass
    return out


# ================================================================ 物品查询旧壳（IQ-B5）+ 商店导航


def item_search(q=""):
    """旧壳（IQ-B5）：库存联想（tasks/stock）、上面的全局搜索还在调。窗口物品查询页走 app/api/trade → tasks/catalog + app/presenters/catalog"""
    return _present_catalog.present_search_results(_catalog.search_items(q))


def nav_shop(shop="", place=""):
    """物品查询里点一处商店 → 导航过去（2026-10-28 用户定）。先找主城 / 空间站里这家店的点（城里导航），
    没有就导航到这个地点本身（星图）"""
    from ..navigation import navigate as n

    data = n.load()
    brand = re.sub(r"[^a-z]", "", (shop.split(" - ")[0] or "").lower())
    place = (
        (place or "").split(" · ")[-1].strip()
    )  # 商店行的地点是「Stanton · MicroTech · New Babbage」，只要最后一段（2026-10-28 反馈：点了说没这个地点）
    site = re.sub(r"[^a-z0-9]", "", place.lower())
    hit = None
    if site:
        pts = [
            q
            for q in n.city_places()
            if re.sub(r"[^a-z0-9]", "", (q.get("site_en") or "").lower()) == site
        ]
        if brand:
            hit = next(
                (
                    q
                    for q in pts
                    if re.sub(r"[^a-z]", "", q["n"].lower()).startswith(brand)
                ),
                None,
            )
        if (
            hit is None and pts
        ):  # 店的点没解出来：去这个地方的取船终端（下了船就在旁边）
            hit = next((q for q in pts if "取船" in (q.get("kinds") or ())), None)
        if hit is None:
            hit = next(
                (
                    q
                    for q in data["pois"]
                    if re.sub(r"[^a-z0-9]", "", q["n"].lower()) == site
                ),
                None,
            )
        if (
            hit is None
        ):  # 派罗的站星图地点表里没有（死局空间站在 PYR2 L4 上）：按设施表找
            for k in n.NEAR_KINDS:
                hit = next(
                    (
                        q
                        for q in n.amenity_targets(k, data)
                        if re.sub(r"[^a-z0-9]", "", q["n"].lower())
                        in (site, re.sub(r"station$", "", site))
                    ),
                    None,
                )
                if hit:
                    break
        for q in (
            [place, re.sub(r"\s+Station$", "", place, flags=re.I)]
            if hit is None
            else []
        ):  # 星图里叫 Checkmate，不带 Station
            hits, _ = n.search(q, data, limit=1)
            if hits:
                hit = hits[0]
                break
    if hit is None:
        return {"error": "导航数据里没有这个地点"}
    _place_row, _places, _start_nav = _nav_objects()
    row = _place_row(hit)
    err = _start_nav(
        _places[row["key"]]
    )  # 停止中被拒时如实返回，不报「已开始」（RT-B5b）
    if err:
        return err
    return {"key": row["key"], "label": row["label"]}


# ================================================================ 交易：玩家市场价、库存

_trade = None
_trade_lock = threading.Lock()


def trade():
    global _trade
    with _trade_lock:
        if _trade is None:
            from ..trade.console import Trade

            _trade = Trade()
    return _trade


def market_lookup(q=""):
    t = trade()
    items, err = t.lookup(q)
    return {
        "err": err or "",
        "items": [
            {
                "id": i.id,
                "label": t.label(i.id),
                "src": i.id.split(":")[0].upper() if ":" in i.id else "UEX",
            }
            for i in items[:15]
        ],
    }


def market_prices(id="", quality="q0", op="sell"):
    out, results = _market_rows(id, quality, op)
    if results is not None:
        from ..trade.console import hud_market

        market = hud_market(results)
        last_hover = _get_last_hover()
        if last_hover.get("id") == id:  # F8 认出的物品：接在买点/兑换/制造后面
            _item_hud("\n".join(last_hover["lines"] + ([market] if market else [])))
        elif market:  # 窗口里查的价
            _item_hud(f"{trade().label(id)}\n{market}")
    return out


def _market_rows(id, quality="q0", op="sell"):
    """(窗口用的价格表, 原始结果)；没有这个物品返回 ({error}, None)"""
    from ..trade.console import _group, _money, SOURCE_ZH, STATE_ZH

    t = trade()
    item = t.catalog.get(id)
    if not item:
        return {"error": "未找到此物品"}, None
    results = t.prices(item, _group(quality), op)
    rows = []
    for r in results:
        src = SOURCE_ZH.get(r.source, r.source)
        if not r.stats:
            rows.append(
                {"src": src, "state": STATE_ZH.get(r.state, r.state) or "暂无报价"}
            )
            continue
        for s in r.stats:
            rows.append(
                {
                    "src": src,
                    "quality": s.key.quality_group.upper(),
                    "unit": s.key.unit,
                    "currency": s.key.currency,
                    "mean": _money(s.mean),
                    "min": _money(s.minimum),
                    "count": s.count,
                    "week": _money(s.week_mean) if s.week_mean is not None else "",
                    "state": STATE_ZH.get(r.state, ""),
                }
            )
    return {"label": t.label(id), "rows": rows}, results


# ================================================================ 找矿点 / 制造


def mineral_search(q=""):
    from ..mining.data import SIGNATURES
    from ..mining.gems import GEMS
    from ..core.i18n import mineral_zh
    from ..mining.locations import _match_zh

    names = list(SIGNATURES) + list(GEMS)  # 地面小矿（车矿、手采）也能搜
    en_names = {k.lower(): k for k in names}
    out = []
    for token in re.split(r"[\s,，、]+", q.strip()):
        if not token:
            continue
        m = (
            en_names.get(token.lower())
            or next(
                (k for k in names if mineral_zh(k) == token), None
            )  # 中文名一字不差的先认（「杰金」不要模糊成「愈金」）
            or _match_zh(token)
        )
        if not m:
            m = next(
                (
                    k
                    for k in names
                    if token.lower() in k.lower() or token in mineral_zh(k)
                ),
                None,
            )
        if m and m not in [x["en"] for x in out]:
            out.append({"en": m, "zh": mineral_zh(m)})
    return out


def _mine_nav(loc, mineral):
    """矿点 → 怎么导航过去：Aaron Halo 用小行星带导航（挑这种矿最多的带）；别的星球、卫星、小行星带去导航页搜它"""
    from ..navigation.halo import BANDS

    if loc["kind"] in (
        "Cave",
        "Interior",
    ):  # 校准站矿洞、Breaker 站内部：没有能量子跳的点
        return {"kind": "none", "hint": "不能直接导航"}
    if loc["name"] == "Aaron Halo":
        bands = sorted((r for r in BANDS if mineral in r[5]), key=lambda r: -r[4])
        return {
            "kind": "halo",
            "band": bands[0][0] if bands else 5,
            "hint": f"第{bands[0][0]}带最多"
            if bands
            else "此矿物不是任何一条带的主要矿物，选择密度最高的第5带",
        }
    from ..mining.locations import zh_name

    if re.fullmatch(r"(ARC|CRU|HUR|MIC)-L\d", loc["name"]):
        return {
            "kind": "hint",
            "hint": f"在星图中选择 {loc['name']} 量子跳跃，矿物位于该处小行星中",
        }
    m = re.search(r"\(([^)]+)\)", loc["name"])
    q = m.group(1) if m else loc["name"]
    if loc["kind"] in ("Moon", "Planet") and _nav_search(q=q).get("total"):
        return {
            "kind": "search",
            "q": q,
            "hint": "量子跳跃到此星球或卫星，低空飞行扫描；导航页列出其上的地点",
        }
    return {"kind": "hint", "hint": f"在星图中量子跳跃到 {zh_name(loc)}"}


def mineral_info(name=""):
    from ..mining.data import best_price, REFINERIES, RARITY
    from ..core.i18n import mineral_zh, station_zh
    from ..mining.locations import where, zh_name, _SYS_ZH, _TYPE_ZH

    rows = []
    for pct, loc in where(name)[:30]:
        others = sorted(
            ((best_price(m)[0], m) for m in loc["minerals"] if m != name), reverse=True
        )[:3]
        rows.append(
            {
                "pct": pct,
                "place": zh_name(loc),
                "system": _SYS_ZH[loc["system"]],
                "kind": _TYPE_ZH[loc["kind"]],
                "also": [mineral_zh(m) for p, m in others if p],
                "name": loc["name"],
                "type": loc["kind"],
                "nav": _mine_nav(loc, name),
            }
        )
    price, city = best_price(name)
    bonus = sorted(
        ((b.get(name, 0), st) for st, (sys_, b) in REFINERIES.items()), reverse=True
    )
    uses = ""
    try:
        from ..crafting.crafting import uses_report

        uses = uses_report(name)
    except Exception:
        pass
    try:
        from ..crafting.crafting import mat_summary

        craft_count = mat_summary(name)["count"]
    except Exception:
        craft_count = 0
    from ..mining.gems import GEMS

    gem = GEMS.get(name)
    if gem:  # 地面小矿：不精炼，卖原矿；写类型、信号、终端价、不稳定性、抗性
        gem = {
            "kind": gem["kind"],
            "rs": gem["rs"],
            "price": gem["price"],
            "inst": gem["inst"],
            "res": gem["res"],
        }
    return {
        "en": name,
        "zh": mineral_zh(name),
        "rarity": RARITY.get(name, ""),
        "price": price,
        "city": city or "",
        "gem": gem,
        "craft_count": craft_count,
        "goal": (lambda g: _goal_text(g) if g else "")(
            _goal_for(name, mineral_zh(name))
        ),
        "rows": rows,
        "total": len(where(name)),
        "refine": [
            {"station": station_zh(st), "bonus": b} for b, st in bonus[:3] if b > 0
        ],
        "uses": uses,
    }


__all__ = [
    "search",
    "item_search",
    "nav_shop",
    "trade",
    "market_lookup",
    "market_prices",
    "_market_rows",
    "mineral_search",
    "_mine_nav",
    "mineral_info",
]
