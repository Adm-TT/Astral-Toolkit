"""F8 物品悬停识别任务模块（Task: Hover & Tooltip）

从 app/services.py 中解耦出来，专职处理：
1. 鼠标悬停位置物品说明框（Tooltip）与格子角标的 OCR 图像裁剪与文字识别；
2. 物品名称汉化纠错、品质与堆叠数量提取；
3. 本机数据匹配、悬浮窗展示以及后台 UEX 市场价格异步查询。
"""
import itertools
import re
import sys
import threading
import time

from ..app import bus

WIN = sys.platform == "win32"

# ---------------------------------------------------------------- 视觉识别组件重导出（保持向后兼容）
from ..trade.inspector import (
    HOVER_REGIONS,
    HOVER_REGION,
    get_hover_regions,
    _read_tooltip,
    tooltip_quality,
    _AMOUNT,
    tooltip_row,
    parse_qlabel,
    parse_count,
    cell_labels,
    _is_mineral,
    inspect_item,
)

_last_hover = {}
_seq = itertools.count(1)          # 每次 F8 一个编号：同一秒按两次也分得清，后台补来的结果不会串到下一次


# ---------------------------------------------------------------- 依赖（2026-10-30 重构阶段 3：不再经 services 转发）
from ..app.hud_state import _item_hud, _off
from . import goals as _t_goals
from . import trade as _t_trade


def item_info(*args, **kwargs):
    return _t_trade.item_info(*args, **kwargs)


def trade():
    return _t_trade.trade()


def _market_rows(item_id, tier):
    return _t_trade._market_rows(item_id, tier)


def _goal_for(*names):
    return _t_goals._goal_for(*names)


def _goal_text(g):
    return _t_goals._goal_text(g)


def qty_text(qty, unit):
    """数量写成玩家看得懂的：0.495 SCU / 200 个 / 495,000 uSCU"""
    if qty is None:
        return ""
    if unit == "SCU":
        return f"{qty:g} SCU"
    if unit == "uSCU":
        return f"{qty:,.0f} uSCU"
    return f"{qty:g} 个"


def _tier(quality):
    """品质 → UEX 玩家市场的品质档 q0–q7（q0 = 品质 0，q1 = 1–499 … q7 = 950–1000）；不知道品质按 q0"""
    from ..trade.providers.http import quality_group
    g = quality_group(quality) if quality is not None else "q0"
    return g if g != "unknown" else "q0"


def _short_buy(info):
    rows = info.get("buy") or (info["variants"][0]["buy"] if info.get("variants") else [])
    if not rows:
        return ""
    r = rows[0]
    return f"{r['dist'] + '｜' if r['dist'] else ''}{r['price']:,.0f}｜{r['shop']}"


def _hover_lines(info, en, zh):
    """悬浮窗里物品下面的几行：买（商店有才写）、维科洛兑换、制造。没有的不写"""
    lines = []
    g = _goal_for(info.get("name"), en, zh)
    if g:
        lines.append(_goal_text(g))
    buy = _short_buy(info)
    if buy:
        lines.append(f"购买：{buy}")
    ships = info.get("ships") or []
    if ships and not buy:                        # 商店买不到、出厂自带在船上（2026-10-27 解包）
        lines.append(f"随船自带：{'、'.join(ships[:3])}" + (f" 等 {len(ships)} 条船" if len(ships) > 3 else ""))
    if info.get("how"):
        lines.append(f"获取：{info['how']}")
    try:
        from ..crafting import wikelo
        name = info.get("name") or en
        got = [c for c in wikelo.load() if any(wikelo._same(x, name) or (zh and wikelo._same(x, zh)) for x in [c.get("rz", ""), *c.get("rewards", [])])]
        if got:
            lines.append(f"可通过维科洛兑换获得：{got[0]['t']}" + (f" 等 {len(got)} 个" if len(got) > 1 else ""))
        uses = info.get("wikelo") or []
        if uses:
            u = uses[0]
            lines.append(f"可用于维科洛兑换：{u['reward']}" + (f" 等 {len(uses)} 个" if len(uses) > 1 else ""))
    except Exception:
        pass
    try:
        from ..crafting import crafting
        fold = lambda x: re.sub(r"[^a-z0-9一-鿿]", "", (x or "").lower())
        want = {fold(info.get("name")), fold(en), fold(zh)} - {""}
        bps = [b for b in crafting.blueprints() if fold(b["n"]) in want or fold(b["z"]) in want]
        if bps:
            lines.append("可制造：有蓝图（材料见物品查询）")
    except Exception:
        pass
    return lines


def _hover_more(seq, at, zh, en, info, quality=None, canon=True):
    """后台：对上玩家市场里的物品、查价、查掉落，查到一样补一样（悬浮窗和窗口都更新）"""
    from ..trade import console as C
    out = {"at": at, "seq": seq}
    t = trade()
    try:
        item, items = C.match_tooltip(t, zh, en)
    except Exception:
        item, items = None, []
    if _last_hover.get("seq") != seq:                     # 已经又按了一次 F8：这次的结果不要了
        return
    if item is not None and zh and C.has_chinese(zh) and canon:      # 只记汉化包里的标准名（认错的字不记，免得库存里显示错名）
        try:
            t.catalog.add_alias(item.id, zh)
        except Exception:
            pass
    out["market"] = {"id": item.id, "label": t.label(item.id)} if item else None
    out["candidates"] = [{"id": i.id, "label": t.label(i.id)} for i in items[:8]] if item is None else []
    # 认出的英文名有错字、本机没对上商店数据时：用市场里的标准英文名再查一次
    if item is not None and info.get("id") is None and C._fold(item.name) != C._fold(en):
        try:
            better = item_info(item.name, zh, loot=False)
            if better.get("id") is not None:
                info = better
                out["info"] = better
                if _last_hover.get("seq") == seq:         # 查的这会儿又按了 F8：别把这个物品的行写进下一次
                    lines = (_last_hover.get("lines") or [zh or en])[:1] + _hover_lines(better, item.name, zh)   # 第一行（名字｜品质｜数量）不动
                    _last_hover["lines"] = lines
                    _item_hud("\n".join(lines))
        except Exception:
            pass
    if _last_hover.get("seq") != seq:                     # 上面查名字、查本机数据的这会儿又按了 F8
        return
    if item is not None:
        bus.runtime_log(f"F8 匹配市场: {item.name}，正在获取价格...", tag="HOVER", level="INFO")
        _last_hover["id"] = item.id
        bus.publish("hover_more", dict(out))
        try:
            tier = _tier(quality)                         # 认出了品质：按那一档查价（925 → q6 900–949）
            prices, results = _market_rows(item.id, tier)
            if _last_hover.get("seq") != seq:
                return
            from ..trade.console import hud_market
            market = hud_market(results) if results is not None else ""
            if market:
                _item_hud("\n".join(_last_hover["lines"] + [market]))
            out["prices"] = dict(prices, quality=tier, op="sell")
        except Exception as e:
            out["prices"] = {"error": f"价格查询失败：{e}", "quality": _tier(quality), "op": "sell"}
    try:
        from ..crafting.loot import info as loot_info
        out["loot"] = loot_info(info.get("name") or en, zh)
    except Exception as e:
        out["loot"] = {"error": f"掉落数据查询失败：{e}"}
    if _last_hover.get("seq") == seq:
        bus.publish("hover_more", out)
        bus.runtime_log(f"F8 价格与数据同步完成: {zh or en}", tag="HOVER", level="INFO")


def hover_once(img=None):
    """F8：认出鼠标指着的物品，马上把名字和本机数据（哪里买、维科洛、制造）显示到悬浮窗；
    要联网的（玩家市场价、掉落）放到后台，查到了再补上。以前要等联网全查完才显示，慢好几秒"""
    from ..mining.screen import grab
    from ..trade import console as C
    why = _off("item")
    if why:
        _item_hud(f"物品识别暂时关闭：{why}", 8)
        return {"error": why}
    t0 = time.time()
    _last_hover.clear()
    _last_hover["seq"] = None                            # 上一次 F8 后台还没查完的价格，不再往悬浮窗上写
    bus.runtime_log("触发 F8 物品悬停识别，截取画面...", tag="HOVER", level="INFO")
    t_grab_0 = time.time()
    img = img or grab()
    t_grab = time.time()
    # 异步更新右下角截图预览，避免在关键路径上阻塞 50~150ms 的双重 JPEG 压缩与缩放
    threading.Thread(target=bus.update_preview, args=(img,), kwargs={"source": "hover", "force": True}, daemon=True).start()
    t1 = time.time()
    bus.publish("hover", {"state": "working"})
    _item_hud("识别中…", 30)                          # 按下就有反应
    cx, cy = C._cursor_on_image(img) if WIN else (img.width // 2, img.height // 2)
    res = inspect_item(img, (cx, cy))
    t2 = time.time()
    if not res:
        msg = "未找到物品说明框。鼠标停在物品上，等说明框出现后再按"
        ms_grab = (t_grab - t_grab_0) * 1000
        ms_ocr = (t2 - t1) * 1000
        bus.runtime_log(
            f"F8 未找到物品说明框 (总耗时 {(t2 - t0) * 1000:.0f}ms: 截图 {ms_grab:.0f}ms, 识别 {ms_ocr:.0f}ms)。请在说明框弹出后再次按下 F8",
            tag="HOVER",
            level="WARN",
        )
        bus.publish("hover", {"state": "miss", "msg": msg})
        _item_hud("未识别到物品\n鼠标停在物品上，等说明框出现后再按", 10)
        threading.Thread(target=C._hover_log, args=(img, [], None, f"识别 {(t2 - t1) * 1000:.0f}ms"),
                         daemon=True).start()
        return {"miss": True}
    zh, en = res["zh"], res["en"]
    canon = res["sure"]
    quality, qty, unit = res["quality"], res["qty"], res["unit"]
    craft = res["craft"]
    tokens = res["tokens"]
    where = res["where"]
    name = res.get("raw") or (zh, en)                      # 记日志、收错题用纠正前照字认出的名字
    at = time.strftime("%H:%M:%S")                         # 给人看的时间
    seq = next(_seq)                                       # 区分每一次 F8（同一秒按两次 at 一样）
    info = item_info(en, zh, loot=False)                   # 只用本机数据，很快
    head = (zh or en) + (f"｜品质 {quality}" if quality is not None else "") + (f"｜{qty_text(qty, unit)}" if qty else "")
    if not canon:                                          # 汉化包里没对上：名字只是照字认的，不硬猜成别的东西
        head += "｜识别结果不确定"
    try:
        from ..crafting.crafting import craft_text
    except Exception:
        craft_text = lambda c: ""
    lines = [head] + ([f"材料品质：{craft_text(craft)}"] if craft else []) + _hover_lines(info, en, zh)
    _last_hover.clear()
    _last_hover.update(at=at, seq=seq, id=None, lines=lines)
    _item_hud("\n".join(lines))                  # 没数据的行不显示；市场价查到了再补上
    t3 = time.time()
    ms_total = (t3 - t0) * 1000
    ms_grab = (t_grab - t_grab_0) * 1000
    ms_ocr = (t2 - t1) * 1000
    ms_local = (t3 - t2) * 1000
    bus.runtime_log(
        f"F8 成功识别: {zh or en}"
        + (f" | 品质 {quality}" if quality is not None else "")
        + (f" | {qty_text(qty, unit)}" if qty else "")
        + f" (总耗时 {ms_total:.0f}ms: 截图 {ms_grab:.0f}ms, 识别[{where}] {ms_ocr:.0f}ms, 解析 {ms_local:.0f}ms)",
        tag="HOVER",
        level="INFO",
    )
    bus.publish("hover", {"state": "ok", "zh": zh, "en": en, "info": info, "market": None, "candidates": [],
                          "pending": True, "at": at, "seq": seq, "quality": quality, "qty": qty, "unit": unit,
                          "tier": _tier(quality), "craft": craft, "sure": bool(canon)})   # sure=False：汉化包里没对上，名字是照字认的
    note = (f"耗时 截图{(t1 - t0) * 1000:.0f}ms 识别({where}){(t2 - t1) * 1000:.0f}ms "
            f"本机数据{(t3 - t2) * 1000:.0f}ms 共{(t3 - t0) * 1000:.0f}ms｜品质 {quality} 数量 {qty} {unit}"
            + ("" if canon else "｜汉化包里没对上"))
    threading.Thread(target=_hover_more, args=(seq, at, zh, en, info, quality, bool(canon)), daemon=True, name="hover-more").start()
    threading.Thread(target=C._hover_log, args=(img, tokens, name, note), daemon=True).start()
    if res.get("canon"):                                   # 帮助改进识别：名字那几行 + 汉化包里的正确名字（后台存，不拖慢 F8）
        from ..system import train_data
        threading.Thread(target=train_data.from_tooltip, args=(img, tokens, name, res["canon"]), daemon=True).start()
    return {"ok": True, "ms": int((t3 - t0) * 1000)}
