"""F6 仓库物品盘点任务模块（Task: Inventory Count & Audit）

从 app/services.py 中解耦出来，专职处理：
1. 鼠标悬停网格物品快速读取与解析（_read_item）；
2. 盘点记录与账面库存比对生成对账单（_count_review）；
3. 盘点状态控制与自动化流程（count_toggle, count_state）；
4. 确认盘点对账与差额写入库存、清零确认（count_apply, count_cancel）。
"""
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from ..app import bus

API = {}


def api(fn):
    """标记为暴露给前端的 API 函数（名字就是接口路径 /api/<fn_name>）"""
    API[fn.__name__] = fn
    return fn


# ---------------------------------------------------------------- 依赖转发与辅助
def _services():
    from ..app import services
    return services


def trade():
    return _services().trade()


def stock():
    try:
        from .stock import stock as _st
        return _st()
    except Exception:
        return _services().stock()


def _place_of(location):
    try:
        from .stock import _place_of as _po
        return _po(location)
    except Exception:
        return _services()._place_of(location)


def _place_for(location, bin=None):
    try:
        from .stock import _place_for as _pf
        return _pf(location, bin)
    except Exception:
        return _services()._place_for(location, bin)


def scu_amount(qty, unit):
    try:
        from .stock import scu_amount as _sa
        return _sa(qty, unit)
    except Exception:
        return _services().scu_amount(qty, unit)


def _invalidate_short():
    try:
        from .stock import _invalidate_short as _inv
        _inv()
    except Exception:
        try:
            _services()._SHORT["t"] = 0.0
        except Exception:
            pass


def _read_tooltip(img, cursor):
    try:
        from .hover import _read_tooltip as _rt
        return _rt(img, cursor)
    except Exception:
        return _services()._read_tooltip(img, cursor)


def tooltip_row(tokens):
    try:
        from .hover import tooltip_row as _tr
        return _tr(tokens)
    except Exception:
        return _services().tooltip_row(tokens)


def tooltip_quality(tokens):
    try:
        from .hover import tooltip_quality as _tq
        return _tq(tokens)
    except Exception:
        return _services().tooltip_quality(tokens)


def cell_labels(img, cursor):
    try:
        from .hover import cell_labels as _cl
        return _cl(img, cursor)
    except Exception:
        return _services().cell_labels(img, cursor)


def _is_mineral(zh, en):
    try:
        from .hover import _is_mineral as _im
        return _im(zh, en)
    except Exception:
        try:
            return _services()._is_mineral(zh, en)
        except Exception:
            return False


# ---------------------------------------------------------------- 盘点引擎单例代理
_local_count = None


class _CountProxy:
    def _target(self):
        global _local_count
        try:
            s = _services()
            if hasattr(s, "_count"):
                return s._count
        except Exception:
            pass
        if _local_count is None:
            from ..app.engines.count import _Count
            _local_count = _Count()
        return _local_count

    def __getattr__(self, name):
        return getattr(self._target(), name)

    def __setattr__(self, name, value):
        setattr(self._target(), name, value)


_count = _CountProxy()


# ================================================================ 盘点（F6）核心识别与对账
def _read_item(img, cursor):
    """鼠标指着的物品：{zh, en, quality, qty, unit, sure}；认不出返回 None（和 F8 用同一套识别）"""
    from ..trade.names import canonical
    tokens, name, _where = _read_tooltip(img, cursor)
    if not name:
        return None
    zh, en = name
    canon = canonical(zh, en)
    if canon:
        zh, en = canon
    row_q, row_amt = tooltip_row(tokens)
    if row_q is None:
        row_q = tooltip_quality(tokens)
    try:
        cell_q, cell_n = cell_labels(img, cursor)
    except Exception:
        cell_q, cell_n = None, None
    mineral = _is_mineral(zh, en)
    quality = row_q if row_q is not None else cell_q if cell_q is not None else (None if mineral else 0)
    qty, unit = (row_amt, "SCU") if mineral else ((cell_n or 1), "个")
    craft = None
    if not mineral:                  # 1.6.67：制造出来的东西没有品质数，只有加成行 → 按蓝图倒推各材料槽的品质，记平均
        try:
            from ..crafting import parse_mods, solve_slots, for_item
            mods = parse_mods(tokens)
            res = solve_slots(for_item(en, zh), mods) if mods else None
            if res and res["exact"]:                       # 加成对不上蓝图：不当品质（Codex 2026-10-27）
                quality, craft = res["avg"], res["slots"]
            elif res and row_q is None and cell_q is None:  # 没直接读到品质、倒推又对不上：品质未知，不记成 0
                quality = None
        except Exception:
            craft = None
    return {"zh": zh, "en": en, "quality": quality, "qty": qty, "unit": unit, "sure": bool(canon), "craft": craft}


def _kl(k):
    return [k.item_id, k.quality, k.location, k.unit]


def _count_review(place, items):
    """本轮盘点 → 和账上对：rows（看到的，账上多少 → 游戏里多少）、missing（账上有、这轮没看到）"""
    from .. import goals as G
    t = trade()
    rev = t.inventory.revision()                       # 先记版本号再读账：读账这会儿别处写了，确认时才查得出来（二审 2026-10-28）
    book = [l for l in t.inventory.list_stock() if _place_of(l.key.location)[0] == place]
    used, rows = set(), []
    # 同一物品 + 品质 + 单位分成了几组（制造品各槽品质不同、两个名字是同一物品）：会配到同一批库存行，先合成一行
    # （各槽品质只留第一组的——库存还不分变体，见待做 #10；复审 2026-10-28）
    merged = {}
    for v in items.values():
        ids = frozenset(G.resolve_all(t, v["en"], v["zh"]))
        qkey = "unknown" if v["quality"] is None else f"exact:{int(v['quality'])}"
        ukey = G.USCU if v["unit"] == "SCU" else "unit"
        k = (ids or (v["en"] or v["zh"]), qkey, ukey)
        if k in merged:
            m = merged[k]
            merged[k] = {**m, "qty": m["qty"] + v["qty"], "cells": m["cells"] + v["cells"]}
        else:
            merged[k] = v
    for (ids, qkey, ukey), v in merged.items():
        ids = ids if isinstance(ids, frozenset) else frozenset()
        lines = [l for l in book if l.key.item_id in ids and l.key.quality == qkey and l.key.unit == ukey]
        have = sum(l.quantity for l in lines)
        game = int(round(v["qty"] * 1_000_000)) if ukey == G.USCU else int(v["qty"])
        used.update(l.key for l in lines)
        show = (lambda n: scu_amount(n, ukey)) if ukey == G.USCU else (lambda n: n)
        rows.append({"zh": v["zh"], "en": v["en"], "quality": v["quality"], "unit": v["unit"], "cells": v["cells"], "craft": v.get("craft"),
                     "book": show(have), "game": show(game), "delta": show(game - have) if game != have else 0,
                     "keys": [_kl(l.key) for l in lines], "raw_game": game})
    missing = []
    for l in book:
        if l.key in used or l.quantity <= 0:
            continue
        item = t.catalog.get(l.key.item_id)
        u = "SCU" if l.key.unit in ("uSCU", "cSCU") else "个"
        missing.append({"item": t.label(l.key.item_id), "en": item.name if item else l.key.item_id,
                        "quality": l.key.quality[6:] if l.key.quality.startswith("exact:") else "",
                        "qty": scu_amount(l.quantity, l.key.unit) if u == "SCU" else l.quantity, "unit": u,
                        "key": _kl(l.key)})
    return {"place": place, "rows": rows, "missing": missing, "at": time.strftime("%H:%M:%S"),
            "revision": rev}                          # 确认时核对：中间改过账就不按这份旧账改（老大审查 2026-10-28 第 8 条）


# ================================================================ 盘点控制与对账 API
@api
def count_toggle():
    """盘点开关（窗口按钮；游戏里是 F6）"""
    return _count.stop() if _count.running() else _count.start()


@api
def count_state():
    return {"running": _count.running(), "place": _count.place, "review": _count.review}


@api
def count_apply(zero=None):
    """确认对账：看到的按游戏里的数改；zero：账上有、这轮没看到、要清零的行（[[物品, 品质, 位置, 单位], …]）"""
    from .. import goals as G
    from ..trade.models import StockKey
    rv, _count.review = _count.review, None             # 先拿走：连点两下「确认」第二下直接提示没有待确认的
    if not rv:
        return {"error": "没有待确认的盘点"}
    t = trade()
    _invalidate_short()

    def put(key, n):
        if key in targets:                              # 对账时已按库存行合并，到这里还重复说明名字认得不一样：别悄悄覆盖
            raise ValueError("同一物品在盘点里出现了两次（名字不一样），这次没改；取消后在库存页手动改数量")
        targets[key] = n
    # 先把每一行要改成多少算清楚（不写库），再一笔事务写进去：要么全改、要么一行不改（老大审查 2026-10-28 第 8 条）
    targets, crafts = {}, []
    try:
        for r in rv["rows"]:
            if not r["delta"]:
                continue
            keys = [StockKey(*k) for k in r["keys"]]
            if not keys:                                # 账上没有：入库
                key, n = G.stock_line(t, r["en"], r["zh"], r["game"], r["unit"], r["quality"], _place_for(rv["place"]))
                put(key, n)
                if r.get("craft"):
                    crafts.append((key.item_id, key.quality, r["craft"]))
                continue
            if r.get("craft"):
                crafts.append((keys[0].item_id, keys[0].quality, r["craft"]))
            # 好几个仓位都有：多出来的记在第一个仓位；少了的从各仓位依次扣（老大审查 2026-10-28：以前只扣第一个、不够就截成 0，总数对不上）
            qs = [t.inventory._quantity_of(k) for k in keys]
            total, target = sum(qs), r["raw_game"]
            if target >= total:
                put(keys[0], qs[0] + (target - total))
            else:
                need = total - target
                for k, q in zip(keys, qs):
                    take = min(q, need)
                    if take > 0:
                        put(k, q - take)
                        need -= take
                    if need <= 0:
                        break
        want = {tuple(k) for k in (zero or [])}
        for m in rv["missing"]:
            if tuple(m["key"]) in want:
                put(StockKey(*m["key"]), 0)
        t.inventory.apply_count(list(targets.items()), rv.get("revision"), source="盘点")
    except ValueError as e:                             # 一行都没改：库存变过了要重新盘；别的错把这轮对账放回去
        if "重新盘点" not in str(e) and _count.review is None and not _count.running():
            _count.review = rv
        else:
            bus.publish("count", {"running": _count.running(), "review": None})
        return {"error": str(e)}
    except Exception:                                   # 数据库出错之类：对账放回去，窗口里还能再点确认
        if _count.review is None and not _count.running():
            _count.review = rv
        raise
    for iid, q, slots in crafts:                        # 制造品各槽品质：不是库存数，批次写完再记
        try:
            t.inventory.set_craft(iid, q, slots)
        except Exception:
            pass
    _count.review = None
    bus.publish("count", {"running": _count.running(), "review": None})
    return stock()


@api
def count_cancel():
    _count.review = None
    bus.publish("count", {"running": _count.running(), "review": None})
    return {"ok": True}


API_FUNCTIONS = [
    count_toggle,
    count_state,
    count_apply,
    count_cancel,
]

__all__ = [
    "_read_item",
    "_kl",
    "_count_review",
    "_count",
    "count_toggle",
    "count_state",
    "count_apply",
    "count_cancel",
    "API",
    "API_FUNCTIONS",
]
