"""目标：玩家定下要换的维科洛兑换 / 要造的东西，对照库存算出还差什么、去哪弄、大概多少钱

- 目标存在 userdata/goals.json：[{id, kind: wikelo|craft, ref, times, title}]，按列表顺序就是优先级
- 库存来自交易模块的库存（和「库存」页同一份数据）
- 几个目标要同一种东西时，按优先级先满足排在前面的，同一份库存不重复算
- 制造的品质门槛：库存里品质够的才算；品质「未知」的单独提示，不算进已有
- 制造的某个部件有几种材料可选时，挑「还差得最少」的那种

2026-11-26 拆出去三块（只搬家，行为不变），名字照旧从这里拿：
- goal_list：目标清单存取（goals.json）
- goal_needs：每个目标要什么
- goal_market：去哪弄、市价
留在这里的是库存那几块（挑批次、认物品、按优先级分库存、完成时扣库存、入库），库存重做时一起处理。
测试要换 goals.json 的位置，换 goal_list.FILE（换这里的没用）。
"""

from .goal_list import _LOCK, _load_strict, _update, load
from .goal_list import add as add, save as save, update as update  # 只是转出去
from .goal_market import PER_SCU as PER_SCU  # 只是转出去
from .goal_market import market_price as market_price
from .goal_needs import requirements

# 交易模块的品质档 → 这一档最低品质（qN 只知道在哪一档，按下限算才不会高估）
GROUP_FLOOR = {
    "q0": 0,
    "q1": 1,
    "q2": 500,
    "q3": 600,
    "q4": 700,
    "q5": 800,
    "q6": 900,
    "q7": 950,
}


# ---------------------------------------------------------------- 库存


def _quality_floor(q):
    """库存里的品质 → 至少多少；未知返回 None"""
    if q.startswith("exact:"):
        try:
            return int(q[6:])
        except ValueError:
            return None
    return GROUP_FLOOR.get(q)


CSCU = "cSCU"  # 1.6.36 以前：矿、材料按 0.01 SCU 记（启动时会换算成 uSCU，这里只为读没换算的旧记录）
USCU = "uSCU"  # 矿、材料按百万分之一 SCU 记（库存数量只能是整数，0.495 SCU 记成 495000 uSCU；游戏里显示到 0.001 SCU）


RESERVED = "stock_reserved"  # 库存页标了「不给目标用」的行（物品|品质|位置|单位），目标不算它们


def lot_key(item_id, quality, location, unit):
    return f"{item_id}|{quality}|{location}|{unit}"


def reserved_keys(trade):
    try:
        return set(trade.db.get(RESERVED, []) or [])
    except Exception:
        return set()


def stock_lots(trade, include_reserved=False):
    """{物品 id: [[品质下限或 None, 品质显示, 位置, 数量, 单位, 品质键, 物品 id], …]}；uSCU / cSCU 已换算成 SCU。
    库存页标了「不给目标用」的行不算（include_reserved=True 时也算上）"""
    lots = {}
    skip = set() if include_reserved else reserved_keys(trade)
    for line in trade.inventory.list_stock():
        k = line.key
        if lot_key(k.item_id, k.quality, k.location, k.unit) in skip:
            continue
        f = _quality_floor(k.quality)
        label = (
            k.quality.replace("exact:", "品质 ")
            if k.quality.startswith("exact:")
            else ("品质未知" if f is None else k.quality.upper())
        )
        qty = (
            line.quantity / 1e6
            if k.unit == USCU
            else line.quantity / 100
            if k.unit == CSCU
            else line.quantity
        )
        lots.setdefault(k.item_id, []).append(
            [f, label, k.location, qty, k.unit, k.quality, k.item_id]
        )
    return lots


def local_id(en):
    return "local:" + en


def resolve_all(trade, en, zh=""):
    """材料名 → 库存里可能记着它的所有物品 id（市场上的正式物品 + 本地物品），第一个是能查价的。
    英文名带出来的（英文别名、名字就是它的、本地副本）都算；按中文别名找到的要 matching.alias_ok 认是同一件，或者和英文名
    带出来的哪件同名，才算——中文别名可能是 F8 以前模糊配上时记错的（本体的中文名记到了变体上、原矿的记到了精炼上），
    信了会把别的东西的库存算成「已有」、完成目标时扣错（老大 2026-11-08 定直接修；和盘点 tasks/count 同一条规则）。
    名字就是这个中文名的物品照算"""
    from ..trade.matching import _fold, alias_ok

    ids = []
    if en:
        item = trade.catalog.by_alias(en)
        if item:
            ids.append(item.id)
        ids += _same_name(trade, en)
    if zh:
        same = {_fold(it.name) for iid in ids if (it := trade.catalog.get(iid))}
        ids += [
            i.id
            for i in trade.catalog.all_by_alias(zh)
            if alias_ok(i, zh, en) or _fold(i.name) in same
        ]
        ids += _same_name(trade, zh)
    if trade.catalog.get(local_id(en)):
        ids.append(local_id(en))
    ids = list(dict.fromkeys(ids))
    ids.sort(key=lambda i: i.startswith("local:"))
    return ids


def _same_name(trade, name):
    """名字一字不差（不分大小写）就是 name 的物品 id"""
    return [
        i.id for i in trade.catalog.search(name) if i.name.casefold() == name.casefold()
    ]


def resolve(trade, en, zh=""):
    """能查价的那个物品 id（只有本地物品时返回本地物品；什么都没有返回 None）"""
    ids = resolve_all(trade, en, zh)
    return ids[0] if ids else None


def ensure_item(trade, en, zh=""):
    """确保库存能记这个材料：交易库里没有就建一个本地物品（和 F8 入库时「记成本地物品」一样）"""
    iid = resolve(trade, en, zh)
    if iid:
        return iid
    from ..trade.models import Item

    item = Item(local_id(en), en)
    trade.catalog.upsert([item])
    if zh:
        trade.catalog.add_alias(item.id, zh)
    return item.id


SCU_UNITS = (USCU, CSCU, "SCU")


def unit_fits(lot, unit):
    """库存这一行能不能算进需求：要 SCU 的只拿按 SCU 记的行，要「个」的只拿按个记的行（混着算会把 5 个当 5 SCU，扣料也扣错）"""
    return (lot[4] in SCU_UNITS) == (unit == "SCU")


def other_unit(lots, unit):
    """单位对不上、没算进来的库存（如需求按个、库存按 SCU 记）→「3 SCU」「5 个」；没有返回空串。别静默丢掉，让玩家知道为什么没算"""
    n = sum(l[3] for l in lots if l[3] > 0 and not unit_fits(l, unit))  # noqa: E741
    if n <= 0:
        return ""
    if unit == "SCU":  # 对不上的是按个记的
        return f"{round(n):d} 个"
    return (
        f"{n:.6f}".rstrip("0").rstrip(".") + " SCU"
    )  # 到 1 uSCU，不出「0 SCU」和科学计数法


def _take(lots, need, minq):
    """从库存里拿 need：先拿品质刚好够的（高品质留给更挑的目标）。返回 (拿到多少, [(位置, 品质, 数量)], 品质未知的有多少)"""
    got, used, unknown = 0.0, [], 0
    # 没有品质要求时，品质未知的也能用（而且先用它们，把知道品质的留给有门槛的目标）
    usable = sorted(
        (
            l
            for l in lots  # noqa: E741
            if l[3] > 0
            and (l[0] is not None and l[0] >= minq or (l[0] is None and not minq))
        ),  # noqa: E741
        key=lambda l: -1 if l[0] is None else l[0],  # noqa: E741
    )  # noqa: E741
    for lot in usable:
        if got >= need - 1e-9:
            break
        take = min(lot[3], need - got)
        lot[3] -= take
        got += take
        used.append(
            (
                lot[2],
                lot[1],
                take,
                lot[0],
                (lot[6], lot[5], lot[2], lot[4]) if len(lot) > 6 else None,
            )
        )
    if got < need - 1e-9 and minq:
        unknown = sum(l[3] for l in lots if l[0] is None and l[3] > 0)  # noqa: E741
    return got, used, unknown


def _slot_zh(slot):
    from .crafting import slot_zh

    return slot_zh(slot) if slot else ""


def _avg_quality(used):
    """分到这个目标的库存按数量加权的平均品质（混在一起做，成品就是这个品质）；没有已知品质的返回 None"""
    known = [(f, qty) for _loc, _q, qty, f, *_ in used if f is not None and qty > 0]
    tot = sum(qty for _f, qty in known)
    return round(sum(f * qty for f, qty in known) / tot) if tot else None


def plan(trade=None, goals=None):
    """按优先级把库存分给每个目标，算出每样还差多少"""
    if trade is None:
        try:
            from ..tasks.trade import trade as _t

            trade = _t()
        except Exception:
            from ..trade.console import Trade

            trade = Trade()
    goals = load() if goals is None else goals
    pool = stock_lots(trade)
    ids = {}

    def ids_of(alt):
        key = (alt["en"], alt["zh"])
        if key not in ids:
            ids[key] = resolve_all(trade, alt["en"], alt["zh"])
        return ids[key]

    out, total, alloc = [], {}, {}
    for g in goals:
        reqs = requirements(g)
        if reqs is None:
            out.append({**g, "missing": True, "rows": [], "progress": 0})
            continue
        rows = []
        for req in reqs:
            best = None
            for n, alt in enumerate(
                req["alts"]
            ):  # 几种材料可选：每种都试拿一下，挑还差最少的
                own = [
                    lot
                    for i in ids_of(alt)
                    for lot in pool.get(i, [])
                    if unit_fits(lot, alt["unit"])
                ]
                trial = [lot[:] for lot in own]
                got, used, unknown = _take(trial, alt["qty"], alt["minq"])
                short = max(0.0, alt["qty"] - got)
                cand = (short / alt["qty"] if alt["qty"] else 0, n)
                if best is None or cand < best[0]:
                    best = (cand, alt, got, used, unknown, own, trial)
            _, alt, got, used, unknown, own, trial = best
            for lot, after in zip(own, trial):  # 真的拿走
                lot[3] = after[3]
            for (
                _loc,
                _q,
                qty,
                _f,
                key,
            ) in used:  # 库存页「目标占用」：每行分给了哪些目标、多少
                if key and qty > 0:
                    a = alloc.setdefault(lot_key(*key), {"qty": 0.0, "goals": []})
                    a["qty"] = round(a["qty"] + qty, 6)
                    if g["title"] not in a["goals"]:
                        a["goals"].append(g["title"])
            iid = (ids_of(alt) or [None])[0]
            wrong = other_unit(
                [lot for i in ids_of(alt) for lot in pool.get(i, [])], alt["unit"]
            )
            short = round(max(0.0, alt["qty"] - got), 4)
            rows.append(
                {
                    "slot": req["slot"],
                    "slot_zh": _slot_zh(req["slot"]),
                    "en": alt["en"],
                    "zh": alt["zh"],
                    "item": iid,
                    "local": bool(iid and iid.startswith("local:")),
                    "need": round(alt["qty"], 4),
                    "have": round(got, 4),
                    "short": short,
                    "unit": alt["unit"],
                    "minq": alt["minq"],
                    "from": [
                        f"{loc}（{q}）{round(qty, 3):g}" for loc, q, qty, *_ in used
                    ],
                    "avg_q": _avg_quality(used),
                    "unknown": unknown,
                    "other_unit": wrong,
                    "others": [a["zh"] or a["en"] for a in req["alts"] if a is not alt],
                }
            )
            if short > 0:
                t = total.setdefault(
                    (alt["en"], alt["minq"], alt["unit"]),
                    {
                        "en": alt["en"],
                        "zh": alt["zh"],
                        "item": iid if iid and not iid.startswith("local:") else None,
                        "unit": alt["unit"],
                        "minq": alt["minq"],
                        "short": 0.0,
                        "goals": [],
                    },
                )
                t["short"] = round(t["short"] + short, 4)
                t["goals"].append(g["title"])
        progress = (
            sum(min(1.0, r["have"] / r["need"]) if r["need"] else 1.0 for r in rows)
            / len(rows)
            if rows
            else 1.0
        )
        out.append(
            {
                **g,
                "rows": rows,
                "progress": progress,
                "done": all(r["short"] <= 0 for r in rows),
            }
        )
    return {
        "goals": out,
        "shortfall": sorted(total.values(), key=lambda t: t["zh"] or t["en"]),
        "alloc": alloc,
    }


def finish_takes(trade, gid):
    """做完一次这个目标要从库存扣的：[{key: (物品, 品质, 位置, 单位), raw: 库存里的整数, en, zh, qty, unit, place, quality}]。
    按做一次的量、从全部库存里拿（标了「不给目标用」的不拿，品质门槛照算）；材料不够返回 (None, 还差的材料名)"""
    g = next((x for x in load() if x["id"] == gid), None)
    if not g:
        raise ValueError("未找到此目标")
    reqs = requirements({**g, "times": 1})
    if reqs is None:
        raise ValueError("新数据中已无此兑换或蓝图")
    pool = stock_lots(trade)
    out, short = [], []
    for req in reqs:
        best = None
        for alt in req["alts"]:
            own = [
                lot
                for i in resolve_all(trade, alt["en"], alt["zh"])
                for lot in pool.get(i, [])
                if unit_fits(lot, alt["unit"])
            ]
            trial = [lot[:] for lot in own]
            got, used, _unknown = _take(trial, alt["qty"], alt["minq"])
            if got >= alt["qty"] - 1e-9 and best is None:
                best = (alt, used, own, trial)
        if best is None:
            a0 = req["alts"][0]
            wrong = other_unit(
                [
                    lot
                    for i in resolve_all(trade, a0["en"], a0["zh"])
                    for lot in pool.get(i, [])
                ],
                a0["unit"],
            )
            short.append(
                (a0["zh"] or a0["en"])
                + (f"（库存另有 {wrong}，单位对不上，未计入）" if wrong else "")
            )
            continue
        alt, used, own, trial = best
        for lot, after in zip(own, trial):
            lot[3] = after[3]
        for loc, qlabel, qty, _f, key in used:
            item_id, quality, _loc, unit = key
            raw = (
                int(round(qty * 1_000_000))
                if unit == USCU
                else int(round(qty * 100))
                if unit == CSCU
                else int(round(qty))
            )
            if raw > 0:
                out.append(
                    {
                        "key": key,
                        "raw": raw,
                        "en": alt["en"],
                        "zh": alt["zh"],
                        "qty": round(qty, 6),
                        "unit": "个" if unit == "unit" else "SCU",
                        "place": loc,
                        "quality": qlabel,
                    }
                )
    return (None, short) if short else (out, [])


def finish(trade, gid):
    """目标「做完了」：从库存扣掉做一次用掉的材料（一笔出库，原因「用于制造」，能撤销），次数 -1（做完最后一次就删掉这个目标）"""
    from ..trade.models import StockKey

    takes, short = finish_takes(trade, gid)
    if takes is None:
        raise ValueError("材料不足，无法扣除：" + "、".join(short))
    with _LOCK:
        g = next(
            (x for x in _load_strict() if x["id"] == gid), None
        )  # 目标文件现在读得到，等下才敢扣库存
        if g is None:
            raise ValueError("未找到此目标")
        batch = (
            trade.inventory.out_many(
                [(StockKey(*t["key"]), t["raw"]) for t in takes],
                reason="用于制造",
                note=g["title"],
                source="目标",
            )
            if takes
            else None
        )
        try:
            if g["times"] > 1:
                _update(gid, times=g["times"] - 1)
            else:
                _update(gid, remove=True)
        except Exception as e:
            if batch:  # 目标没记下来：把刚扣的材料退回去，别再点一次就重复扣（审查 2026-10-28）
                try:
                    trade.inventory.undo(batch)
                except Exception as u:  # 退也没退成：不能吞掉，不然玩家以为什么都没发生、再点一次就扣两遍
                    raise ValueError(
                        f"目标次数没记上（{e}），刚扣的材料也没能退回（{u}）。"
                        f"请到库存页的记录里核对「{g['title']}」这笔「用于制造」的出库，需要时手动撤销"
                    ) from e
            raise
    return {
        "batch": batch,
        "taken": takes,
        "title": g["title"],
        "left": max(0, g["times"] - 1),
    }


def stock_line(trade, en, zh, qty, unit, quality, location, item_id=None):
    """入库前把一行算清楚（不写库）：返回 (StockKey, 数量)。unit 是「个」「SCU」「uSCU」，SCU 和 uSCU 都按 uSCU 存。
    数量、单位、位置不对就抛 ValueError（盘点确认也用它，审查 2026-10-28 第 8 条）"""
    from ..trade.console import _quality
    from ..trade.models import StockKey

    qty = float(qty)
    import math

    if not math.isfinite(qty):  # inf、nan：比大小全是 False，会一路混过下面的校验
        raise ValueError("数量不对")
    if qty <= 0 or not str(location).strip():
        raise ValueError("数量要大于 0，位置不能空")
    if unit in ("SCU", "uSCU"):
        n, u = int(round(qty * 1_000_000 if unit == "SCU" else qty)), USCU
        if n <= 0:
            raise ValueError("最少 1 uSCU")
        if unit == "uSCU" and qty != int(qty):
            raise ValueError("uSCU 要是整数")
    else:
        if qty != int(qty):
            raise ValueError("这个按「个」记，数量要是整数")
        n, u = int(qty), "unit"
    qs = (
        "" if quality is None else str(quality).strip()
    )  # 品质 0 是「没有品质」，不是没填
    q = _quality(qs) if qs else "unknown"
    iid = (
        item_id
        if item_id and trade.catalog.get(item_id)
        else ensure_item(trade, en, zh)
    )  # 全校验过了再建本地物品，被拒的不留下空物品
    return StockKey(iid, q, location.strip(), u), n


def add_stock(
    trade,
    en,
    zh,
    qty,
    unit,
    quality,
    location,
    item_id=None,
    note="",
    source="",
    craft=None,
):
    """入库：unit 是「个」「SCU」「uSCU」。SCU 和 uSCU 都按 uSCU 存（1 SCU = 1,000,000 uSCU）。
    item_id：已经知道是交易库里哪个物品（物品查询里查过价的）就直接用它，不再按名字找。
    note / source：这笔记录的备注、从哪录的（库存页 / F8 / 物品查询 / 目标），仓储记录里显示"""
    from ..trade.models import StockLine

    key, n = stock_line(trade, en, zh, qty, unit, quality, location, item_id=item_id)
    iid, q = key.item_id, key.quality
    with trade.db.connection():  # 预览、确认、备注放进同一个事务：中间别的线程写一笔，这笔入库不会白白报「库存已经变化」（同 S3 15cfbde）
        preview = trade.inventory.prepare([StockLine(key, n)], "add")
        batch = trade.inventory.commit(preview, allow_duplicate=True)
        if note or source:
            trade.inventory.set_note(batch, note=note, source=source)
        if craft:  # 制造出来的东西：各材料槽的品质（1.6.67）
            trade.inventory.set_craft(iid, q, craft)
        trade.db.set(
            "last_location", key.location
        )  # 入库成了才记「上次位置」，失败一起回滚
    return iid
