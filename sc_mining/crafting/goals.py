"""目标：玩家定下要换的维科洛兑换 / 要造的东西，对照库存算出还差什么、去哪弄、大概多少钱

- 目标存在 userdata/goals.json：[{id, kind: wikelo|craft, ref, times, title}]，按列表顺序就是优先级
- 库存来自交易模块的库存（和「库存」页同一份数据）
- 几个目标要同一种东西时，按优先级先满足排在前面的，同一份库存不重复算
- 制造的品质门槛：库存里品质够的才算；品质「未知」的单独提示，不算进已有
- 制造的某个部件有几种材料可选时，挑「还差得最少」的那种
"""
import json
import time
import uuid
from functools import lru_cache

from ..core.paths import USER

FILE = USER / "goals.json"
MAX_TIMES = 99
# 交易模块的品质档 → 这一档最低品质（qN 只知道在哪一档，按下限算才不会高估）
GROUP_FLOOR = {"q0": 0, "q1": 1, "q2": 500, "q3": 600, "q4": 700, "q5": 800, "q6": 900, "q7": 950}


# ---------------------------------------------------------------- 存取

def load():
    """目标表（查询用：读不到就当没有）"""
    try:
        return _load_strict()
    except RuntimeError:
        return []


def _load_strict():
    """目标表（改写前用）：文件读不到或坏了就抛错，别当成空表（细查 2026-10-28：否则接着加一个目标会把整份覆盖掉）"""
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise RuntimeError(f"目标文件暂时读不到：{e}")
    except ValueError as e:
        raise RuntimeError(f"目标文件损坏（userdata 里的 goals.json）：{e}")
    return [g for g in data if isinstance(g, dict) and g.get("kind") in ("wikelo", "craft")] if isinstance(data, list) else []


def save(goals):
    from ..core.paths import write_json
    write_json(FILE, goals, indent=1)


def add(kind, ref, times=1):
    if kind not in ("wikelo", "craft"):
        raise ValueError("目标仅支持维科洛兑换或制造")
    src = _source(kind, ref)
    if not src:
        raise ValueError("未找到此兑换或蓝图")
    with _LOCK:
        return _add(kind, ref, times, src)


def _add(kind, ref, times, src):
    goals = _load_strict()
    for g in goals:                      # 同一个目标再加一次：次数 +1
        if g["kind"] == kind and g["ref"] == ref:
            g["times"] = min(MAX_TIMES, g["times"] + max(1, int(times)))
            save(goals)
            return goals
    goals.append({"id": uuid.uuid4().hex[:10], "kind": kind, "ref": ref,
                  "times": max(1, min(MAX_TIMES, int(times))), "title": _title(kind, src), "at": time.time()})
    save(goals)
    return goals


_LOCK = __import__("threading").RLock()      # 读-改-写连在一起（老大审查 2026-10-28：两个请求同时改会丢一个）


def update(gid, times=None, move=0, remove=False):
    with _LOCK:
        return _update(gid, times, move, remove)


def _update(gid, times=None, move=0, remove=False):
    goals = _load_strict()
    i = next((n for n, g in enumerate(goals) if g["id"] == gid), None)
    if i is None:
        raise ValueError("未找到此目标")
    if remove:
        goals.pop(i)
    else:
        if times is not None:
            goals[i]["times"] = max(1, min(MAX_TIMES, int(times)))
        if move:
            j = max(0, min(len(goals) - 1, i + (1 if move > 0 else -1)))
            goals[i], goals[j] = goals[j], goals[i]
    save(goals)
    return goals


# ---------------------------------------------------------------- 目标要什么

def _source(kind, ref):
    if kind == "wikelo":
        from . import wikelo
        return next((c for c in wikelo.load() if c["id"] == ref), None)
    from .crafting import by_key
    return by_key(ref)


def _title(kind, src):
    if kind == "wikelo":
        reward = src["rz"] or "、".join(src["rewards"][:2]) or src["te"]
        return f"维科洛：{src['t']}（换 {reward}）"
    from .crafting import display_name
    return f"制造：{display_name(src)}"


def requirements(goal):
    """[{"slot": 部件名或空, "alts": [{en, zh, qty, unit, minq}]}]，数量已乘次数"""
    src = _source(goal["kind"], goal["ref"])
    if not src:
        return None
    n = goal["times"]
    out = []
    if goal["kind"] == "wikelo":
        for r in src["req"]:
            out.append({"slot": "", "alts": [{"en": r["n"], "zh": r["z"], "qty": (r["q"] or 1) * n,
                                              "unit": r["u"], "minq": 0}]})
    else:
        from .crafting import material_zh
        for slot, opts, _mods in src["slots"]:
            alts = [{"en": name, "zh": material_zh(name), "qty": qty * n, "unit": "SCU" if k == "r" else "个",
                     "minq": minq if minq > 1 else 0} for k, name, qty, minq in opts]
            if alts:
                out.append({"slot": slot, "alts": alts})
    return out


# ---------------------------------------------------------------- 库存

def _quality_floor(q):
    """库存里的品质 → 至少多少；未知返回 None"""
    if q.startswith("exact:"):
        try:
            return int(q[6:])
        except ValueError:
            return None
    return GROUP_FLOOR.get(q)


CSCU = "cSCU"      # 1.6.36 以前：矿、材料按 0.01 SCU 记（启动时会换算成 uSCU，这里只为读没换算的旧记录）
USCU = "uSCU"      # 矿、材料按百万分之一 SCU 记（库存数量只能是整数，0.495 SCU 记成 495000 uSCU；游戏里显示到 0.001 SCU）


RESERVED = "stock_reserved"     # 库存页标了「不给目标用」的行（物品|品质|位置|单位），目标不算它们


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
        label = k.quality.replace("exact:", "品质 ") if k.quality.startswith("exact:") else (
            "品质未知" if f is None else k.quality.upper())
        qty = line.quantity / 1e6 if k.unit == USCU else line.quantity / 100 if k.unit == CSCU else line.quantity
        lots.setdefault(k.item_id, []).append([f, label, k.location, qty, k.unit, k.quality, k.item_id])
    return lots


def local_id(en):
    return "local:" + en


def resolve_all(trade, en, zh=""):
    """材料名 → 库存里可能记着它的所有物品 id（市场上的正式物品 + 本地物品），第一个是能查价的"""
    ids = []
    for name in (en, zh):
        if not name:
            continue
        item = trade.catalog.by_alias(name)
        if item:
            ids.append(item.id)
        ids += [i.id for i in trade.catalog.search(name) if i.name.casefold() == name.casefold()]
    if trade.catalog.get(local_id(en)):
        ids.append(local_id(en))
    ids = list(dict.fromkeys(ids))
    ids.sort(key=lambda i: i.startswith("local:"))
    return ids


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


def _take(lots, need, minq):
    """从库存里拿 need：先拿品质刚好够的（高品质留给更挑的目标）。返回 (拿到多少, [(位置, 品质, 数量)], 品质未知的有多少)"""
    got, used, unknown = 0.0, [], 0
    # 没有品质要求时，品质未知的也能用（而且先用它们，把知道品质的留给有门槛的目标）
    usable = sorted((l for l in lots if l[3] > 0 and (l[0] is not None and l[0] >= minq or (l[0] is None and not minq))),
                    key=lambda l: -1 if l[0] is None else l[0])
    for lot in usable:
        if got >= need - 1e-9:
            break
        take = min(lot[3], need - got)
        lot[3] -= take
        got += take
        used.append((lot[2], lot[1], take, lot[0], (lot[6], lot[5], lot[2], lot[4]) if len(lot) > 6 else None))
    if got < need - 1e-9 and minq:
        unknown = sum(l[3] for l in lots if l[0] is None and l[3] > 0)
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
            for n, alt in enumerate(req["alts"]):   # 几种材料可选：每种都试拿一下，挑还差最少的
                own = [lot for i in ids_of(alt) for lot in pool.get(i, [])]
                trial = [lot[:] for lot in own]
                got, used, unknown = _take(trial, alt["qty"], alt["minq"])
                short = max(0.0, alt["qty"] - got)
                cand = (short / alt["qty"] if alt["qty"] else 0, n)
                if best is None or cand < best[0]:
                    best = (cand, alt, got, used, unknown, own, trial)
            _, alt, got, used, unknown, own, trial = best
            for lot, after in zip(own, trial):  # 真的拿走
                lot[3] = after[3]
            for _loc, _q, qty, _f, key in used:  # 库存页「目标占用」：每行分给了哪些目标、多少
                if key and qty > 0:
                    a = alloc.setdefault(lot_key(*key), {"qty": 0.0, "goals": []})
                    a["qty"] = round(a["qty"] + qty, 6)
                    if g["title"] not in a["goals"]:
                        a["goals"].append(g["title"])
            iid = (ids_of(alt) or [None])[0]
            short = round(max(0.0, alt["qty"] - got), 4)
            rows.append({"slot": req["slot"], "slot_zh": _slot_zh(req["slot"]), "en": alt["en"], "zh": alt["zh"], "item": iid, "local": bool(iid and iid.startswith("local:")),
                         "need": round(alt["qty"], 4), "have": round(got, 4), "short": short, "unit": alt["unit"],
                         "minq": alt["minq"], "from": [f"{loc}（{q}）{round(qty, 3):g}" for loc, q, qty, *_ in used],
                         "avg_q": _avg_quality(used),
                         "unknown": unknown, "others": [a["zh"] or a["en"] for a in req["alts"] if a is not alt]})
            if short > 0:
                t = total.setdefault((alt["en"], alt["minq"], alt["unit"]),
                                     {"en": alt["en"], "zh": alt["zh"], "item": iid if iid and not iid.startswith("local:") else None,
                                      "unit": alt["unit"],
                                      "minq": alt["minq"], "short": 0.0, "goals": []})
                t["short"] = round(t["short"] + short, 4)
                t["goals"].append(g["title"])
        progress = sum(min(1.0, r["have"] / r["need"]) if r["need"] else 1.0 for r in rows) / len(rows) if rows else 1.0
        out.append({**g, "rows": rows, "progress": progress, "done": all(r["short"] <= 0 for r in rows)})
    return {"goals": out, "shortfall": sorted(total.values(), key=lambda t: (t["zh"] or t["en"])), "alloc": alloc}


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
            own = [lot for i in resolve_all(trade, alt["en"], alt["zh"]) for lot in pool.get(i, [])]
            trial = [lot[:] for lot in own]
            got, used, _unknown = _take(trial, alt["qty"], alt["minq"])
            if got >= alt["qty"] - 1e-9 and best is None:
                best = (alt, used, own, trial)
        if best is None:
            short.append(req["alts"][0]["zh"] or req["alts"][0]["en"])
            continue
        alt, used, own, trial = best
        for lot, after in zip(own, trial):
            lot[3] = after[3]
        for loc, qlabel, qty, _f, key in used:
            item_id, quality, _loc, unit = key
            raw = int(round(qty * 1_000_000)) if unit == USCU else int(round(qty * 100)) if unit == CSCU else int(round(qty))
            if raw > 0:
                out.append({"key": key, "raw": raw, "en": alt["en"], "zh": alt["zh"], "qty": round(qty, 6),
                            "unit": "个" if unit == "unit" else "SCU", "place": loc, "quality": qlabel})
    return (None, short) if short else (out, [])


def finish(trade, gid):
    """目标「做完了」：从库存扣掉做一次用掉的材料（一笔出库，原因「用于制造」，能撤销），次数 -1（做完最后一次就删掉这个目标）"""
    from ..trade.models import StockKey
    takes, short = finish_takes(trade, gid)
    if takes is None:
        raise ValueError("材料不足，无法扣除：" + "、".join(short))
    with _LOCK:
        g = next((x for x in _load_strict() if x["id"] == gid), None)      # 目标文件现在读得到，等下才敢扣库存
        if g is None:
            raise ValueError("未找到此目标")
        batch = trade.inventory.out_many([(StockKey(*t["key"]), t["raw"]) for t in takes], reason="用于制造",
                                         note=g["title"], source="目标") if takes else None
        try:
            if g["times"] > 1:
                _update(gid, times=g["times"] - 1)
            else:
                _update(gid, remove=True)
        except Exception:
            if batch:                            # 目标没记下来：把刚扣的材料退回去，别再点一次就重复扣（老大审查 2026-10-28）
                try:
                    trade.inventory.undo(batch)
                except Exception:
                    pass
            raise
    return {"batch": batch, "taken": takes, "title": g["title"], "left": max(0, g["times"] - 1)}


# ---------------------------------------------------------------- 去哪弄、多少钱

@lru_cache(maxsize=512)
def where_to_get(en):
    """一句话：商店最便宜在哪 / 去哪挖 / 维科洛特殊材料说明"""
    try:
        from ..trade.console import material_source
        return material_source(en) or ""
    except Exception:
        return ""


def market_price(trade, item_id, minq=0):
    """玩家市场（UEX / SCM）出售挂牌里最便宜的单价；没有挂牌返回 None"""
    from decimal import Decimal
    from ..trade.providers.http import quality_group
    item = trade.catalog.get(item_id)
    if not item:
        return None
    group = quality_group(minq) if minq else "q0"
    best = None
    for r in trade.prices(item, group, "sell"):
        for s in r.stats or []:
            v = s.minimum if s.minimum is not None else s.mean
            if v is None:
                continue
            v = Decimal(v)
            if best is None or v < best[0]:
                best = (v, r.source, s.key.unit, s.key.currency)
    return best


def stock_line(trade, en, zh, qty, unit, quality, location, item_id=None):
    """入库前把一行算清楚（不写库）：返回 (StockKey, 数量)。unit 是「个」「SCU」「uSCU」，SCU 和 uSCU 都按 uSCU 存。
    数量、单位、位置不对就抛 ValueError（盘点确认也用它，老大审查 2026-10-28 第 8 条）"""
    from ..trade.console import _quality
    from ..trade.models import StockKey
    iid = item_id if item_id and trade.catalog.get(item_id) else ensure_item(trade, en, zh)
    qty = float(qty)
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
    qs = "" if quality is None else str(quality).strip()            # 品质 0 是「没有品质」，不是没填
    q = _quality(qs) if qs else "unknown"
    return StockKey(iid, q, location.strip(), u), n


def add_stock(trade, en, zh, qty, unit, quality, location, item_id=None, note="", source="", craft=None):
    """入库：unit 是「个」「SCU」「uSCU」。SCU 和 uSCU 都按 uSCU 存（1 SCU = 1,000,000 uSCU）。
    item_id：已经知道是交易库里哪个物品（物品查询里查过价的）就直接用它，不再按名字找。
    note / source：这笔记录的备注、从哪录的（库存页 / F8 / 物品查询 / 目标），仓储记录里显示"""
    from ..trade.models import StockLine
    key, n = stock_line(trade, en, zh, qty, unit, quality, location, item_id=item_id)
    iid, q = key.item_id, key.quality
    trade.db.set("last_location", key.location)
    preview = trade.inventory.prepare([StockLine(key, n)], "add")
    batch = trade.inventory.commit(preview, allow_duplicate=True)
    if note or source:
        trade.inventory.set_note(batch, note=note, source=source)
    if craft:                                   # 制造出来的东西：各材料槽的品质（1.6.67）
        trade.inventory.set_craft(iid, q, craft)
    return iid
