"""F8 物品悬停识别任务模块（Task: Hover & Tooltip）

从 app/services.py 中解耦出来，专职处理：
1. 鼠标悬停位置物品说明框（Tooltip）与格子角标的 OCR 图像裁剪与文字识别；
2. 物品名称汉化纠错、品质与堆叠数量提取；
3. 本机数据匹配、悬浮窗展示以及后台 UEX 市场价格异步查询。
"""
import re
import sys
import threading
import time

from ..app import bus

WIN = sys.platform == "win32"

# 物品说明框识别区域：整个中间部分（从左到右 25% ~ 75%，纵向覆盖 0% ~ 100% 全高）
HOVER_REGION = (0.25, 0.0, 0.75, 1.0)

_last_hover = {}


# ---------------------------------------------------------------- 依赖转发辅助
def _services():
    from ..app import services
    return services


def _item_hud(text, secs=30):
    try:
        _services()._item_hud(text, secs=secs)
    except Exception:
        pass


def _off(feature):
    try:
        return _services()._off(feature)
    except Exception:
        return None


def item_info(*args, **kwargs):
    return _services().item_info(*args, **kwargs)


def trade():
    return _services().trade()


def _market_rows(item_id, tier):
    return _services()._market_rows(item_id, tier)


def _goal_for(*names):
    try:
        return _services()._goal_for(*names)
    except Exception:
        return None


def _goal_text(g):
    try:
        return _services()._goal_text(g)
    except Exception:
        return ""


# ---------------------------------------------------------------- OCR 与说明框解析
def _read_tooltip(img, cursor):
    """→ (文字, (中文名, 英文名) 或 None, 认的范围)"""
    from ..trade import console as C
    from ..trade.ocr import recognize
    W, H = img.size
    l, t, r, b = HOVER_REGION
    box = (int(W * l), int(H * t), int(W * r), int(H * b))
    tokens = recognize(img.crop(box), urgent=True, offset=box[:2])
    name, sure = C.tooltip_pick(tokens, cursor, img)
    if name and sure:
        return tokens, name, "中间"
    # 中间这块连说明框的样子（体积 / 制造商 / 物品类型…）都没有、鼠标也在中间：多半是开着船按了 F8，
    # 不再整屏找（整屏一次 5~16 秒，2026-10-23 两位玩家在驾驶位上按 F8 都等了很久，CPU 也白占）
    inside = cursor is None or (box[0] <= cursor[0] <= box[2] and box[1] <= cursor[1] <= box[3])
    if inside and not any(C._is_anchor(k.text) for k in tokens):
        if name and C.plausible_name(*name):
            return tokens, name, "中间"
        return tokens, None, "中间"
    full = recognize(img, urgent=True)
    name_full, sure_full = C.tooltip_pick(full, cursor, img)
    if name_full and sure_full:                       # 整屏找：必须名字下面紧跟「体积/制造商/物品类型…」才算物品说明框
        return full, name_full, "整屏"                 # （不然会把全局聊天、飞船 HUD、地点标记当成物品，2026-10-23 用户反馈）
    if name and C.plausible_name(*name):              # 中间认到但没把握：像物品名才要（2026-10-23 全量样本测试：碎字、系统界面会被当物品）
        return tokens, name, "中间"
    return full, None, "整屏"


def tooltip_quality(tokens):
    """说明框里的品质：「品质：650」「品质 650」「Quality: 650」「Q650」→ 650；没有返回 None"""
    for t in sorted(tokens or [], key=lambda k: (k.box[1], k.box[0])):
        m = re.search(r"(?:品质|品貭|晶质|Quality)\s*[:：]?\s*(\d{1,4})", t.text, re.I) or re.fullmatch(r"\s*Q\s*(\d{3,4})\s*", t.text)
        if m and 0 <= int(m.group(1)) <= 1000:
            return int(m.group(1))
    return None


_AMOUNT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*[S5]\s*C\s*U$", re.I)


def tooltip_row(tokens):
    """说明框里的内容行「塔兰导电石Taranite｜925｜0.495 SCU」→ (品质, 数量 SCU)；没有返回 (None, None)。
    品质是数量左边、同一行最近的那个 0–1000 的整数（前面没写「品质」两个字，2026-10-23 用户截图）；
    「容量：1.00SCU」是箱子能装多少，不算"""
    toks = list(tokens or [])
    for a in sorted(toks, key=lambda k: (k.box[1], k.box[0])):
        t = a.text.replace(" ", "")
        if "容量" in t or "体积" in t:
            continue
        m = _AMOUNT.match(t)
        if not m:
            continue
        amount = float(m.group(1).replace(",", "."))
        h = max(a.box[3], 10)
        mid = a.box[1] + a.box[3] / 2
        same = [k for k in toks if k is not a and abs(k.box[1] + k.box[3] / 2 - mid) < 0.6 * h and k.box[0] < a.box[0]]
        q = None
        for k in sorted(same, key=lambda k: -k.box[0]):          # 数量左边最近的整数
            mq = re.fullmatch(r"\d{1,4}", k.text.strip()) or re.search(r"\s(\d{1,4})$", k.text.strip())
            if mq and 0 <= int(mq.group(mq.lastindex or 0)) <= 1000:
                q = int(mq.group(mq.lastindex or 0))
                break
        return q, amount
    return None, None


def parse_qlabel(text):
    """物品格子左上角的品质标签 → 品质；不是品质标签返回 None。
    游戏里写成「575Q」「0Q」。OCR 常把 Q 认成 0（907Q → 9070）、把 0 认成 Q（0Q → QQ），
    品质最多 1000，四位数末尾是 0 就是 Q 认错了（2026-10-23 用户截图实测 23 个全对）"""
    t = (text or "").replace(" ", "").upper()
    if t in ("QQ", "OQ", "0Q", "00", "0O"):
        return 0
    m = re.fullmatch(r"(\d{1,4})[QO]", t)
    if m:
        return int(m.group(1)) if int(m.group(1)) <= 1000 else None
    m = re.fullmatch(r"\d{1,5}", t)
    if not m:
        return None
    if len(t) >= 4 and t.endswith("0") and t != "1000":
        v = int(t[:-1])                                   # Q 认成了 0
        return v if v <= 1000 else None
    return int(t) if int(t) <= 1000 else None


def parse_count(text):
    """格子右上角的堆叠数量「200x」→ 200；「200/200」（当前量 / 上限）不是数量"""
    m = re.fullmatch(r"(\d{1,5})[xX×]", (text or "").replace(" ", ""))
    return int(m.group(1)) if m else None


def cell_labels(img, cursor, tokens=None, size=None):
    """鼠标指着的那个物品格子：左上角的品质（575Q）和右上角的数量（200x）。没有返回 None。
    只认鼠标上方一个格子高度以内的标签；同一排里品质取鼠标左边最近的、数量取鼠标右边最近的。
    size：格子大小 (宽, 高)，默认按整屏比例估（1440p 下约 150×140）"""
    W, H = img.size
    cw, ch = size or (int(W * 0.065), int(H * 0.11))
    cx, cy = cursor
    if tokens is None:
        from ..trade.ocr import recognize
        box = (max(0, cx - cw), max(0, cy - ch), min(W, cx + cw), min(H, cy + ch // 6))
        # native=True 避免小裁剪图被 RapidOCR 强行放大至 736px，提速 2~3 倍
        tokens = recognize(img.crop(box), urgent=True, offset=box[:2], native=True)
    best_q = best_n = None
    for t in tokens:
        x, y, w, h = t.box
        if not cy - ch < y < cy:
            continue
        q = parse_qlabel(t.text)
        if q is not None and cx - cw < x <= cx + 4 and (best_q is None or (y, x) > best_q[:2]):
            best_q = (y, x, q)
        n = parse_count(t.text)
        if n is not None and cx - 4 <= x + w < cx + cw and (best_n is None or (y, -x) > best_n[:2]):
            best_n = (y, -x, n)
    return (best_q[2] if best_q else None), (best_n[2] if best_n else None)


def _is_mineral(zh, en):
    from ..mining.data import SIGNATURES
    from ..core.i18n import mineral_en
    return (en or "").strip().lower() in {k.lower() for k in SIGNATURES} or bool(zh and mineral_en(zh))


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


def _hover_more(at, zh, en, info, quality=None, canon=True):
    """后台：对上玩家市场里的物品、查价、查掉落，查到一样补一样（悬浮窗和窗口都更新）"""
    from ..trade import console as C
    out = {"at": at}
    t = trade()
    try:
        item, items = C.match_tooltip(t, zh, en)
    except Exception:
        item, items = None, []
    if _last_hover.get("at") != at:                       # 已经又按了一次 F8：这次的结果不要了
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
                lines = (_last_hover.get("lines") or [zh or en])[:1] + _hover_lines(better, item.name, zh)   # 第一行（名字｜品质｜数量）不动
                _last_hover["lines"] = lines
                _item_hud("\n".join(lines))
        except Exception:
            pass
    if item is not None:
        bus.runtime_log(f"F8 匹配市场: {item.name}，正在获取价格...", tag="HOVER", level="INFO")
        _last_hover["id"] = item.id
        bus.publish("hover_more", dict(out))
        try:
            tier = _tier(quality)                         # 认出了品质：按那一档查价（925 → q6 900–949）
            prices, results = _market_rows(item.id, tier)
            if _last_hover.get("at") != at:
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
    if _last_hover.get("at") == at:
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
    _last_hover["at"] = "识别中"                          # 上一次 F8 后台还没查完的价格，不再往悬浮窗上写
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
    tokens, name, where = _read_tooltip(img, (cx, cy))
    t2 = time.time()
    if not name:
        msg = "未找到物品说明框。鼠标停在物品上，等说明框出现后再按"
        ms_grab = (t_grab - t_grab_0) * 1000
        ms_ocr = (t2 - t1) * 1000
        bus.runtime_log(
            f"F8 未找到物品说明框 (总耗时 {(t2 - t0) * 1000:.0f}ms: 截图 {ms_grab:.0f}ms, 识别[{where}] {ms_ocr:.0f}ms)。请在说明框弹出后再次按下 F8",
            tag="HOVER",
            level="WARN",
        )
        bus.publish("hover", {"state": "miss", "msg": msg})
        _item_hud("未识别到物品\n鼠标停在物品上，等说明框出现后再按", 10)
        threading.Thread(target=C._hover_log, args=(img, tokens, None, f"识别({where}) {(t2 - t1) * 1000:.0f}ms"),
                         daemon=True).start()
        return {"miss": True}
    zh, en = name
    from ..trade.names import canonical
    canon = canonical(zh, en)                              # 认错的字按汉化包纠正（冷冻舱（刻度）→ 冷冻舱（剜度））
    if canon:
        zh, en = canon
    at = time.strftime("%H:%M:%S")
    info = item_info(en, zh, loot=False)                   # 只用本机数据，很快
    mineral = _is_mineral(zh, en)
    # 品质：说明框内容行（矿：925｜0.495 SCU）> 格子左上角 575Q > 没写就是 0（矿没读到就空着，让玩家自己填）
    # 数量：矿按说明框里的 SCU，其他按格子右上角的 200x，没有就是 1 个
    row_q, row_amt = tooltip_row(tokens)
    if row_q is None:
        row_q = tooltip_quality(tokens)                    # 「品质：650」这种写了字的
    cell_q, cell_n = None, None
    # 矿物直接由说明框提取数量和品质，跳过格子 OCR；非矿物优先复用 tokens，避免二次整图/局域推理
    if not mineral:
        can_reuse = False
        if where == "整屏":
            can_reuse = True
        else:
            cw, ch = int(img.width * 0.065), int(img.height * 0.11)
            l, t, r, b = HOVER_REGION
            box_hover = (int(img.width * l), int(img.height * t), int(img.width * r), int(img.height * b))
            if cx - cw >= box_hover[0] and cy - ch >= box_hover[1] and cx + cw <= box_hover[2] and cy + ch // 6 <= box_hover[3]:
                can_reuse = True
        try:
            cell_q, cell_n = cell_labels(img, (cx, cy), tokens=tokens if can_reuse else None)
        except Exception:
            cell_q, cell_n = None, None
    quality = row_q if row_q is not None else cell_q if cell_q is not None else (None if mineral else 0)
    if mineral:
        qty, unit = row_amt, "SCU"
    else:
        qty, unit = (cell_n or 1), "个"
    craft = None
    if not mineral and row_q is None and cell_q is None:   # 制造出来的东西没写品质：按加成行倒推各材料槽（和盘点同一套，老大 2026-10-27 反馈 F8 显示品质 0）
        try:
            from ..crafting.crafting import parse_mods, solve_slots, for_item, craft_text
            mods = parse_mods(tokens)
            res = solve_slots(for_item(en, zh), mods) if mods else None
            if res and res["exact"]:                       # 加成对不上蓝图（认错数字 / 蓝图不对）：不当品质（Codex 2026-10-27）
                quality, craft = res["avg"], res["slots"]
            elif res:
                quality = None
        except Exception:
            craft = None
    head = (zh or en) + (f"｜品质 {quality}" if quality is not None else "") + (f"｜{qty_text(qty, unit)}" if qty else "")
    if not canon:                                          # 汉化包里没对上：名字只是照字认的，不硬猜成别的东西
        head += "｜识别结果不确定"
    lines = [head] + ([f"材料品质：{craft_text(craft)}"] if craft else []) + _hover_lines(info, en, zh)
    _last_hover.clear()
    _last_hover.update(at=at, id=None, lines=lines)
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
                          "pending": True, "at": at, "quality": quality, "qty": qty, "unit": unit,
                          "tier": _tier(quality), "craft": craft})
    note = (f"耗时 截图{(t1 - t0) * 1000:.0f}ms 识别({where}){(t2 - t1) * 1000:.0f}ms "
            f"本机数据{(t3 - t2) * 1000:.0f}ms 共{(t3 - t0) * 1000:.0f}ms｜品质 {quality} 数量 {qty} {unit}"
            + ("" if canon else "｜汉化包里没对上"))
    threading.Thread(target=_hover_more, args=(at, zh, en, info, quality, bool(canon)), daemon=True, name="hover-more").start()
    threading.Thread(target=C._hover_log, args=(img, tokens, name, note), daemon=True).start()
    if canon:                                              # 帮助改进识别：名字那几行 + 汉化包里的正确名字（后台存，不拖慢 F8）
        from ..system import train_data
        threading.Thread(target=train_data.from_tooltip, args=(img, tokens, name, canon), daemon=True).start()
    return {"ok": True, "ms": int((t3 - t0) * 1000)}
