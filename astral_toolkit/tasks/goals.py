"""制造与目标规划任务模块（Task: Goals, Crafting & Wikelo Exchanges）

专职处理：
1. 制造查询、分类检索、槽位结构化解析、属性计算与混料算法的旧壳（用例已搬到 tasks/crafting.py）；
2. 目标规划（联动库存、计算材料缺口、市价估算、目标材料扣减及直接入库）；
3. Wikelo 特殊兑换搜索与材料需求解析的旧壳（用例已搬到 tasks/wikelo.py）；
4. 采矿/悬停识别等模块所需的目标材料缺口判定与标记 (_goal_for, _mark_goal_lines 等)。
"""

from concurrent.futures import ThreadPoolExecutor
import re
import time

try:
    from ..crafting import goals as G
except ImportError:
    from ..crafting import goals as G

from ..crafting.crafting import by_key, effect, laser_total, material_zh, slot_zh
from ..trade.console import SOURCE_ZH


# ---------------------------------------------------------------- 依赖：交易库、库存地点
# 2026-10-30 重构阶段 2：直接用 tasks 里的交易库和库存地点，不再经 services 转发、出错也不再回头找 services 兜底。
from .trade import trade

from . import crafting as _crafting_uc
from . import wikelo as _wikelo_uc
from ..app.presenters import crafting as _present_crafting
from ..app.presenters import wikelo as _present_wikelo


def _place_for(location, bin=None):
    from . import (
        stock,
    )  # 在函数里 import：stock 也在函数里引用 goals，取模块属性，测试换掉的名字能打中

    return stock._place_for(location, bin)


# ---------------------------------------------------------------- 内部状态与缓存
_SHORT = {"t": 0.0, "map": {}}


def clear_caches():
    """更新数据后清掉接口层的缓存"""
    _crafting_uc.clear_caches()
    _wikelo_uc.clear_caches()
    _SHORT.update(t=0.0, map={})


try:
    from ..update.data_pack import CACHE_HOOKS as _CACHE_HOOKS

    _CACHE_HOOKS.append(clear_caches)
except Exception:
    pass


# ---------------------------------------------------------------- 目标：库存联动维科洛兑换 / 制造 / 交易
def _gkey(name):
    """目标材料和矿 / 物品对名字用：忽略大小写、空格和「(Ore)」「(Raw)」「原矿」这类后缀"""
    n = re.sub(
        r"\s*[\(（](ore|raw|原矿|矿石)[\)）]\s*$", "", (name or "").strip(), flags=re.I
    )
    n = re.sub(r"(原矿|矿石)$", "", n)
    return re.sub(r"\s+", "", n.lower())


def goal_short(force=False):
    """目标还缺的材料：{名字键: {en, zh, short, unit, minq, goals}}，英文名和中文名都能查。算一次记 30 秒；
    目标或库存一改就清掉重算"""
    now = time.time()
    if not force and now - _SHORT["t"] < 30:
        return _SHORT["map"]
    m = {}
    try:
        if G.load():
            for t in G.plan(trade())["shortfall"]:
                for k in {_gkey(t["en"]), _gkey(t["zh"])} - {""}:
                    m[k] = t
    except Exception:
        m = {}
    _SHORT.update(t=now, map=m)
    return m


def _goal_for(*names):
    sm = goal_short()
    for n in names:
        if n and _gkey(n) in sm:
            return sm[_gkey(n)]
    return None


def _goal_text(t, q=None, lots=None):
    """「🎯 目标还缺 金 2 SCU（品质 ≥800，这块 650 不够）」。
    lots：扫描结果里这种矿的每一份（1.6.42）：同一种矿有几种品质时逐份写够不够，
    「品质 ≥600：662 那份够（精炼后 1.50 SCU），363 那份不够」"""
    amt = f"{t['short']:g} {t['unit']}" if t.get("unit") else f"{t['short']:g}"
    need_q = f"品质 ≥{t['minq']}" if t.get("minq", 0) > 1 else ""
    known = [r for r in (lots or []) if r.get("q") is not None]
    if need_q and len(known) >= 2:
        parts = []
        for r in sorted(known, key=lambda r: -r["q"]):
            good = r["q"] >= t["minq"]
            v = r.get("refined")
            got = (
                ""
                if not v
                else f"（精炼后 {v:.2f} SCU）"
                if v >= 1
                else f"（精炼后 {v * 1e6:,.0f} uSCU）"
            )
            parts.append(f"品质 {r['q']}：" + ("已达标" + got if good else "未达标"))
        need_q += "：" + "，".join(parts)
    elif q is not None and need_q:
        need_q += f"，当前 {q} " + ("已达标" if q >= t["minq"] else "未达标")
    return f"🎯 目标缺少 {t['zh'] or t['en']} {amt}" + (
        f"（{need_q}）" if need_q else ""
    )


def _mark_goal_lines(lines):
    """信号说明里有目标还缺的矿：行首加 🎯"""
    pats = []
    for t in goal_short().values():
        if t.get("zh"):  # 整词匹配：目标要「金」，不能把「林登金」「艾格瑞金属」也标上
            pats.append(
                re.compile(
                    f"(?<![\u4e00-\u9fff]){re.escape(t['zh'])}(?![\u4e00-\u9fff])"
                )
            )
        if t.get("en"):
            pats.append(re.compile(rf"\b{re.escape(t['en'])}\b", re.I))
    return [("🎯 " + l) if any(p.search(l) for p in pats) else l for l in lines]  # noqa: E741


def crafting_zh(opt):
    """蓝图材料的中文名（手挖的萨达瑞晶、哈丹水晶这些也有中文名，1.6.41 以前显示英文）"""
    k, name, *_ = opt
    return material_zh(name)


def _goals_view():
    t = trade()
    p = G.plan(t)
    p["last_location"] = t.db.get("last_location", "")
    for g in p["goals"]:
        for r in g["rows"]:
            if r["short"] > 0:
                r["tip"] = _present_wikelo.source_text(G.where_to_get(r["en"]))
    for t_item in p["shortfall"]:
        t_item["tip"] = _present_wikelo.source_text(G.where_to_get(t_item["en"]))
    for g in p["goals"]:
        if g.get("kind") != "craft" or g.get("missing"):
            continue
        bp = by_key(g["ref"])
        if not bp:
            continue
        # 每个材料槽的品质：先用分给它的库存的加权平均品质（混着做出来就是这个品质）
        qs = {}
        for idx, (slot, opts, mods) in enumerate(bp["slots"]):
            row = next((r for r in g["rows"] if r["slot"] == slot), None)
            qs[idx] = row.get("avg_q") if row else None
        g["slots_q"] = [
            {
                "idx": i,
                "slot": slot_zh(sl),
                "has_mods": bool(m),
                "material": "/".join(crafting_zh(o) for o in opts),
                "q": qs[i],
                "minq": max([x[3] for x in opts] + [0]),
            }
            for i, (sl, opts, m) in enumerate(bp["slots"])
        ]
        g["effect"] = effect(bp, {i: q for i, q in qs.items() if q is not None})
        g["effect_total"] = (
            laser_total(bp, {i: q for i, q in qs.items() if q is not None})
            if g["effect"]
            else None
        )
        st = _craft_struct(bp)  # 1.6.47：目标页和制造页共用槽位卡片 + 属性统计
        for sl in st["slots"]:
            sl["q"] = qs.get(sl["idx"])
        g["craft"] = {"head": st["head"], "slots": st["slots"]}
    return p


def goals():
    return _goals_view()


def goal_finish_preview(id=""):
    """目标「做完了」之前先看要扣哪些材料（做一次的量）"""
    try:
        takes, short = G.finish_takes(trade(), id)
    except ValueError as e:
        return {"error": str(e)}
    g = next((x for x in G.load() if x["id"] == id), {})
    return {
        "title": g.get("title", ""),
        "times": g.get("times", 1),
        "short": short,
        "takes": [
            {
                "name": x["zh"] or x["en"],
                "place": x["place"],
                "quality": x["quality"],
                "qty": x["qty"],
                "unit": x["unit"],
            }
            for x in (takes or [])
        ],
    }


def goal_finish(id=""):
    """目标「做完了」：从库存扣掉做一次用掉的材料（库存页的记录里能撤销），次数减一，最后一次做完就删掉这个目标"""
    _SHORT["t"] = 0.0
    try:
        r = G.finish(trade(), id)
    except ValueError as e:
        return {"error": str(e)}
    out = _goals_view()
    out["finished"] = {"title": r["title"], "left": r["left"], "lines": len(r["taken"])}
    return out


def goal_add(kind="", ref="", times=1):
    _SHORT["t"] = 0.0
    try:
        G.add(kind, ref, int(times or 1))
    except ValueError as e:
        return {"error": str(e)}
    return _goals_view()


def goal_update(id="", times=None, move=0, remove=False):
    _SHORT["t"] = 0.0
    try:
        G.update(
            id,
            None if times in (None, "") else int(times),
            int(move or 0),
            bool(remove),
        )
    except ValueError as e:
        return {"error": str(e)}
    return _goals_view()


def goal_stock_add(en="", zh="", qty=0, unit="", quality="", location=""):
    """目标页里直接入库（交易库里没有的材料自动建成本地物品）"""
    _SHORT["t"] = 0.0
    try:
        G.add_stock(
            trade(), en, zh, qty, unit, quality, _place_for(location), source="目标"
        )
    except ValueError as e:
        return {"error": str(e)}
    return _goals_view()


def goal_prices():
    """还差的东西在玩家市场（UEX / SCM）上最便宜多少钱，合计大概要花多少（同时查，结果缓存）"""
    t = trade()
    todo = G.plan(t)["shortfall"]

    def one(x):
        try:
            iid = x["item"]
            if not iid:  # 交易库里还没有：按英文名去玩家市场搜一次，名字完全一样才算
                items, _ = t.market.lookup(x["en"])
                hit = next(
                    (i for i in items if i.name.casefold() == x["en"].casefold()), None
                )
                if not hit:
                    return x, None
                if x["zh"]:
                    t.catalog.add_alias(hit.id, x["zh"])
                iid = hit.id
            return x, G.market_price(t, iid, x["minq"], x["unit"])
        except Exception:
            return x, None

    rows, total, priced = [], 0.0, 0
    with ThreadPoolExecutor(4) as ex:
        for x, best in ex.map(one, todo):
            if best:
                price, src, unit, cur = best
                cost = float(price) * x["short"]
                total += cost
                priced += 1
                rows.append(
                    {
                        "en": x["en"],
                        "minq": x["minq"],
                        "unit": x["unit"],
                        "price": float(price),
                        "price_unit": unit,
                        "currency": cur,
                        "src": SOURCE_ZH.get(src, src),
                        "cost": cost,
                    }
                )
            else:
                rows.append(
                    {"en": x["en"], "minq": x["minq"], "unit": x["unit"], "price": None}
                )
    return {
        "rows": rows,
        "total": total,
        "priced": priced,
        "unpriced": len(rows) - priced,
    }


# ---------------------------------------------------------------- 维科洛兑换
# 旧壳：用例在 tasks/crafting.py、tasks/wikelo.py，排版在 app/presenters/；全局搜索、目标页、测试还在调，B5 换调用方、B6 删
def wikelo_search(q=""):
    return _present_wikelo.present_search(_wikelo_uc.search_exchanges(q))


def wikelo_detail(key=""):
    return _present_wikelo.present_detail(_wikelo_uc.exchange_detail(key))


# ---------------------------------------------------------------- 制造与蓝图
# 旧壳：用例在 tasks/crafting.py、tasks/wikelo.py，排版在 app/presenters/；全局搜索、目标页、测试还在调，B5 换调用方、B6 删
def craft_effect(key="", qualities=None):
    return _crafting_uc.craft_effect(key, qualities)


def craft_search(q=""):
    return _present_crafting.present_search(_crafting_uc.search_blueprints(q))


def craft_browse(
    cat="", sub="", part="", maker="", q="", unlocked=False, offset=0, mat="", mq=None
):
    return _present_crafting.present_browse(
        _crafting_uc.browse_blueprints(
            cat, sub, part, maker, q, unlocked, offset, mat, mq
        )
    )


def _craft_struct(bp, note=""):
    return _present_crafting.present_struct(_crafting_uc.struct_facts(bp, note))


def craft_detail(key=""):
    return _present_crafting.present_detail(_crafting_uc.blueprint_detail(key))


def craft_stats(key="", qualities=None):
    return _crafting_uc.craft_stats(key, qualities)


def craft_mix(need=0, target=0, margin=2, boxes=()):
    return _crafting_uc.craft_mix(need, target, margin, boxes)


__all__ = [
    # 状态与缓存
    "_SHORT",
    "clear_caches",
    # 内部辅助函数
    "_gkey",
    "goal_short",
    "_goal_for",
    "_goal_text",
    "_mark_goal_lines",
    "crafting_zh",
    "_goals_view",
    "_craft_struct",
    # 目标管理函数
    "goal_finish_preview",
    "goal_finish",
    "goals",
    "goal_add",
    "goal_update",
    "goal_stock_add",
    "goal_prices",
    # 制造与蓝图
    "craft_effect",
    "craft_search",
    "craft_browse",
    "craft_detail",
    "craft_stats",
    "craft_mix",
    # 维科洛兑换
    "wikelo_search",
    "wikelo_detail",
]
