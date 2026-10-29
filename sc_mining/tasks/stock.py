"""库存管理与台账任务模块（Task: Stock & Inventory Management）

从 app/services.py 中解耦出来，专职处理：
1. 仓库、货架、库位（Bin）与标准地点映射管理；
2. 物品出入库、改数量、改品质、移库与撤销历史；
3. 库存估值计算、目标材料占用计算与台账流水明细查询。
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal

# ---------------------------------------------------------------- 依赖转发辅助
def _services():
    from ..app import services
    return services


def api(fn):
    """API 路由注册装饰器（兼容主服务路由表）"""
    try:
        from ..app.services import api as _reg
        return _reg(fn)
    except Exception:
        try:
            from ..app.services import API
            API[fn.__name__] = fn
        except Exception:
            pass
    return fn


def trade():
    return _services().trade()


def mineral_search(q=""):
    try:
        return _services().mineral_search(q=q)
    except Exception:
        return []


def item_search(q=""):
    try:
        return _services().item_search(q=q)
    except Exception:
        return []


def _invalidate_short():
    try:
        _services()._SHORT["t"] = 0.0
    except Exception:
        pass


def _is_mineral(zh, en):
    try:
        from .hover import _is_mineral as im
        return im(zh, en)
    except Exception:
        return False


# ---------------------------------------------------------------- 基础常量与转换函数

def scu_amount(qty, unit):
    """库存里存的整数 → SCU（uSCU 是百万分之一，旧的 cSCU 是百分之一），去掉浮点误差"""
    return round(qty / (1_000_000 if unit == "uSCU" else 100), 6)


MODE_ZH = {"add": "入库", "count": "盘点", "adjust": "改数量", "out": "出库", "set": "改数量", "move": "移库", "quality": "改品质"}
LEDGER_TYPES = ("入库", "出库", "移库", "改数量", "改品质", "盘点", "撤销")


def _qlabel(qkey, short=False):
    if qkey.startswith("exact:"):
        return ("" if short else "品质 ") + qkey[6:]
    return "品质未知" if qkey == "unknown" else qkey.upper()


def _amount_text(raw, ukey, sign=False):
    """库存里存的整数 → 「0.495 SCU」「3 个」（sign：带 +/-）"""
    if ukey in ("uSCU", "cSCU"):
        v = scu_amount(raw, ukey)
        return f"{v:+g} SCU" if sign else f"{v:g} SCU"
    return f"{raw:+d} 个" if sign else f"{raw} 个"


def _stock_kind(zh, en, ukey):
    """库存页筛选用的类别：矿物（能挖的）/ 材料（按 SCU 记的其他东西）/ 物品（按个记的）"""
    if ukey == "unit":
        return "物品"
    return "矿物" if _is_mineral(zh, en) else "材料"


def _place_of(location):
    """库存里记的位置 → (地点叫法, 仓位, 地点信息或 None)：「新巴贝奇｜待卖」→ (新巴贝奇, 待卖, …)；New Babbage → (新巴贝奇, 总仓, …)"""
    from .. import stockplaces as SP
    place, b = SP.split_loc(location)
    p = SP.match(place)
    return (p["label"] if p else place), b, p


def _all_batches(t):
    """全部库存记录（新的在前）：每笔的类型、时间、内容（移库写「从 → 到」，改品质写「旧 → 新」）、备注、涉及的地点和物品"""
    batches = []
    for r in t.inventory.history():
        if not batches or batches[-1]["batch"] != r["batch_id"]:
            mode = r["mode"]
            batches.append({"batch": r["batch_id"], "at": r["at"], "mode": mode, "undone": bool(r["undone"]),
                            "type": "撤销" if mode.startswith("undo:") else MODE_ZH.get(mode, mode),
                            "note": r.get("note") or "", "reason": r.get("reason") or "", "source": r.get("source") or "", "_rows": []})
        batches[-1]["_rows"].append(r)
    labels = {}

    def name(iid):
        if iid not in labels:
            labels[iid] = t.label(iid)
        return labels[iid]
    for b in batches:
        rows, items = b.pop("_rows"), []
        if b["mode"] == "adjust" and len(rows) == 2:              # 1.6.38 以前的改品质也记成 adjust：一减一加、品质不同
            x, y = rows
            if (x["item_id"], x["location"], x["unit"]) == (y["item_id"], y["location"], y["unit"]) \
                    and x["delta"] == -y["delta"] and x["quality"] != y["quality"]:
                b["mode"], b["type"] = "quality", "改品质"
        if b["mode"] in ("move", "quality"):
            # 成对的一减一加：移库按物品+品质+单位配对，改品质按物品+位置+单位配对
            pair = (lambda r: (r["item_id"], r["quality"], r["unit"])) if b["mode"] == "move" else (lambda r: (r["item_id"], r["location"], r["unit"]))
            plus = {pair(r): r for r in rows if r["delta"] > 0}
            for r in rows:
                if r["delta"] >= 0:
                    continue
                to = plus.get(pair(r))
                amt = _amount_text(-r["delta"], r["unit"])
                if b["mode"] == "move":
                    items.append(f"{name(r['item_id'])}（{_qlabel(r['quality'])}）{amt}：{r['location']} → {to['location'] if to else '?'}")
                else:
                    items.append(f"{name(r['item_id'])} {amt}：{_qlabel(r['quality'])} → {_qlabel(to['quality']) if to else '?'}（{r['location']}）")
        if not items:
            items = [f"{name(r['item_id'])}（{_qlabel(r['quality'])}）{_amount_text(r['delta'], r['unit'], True)}｜{r['location']}" for r in rows]
        b["items"] = items
        b["places"] = sorted({_place_of(r["location"])[0] for r in rows})
        b["names"] = " ".join(sorted({name(r["item_id"]) for r in rows}))
    return batches


def _history_view(t, limit=12):
    return [{k: v for k, v in b.items() if k != "names"} for b in _all_batches(t)[:limit]]


def _bins(t):
    """仓位：{地点: {"bins": [{name, desc}], "default": 默认仓位名或空}}（存在交易库的设置里）"""
    d = t.db.get("stock_bins", {}) or {}
    return d if isinstance(d, dict) else {}


def _price_index(t):
    """缓存里的玩家市场挂牌价（不联网）：{(物品, 品质档, 单位): (单价, 来源)}，同一档取最便宜的出售挂牌"""
    best = {}
    try:
        stats = t.market.cached_stats()
    except Exception:
        stats = []
    for s in stats:
        if s.key.operation != "sell":
            continue
        v = s.minimum if s.minimum is not None else s.mean
        if v is None or (s.count or 0) <= 0:
            continue
        k = (s.key.item_id, s.key.quality_group, s.key.unit)
        if k not in best or Decimal(v) < best[k][0]:
            best[k] = (Decimal(v), s.key.source)
    return best


def _row_value(prices, item_id, qkey, ukey, raw):
    """这一行按最便宜的出售挂牌值多少 aUEC；品质未知、没报价、单位对不上返回 None"""
    from ..trade.providers.http import quality_group
    if not qkey.startswith("exact:"):
        return None
    group = quality_group(qkey[6:])
    if ukey == "unit":
        hit = prices.get((item_id, group, "unit"))
        return float(hit[0]) * raw if hit else None
    scu = scu_amount(raw, ukey)
    for unit, per in (("SCU", scu), ("cSCU", scu * 100), ("uSCU", scu * 1_000_000)):
        hit = prices.get((item_id, group, unit))
        if hit:
            return float(hit[0]) * per
    return None


# ---------------------------------------------------------------- 库存展示与操作

@api
def stock():
    """库存页：每一行（地点、仓位、类别、最后变动、目标占用、不给目标用、估值）、左边的地点树（带仓位）、当前位置、最近记录"""
    from .. import stockplaces as SP
    from .. import goals as G
    from ..trade.names import has_chinese
    t = trade()
    custom = list(t.db.get("stock_custom_places", []) or [])
    bins = _bins(t)
    changed = t.inventory.last_changes()
    reserved = G.reserved_keys(t)
    from ..crafting import craft_text
    try:
        crafts = t.inventory.craft_map()
    except Exception:
        crafts = {}
    try:
        alloc = G.plan(t).get("alloc", {})
    except Exception:
        alloc = {}
    prices = _price_index(t)
    rows, groups = [], {}

    def group(label, p):
        if label not in groups:
            state = "known" if p else ("custom" if label in custom else "unmatched")
            groups[label] = {"label": label, "path": p["path"] if p else label, "sys": p["sys_zh"] if p else "",
                             "kind": p["kind"] if p else "其他", "state": state, "count": 0, "value": 0.0, "bins": {}}
        return groups[label]
    for line in t.inventory.list_stock():
        k = line.key
        place, b, p = _place_of(k.location)
        g = group(place, p)
        g["count"] += 1
        g["bins"][b] = g["bins"].get(b, 0) + 1
        item = t.catalog.get(k.item_id)
        en = item.name if item else k.item_id
        label = t.label(k.item_id)
        zh = label.split("（")[0] if label.endswith("）") and "（" in label else (label if has_chinese(label) else "")
        qty, unit = line.quantity, k.unit
        if unit in ("uSCU", "cSCU"):                # 矿和材料按 uSCU（以前 0.01 SCU）记的，显示成 SCU
            qty, unit = scu_amount(qty, unit), "SCU"
        elif unit == "unit":
            unit = "个"
        lk = G.lot_key(k.item_id, k.quality, k.location, k.unit)
        a = alloc.get(lk) or {}
        value = _row_value(prices, k.item_id, k.quality, k.unit, line.quantity)
        if value:
            g["value"] += value
        rows.append({"item": label, "zh": zh, "en": en, "kind": _stock_kind(zh, en, k.unit),
                     "quality": "未知" if k.quality == "unknown" else _qlabel(k.quality),
                     "q": int(k.quality[6:]) if k.quality.startswith("exact:") else None,
                     "location": k.location, "place": place, "bin": b, "place_state": g["state"],
                     "qty": qty, "unit": unit, "id": k.item_id, "qkey": k.quality, "ukey": k.unit, "raw": line.quantity,
                     "changed": changed.get((k.item_id, k.quality, k.location, k.unit), ""),
                     "goal_qty": round(a.get("qty", 0.0), 6), "goal_titles": a.get("goals", []), "reserved": lk in reserved,
                     # 可用 = 在库 − 目标占用（1.6.55；以后再减挂单锁定）。挂单只能卖可用的
                     "avail": round(max(0.0, qty - a.get("qty", 0.0)), 6),
                     "value": round(value) if value else None,
                     "craft": craft_text(crafts.get((k.item_id, k.quality))) if crafts.get((k.item_id, k.quality)) else ""})
    here = SP.current_place()
    if here and not here.get("custom"):              # 当前位置还没东西：也列出来，方便直接入库到这里
        group(here["label"], SP.by_label(here["label"]))
    for place, meta in bins.items():                 # 建好还没放东西的仓位也列出来
        if meta.get("bins"):
            g = group(place, SP.match(place))
            for x in meta["bins"]:
                g["bins"].setdefault(x["name"], 0)
    for g in groups.values():                        # 仓位：总仓在前，其余按名字；带描述、默认
        meta = bins.get(g["label"]) or {}
        desc = {x["name"]: x.get("desc", "") for x in meta.get("bins", [])}
        names = sorted(n for n in g["bins"] if n != SP.MAIN_BIN)
        g["bins"] = ([{"name": SP.MAIN_BIN, "count": g["bins"].get(SP.MAIN_BIN, 0), "desc": "", "default": not meta.get("default")}]
                     + [{"name": n, "count": g["bins"][n], "desc": desc.get(n, ""), "default": meta.get("default") == n} for n in names])
        g["value"] = round(g["value"])
    order = {p["label"]: i for i, p in enumerate(SP.places())}
    known = sorted((g for g in groups.values() if g["state"] == "known"), key=lambda g: order.get(g["label"], 999))
    tree = []
    for g in known:
        if not tree or tree[-1]["sys"] != g["sys"]:
            tree.append({"sys": g["sys"], "places": []})
        tree[-1]["places"].append(g)
    priced = [r for r in rows if r["value"]]
    total = round(sum(r["value"] for r in priced))
    value = [f"参考估值（玩家市场最低出售挂牌价）：≈ {total:,} aUEC｜{len(priced)} 行有报价，{len(rows) - len(priced)} 行无报价"] if priced else []
    return {"rows": rows, "tree": tree,
            "custom": sorted((g for g in groups.values() if g["state"] == "custom"), key=lambda g: g["label"]),
            "unmatched": sorted((g for g in groups.values() if g["state"] == "unmatched"), key=lambda g: g["label"]),
            "here": here, "value": value, "value_total": total, "priced": len(priced), "bins": bins,
            "history": _history_view(t), "last_location": t.db.get("last_location", "")}


def _place_for(location, bin=None):
    """入库 / 移库的目标 → 库存里记的叫法「地点」或「地点｜仓位」。
    地点：列表里的用标准中文名（New Babbage → 新巴贝奇），别的（船、前哨、自己起的名字）检查一下、记进「自己的地点」。
    仓位：bin=None 时用地点的默认仓位；「总仓」或空 = 不分仓位；别的名字没建过就顺手建上"""
    from .. import stockplaces as SP
    place, b = SP.split_loc(location)
    if "｜" in str(location or "") and bin is None:
        bin = b
    p = SP.match(place)
    t = trade()
    if p:
        label = p["label"]
    else:
        label = SP.check_name(place)
        custom = list(t.db.get("stock_custom_places", []) or [])
        if label not in custom:
            t.db.set("stock_custom_places", custom + [label])
    bins = _bins(t)
    if bin is None:
        bin = (bins.get(label) or {}).get("default") or SP.MAIN_BIN
    bin = (bin or "").strip() or SP.MAIN_BIN
    if bin != SP.MAIN_BIN:
        bin = SP.check_bin(bin)
        meta = bins.setdefault(label, {"bins": [], "default": ""})
        if not any(x["name"] == bin for x in meta.setdefault("bins", [])):
            meta["bins"].append({"name": bin, "desc": ""})
            t.db.set("stock_bins", bins)
    return SP.join_loc(label, bin)


def _raw_amount(qty, ukey, allow_zero=False):
    """窗口里填的数量（SCU 或 个）→ 库存里存的整数（uSCU 或 个）"""
    try:
        v = float(str(qty).replace(",", "").strip())
    except ValueError:
        raise ValueError("数量需为数字")
    if ukey == "uSCU":
        n = int(round(v * 1_000_000))
    elif ukey == "cSCU":
        n = int(round(v * 100))
    else:
        if v != int(v):
            raise ValueError("此物品按「个」计数，数量需为整数")
        n = int(v)
    if n < 0 or v < 0:
        raise ValueError("数量不能是负数")
    if n == 0 and not allow_zero:
        raise ValueError("最小 1 uSCU（0.000001 SCU）" if v > 0 else "数量需大于 0")
    return n


@api
def stock_add(id="", qty=1, quality="", location=""):
    _invalidate_short()
    from ..trade.console import _quality
    from ..trade.models import StockKey, StockLine
    t = trade()
    if not t.catalog.get(id):
        return {"error": "未找到此物品"}
    qty = int(qty)
    if qty <= 0 or not location.strip():
        return {"error": "数量需大于 0，地点不能为空"}
    try:
        location = _place_for(location)
    except ValueError as e:
        return {"error": str(e)}
    q = _quality(quality) if quality else "unknown"
    t.db.set("last_location", location)
    preview = t.inventory.prepare([StockLine(StockKey(id, q or "unknown", location), qty)], "add")
    t.inventory.commit(preview, allow_duplicate=True)
    return stock()


@api
def craft_slots_for(en="", zh=""):
    """入库时：制造出来的东西有哪些材料槽要填品质（1.6.67）；不是能制造的返回 []"""
    from ..crafting import for_item, craft_slots
    return craft_slots(for_item(en, zh)) if (en or zh) else []


@api
def stock_add_named(name="", qty=0, unit="", quality="", location="", en="", zh="", kind="", id="", note="", source="", bin=None, craft=None):
    """库存页手动入库：名字（中文或英文；矿物、材料、物品都行）、数量、单位（个 / SCU / uSCU）、品质、位置、备注。
    从联想里点选的会带上 en / zh / kind，直接用，不再猜；矿物默认按 SCU，其他默认按个；交易库里没有的自动建成本地物品。
    位置：地点列表里的用标准中文名，别的记成自己的地点；source：从哪录的（库存页 / F8 / 物品查询）"""
    _invalidate_short()
    from .. import goals as G
    name = (name or "").strip()
    if en:
        u = unit or ("SCU" if kind == "矿物" else "个")
    else:
        if not name:
            return {"error": "需填写物品或矿物名称"}
        ores = mineral_search(q=name)
        if ores and (len(name) >= 2 or ores[0]["zh"] == name):
            en, zh, u = ores[0]["en"], ores[0]["zh"], unit or "SCU"
        else:
            from ..trade.names import canonical
            hit = canonical(name, "")                          # 汉化包里有的：用标准中英文名
            if hit:
                zh, en = hit
            else:
                hits = item_search(q=name)
                exact = [h for h in hits if name.lower() in ((h.get("zh") or "").lower(), h["name"].lower())]
                h = (exact or hits or [None])[0]
                en, zh = (h["name"], h.get("zh") or "") if h else (name, "")
            u = unit or "个"
    if u not in ("个", "SCU", "uSCU"):
        return {"error": "单位仅支持 个、SCU 或 uSCU"}
    try:
        location = _place_for(location, bin)
        craft = [x for x in (craft or []) if str(x.get("q", "")).strip() != ""]
        if craft:                                              # 制造的东西：品质记各槽平均，各槽另外存（1.6.67）
            for x in craft:
                x["q"] = max(0, min(1000, int(float(x["q"]))))
            quality = round(sum(x["q"] for x in craft) / len(craft))
        G.add_stock(trade(), en, zh, qty, u, quality, location, item_id=id or None, note=note, source=source or "库存页", craft=craft)
    except ValueError as e:
        return {"error": str(e)}
    out = stock()
    out["added"] = f"{zh or en} {qty} {u}" + (f"（品质 {quality}）" if str(quality).strip() else "")
    return out


@api
def stock_suggest(q=""):
    """手动入库的名字联想：矿物、交易库里的物品、汉化包里的物品名，中文 / 英文 / 名字的一部分 / 错一两个字都行。
    返回 [{zh, en, kind: 矿物 / 物品, unit}]，最多 12 个"""
    from ..trade.names import suggest, _fold_en
    q = (q or "").strip()
    if not q:
        return []
    out, seen = [], set()

    def add(zh, en, kind):
        k = _fold_en(en)
        if k and k not in seen:
            seen.add(k)
            out.append({"zh": zh or "", "en": en, "kind": kind, "unit": "SCU" if kind == "矿物" else "个"})
    for o in mineral_search(q=q)[:4]:
        add(o["zh"], o["en"], "矿物")
    for zh, en in suggest(q, 12):
        add(zh, en, "物品")
    try:
        t = trade()
        for i in t.catalog.search(q)[:6]:                 # 以前入过库、查过价的（本地物品也在这里）
            lab = t.label(i.id)
            add(lab.split("（")[0] if "（" in lab else "", i.name, "物品")
    except Exception:
        pass
    return out[:12]


@api
def stock_set_quality(id="", qkey="", location="", ukey="", quality="", note=""):
    """改一行库存的品质（比如「未知」改成 650；空着 = 未知）：同一批数量从旧品质挪到新品质，一次记录、能撤销"""
    _invalidate_short()
    from ..trade.console import _quality
    from ..trade.models import StockKey
    t = trade()
    try:
        newq = _quality(str(quality)) if str(quality or "").strip() else "unknown"
        newq = newq or "unknown"
    except ValueError as e:
        return {"error": str(e)}
    if newq == qkey:
        return stock()
    try:
        t.inventory.requality(StockKey(id, qkey, location, ukey), newq, note=note)
    except ValueError as e:
        return {"error": str(e)}
    return stock()


@api
def stock_undo(batch=""):
    _invalidate_short()
    try:
        trade().inventory.undo(batch)
    except ValueError as e:
        msg = str(e)
        if "负数" in msg:
            msg = "无法撤销：此记录之后，相关物品已出库、移库或修改过数量"
        return {"error": msg}
    return stock()


def _row_key(id, qkey, location, ukey):
    from ..trade.models import StockKey
    if not all(str(v or "").strip() for v in (id, qkey, location, ukey)):
        raise ValueError("此行库存已变更，需刷新")
    return StockKey(id, qkey, location, ukey)


@api
def stock_out(id="", qkey="", location="", ukey="", qty="", reason="", note=""):
    """出库：卖了、用掉、交了维科洛……（qty 按这一行显示的单位：SCU 或 个）"""
    _invalidate_short()
    try:
        trade().inventory.out(_row_key(id, qkey, location, ukey), _raw_amount(qty, ukey), reason=reason, note=note, source="库存页")
    except ValueError as e:
        return {"error": str(e)}
    return stock()


@api
def stock_set_qty(id="", qkey="", location="", ukey="", qty="", note=""):
    """改数量：在游戏里数完直接改成实际数（可以改成 0）"""
    _invalidate_short()
    try:
        trade().inventory.set_quantity(_row_key(id, qkey, location, ukey), _raw_amount(qty, ukey, allow_zero=True),
                                       note=note, source="库存页")
    except ValueError as e:
        return {"error": str(e)}
    return stock()


@api
def stock_move(id="", qkey="", location="", ukey="", qty="", to="", note="", bin=None):
    """移库：搬到别的地点（qty 空着 = 整行都搬）"""
    _invalidate_short()
    try:
        key = _row_key(id, qkey, location, ukey)
        dest = _place_for(to, bin)
        n = _raw_amount(qty, ukey) if str(qty or "").strip() else next(
            (l.quantity for l in trade().inventory.list_stock() if l.key == key), 0)
        if not n:
            raise ValueError("此行库存已变更，需刷新")
        trade().inventory.move(key, dest, n, note=note, source="库存页")
    except ValueError as e:
        return {"error": str(e)}
    out = stock()
    out["moved_to"] = dest
    return out


@api
def stock_relocate(location="", to="", bin=None):
    """「未归类」里的一个位置（以前手打的，对不上地点列表）：整个归到选好的地点"""
    _invalidate_short()
    try:
        dest = _place_for(to, bin)
        n = trade().inventory.relocate(location, dest, note=f"归位：{location} → {dest}")
    except ValueError as e:
        return {"error": str(e)}
    out = stock()
    out["relocated"] = n
    return out


@api
def stock_keep_custom(location=""):
    """「未归类」里的位置其实没错（比如船名）：留下来当自己的地点"""
    from .. import stockplaces as SP
    try:
        name = SP.check_name(location)
    except ValueError as e:
        return {"error": str(e)}
    if name != location:
        return {"error": "地点名称含多余的空格或符号，可用「归入地点」更换"}
    t = trade()
    custom = list(t.db.get("stock_custom_places", []) or [])
    if name not in custom:
        t.db.set("stock_custom_places", custom + [name])
    return stock()


@api
def stock_places():
    """选地点用：游戏里所有能存东西的地方（按星系、星球排好）、自己的地点、当前位置"""
    from .. import stockplaces as SP
    t = trade()
    return {"places": [SP.public(p) for p in SP.places()], "custom": list(t.db.get("stock_custom_places", []) or []),
            "here": SP.current_place(), "last": t.db.get("last_location", ""), "bins": _bins(t)}


@api
def stock_place_add(name=""):
    """选地点时自己写的名字：能对上列表的就用列表里的；对不上的检查一下（不能只有数字）记成自己的地点"""
    from .. import stockplaces as SP
    p = SP.match(name)
    if p:
        return SP.public(p)
    try:
        label = _place_for(name)
    except ValueError as e:
        return {"error": str(e)}
    return {"label": label, "zh": label, "en": "", "sys_zh": "", "path": label, "kind": "其他", "custom": True}


@api
def stock_bin_save(place="", name="", desc="", default=False, old=""):
    """新建仓位 / 改仓位（名字、描述、是不是默认）。改名时这个仓位里的东西一起换过去（一笔移库，能撤销）"""
    from .. import stockplaces as SP
    _invalidate_short()
    t = trade()
    try:
        label = SP.split_loc(_place_for(place, SP.MAIN_BIN))[0]
        name = SP.check_bin(name)
        bins = _bins(t)
        meta = bins.setdefault(label, {"bins": [], "default": ""})
        meta.setdefault("bins", [])
        old = (old or "").strip()
        if old and old != name:
            if any(x["name"] == name for x in meta["bins"]):
                raise ValueError(f"{label} 已有名为「{name}」的仓位")
            t.inventory.rename_location(SP.join_loc(label, old), SP.join_loc(label, name), note=f"仓位改名：{old} → {name}")
            meta["bins"] = [x for x in meta["bins"] if x["name"] != old]
            if meta.get("default") == old:
                meta["default"] = name
        elif not old and any(x["name"] == name for x in meta["bins"]):
            raise ValueError(f"{label} 已有名为「{name}」的仓位")
        hit = next((x for x in meta["bins"] if x["name"] == name), None)
        if hit:
            hit["desc"] = str(desc or "").strip()[:100]
        else:
            meta["bins"].append({"name": name, "desc": str(desc or "").strip()[:100]})
        if default:
            meta["default"] = name
        elif meta.get("default") == name:
            meta["default"] = ""
        t.db.set("stock_bins", bins)
    except ValueError as e:
        return {"error": str(e)}
    out = stock()
    out["bin"] = SP.join_loc(label, name)
    return out


@api
def stock_bin_delete(place="", name=""):
    """删仓位：里面的东西放回这个地点的总仓（一笔移库，能撤销）"""
    from .. import stockplaces as SP
    _invalidate_short()
    t = trade()
    bins = _bins(t)
    meta = bins.get(place) or {}
    if not any(x["name"] == name for x in meta.get("bins", [])) and not any(
            l.key.location == SP.join_loc(place, name) for l in t.inventory.list_stock()):
        return {"error": "未找到此仓位"}
    try:
        n = t.inventory.rename_location(SP.join_loc(place, name), place, note=f"删除仓位「{name}」：物品移回总仓")
    except ValueError as e:
        return {"error": str(e)}
    meta["bins"] = [x for x in meta.get("bins", []) if x["name"] != name]
    if meta.get("default") == name:
        meta["default"] = ""
    t.db.set("stock_bins", bins)
    out = stock()
    out["moved"] = n
    return out


@api
def stock_reserve(id="", qkey="", location="", ukey="", on=True):
    """这一行「不给目标用」（比如留着卖的）：目标不算它；再点一次取消"""
    from .. import goals as G
    _invalidate_short()
    t = trade()
    keys = list(t.db.get(G.RESERVED, []) or [])
    k = G.lot_key(id, qkey, location, ukey)
    if on and k not in keys:
        keys.append(k)
    if not on:
        keys = [x for x in keys if x != k]
    t.db.set(G.RESERVED, keys)
    return stock()


@api
def stock_ledger(start="", end="", type="", place="", q="", page=1, size=20):
    """仓储流水：按日期（本地日期，含两头）、类型、地点、物品名筛选，分页。新的在前"""
    t = trade()

    def day(v):
        try:
            return date.fromisoformat(str(v)[:10]) if v else None
        except ValueError:
            return None
    d0, d1 = day(start), day(end)
    q = (q or "").strip().lower()
    out = []
    for b in _all_batches(t):
        try:
            local = datetime.fromisoformat(b["at"]).astimezone().date()
        except ValueError:
            local = None
        if local and ((d0 and local < d0) or (d1 and local > d1)):
            continue
        if type and b["type"] != type:
            continue
        if place and place not in b["places"]:
            continue
        if q and q not in (b["names"] + " " + " ".join(b["items"]) + " " + b["note"]).lower():
            continue
        out.append(b)
    size = max(5, min(100, int(size or 20)))
    pages = max(1, (len(out) + size - 1) // size)
    page = max(1, min(pages, int(page or 1)))
    rows = [{k: v for k, v in b.items() if k != "names"} for b in out[(page - 1) * size: page * size]]
    places = sorted({p for b in _all_batches(t) for p in b["places"]})
    return {"rows": rows, "total": len(out), "page": page, "pages": pages, "size": size, "types": list(LEDGER_TYPES), "places": places}


@api
def stock_prices():
    """库存里有品质的东西去玩家市场（UEX / SCM）查一遍价（同时查，结果缓存 1 小时），查完重算估值"""
    from ..trade.providers.http import quality_group
    t = trade()
    todo = {}
    for line in t.inventory.list_stock():
        k = line.key
        if k.quality.startswith("exact:"):
            todo[(k.item_id, quality_group(k.quality[6:]))] = True

    def one(key):
        iid, group = key
        item = t.catalog.get(iid)
        if not item or iid.startswith("local:"):
            return 0
        try:
            return sum(1 for r in t.prices(item, group, "sell") if r.stats)
        except Exception:
            return 0
    with ThreadPoolExecutor(4) as ex:
        found = sum(1 for n in ex.map(one, list(todo)) if n)
    out = stock()
    out["checked"], out["found"] = len(todo), found
    return out


__all__ = [
    "MODE_ZH",
    "LEDGER_TYPES",
    "scu_amount",
    "_qlabel",
    "_amount_text",
    "_stock_kind",
    "_place_of",
    "_all_batches",
    "_history_view",
    "_bins",
    "_price_index",
    "_row_value",
    "stock",
    "_place_for",
    "_raw_amount",
    "stock_add",
    "craft_slots_for",
    "stock_add_named",
    "stock_suggest",
    "stock_set_quality",
    "stock_undo",
    "_row_key",
    "stock_out",
    "stock_set_qty",
    "stock_move",
    "stock_relocate",
    "stock_keep_custom",
    "stock_places",
    "stock_place_add",
    "stock_bin_save",
    "stock_bin_delete",
    "stock_reserve",
    "stock_ledger",
    "stock_prices",
]
