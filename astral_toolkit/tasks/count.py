"""F6 仓库物品盘点任务模块（Task: Inventory Count & Audit）

专职处理：
1. 鼠标悬停网格物品快速读取与解析（_read_item）；
2. 盘点记录与账面库存比对生成对账单（_count_review）；
3. 盘点状态控制与自动化流程（count_toggle, count_state）；
4. 确认盘点对账与差额写入库存、清零确认（count_apply, count_cancel）。
"""

import time
from typing import Any, Dict, List, Optional, Set, Tuple  # noqa: F401

API = {}


# ---------------------------------------------------------------- 依赖（2026-10-30 重构阶段 3：不再经 services 转发）
from ..trade.inspector import (  # noqa: E402
    _read_tooltip,  # noqa: F401
    tooltip_row,  # noqa: F401
    tooltip_quality,  # noqa: F401
    cell_labels,  # noqa: F401
    _is_mineral,  # noqa: F401
)  # noqa: E402, F401
from . import stock as _t_stock  # noqa: E402
from . import trade as _t_trade  # noqa: E402


def trade():
    return _t_trade.trade()


def stock():
    return _t_stock.stock()


def _place_of(location):
    return _t_stock._place_of(location)


def _place_for(location, bin=None):
    return _t_stock._place_for(location, bin)


def scu_amount(qty, unit):
    return _t_stock.scu_amount(qty, unit)


def _invalidate_short():
    _t_stock._invalidate_short()


_count: Any = None
_UNBOUND = "tasks.count 未绑定：先调用 bind(count)"


def bind(count, *, replace: bool = False) -> None:
    """组装处调用一次（B7 由 bootstrap 完成）。导入本模块不再取引擎、不再有副作用"""
    global _count
    if _count is not None and not replace:
        raise RuntimeError(
            "tasks.count 已绑定：生产只绑一次；测试用 replace=True 并在用完后恢复"
        )
    _count = count


def _need_count() -> Any:
    count = _count
    if count is None:
        raise RuntimeError(_UNBOUND)
    return count


# ================================================================ 盘点（F6）核心识别与对账
# 盘点只在区域文件的 count.tooltip 里认说明框（老大 11-09 定）：不走 F8 按鼠标挑的竖带，也不整屏兜底（以前认不出时
# 整屏一次约 2.8 秒）。先认标题那一截（和 F8 标题带同高：屏高 24%~36%，按原尺寸认字），名字在汉化包里精确对上就停；
# 对不上再认整块。区域文件读不了用下面的默认值（和区域文件第 7 版一样）
TOOLTIP = (0.5, 0.1191, 0.7132, 0.8345)
TITLE_ROWS = (0.24, 0.36)


def _tooltip_boxes(size):
    """→ (整块说明框区域, 标题那一截或 None)，像素"""
    from ..core import screen_regions

    W, H = size
    box = screen_regions.px("count.tooltip", TOOLTIP, size)
    title = (
        box[0],
        max(box[1], int(H * TITLE_ROWS[0])),
        box[2],
        min(box[3], int(H * TITLE_ROWS[1])),
    )
    return box, (title if title[3] - title[1] >= H * 0.03 else None)


def _ocr(img, box, label, stage, native):
    from ..ocr import recognize
    from ..trade import debug_shots

    crop = img.crop(box)
    shot = debug_shots.current()
    if shot is not None:
        try:
            shot.add_attempt(label, stage, box, crop)
        except Exception:
            pass
    return recognize(crop, urgent=True, offset=box[:2], native=native)


def _read_item(img, cursor):
    """鼠标指着的物品：{zh, en, quality, qty, unit, sure, craft}；认不出返回 None（调用通用 inspector 组件）"""
    from ..trade import debug_shots
    from ..trade.inspector import _strong_canonical, inspect_item, tooltip_pick

    debug_shots.begin_if_debug()  # 调试开着时，下面两次裁切记进同一份调试图
    box, title = _tooltip_boxes(img.size)
    tokens, where = None, "盘点说明框"
    if title:
        t = _ocr(img, title, "盘点说明框@title", "title", True)
        name, _sure = tooltip_pick(t, cursor, img)
        if name and _strong_canonical(name):
            tokens, where = t, "盘点说明框@title"
    if tokens is None:
        tokens = _ocr(img, box, where, "body", False)
    # 盘点：制造品按蓝图倒推的品质为准，带上各槽品质；标题那截命中的制造品补认加成行也在这块区域里认
    return inspect_item(
        img, cursor, tokens=tokens, where=where, craft_override=True, body_box=box
    )


def _kl(k):
    return [k.item_id, k.quality, k.location, k.unit]


def _id_order(iid):
    """挑一件来记新库存时的先后：交易平台上的正式物品在前、本地物品在后，同类按编号"""
    return (iid.startswith("local:"), iid)


def _count_review(place, items):
    """本轮盘点 → 和账上对：rows（看到的，账上多少 → 游戏里多少）、missing（账上有、这轮没看到；same：和这轮盘到的
    哪件挂着同一个中文名，可能是同一件记在了另一条名下）"""
    from ..crafting import goals as G
    from ..trade.matching import _fold, alias_ok

    t = trade()
    rev = (
        t.inventory.revision()
    )  # 先记版本号再读账：读账这会儿别处写了，确认时才查得出来（二审 2026-10-28）
    book = [
        l
        for l in t.inventory.list_stock()  # noqa: E741
        if _place_of(l.key.location)[0] == place  # noqa: E741
    ]  # noqa: E741
    used, rows = set(), []
    same_zh = {}  # 同一个中文名带出来、没并进来的条目 → 盘到的那件「中文（英文）」（「未盘到」那行注明，审查 2026-11-08 第三轮）
    # 同一物品 + 品质 + 单位分成了几组（制造品各槽品质不同、两个名字是同一物品）：会配到同一批库存行，先合成一行
    # （各槽品质只留第一组的——库存还不分变体，见待做 #10；复审 2026-10-28）
    merged = {}
    for v in items.values():
        ids = frozenset(G.resolve_all(t, v["en"], v["zh"]))
        qkey = "unknown" if v["quality"] is None else f"exact:{int(v['quality'])}"
        ukey = G.USCU if v["unit"] == "SCU" else "unit"
        # 当前地点没库存不代表它和另一个物品同名：英文明确对应的真实目录身份不能丢。
        en = v["en"]
        named = {
            item.id
            for item in (t.catalog.search(en) if en else [])
            if item.name.casefold() == en.casefold()
            and not item.id.startswith("local:")
        }
        alias = t.catalog.by_alias(en) if en and not named else None
        if alias and not alias.id.startswith("local:"):
            named.add(alias.id)
        alias_ids = (
            {i.id for i in t.catalog.all_by_alias(v["zh"])} if v["zh"] else set()
        )
        if named:
            # 英文名明确对上正式物品：只拿它和英文名自己的本地副本（旧库存的另一种记法）去配账。同一个中文名带出来的
            # 别的条目一律不并：英文名像的也可能是另一件东西——F8 模糊配上时会把本体的中文名记到变体上（轻机枪和它的
            # 电池、同一件衣服的几种颜色），并了确认时会悄悄扣掉它的库存（审查 2026-11-08 第三轮）。它们在这个地点
            # 有库存、这轮又没盘到，就进「未盘到」并注明和谁挂着同一个中文名，清不清零让玩家自己定
            kept = frozenset(
                named
                | {
                    item.id
                    for item in t.catalog.search(en)
                    if item.id.startswith("local:")
                    and item.name.casefold() == en.casefold()
                }
            )
        else:
            # 英文名没对上正式物品：英文名带出来的（英文别名、本地副本）照并；中文名带出来的（中文别名、名字就是这个
            # 中文的）要 matching.alias_ok 认是同一件，或者和英文名带出来的哪件同名（旧英文别名只挂在本地副本上、
            # 本地副本和正式物品同名），才并。以前按中文别名直接并：目录里只有电池、电池挂着轻机枪的中文名（F8 以前
            # 模糊配上时记的）时，盘轻机枪 1 会把电池的 20 并进来，确认后电池剩 1（待做 125，老大 2026-11-08）
            by_en = set(G.resolve_all(t, en, "")) if en else set()
            same_names = {_fold(it.name) for iid in by_en if (it := t.catalog.get(iid))}
            kept = frozenset(
                by_en
                | {
                    iid
                    for iid in (set(ids) | alias_ids) - by_en
                    if (it := t.catalog.get(iid))
                    and (alias_ok(it, v["zh"], en) or _fold(it.name) in same_names)
                }
            )
        for iid in (set(ids) | alias_ids) - kept:
            same_zh.setdefault(iid, f"{v['zh']}（{en}）" if v["zh"] else en)
        ids = kept
        real_ids = {
            iid for iid in ids if not iid.startswith("local:") and t.catalog.get(iid)
        }
        lines = [
            line
            for line in book
            if line.key.item_id in ids
            and line.key.quality == qkey
            and line.key.unit == ukey
        ]
        # 候选名可能多带一个账上没有的 id；只要实际命中的库存行相同，就共用一份账面数量。
        matched = frozenset(line.key for line in lines)
        identity = frozenset(
            named
            or {
                line.key.item_id
                for line in lines
                if not line.key.item_id.startswith("local:")
            }
            or real_ids
        )
        # 没配到账上的行时，英文名明确的按它对上的正式物品分组：同一物品两个英文名在新地点也合成一行（审查 2026-11-08）
        k = (
            matched or frozenset(named) or ids or (en or v["zh"]),
            qkey,
            ukey,
            identity,
        )
        if k in merged:
            m, _ = merged[k]
            merged[k] = (
                {
                    **m,
                    "qty": m["qty"] + v["qty"],
                    "cells": m["cells"] + v["cells"],
                },
                lines,
            )
        else:
            # 账上没有、要新入库时记到哪件下面：认定的那几件里 resolve_all 排最前的（能查价的在前）；
            # 一件都没认定就留空，确认时照英文名建本地物品，不再按中文名去找（待做 125）
            order = [i for i in G.resolve_all(t, en, v["zh"]) if i in ids]
            pick = order[0] if order else min(ids, key=_id_order, default=None)
            merged[k] = ({**v, "item_id": pick}, lines)
    for (_, qkey, ukey, _identity), (v, lines) in merged.items():
        have = sum(l.quantity for l in lines)  # noqa: E741
        game = int(round(v["qty"] * 1_000_000)) if ukey == G.USCU else int(v["qty"])
        used.update(l.key for l in lines)  # noqa: E741
        show = (lambda n: scu_amount(n, ukey)) if ukey == G.USCU else (lambda n: n)
        rows.append(
            {
                "zh": v["zh"],
                "en": v["en"],
                "quality": v["quality"],
                "unit": v["unit"],
                "cells": v["cells"],
                "craft": v.get("craft"),
                "book": show(have),
                "game": show(game),
                "delta": show(game - have) if game != have else 0,
                "keys": [_kl(l.key) for l in lines],  # noqa: E741
                "raw_game": game,
                "item_id": v.get("item_id"),
            }
        )  # noqa: E741
    missing = []
    for l in book:  # noqa: E741
        if l.key in used or l.quantity <= 0:
            continue
        item = t.catalog.get(l.key.item_id)
        u = "SCU" if l.key.unit in ("uSCU", "cSCU") else "个"
        missing.append(
            {
                "item": t.label(l.key.item_id),
                "en": item.name if item else l.key.item_id,
                "quality": l.key.quality[6:]
                if l.key.quality.startswith("exact:")
                else "",
                "qty": scu_amount(l.quantity, l.key.unit) if u == "SCU" else l.quantity,
                "unit": u,
                "key": _kl(l.key),
                "same": same_zh.get(l.key.item_id, ""),
            }
        )
    return {
        "place": place,
        "rows": rows,
        "missing": missing,
        "at": time.strftime("%H:%M:%S"),
        "revision": rev,
    }  # 确认时核对：中间改过账就不按这份旧账改（审查 2026-10-28 第 8 条）


# ================================================================ 盘点控制与对账 API
def count_toggle(place=""):
    """盘点开关（窗口按钮；游戏里是 F6）。正在退出时只拦「开」，正在盘点照样能停（RT-B6）"""
    count = _need_count()
    if not count.running():
        from ..app.lifecycle_gate import is_closing

        if is_closing():
            return {"error": "正在退出"}
    if count.running():
        # 选地点框还开着时游戏里已经按 F6 开始了：选了地点不把刚开始的盘点停掉（审查 2026-11-08）
        if place:
            return count_state()
        return count.stop()
    if not isinstance(place, str):
        return {"error": "请选择有效的盘点地点"}
    if place:
        from ..crafting import stockplaces as SP

        try:
            name = SP.check_name(place)
        except ValueError as exc:
            return {"error": str(exc)}
        known = SP.match(name)
        return count.start(place=known["label"] if known else name)
    return count.start()


def count_state():
    count = _need_count()
    return {"running": count.running(), "place": count.place, "review": count.review}


def count_apply(zero=None):
    """确认对账：看到的按游戏里的数改；zero：账上有、这轮没看到、要清零的行（[[物品, 品质, 位置, 单位], …]）"""
    count = _need_count()
    from ..crafting import goals as G
    from ..trade.models import StockKey

    # 先拿走：连点两下「确认」第二下直接提示没有待确认的
    rv = count.take_review()
    if not rv:
        return {"error": "没有待确认的盘点"}
    t = trade()
    _invalidate_short()

    def put(key, n):
        if (
            key in targets
        ):  # 对账时已按库存行合并，到这里还重复说明名字认得不一样：别悄悄覆盖
            raise ValueError(
                "同一物品在盘点里出现了两次（名字不一样），这次没改；取消后在库存页手动改数量"
            )
        targets[key] = n

    # 先把每一行要改成多少算清楚（不写库），再一笔事务写进去：要么全改、要么一行不改（审查 2026-10-28 第 8 条）
    targets, crafts = {}, []
    try:
        for r in rv["rows"]:
            if not r["delta"]:
                continue
            keys = [StockKey(*k) for k in r["keys"]]
            if not keys:  # 账上没有：入库
                # 记到对账时认定的那件下面；没认定的照英文名找或建本地物品，不按中文名去找（中文别名可能记错在
                # 变体上，新库存会记到变体的 id 下，待做 125）
                key, n = G.stock_line(
                    t,
                    r["en"],
                    "" if r["en"] else r["zh"],
                    r["game"],
                    r["unit"],
                    r["quality"],
                    _place_for(rv["place"]),
                    item_id=r.get("item_id"),
                )
                put(key, n)
                if r.get("craft"):
                    crafts.append((key.item_id, key.quality, r["craft"]))
                continue
            if r.get("craft"):
                crafts.append((keys[0].item_id, keys[0].quality, r["craft"]))
            # 好几个仓位都有：多出来的记在第一个仓位；少了的从各仓位依次扣（审查 2026-10-28：以前只扣第一个、不够就截成 0，总数对不上）
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
        t.inventory.apply_count(
            list(targets.items()), rv.get("revision"), source="盘点"
        )
    except ValueError as e:  # 一行都没改：库存变过了要重新盘；别的错把这轮对账放回去
        count.publish_review(restore=rv if "重新盘点" not in str(e) else None)
        return {"error": str(e)}
    except Exception:  # 数据库出错之类：对账放回去，窗口里还能再点确认
        count.publish_review(restore=rv)
        raise
    for iid, q, slots in crafts:  # 制造品各槽品质：不是库存数，批次写完再记
        try:
            t.inventory.set_craft(iid, q, slots)
        except Exception:
            pass
    # take_review 已消费旧对账；提交期间另一轮可能收尾，不清掉它的新对账。
    count.publish_review()
    return stock()


def count_cancel():
    count = _need_count()
    count.publish_review(clear=True)
    return {"ok": True}


API_FUNCTIONS = [
    count_toggle,
    count_state,
    count_apply,
    count_cancel,
]
API.update(
    {f.__name__: f for f in API_FUNCTIONS}
)  # 原来由 api 装饰器填，名字照旧（接口改由 app/api/vision.py 注册）

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
