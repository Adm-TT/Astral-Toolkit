"""F8 物品悬停识别任务模块（Task: Hover & Tooltip）

专职处理：
1. 鼠标悬停位置物品说明框（Tooltip）与格子角标的 OCR 图像裁剪与文字识别；
2. 物品名称汉化纠错、品质与堆叠数量提取；
3. 本机数据匹配、悬浮窗展示以及后台 UEX 市场价格异步查询；本机数据、掉落、玩家市场经 bootstrap 接的 HoverLinks（IQ-B6；F 段 B5 起由「识别」接口和 F8 热键当参数传进来）。
"""

import itertools
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..app import bus, preview
from ..trade.inspector import inspect_item, _read_tooltip, HOVER_REGION  # noqa: F401

WIN = sys.platform == "win32"

_last_hover = {}
_seq = itertools.count(
    1
)  # 每次 F8 一个编号：同一秒按两次也分得清，后台补来的结果不会串到下一次


# ---------------------------------------------------------------- 依赖（2026-10-30 重构阶段 3：不再经 services 转发）
# IQ-B6：物品卡片、掉落、玩家市场经 bootstrap 接的 HoverLinks（tasks/catalog），不再直接拿 tasks/trade 和 Trade
from ..app.hud_state import _item_hud  # noqa: E402
from . import goals as _t_goals  # noqa: E402


@dataclass(frozen=True)
class HoverLinks:
    """F8 要用的物品查询（IQ-B6，bootstrap._hover_links 接）：
    item_card(name, zh, id=None, loot=True, exact=False)：物品卡片字典，和窗口物品查询页同一份；
    loot(name, zh)：掉落 → LootLookup（loot / error）；
    market()：开一个玩家市场会话（match / remember_alias / label），Trade 第一次用才造；
    market_rows(item_id, tier)：报价表 (prices, results)；hud_market(results)：悬浮窗「市场」那一行；
    wikelo_rewards(name, zh)：能换到这件东西的维科洛兑换（tasks/wikelo.rewards_for）；
    has_blueprint(*names)：有没有做这件东西的蓝图（tasks/crafting.has_blueprint）"""

    item_card: Callable[..., dict]
    loot: Callable[[str, str], Any]
    market: Callable[[], Any]
    market_rows: Callable[[Any, str], Any]
    hud_market: Callable[[Any], str]
    wikelo_rewards: Callable[[str, str], list]
    has_blueprint: Callable[..., bool]


def item_info(links: HoverLinks, /, *args, **kwargs):
    """物品卡片（和窗口物品查询页同一份）：F8 首屏、市场名纠正后重查都用它
    links：bootstrap 接的 HoverLinks"""
    return links.item_card(*args, **kwargs)


def last_hover():
    """最近一次 F8 的状态（at、seq、id、lines）的快照，给查价、问题反馈读（IQ-B6）：拿到的是副本，改了不影响 F8"""
    snap = dict(_last_hover)
    if "lines" in snap:
        snap["lines"] = list(snap["lines"])
    return snap


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
    rows = info.get("buy") or (
        info["variants"][0]["buy"] if info.get("variants") else []
    )
    if not rows:
        return ""
    r = rows[0]
    return f"{r['dist'] + '｜' if r['dist'] else ''}{r['price']:,.0f}｜{r['shop']}"


def _hover_lines(links: HoverLinks, info, en, zh):
    """悬浮窗里物品下面的几行：买（商店有才写）、维科洛兑换、制造。没有的不写"""
    lines = []
    g = _goal_for(info.get("name"), en, zh)
    if g:
        lines.append(_goal_text(g))
    buy = _short_buy(info)
    if buy:
        lines.append(f"购买：{buy}")
    ships = info.get("ships") or []
    if ships and not buy:  # 商店买不到、出厂自带在船上（2026-10-27 游戏数据）
        lines.append(
            f"随船自带：{'、'.join(ships[:3])}"
            + (f" 等 {len(ships)} 条船" if len(ships) > 3 else "")
        )
    if info.get("how"):
        lines.append(f"获取：{info['how']}")
    try:
        name = info.get("name") or en
        got = links.wikelo_rewards(name, zh)
        if got:
            lines.append(
                f"可通过维科洛兑换获得：{got[0]['t']}"
                + (f" 等 {len(got)} 个" if len(got) > 1 else "")
            )
        uses = info.get("wikelo") or []
        if uses:
            u = uses[0]
            lines.append(
                f"可用于维科洛兑换：{u['reward']}"
                + (f" 等 {len(uses)} 个" if len(uses) > 1 else "")
            )
    except Exception:
        pass
    try:
        if links.has_blueprint(info.get("name"), en, zh):
            lines.append("可制造：有蓝图（材料见物品查询）")
    except Exception:
        pass
    return lines


def _hover_more(links: HoverLinks, seq, at, zh, en, info, quality=None, canon=True):
    """后台：对上玩家市场里的物品、查价、查掉落，查到一样补一样（悬浮窗和窗口都更新）"""
    from ..trade.matching import _fold, alias_ok
    from ..trade.names import has_chinese  # 只拿名字小工具，不碰 Trade

    out = {"at": at, "seq": seq}
    m = links.market()  # 以前 Trade 造不出来这次后台补价整个不做，现在一样
    try:
        item, items = m.match(zh, en)
    except Exception:
        item, items = None, []
    if _last_hover.get("seq") != seq:  # 已经又按了一次 F8：这次的结果不要了
        return
    if (
        item is not None and zh and has_chinese(zh) and canon and alias_ok(item, zh, en)
    ):  # 只记汉化包里的标准名（认错的字不记，免得库存里显示错名）；配上的得是同一件（模糊、前缀配上的变体不记，待做 61）
        try:
            m.remember_alias(item.id, zh)
        except Exception:
            pass
    out["market"] = {"id": item.id, "label": m.label(item.id)} if item else None
    out["candidates"] = (
        [{"id": i.id, "label": m.label(i.id)} for i in items[:8]]
        if item is None
        else []
    )
    # 认出的英文名有错字、本机没对上商店数据时：用市场里的标准英文名再查一次
    if item is not None and info.get("id") is None and _fold(item.name) != _fold(en):
        try:
            better = item_info(links, item.name, zh, loot=False)
            if better.get("id") is not None:
                info = better
                out["info"] = better
                if (
                    _last_hover.get("seq") == seq
                ):  # 查的这会儿又按了 F8：别把这个物品的行写进下一次
                    lines = (_last_hover.get("lines") or [zh or en])[:1] + _hover_lines(
                        links, better, item.name, zh
                    )  # 第一行（名字｜品质｜数量）不动
                    _last_hover["lines"] = lines
                    _item_hud("\n".join(lines))
        except Exception:
            pass
    if _last_hover.get("seq") != seq:  # 上面查名字、查本机数据的这会儿又按了 F8
        return
    if item is not None:
        bus.runtime_log(
            f"F8 匹配市场: {item.name}，正在获取价格...", tag="HOVER", level="INFO"
        )
        _last_hover["id"] = item.id
        bus.publish("hover_more", dict(out))
        try:
            tier = _tier(quality)  # 认出了品质：按那一档查价（925 → q6 900–949）
            prices, results = links.market_rows(item.id, tier)
            if _last_hover.get("seq") != seq:
                return

            market = links.hud_market(results) if results is not None else ""
            if market:
                _item_hud("\n".join(_last_hover["lines"] + [market]))
            out["prices"] = dict(prices, quality=tier, op="sell")
        except Exception as e:
            out["prices"] = {
                "error": f"价格查询失败：{e}",
                "quality": _tier(quality),
                "op": "sell",
            }
    try:
        r = links.loot(info.get("name") or en, zh)
        out["loot"] = (
            r.loot if r.error is None else {"error": f"掉落数据查询失败：{r.error}"}
        )
    except Exception as e:
        out["loot"] = {"error": f"掉落数据查询失败：{e}"}
    if _last_hover.get("seq") == seq:
        bus.publish("hover_more", out)
        bus.runtime_log(f"F8 价格与数据同步完成: {zh or en}", tag="HOVER", level="INFO")


# F8 第一遍没认准时，等这么久再截一次（说明框还没出来 / 没出完，2026-11-06 老大验收 RD-B1）
RETRY_WAIT = 0.5


def hover_once(links: HoverLinks, /, img=None):
    """F8：认出鼠标指着的物品，马上把名字和本机数据（哪里买、维科洛、制造）显示到悬浮窗；
    要联网的（玩家市场价、掉落）放到后台，查到了再补上。以前要等联网全查完才显示，慢好几秒"""
    from ..mining.screen import grab
    from ..trade import inspector as _insp

    t0 = time.time()
    _last_hover.clear()
    _last_hover["seq"] = None  # 上一次 F8 后台还没查完的价格，不再往悬浮窗上写
    from ..core import run_records

    run_records.record("HOVER", "触发 F8 物品识别", ui_tag="HOVER")
    own = img is None  # 自己截的图才等一下再截第二次；窗口、测试传进来的图照旧只认一遍
    t_grab_0 = time.time()
    img = img or grab()
    t_grab = time.time()
    # 异步更新右下角截图预览，避免在关键路径上阻塞 50~150ms 的双重 JPEG 压缩与缩放
    threading.Thread(
        target=preview.update_preview,
        args=(img,),
        kwargs={"source": "hover", "force": True},
        daemon=True,
    ).start()
    t1 = time.time()
    bus.publish("hover", {"state": "working"})
    _item_hud("识别中…", 30)  # 按下就有反应
    cx, cy = _insp._cursor_on_image(img) if WIN else (img.width // 2, img.height // 2)
    res = (
        inspect_item(img, (cx, cy), whole_screen=False)
        if own
        else inspect_item(img, (cx, cy))
    )
    if own and not (res and res["sure"]):
        # 第一遍没认准：多半按早了，说明框还没出来 / 没出完（截到半透明的）。等一下再截一次，这一遍照旧可以整屏；
        # 第二遍什么都没认出来就还用第一遍的（2026-11-06 老大验收：一次没认出、一次 8 秒认成制造商）
        got = f"认成「{res['zh'] or res['en']}」没对上汉化包" if res else "没找到说明框"
        bus.runtime_log(
            f"F8 第一遍{got}，等 {RETRY_WAIT} 秒再截一次", tag="HOVER", level="INFO"
        )
        time.sleep(RETRY_WAIT)
        img2 = grab()
        cur2 = (
            _insp._cursor_on_image(img2) if WIN else (img2.width // 2, img2.height // 2)
        )
        res2 = inspect_item(img2, cur2)
        if res2 is not None or res is None:
            img, (cx, cy), res = img2, cur2, res2
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
        threading.Thread(
            target=_insp._hover_log,
            args=(img, [], None, f"识别 {(t2 - t1) * 1000:.0f}ms"),
            daemon=True,
        ).start()
        return {"miss": True}
    zh, en = res["zh"], res["en"]
    canon = res["sure"]
    quality, qty, unit = res["quality"], res["qty"], res["unit"]
    craft = res["craft"]
    tokens = res["tokens"]
    where = res["where"]
    name = res.get("raw") or (zh, en)  # 记日志、收错题用纠正前照字认出的名字
    at = time.strftime("%H:%M:%S")  # 给人看的时间
    seq = next(_seq)  # 区分每一次 F8（同一秒按两次 at 一样）
    info = item_info(links, en, zh, loot=False)  # 只用本机数据，很快
    from .system.about import data_names_ready

    library_ready = data_names_ready()
    head = (
        (zh or en)
        + (f"｜品质 {quality}" if quality is not None else "")
        + (f"｜{qty_text(qty, unit)}" if qty else "")
    )
    if not canon:
        # 库没下全时优先提示更新数据，避免误当成 OCR/汉化对不上
        # （docs/superpowers/specs/2026-11-04-f8-unsure-data-hint.md）
        head += (
            "｜本地数据不完整，请先更新数据"
            if not library_ready
            else "｜识别结果不确定"
        )
    try:
        from ..crafting.reverse import craft_text
    except Exception:
        craft_text = lambda c: ""  # noqa: E731
    lines = (
        [head]
        + ([f"材料品质：{craft_text(craft)}"] if craft else [])
        + _hover_lines(links, info, en, zh)
    )
    _last_hover.clear()
    _last_hover.update(at=at, seq=seq, id=None, lines=lines)
    _item_hud("\n".join(lines))  # 没数据的行不显示；市场价查到了再补上
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
    bus.publish(
        "hover",
        {
            "state": "ok",
            "zh": zh,
            "en": en,
            "info": info,
            "market": None,
            "candidates": [],
            "pending": True,
            "at": at,
            "seq": seq,
            "quality": quality,
            "qty": qty,
            "unit": unit,
            "tier": _tier(quality),
            "craft": craft,
            "sure": bool(canon),
            "library_ready": bool(library_ready),
        },
    )  # sure=False：名字照字认的；library_ready 供 UI 区分「没更新数据」
    note = (
        f"耗时 截图{(t1 - t0) * 1000:.0f}ms 识别({where}){(t2 - t1) * 1000:.0f}ms "
        f"本机数据{(t3 - t2) * 1000:.0f}ms 共{(t3 - t0) * 1000:.0f}ms｜品质 {quality} 数量 {qty} {unit}"
        + (
            ""
            if canon
            else ("｜本地数据不完整" if not library_ready else "｜汉化包里没对上")
        )
    )
    threading.Thread(
        target=_hover_more,
        args=(links, seq, at, zh, en, info, quality, bool(canon)),
        daemon=True,
        name="hover-more",
    ).start()
    threading.Thread(
        target=_insp._hover_log, args=(img, tokens, name, note), daemon=True
    ).start()
    if res.get(
        "canon"
    ):  # 帮助改进识别：名字那几行 + 汉化包里的正确名字（后台存，不拖慢 F8）
        from ..system import train_data

        threading.Thread(
            target=train_data.from_tooltip,
            args=(img, tokens, name, res["canon"]),
            daemon=True,
        ).start()
    return {"ok": True, "ms": int((t3 - t0) * 1000)}
