"""窗口调用的功能接口：每个函数收 JSON 参数、返回 JSON。耗时的放后台线程，结果用 bus 推给窗口

和命令行版本用同一套数据和算法（shops / loot / acquire / navigate / locations / crafting / wikelo / trade），
只是不再 input() 一步步问，改成窗口里点选。
"""
import math
import re
from pathlib import Path
import sys
import threading
import time

from . import bus

WIN = sys.platform == "win32"
API = {}


def api(fn):
    API[fn.__name__] = fn
    return fn


def _hud():
    from ..overlay import hud
    return hud()


_ITEM_SEQ = [0]
ITEM_HUD_SECONDS = 60     # F8 物品结果在悬浮窗上留多久（2026-10-23 用户：一直挂着不消失）


_OFF_TOLD = set()


def _off(feature):
    """这个功能有没有被远程关掉（latest.json 的 disabled，update_check.disabled）：关了返回原因，第一次碰到时在悬浮窗提示一次"""
    try:
        from .. import update_check
        why = update_check.disabled(feature)
    except Exception:
        return None
    if why and feature not in _OFF_TOLD:
        _OFF_TOLD.add(feature)
        try:
            _note_hud("AT", f"{update_check.FEATURES.get(feature, feature)}暂时关闭：{why}", 8)
        except Exception:
            pass
    return why


def _note_hud(section, text, secs=6):
    """悬浮窗上一条短提示，secs 秒后自己收起（1.6.61：白色胶囊，同时只有一条，新的顶掉旧的）"""
    h = _hud()
    if hasattr(h, "note"):
        h.note(text, secs)
        return
    h.set(section, text)

    def gone():
        if getattr(_hud(), "sections", {}).get(section) == text:
            _hud().clear(section)
    t = threading.Timer(secs, gone)
    t.daemon = True
    t.start()


ITEM_AWAY_PX = 160         # 鼠标离开按 F8 时的位置这么远（1080p 像素，按屏幕高度放大）就收起物品结果
ITEM_AWAY_AFTER = 1.5      # 至少先显示这么久（秒）
_ITEM_MODE = {"pinned": False, "origin": None, "shown_at": 0.0}


def _cursor():
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return None


def _key_down(vk):
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def item_key_pressed():
    """按下物品识别键那一刻：记下鼠标在哪、是不是按着 Shift（Shift+F8 = 钉住，一直挂着，再按 F8 换掉）。
    借鉴流放之路的 Awakened PoE Trade（MIT）：鼠标移开自动收起、按住 Ctrl 不收、另一个键弹出固定的（2026-10-27）"""
    _ITEM_MODE.update(pinned=_key_down(0x10), origin=_cursor(), shown_at=time.time())


def _item_hud(text, secs=ITEM_HUD_SECONDS):
    """悬浮窗「物品」分区：鼠标从物品上移开就收起（按住 Ctrl 不收）；钉住的（Shift+F8）一直挂着；
    最多 secs 秒。期间内容更新了（比如市场价补上）就按新内容重新计时"""
    _ITEM_SEQ[0] += 1
    my = _ITEM_SEQ[0]
    _hud().set("物品", text)
    _ITEM_MODE["shown_at"] = time.time()      # 每次显示（识别中、结果、补上价格）都重新给够阅读时间（Codex 2026-10-27）
    if _ITEM_MODE["pinned"]:
        return

    def watch():
        import ctypes
        try:
            h = ctypes.windll.user32.GetSystemMetrics(1) or 1080
        except Exception:
            h = 1080
        away = ITEM_AWAY_PX * max(1.0, h / 1080)
        end = time.time() + secs
        while _ITEM_SEQ[0] == my and time.time() < end:
            time.sleep(0.1)
            o, c = _ITEM_MODE["origin"], _cursor()
            if (o and c and time.time() - _ITEM_MODE["shown_at"] >= ITEM_AWAY_AFTER and not _key_down(0x11)
                    and math.dist(o, c) > away):
                break
            if _key_down(0x11):                 # 按住 Ctrl：不收，也不算时间
                end = max(end, time.time() + 1)
        if _ITEM_SEQ[0] == my:                 # 之后又写过（再按 F8、价格补上）就不归这次管
            _hud().clear("物品")
    threading.Thread(target=watch, daemon=True, name="item-hud").start()


# ================================================================ 状态 / 设置 / 升级 / 诊断
# 已解耦迁移至 sc_mining.tasks.system
from ..tasks.system import (
    HOTKEYS,
    _hotkey_values,
    hotkey_conflicts,
    status,
    _gridtext_status,
    _version,
    _upgrade_found,
    _online_info,
    _online_loop,
    _online_public,
    upgrade_check,
    _online_task,
    upgrade_online,
    upgrade_rollback,
    _task_print,
    _vpk_rollback_task,
    upgrade_mark_stable,
    _upgrade_task,
    _drop_upload,
    legacy_scan,
    legacy_import,
    legacy_skip,
    legacy_quit,
    upgrade_apply,
    upgrade_receive,
    _sweep_uploads,
    upgrade_upload,
    upgraded,
    _data_versions,
    _desktop,
    _system_info,
    export_logs,
    _fb_dir,
    feedback_report,
    feedback_list,
    feedback_export,
    feedback_clear,
    cockpit_check,
    overlay_move,
    set_settings,
    update_data,
    about_info,
    open_source_site,
    third_party_licenses,
    open_referral,
    agree,
    show,
    quit,
)

# ================================================================ 全局搜索

@api
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
        out["places"] = nav_search(q)["rows"][:6]
    except Exception:
        pass
    try:
        out["blueprints"] = craft_search(q)[:6]
    except Exception:
        pass
    try:
        out["wikelo"] = wikelo_search(q)[:5]
    except Exception:
        pass
    return out


# ================================================================ 物品：在哪买 / 同款 / 掉落 / 维科洛

@api
def item_search(q=""):
    """物品查询搜索（1.6.41 起商店、掉落、汉化包一起搜，见 itemsearch.py）。
    src：shop 商店有数据 / loot 只在掉落数据里 / loc 商店和掉落数据里都没有（只有汉化包里有名字）"""
    from .. import itemsearch
    from ..i18n import shop_cat_zh
    return [{"id": r["shop"], "name": r["en"], "zh": r["zh"], "category": shop_cat_zh(r["cat"]) or _wiki_cat(r),
             "src": "shop" if r["shop"] is not None else "loot" if r["loot"] else "wiki" if r.get("wiki") else "loc"}
            for r in itemsearch.find(q, limit=30)]


WIKI_TYPE_ZH = {"WeaponPersonal": "单兵武器", "WeaponGun": "舰炮", "MissileLauncher": "导弹架", "Missile": "导弹", "Turret": "炮塔",
                "Char_Armor_Helmet": "头盔", "Char_Armor_Torso": "胸甲", "Char_Armor_Arms": "臂甲", "Char_Armor_Legs": "腿甲",
                "Char_Armor_Backpack": "背包", "Char_Armor_Undersuit": "基底服", "Char_Clothing_Torso_0": "上衣", "Char_Clothing_Torso_1": "外套",
                "Char_Clothing_Legs": "裤子", "Char_Clothing_Feet": "鞋", "Char_Clothing_Hat": "帽子", "Char_Clothing_Hands": "手套",
                "WeaponAttachment": "附件", "Shield": "护盾生成器", "PowerPlant": "发电机", "Cooler": "冷却器", "QuantumDrive": "量子驱动器",
                "Radar": "雷达", "WeaponMining": "采矿激光器", "MiningModifier": "采矿模组", "Container": "货柜", "TractorBeam": "牵引光束",
                "FuelTank": "燃料箱", "FuelIntake": "燃料进气口", "Thruster": "推进器", "Armor": "舰船装甲", "UtilityTurret": "工具炮塔",
                "RemovableChip": "钥匙卡", "FPS_Consumable": "消耗品", "Food": "食物", "Drink": "饮料", "Commodity": "商品"}


def _wiki_cat(r):
    """只在 wiki 清单里的物品：类型 + 尺寸当分类显示（「导弹架 S5」）"""
    if not r.get("wtype"):
        return ""
    t = WIKI_TYPE_ZH.get(r["wtype"], r["wtype"])
    return f"{t} S{r['wsize']}" if r.get("wsize") not in (None, 0, 1) or (r.get("wsize") == 1 and r["wtype"] in ("WeaponGun", "MissileLauncher", "Shield", "PowerPlant", "Cooler", "QuantumDrive", "Radar", "WeaponMining")) else t


def _zh_of(en):
    try:
        from ..trade.names import table
        rev = getattr(_zh_of, "_rev", None)
        if rev is None:
            rev = _zh_of._rev = {v.lower(): k for k, v in table().items()}
        return rev.get(en.lower(), "")
    except Exception:
        return ""


@api
def item_info(name="", zh="", id=None, loot=True, exact=False):
    """exact=True：从物品查询 / 顶上搜索框的结果点进来的（名字是准的）。
    掉落明细本机没有时不上网等（loot 里给 pending），窗口再调 item_loot 后台取（2026-10-28 用户反馈卡 10 秒）"""
    from .. import acquire
    d = acquire.info(name, zh, id, show_loot=loot, exact=bool(exact), loot_online=False)
    from ..i18n import gear_zh_of_item, shop_cat_zh
    d["zh"] = gear_zh_of_item(d["name"]) or d.get("zh") or _zh_of(d["name"])   # 采矿装备的中文不带型号，和配置区一致
    if d.get("category"):
        d["category"] = shop_cat_zh(d["category"])
    g = _goal_for(d.get("name"), name, zh, d["zh"])
    d["goal"] = _goal_text(g) if g else ""
    return d


@api
def item_loot(name="", zh=""):
    """物品查询里掉落那一块：明细本机没有时窗口在后面单独调这个（会上网，最多等 15 秒，不挡别的）"""
    try:
        from ..loot import info as loot_info
        return {"loot": loot_info(name, zh)}
    except Exception as e:
        return {"loot": {"error": f"掉落数据出错：{e}"}}


@api
def nav_shop(shop="", place=""):
    """物品查询里点一处商店 → 导航过去（2026-10-28 用户定）。先找主城 / 空间站里这家店的点（城里导航），
    没有就导航到这个地点本身（星图）"""
    from .. import navigate as n
    data = n.load()
    brand = re.sub(r"[^a-z]", "", (shop.split(" - ")[0] or "").lower())
    place = (place or "").split(" · ")[-1].strip()      # 商店行的地点是「Stanton · MicroTech · New Babbage」，只要最后一段（2026-10-28 反馈：点了说没这个地点）
    site = re.sub(r"[^a-z0-9]", "", place.lower())
    hit = None
    if site:
        pts = [q for q in n.city_places() if re.sub(r"[^a-z0-9]", "", (q.get("site_en") or "").lower()) == site]
        if brand:
            hit = next((q for q in pts if re.sub(r"[^a-z]", "", q["n"].lower()).startswith(brand)), None)
        if hit is None and pts:                            # 店的点没解出来：去这个地方的取船终端（下了船就在旁边）
            hit = next((q for q in pts if "取船" in (q.get("kinds") or ())), None)
        if hit is None:
            hit = next((q for q in data["pois"] if re.sub(r"[^a-z0-9]", "", q["n"].lower()) == site), None)
        if hit is None:                                    # 派罗的站星图地点表里没有（死局空间站在 PYR2 L4 上）：按设施表找
            for k in n.NEAR_KINDS:
                hit = next((q for q in n.amenity_targets(k, data)
                            if re.sub(r"[^a-z0-9]", "", q["n"].lower()) in (site, re.sub(r"station$", "", site))), None)
                if hit:
                    break
        for q in ([place, re.sub(r"\s+Station$", "", place, flags=re.I)] if hit is None else []):   # 星图里叫 Checkmate，不带 Station
            hits, _ = n.search(q, data, limit=1)
            if hits:
                hit = hits[0]
                break
    if hit is None:
        return {"error": "导航数据里没有这个地点"}
    row = _place_row(hit)
    _nav.start(_places[row["key"]])
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


@api
def market_lookup(q=""):
    t = trade()
    items, err = t.lookup(q)
    return {"err": err or "", "items": [{"id": i.id, "label": t.label(i.id),
                                         "src": i.id.split(":")[0].upper() if ":" in i.id else "UEX"} for i in items[:15]]}


@api
def market_prices(id="", quality="q0", op="sell"):
    out, results = _market_rows(id, quality, op)
    if results is not None:
        from ..trade.console import hud_market
        market = hud_market(results)
        if _last_hover.get("id") == id:                   # F8 认出的物品：接在买点/兑换/制造后面
            _item_hud("\n".join(_last_hover["lines"] + ([market] if market else [])))
        elif market:                                      # 窗口里查的价
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
            rows.append({"src": src, "state": STATE_ZH.get(r.state, r.state) or "暂无报价"})
            continue
        for s in r.stats:
            rows.append({"src": src, "quality": s.key.quality_group.upper(), "unit": s.key.unit,
                         "currency": s.key.currency, "mean": _money(s.mean), "min": _money(s.minimum),
                         "count": s.count, "week": _money(s.week_mean) if s.week_mean is not None else "",
                         "state": STATE_ZH.get(r.state, "")})
    return {"label": t.label(id), "rows": rows}, results


# ================================================================ 库存仓储与台账
# 已解耦迁移至 sc_mining.tasks.stock
from ..tasks.stock import (
    MODE_ZH,
    LEDGER_TYPES,
    scu_amount,
    _qlabel,
    _amount_text,
    _stock_kind,
    _place_of,
    _all_batches,
    _history_view,
    _bins,
    _price_index,
    _row_value,
    stock,
    _place_for,
    _raw_amount,
    stock_add,
    craft_slots_for,
    stock_add_named,
    stock_suggest,
    stock_set_quality,
    stock_undo,
    _row_key,
    stock_out,
    stock_set_qty,
    stock_move,
    stock_relocate,
    stock_keep_custom,
    stock_places,
    stock_place_add,
    stock_bin_save,
    stock_bin_delete,
    stock_reserve,
    stock_ledger,
    stock_prices,
)


# ================================================================ 制造目标规划
# 已解耦迁移至 sc_mining.tasks.goals
from ..tasks.goals import (
    _gkey,
    goal_short,
    _goal_for,
    _goal_text,
    _mark_goal_lines,
    crafting_zh,
    _goals_view,
    goals,
    goal_add,
    goal_update,
    goal_stock_add,
    goal_finish_preview,
    goal_finish,
    wikelo_search,
    wikelo_detail,
    craft_effect,
    goal_prices,
)


# ================================================================ 找矿点 / 制造

@api
def mineral_search(q=""):
    from ..data import SIGNATURES
    from ..gems import GEMS
    from ..i18n import mineral_zh
    from ..locations import _match_zh
    names = list(SIGNATURES) + list(GEMS)              # 地面小矿（车矿、手采）也能搜
    en_names = {k.lower(): k for k in names}
    out = []
    for token in re.split(r"[\s,，、]+", q.strip()):
        if not token:
            continue
        m = (en_names.get(token.lower()) or next((k for k in names if mineral_zh(k) == token), None)   # 中文名一字不差的先认（「杰金」不要模糊成「愈金」）
             or _match_zh(token))
        if not m:
            m = next((k for k in names if token.lower() in k.lower() or token in mineral_zh(k)), None)
        if m and m not in [x["en"] for x in out]:
            out.append({"en": m, "zh": mineral_zh(m)})
    return out


def _mine_nav(loc, mineral):
    """矿点 → 怎么导航过去：Aaron Halo 用小行星带导航（挑这种矿最多的带）；别的星球、卫星、小行星带去导航页搜它"""
    from ..halo import BANDS
    if loc["kind"] in ("Cave", "Interior"):          # 校准站矿洞、Breaker 站内部：没有能量子跳的点
        return {"kind": "none", "hint": "不能直接导航"}
    if loc["name"] == "Aaron Halo":
        bands = sorted((r for r in BANDS if mineral in r[5]), key=lambda r: -r[4])
        return {"kind": "halo", "band": bands[0][0] if bands else 5,
                "hint": f"第{bands[0][0]}带最多" if bands else "此矿物不是任何一条带的主要矿物，选择密度最高的第5带"}
    from ..locations import zh_name
    if re.fullmatch(r"(ARC|CRU|HUR|MIC)-L\d", loc["name"]):
        return {"kind": "hint", "hint": f"在星图中选择 {loc['name']} 量子跳跃，矿物位于该处小行星中"}
    m = re.search(r"\(([^)]+)\)", loc["name"])
    q = m.group(1) if m else loc["name"]
    if loc["kind"] in ("Moon", "Planet") and nav_search(q=q).get("total"):
        return {"kind": "search", "q": q, "hint": "量子跳跃到此星球或卫星，低空飞行扫描；导航页列出其上的地点"}
    return {"kind": "hint", "hint": f"在星图中量子跳跃到 {zh_name(loc)}"}


@api
def mineral_info(name=""):
    from ..data import best_price, REFINERIES, RARITY
    from ..i18n import mineral_zh, station_zh
    from ..locations import where, zh_name, _SYS_ZH, _TYPE_ZH
    rows = []
    for pct, loc in where(name)[:30]:
        others = sorted(((best_price(m)[0], m) for m in loc["minerals"] if m != name), reverse=True)[:3]
        rows.append({"pct": pct, "place": zh_name(loc), "system": _SYS_ZH[loc["system"]], "kind": _TYPE_ZH[loc["kind"]],
                     "also": [mineral_zh(m) for p, m in others if p], "name": loc["name"], "type": loc["kind"],
                     "nav": _mine_nav(loc, name)})
    price, city = best_price(name)
    bonus = sorted(((b.get(name, 0), st) for st, (sys_, b) in REFINERIES.items()), reverse=True)
    uses = ""
    try:
        from ..crafting import uses_report
        uses = uses_report(name)
    except Exception:
        pass
    try:
        from ..crafting import mat_summary
        craft_count = mat_summary(name)["count"]
    except Exception:
        craft_count = 0
    from ..gems import GEMS
    gem = GEMS.get(name)
    if gem:                                   # 地面小矿：不精炼，卖原矿；写类型、信号、终端价、不稳定性、抗性
        gem = {"kind": gem["kind"], "rs": gem["rs"], "price": gem["price"], "inst": gem["inst"], "res": gem["res"]}
    return {"en": name, "zh": mineral_zh(name), "rarity": RARITY.get(name, ""), "price": price, "city": city or "", "gem": gem,
            "craft_count": craft_count, "goal": (lambda g: _goal_text(g) if g else "")(_goal_for(name, mineral_zh(name))),
            "rows": rows, "total": len(where(name)),
            "refine": [{"station": station_zh(st), "bonus": b} for b, st in bonus[:3] if b > 0], "uses": uses}


# ================================================================ 蓝图制造查询与混料
# 已解耦迁移至 sc_mining.tasks.goals
from ..tasks.goals import (
    craft_search,
    craft_browse,
    craft_detail,
    _craft_struct,
    craft_stats,
    craft_mix,
)


# ================================================================ 导航、光环与路标
# 已解耦迁移至 sc_mining.tasks.navigation
from ..tasks.navigation import (
    _places,
    POS_FRESH,
    _WHERE,
    _AREA,
    AREA_MAX_AGE,
    HERE_WAIT,
    _HERE,
    _HALO,
    QT_SPEED,
    LIVE_STALE,
    DI_HELP,
    _place_row,
    nav_search,
    nav_near,
    nav_site,
    nav_plan,
    nav_start,
    nav_mode,
    sig_name,
    sig_names,
    nav_stop,
    nav_refresh,
    waypoints,
    waypoint_add,
    waypoint_preview,
    waypoint_from_text,
    _where_now,
    _area_now,
    fix_key_hint,
    settings_key,
    _wp_log,
    _save_here,
    _take_here_name,
    _saved,
    _start_here_watch,
    mark_here,
    _coord_desc,
    ore_record,
    ore_list,
    ore_delete,
    ore_restore,
    ore_go,
    halo_options,
    halo_routes,
    halo_pin,
    halo_unpin,
    _halo_watch,
    halo_check,
    fix_here,
    _surface_limit,
    waypoint_delete,
)


# ---- 引擎类 2026-10-28 剪到 engines/（逻辑没改）；实例仍在下面创建，测试里 S._live / S._Steady 照旧
from .engines.nav import _Steady, _CamFilter, _Nav, _GameEvents
from .engines.live import _Live
from .engines.hover import _Hover
from .engines.count import _Count
from .engines.pos import _Pos, _LogWatch


def _mark_hud(data):
    try:
        _hud().marker(data)
    except Exception:            # 测试里的假悬浮窗没有这个接口
        pass


_MK_CFG = {"on": True, "at": 0.0}


def _marker_on():
    """设置里的 nav_marker（两秒读一次，导航每 0.1 秒问一次）"""
    if time.time() - _MK_CFG["at"] > 2:
        _MK_CFG["at"] = time.time()
        try:
            from .. import settings
            _MK_CFG["on"] = settings.load().get("nav_marker", True) is not False
        except Exception:
            _MK_CFG["on"] = True
    return _MK_CFG["on"]


MARKER_STALE = 4.0         # 右上角多少秒没读到就收起导航记号（城里偶尔几次读不到，1.5 秒就收会一直闪，2026-10-27 实测）


def _marker_tick(target, data, state, shown, ref=None):
    """导航记号（2026-10-27）：每圈先判断该不该显示（还没算出位置、到了、跨星系、1.5 秒没读到、切出游戏、玩家关了、
    采矿助手开着——记号窗口读屏时会被涂黑，会挡住扫描面板和雷达信号），不该显示就收起；
    该显示且右上角有新截图（停着只转镜头也算）就按镜头朝向和视角重算位置。返回这次画的截图时间，收起了返回 None"""
    from .. import navigate as n
    from ..showloc import game_foreground
    t, g, info = _pos.current
    h = state.get("here")
    cam = (info or {}).get("camdir")
    try:
        fg = game_foreground()
    except Exception:
        fg = True
    show = (h is not None and g and cam and time.time() - t < MARKER_STALE and not h.get("arrived") and not h.get("far")
            and fg and not _live.running() and _marker_on() and not _off("nav_marker"))
    if not show:
        if shown is not None:
            _mark_hud(None)
        return None
    if t == shown:
        return shown
    try:
        from ..displayinfo import last_fov
        from ..perf import game_area
        a = game_area()
        fov = info.get("fov") or last_fov() or 70.0
        tg = n.target_global(target, data, info.get("t"), ref)
        pr = n.project(g, cam, fov, tg, a["width"], a["height"], vertical=settings_key("fov_axis", "v") != "h")
        _mark_hud({"area": (a["left"], a["top"], a["width"], a["height"]), "proj": pr, "label": n.dist_text(pr["dist"])})
        return t
    except Exception:
        _mark_hud(None)
        return None


_game_events = _GameEvents()


def _nav_log(here, info, view):
    """导航时每次算出新位置记一行（logs/nav_log.txt），方向不对时用来查是哪一步的问题"""
    try:
        from .. import paths
        p = paths.log("nav_log.txt")
        if p.exists() and p.stat().st_size > 300_000:
            p.write_text("\n".join(p.read_text(encoding="utf-8").splitlines()[-1000:]) + "\n", encoding="utf-8")
        loc = info.get("local")
        line = (f"{time.strftime('%H:%M:%S')} 来源={here.get('src', '?')} 核对={info.get('local_ok')} "
                f"游戏局部={tuple(round(v, 4) for v in loc) if loc else None} "
                f"用的=({here['x']:.4f}, {here['y']:.4f}, {here['z']:.4f}) "
                f"方位={view.get('raw_bearing', 0):.1f}° 显示={view.get('bearing', 0):.0f}° 距离={view.get('surface', 0):.2f}km")
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


_cam_filter = _CamFilter()


def _space_view(g, target, data):
    """导航去太空路标：没有南北，给直线距离、先量子跳到哪、对准哪个标记偏几度"""
    from .. import navigate as n
    s = n.space_guide(g, target, data)
    out = {"space": True, "same_body": False, "inside": False, "text": n.space_text(g, target, data)}
    if not s["same_system"]:
        out["far"] = f"目标位于 {n.SYS_ZH.get(s['target_system'], s['target_system'])}星系，需先跃迁到该星系"
        return out
    out.update(direct=s["direct"], arrived=s["arrived"], aim=s.get("aim"), qt=s.get("qt"))
    return out


def _station_view(g, target, data, when=None, prev=None, info=None):
    """拉格朗日点 / 跳跃点空间站里走路：距离按米、按站自己的朝向分上下；转向靠机头那一行和屏幕记号"""
    from .. import navigate as n
    out = {"space": True, "city": True, "station": True, "inside": True, "same_body": True}
    try:                                                   # 先核对星系：别的星系同一个坐标也可能有东西（二审 2026-10-27）
        system, sure = n.system_info(g, data, **{k: (info or {}).get(k) or "" for k in ("zone", "location", "solar_id")})
    except Exception:
        system, sure = "", False
    if target.get("sys") and system and system != target["sys"]:   # 猜出来的星系不一样也不算到（复审 2026-10-27）
        out["far"] = f"目标位于 {n.SYS_ZH.get(target['sys'], target['sys'])}星系，需先跃迁到该星系"
        return out
    tg = n.target_global(target, data, when)
    d = math.dist(g, tg)
    out.update(direct=d / 1000, direct_m=d)
    if d > 50_000:
        out["far"] = f"先前往{target.get('city_zh') or target.get('site_en') or '空间站'}，到站后按步行指引前往"
        return out
    up = sum((t - a) * u for t, a, u in zip(tg, g, target.get("up") or (0, 0, 0)))
    arrived = n.city_arrived(d, bool(prev and prev.get("station") and prev.get("arrived")))
    out.update(arrived=arrived, close=not arrived and d < n.CITY_NEAR_M, updown=up,
               text=n.station_text(g, target, data, when, arrived))
    return out


def _nav_view(here, target, data, steady=None, prev=None):
    from .. import navigate as n
    out = {"text": n.here_text(here, data), "inside": here["inside"], "body": n.body_label(here["body"]),
           "same_body": here["inside"] and here["body"] == target["b"]}
    if not out["same_body"]:
        out["far"] = (f"先前往{target.get('city_zh') or n.body_label(target['b'])}，到达城市后按步行指引前往" if n.is_city(target)
                      else f"先量子跳跃到 {n.body_label(target['b'])}，再按推荐路线前往")
        return out
    a, t = n.pos(here), n.pos(target)
    out["raw_bearing"] = n.bearing(a, t)
    out["bearing"] = steady(out["raw_bearing"]) if steady else out["raw_bearing"]
    out["compass"] = n.compass(out["bearing"])
    out["surface"] = n.surface_km(a, t, here["radius_km"])
    out["direct"] = n.direct_km(a, t)
    out["height"] = here["height_m"]
    out["target_height"] = n.latlon(t)[2] * 1000 - here["radius_km"] * 1000
    out["lat"], out["lon"] = here["lat"], here["lon"]
    out["arrived"] = out["surface"] < 1
    if n.is_city(target):                         # 城里：几米以内才算到，距离按米、加上下楼层（2026-10-27）
        d, up = n.city_metrics(here, target)
        arrived = n.city_arrived(d, bool(prev and prev.get("city") and prev.get("arrived")))
        out.update(city=True, arrived=arrived, close=not arrived and d < n.CITY_NEAR_M, direct_m=d, updown=up, near=None,
                   station=bool(target.get("up")))      # 绕星球轨道的空间站：不给南北方位
        return out
    near = n.nearby(here, data)
    out["near"] = {"name": n.label(near[1]), "km": near[0]} if near else None
    best = n.approaches(target, data, top=1)
    if best and best[0][1] < out["surface"] * 0.5 and out["surface"] > 30:
        d3q, dsq, brgq, q = best[0]
        out["hint"] = f"距离过远：先量子跳跃到 {n.label(q)}（距目标 {dsq:,.1f} km），再朝 {n.deg_text(brgq)}° 飞行"
    return out


_nav = _Nav()


# ================================================================ 实时读屏

def _game_front():
    """游戏窗口在不在最前面：True / False；判断不了（不是 Windows、读不到前台窗口）返回 None——照常识别"""
    from .. import showloc
    return showloc.game_front()


def scu_text(v):
    """精炼后的量：1 SCU 以上写 SCU，不到 1 SCU 写 uSCU（1 SCU = 1,000,000 uSCU）；两种都给"""
    if v >= 1:
        return f"{v:,.2f} SCU（{v * 1e6:,.0f} uSCU）"
    return f"{v * 1e6:,.0f} uSCU（{v:.3f} SCU）"


def _station_bonus(station, minerals):
    """精炼站对这块石头里的矿的加成：只有一种值钱的矿写「+3%」，几种不一样就写「铁 +3%、金 -2%」，都是 0 返回空"""
    from ..data import REFINERIES, best_price
    from ..i18n import mineral_zh
    bonus = REFINERIES.get(station, ("", {}))[1]
    worth = sorted(minerals, key=lambda m: -(minerals[m] * (best_price(m)[0] or 0)))
    worth = [m for m in worth if (best_price(m)[0] or 0) > 0] or worth
    vals = {m: bonus.get(m, 0) for m in worth}
    if not any(vals.values()):
        return ""
    if len(set(vals.values())) == 1:
        return f"{next(iter(vals.values())):+d}%"
    return "、".join(f"{mineral_zh(m)} {v:+d}%" for m, v in vals.items() if v)


def _lots(scan, plan=None):
    """成分表（1.6.42）：石头里的每一份（矿 × 品质、惰性物质）一行。同一种矿有几种品质时标「高品质 / 低品质」；
    品质写上这种矿的第几档（quality.py，4.8 起每种矿只有 7 档）。plan = (精炼方式, 站点)：按它算这一份精炼后多少。
    精炼保留品质、不同品质精炼完还是分开的两份（expcarry、scopique、The Impound），所以按份算"""
    from collections import defaultdict
    from ..i18n import mineral_zh
    from ..quality import tier_of
    from ..refinery import refined_scu, INERT
    total = scan.total_scu
    groups = defaultdict(list)
    for i, (n, p, q) in enumerate(scan.composition):
        if n and n != INERT:
            groups[n].append(i)
    rank = {}
    for n, idx in groups.items():
        qs = [scan.composition[i][2] for i in idx]
        if len(idx) < 2 or None in qs or len(set(qs)) < 2:
            continue
        order = sorted(idx, key=lambda i: scan.composition[i][2])
        for k, i in enumerate(order):
            rank[i] = "低品质" if k == 0 else "高品质" if k == len(order) - 1 else "中等品质"
    rows = []
    for i, (n, p, q) in enumerate(scan.composition):
        inert = n == INERT
        scu = total * p / 100 if total else None
        row = {"en": n or "", "zh": "惰性物质" if inert else (mineral_zh(n) if n else "?"), "pct": p,
               "scu": round(scu, 4) if scu is not None else None, "q": None if inert else q, "tier": "",
               "rank": rank.get(i, ""), "inert": inert, "refined": None, "refined_text": ""}
        t = tier_of(n, q) if (n and not inert and q is not None) else None
        if t:
            row["tier"] = "完美" if t[0] == "完美" else f"{t[0]} 档" + ("（最低）" if t[1] == 1 else "（最高）" if t[1] == t[2] else "")
        if inert:
            row["refined_text"] = "无精炼产出，仅占用矿袋"
        elif plan and scu is not None and n:
            v = refined_scu({n: scu}, plan[1], plan[0]).get(n, 0.0)
            row["refined"] = round(v, 6)
            row["refined_text"] = scu_text(v)
        rows.append(row)
    return rows


def _lots_hud(lots):
    """悬浮窗一行：「惰性 31%｜钨 662 那份 3.07 SCU」（同一种矿有高低两种品质时写高品质那份）；没什么可说返回空"""
    parts = []
    inert = sum(r["pct"] for r in lots if r["inert"])
    if inert >= 0.5:
        parts.append(f"惰性 {inert:.0f}%")
    for r in lots:
        if r["rank"] == "高品质":
            low = [x["q"] for x in lots if x["en"] == r["en"] and x["rank"] == "低品质"]
            parts.append(f"{r['zh']} 品质 {r['q']}：{r['scu']:.2f} SCU" if r["scu"] is not None
                         else f"{r['zh']} 品质 {r['q']}/{low[0] if low else '?'}")
    return "｜".join(parts)


def scan_view(scan, bag, cut=False):
    """一块石头的读屏结果（窗口用）。cut=True：面板被屏幕右边挡住，品质和总 SCU 读不到，只有破碎方案和成分占比"""
    from ..i18n import mineral_zh, method_zh, station_zh
    from ..laser import recommend
    from ..data import best_price, GADGETS
    from ..refinery import refined_plan
    rock = mineral_zh(scan.main_mineral) if scan.main_mineral else "?"
    out = {"rock": rock, "mass": scan.mass, "resistance": scan.resistance, "instability": scan.instability,
           "difficulty": scan.difficulty or "", "minerals": [], "refine": [], "sell": [], "craft": [], "craft_mats": [], "goal": [], "plans": [],
           "total_scu": scan.total_scu, "lots": [], "lots_plan": "", "cut": bool(cut), "note": "",
           "at": time.strftime("%H:%M:%S")}
    hud = [f"{rock}｜{scan.mass:,.0f} kg｜抗性 {scan.resistance:g}%｜不稳定 {scan.instability:g}"]
    # 1.6.64：悬浮窗按层次排（审查意见）：矿名 → 关键读数 → 怎么碎 → 收益 → 次要详情；文字版 hud 还给窗口右侧用
    # 1.6.65 照用户给的样图：矿名、三格读数、矿物组成（每种矿下面列各品质、占整石）、开采建议、精炼产量和净值、次要
    rich = {"title": rock, "stats": [["质量", f"{scan.mass:,.0f}", "kg"], ["抗性", f"{scan.resistance:g}", "%"],
                                     ["不稳定性", f"{scan.instability:g}", ""]], "comp": [], "advice": None, "gain": [], "minor": [], "foot": ""}
    if cut:
        out["note"] = ("扫描面板右侧被屏幕边缘遮挡，无法识别品质和总 SCU：仅计算破碎方案和成分占比。"
                       "在游戏设置中调大「FOV视野」使面板完整显示后，可计算精炼收益和价格。")
        hud.append("面板被遮挡：仅计算破碎方案")
        rich["minor"].append("面板被遮挡：仅计算破碎方案")
    minerals = {k: v for k, v in scan.minerals_scu().items() if k not in ("Inert Materials", "?")}
    out["minerals"] = [{"name": mineral_zh(k), "en": k, "scu": v} for k, v in minerals.items()]
    first = None
    if minerals:
        for i, (method, station, value, rscu, fee, hours) in enumerate(refined_plan(minerals)):
            bonus = _station_bonus(station, minerals)
            from ..refinery import refined_scu
            per = refined_scu(minerals, station, method)
            out["refine"].append({"method": method_zh(method), "station": station_zh(station), "value": value,
                                  "scu": rscu, "fee": fee, "hours": hours, "bonus": bonus, "amount": scu_text(rscu),
                                  "yield": [{"zh": mineral_zh(k), "amount": scu_text(v)} for k, v in per.items() if v > 0]})
            if i == 0:
                first = (method, station)
                out["lots_plan"] = f"{method_zh(method)}，{station_zh(station)}"
                hud.append(f"精炼后 {scu_text(rscu)}，价值 {value:,.0f} aUEC（建议：{method_zh(method)}，{station_zh(station)}精炼"
                           + (f" {bonus}" if bonus else "") + "）")
                rich["gain"] = [["预计精炼产量", f"{rscu:,.2f}", "SCU"], ["价格", f"{value:,.0f}", "aUEC"]]
                rich["minor"].append(f"{method_zh(method)} · {station_zh(station)}" + (f" {bonus}" if bonus else ""))
                rich["foot"] = "精炼结果为估算"
        out["sell"] = [{"name": mineral_zh(k), "where": best_price(k)[1] or "无收购"} for k in minerals]
    out["lots"] = _lots(scan, first)
    if out["refine"]:          # 精炼后按品质分开写：「钨 662 有 1.50 SCU、钨 363 有 5.74 SCU」
        out["refine"][0]["lots"] = [{"zh": r["zh"], "q": r["q"], "amount": r["refined_text"]}
                                    for r in out["lots"] if not r["inert"] and r["refined"]]
    line = _lots_hud(out["lots"])
    if line:
        hud.append(line)
    groups = {}                                                # 矿物组成：同一种矿合在一起，下面列各品质（高品质那份标蓝）
    for row in out["lots"]:                                    # 占比照游戏里的两位小数写
        key = "惰性物质" if row["inert"] else row["zh"]
        g = groups.setdefault(key, {"name": key, "inert": row["inert"], "pct_n": 0.0, "subs": []})
        g["pct_n"] += row["pct"] or 0
        if not row["inert"]:                                  # 品质没认出来写「未知」，单独一份，不混进别的品质
            g["subs"].append({"q": "未知" if row["q"] is None else str(row["q"]), "pct": f"{row['pct'] or 0:.2f}%",
                              "hi": row["rank"] == "高品质", "n": row["pct"] or 0})
    for g in groups.values():
        g["subs"].sort(key=lambda x: -int(x["q"]) if x["q"].isdigit() else 1)
        g["pct"] = f"{g.pop('pct_n'):.2f}%"                  # 1.6.70（用户）：游戏里读到多少写多少，不四舍五入
        for x in g["subs"]:
            x.pop("n", None)
    rich["comp"] = sorted(groups.values(), key=lambda g: (g["inert"], -float(g["pct"][:-1] or 0)))
    if minerals:
        try:
            from ..crafting import quality_hints
            out["craft"] = list(quality_hints(scan.composition))
            from ..crafting import mat_summary
            best = {}
            for nm, pct, qq in scan.composition:
                if nm and nm not in ("Inert Materials", "?"):
                    best[nm] = max(best.get(nm) or 0, qq or 0) if qq is not None else best.get(nm)
            out["craft_mats"] = [{"en": nm, "zh": mineral_zh(nm), "q": qq, **mat_summary(nm, qq)}
                                 for nm, qq in best.items() if mat_summary(nm)["count"]]
            for nm, qq in best.items():                       # 目标还缺这种矿：窗口和悬浮窗都标出来（有品质门槛的按每一份判断）
                g = _goal_for(nm, mineral_zh(nm))
                if g:
                    lots = [r for r in out["lots"] if r["en"] == nm]
                    ok = any((r["q"] or 0) >= g["minq"] for r in lots) if g["minq"] > 1 else True
                    out["goal"].append({"en": nm, "zh": g["zh"] or mineral_zh(nm), "short": g["short"], "unit": g["unit"],
                                        "minq": g["minq"], "q": qq, "ok": ok, "goals": g["goals"], "text": _goal_text(g, qq, lots)})
            hud += [x["text"] for x in out["goal"][:2]]
            rich["minor"] += [x["text"] for x in out["goal"][:2]]
        except Exception:
            pass
    plans = recommend(scan.mass, scan.resistance, scan.instability)
    for p in plans:
        out["plans"].append({"heads": p.names, "short": p.short(), "summary": p.summary(),
                             "ratio": p.ratio, "breakable": p.breakable, "comfortable": p.comfortable,
                             "throttle": p.throttle if p.breakable else None})
    if plans:
        hud.insert(1, plans[0].short())
        p0 = plans[0]
        from ..laser import gadget_label
        heads = p0.names + (f" + {gadget_label(p0.gadget)}" if p0.gadget else "")
        rich["advice"] = {"heads": heads, "power": f"建议功率 {p0.throttle * 100:.0f}%" if p0.breakable else "满功率也无法破碎"}
    contents, used, cap = bag
    out["bag"] = None
    out["bag_text"] = ""
    if used is not None:
        out["bag"] = {"used": used, "cap": cap, "items": [{"name": mineral_zh(k), "scu": v} for k, v in contents.items()]}
        out["bag_text"] = f"{used:g}/{cap:g} SCU\n" + "，".join(f"{mineral_zh(k)} {v:g}" for k, v in contents.items())
    out["hud"] = "\n".join(hud)
    out["hud_rich"] = rich
    return out


_live = _Live()


@api
def live_start():
    from .. import settings
    _live.start()
    settings.update(live_on=True)          # 记住：重启、升级后自动接着扫
    return {"running": True}


@api
def live_stop():
    from .. import settings
    _live.stop()
    settings.update(live_on=False)
    return {"running": False}


MOD_GROUPS = (("rieger", "提高功率"), ("vaux", "提高提取功率"), ("focus", "扩大绿区"), ("xtr", "扩大绿区"),
              ("torrent", "加快充能"), ("deluge", "降低抗性"), ("overrun", "降低抗性"), ("fltr", "过滤惰性物质"))
STAT_ZH = {"power": "功率", "extract": "提取功率", "res": "抗性", "instab": "不稳定性", "window": "绿区", "rate": "充能",
           "filter": "过滤"}


def _gear_summary(key, lo):
    """一条船当前配置的汇总：同时操作的矿头总功率、满功率能破多重（抗性 30%；使用萨比尔 Sabir 时）。
    和破碎方案同一套公式（laser.evaluate）：在 crew 个矿头的组合里取最强的"""
    from itertools import combinations
    from ..laser import HeadSetup, evaluate, active_model, gadget_label
    craft = lo.get("craft") or [None] * len(lo["heads"])
    setups = [HeadSetup(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])]
    model, k = active_model()
    n = max(1, min(lo.get("crew") or 1, len(setups)))
    combos = list(combinations(setups, n))
    best = lambda g: max(evaluate(list(c), g, 1.0, 30, 0, k=k, model=model).max_mass for c in combos)
    return {"crew": n, "power": round(max(sum(h.max_power() for h in c) for c in combos)),
            "mass": round(best(None), -1), "mass_gadget": round(best("sabir"), -1), "gadget": gadget_label("sabir")}


def _gear(ship=None):
    """配置区要的东西：几条船、每条船现在的配置（每个矿头加上模组后的读数、汇总）、能选的矿头和模组。
    名字一律「中文 English」（2026-10-26 用户定：霍夫斯泰德 Hofstede-S2）"""
    from ..data import SHIPS, HEADS, MODULES, DEFAULT_LOADOUTS, AUTHOR_MOLE
    from ..laser import ship_loadout, current_ship, clean_loadout, HeadSetup, _mult
    from ..i18n import gear_label

    def fmt(d, keys):
        return "，".join(f"{STAT_ZH[k]} {d[k]:+g}%" for k in keys if d.get(k))

    from ..laser import craft_slots, craft_mult
    from ..quality import tiers

    def power(k, craft):
        """矿头自己的激光功率（不算模组）：商店买的 → 自造的"""
        m = craft_mult(k, craft)
        return {"base": HEADS[k]["pmax"], "now": round(HEADS[k]["pmax"] * m), "pct": round((m - 1) * 100, 1), "craft": bool(craft)}

    def card(k, mods, craft):
        """一个矿头装上模组（和自造）后的读数：功率 W，其余是相对没有修正时的变化 %"""
        h = HeadSetup(k, mods, craft)
        pct = lambda m: round((m - 1) * 100)
        return {"power": round(h.max_power()), "base": HEADS[k]["pmax"],
                "stats": {"power": pct(h.max_power() / HEADS[k]["pmax"]),
                          "res": pct(_mult(HEADS[k]["res"], *h.res_mods())), "instab": pct(h.instab_mult()),
                          "window": pct(h.window_mult()), "rate": pct(h.rate_mult())}}

    ships = []
    for key, spec in SHIPS.items():
        _, lo = ship_loadout(key)
        craft = lo.get("craft") or [None] * len(lo["heads"])
        presets = [{"key": "factory", "name": "出厂配置"}]
        if key == "mole":
            presets.append({"key": "author", "name": "作者推荐（2 人）", "loadout": clean_loadout(key, AUTHOR_MOLE)})
        ships.append({"key": key, "name": spec["name"], "size": spec["size"], "heads": spec["heads"],
                      "crew_max": spec["crew_max"], "fixed": spec.get("fixed"), "loadout": lo,
                      "power": [power(k, craft[i]) for i, (k, _) in enumerate(lo["heads"])],
                      "cards": [card(k, mods, craft[i]) for i, (k, mods) in enumerate(lo["heads"])],
                      "summary": _gear_summary(key, lo), "presets": presets,
                      "is_default": lo == clean_loadout(key, DEFAULT_LOADOUTS[key])})
    heads = [{"key": k, "name": gear_label(h["name"]), "en": h["name"], "size": h["size"], "slots": h["slots"], "ship": h.get("ship"),
              "pmax": h["pmax"], "desc": f"最大功率 {h['pmax']:,.0f} W｜" + (fmt(h, ("res", "instab", "window", "rate")) or "无修正"),
              # 自造时影响激光功率的材料槽，和这种材料的品质档位（选档或者直接填数字）
              "craft": [{"slot": s["slot"], "slot_zh": s["slot_zh"], "mat_zh": s["mat_zh"], "segs": [list(x[:4]) for x in s["segs"]],
                         "tiers": [["商店标准", 500]] + [[n, q] for n, q in tiers(s["mat"])]} for s in craft_slots(k)]}
             for k, h in HEADS.items()]
    mods = [{"key": k, "name": gear_label(m["name"]), "en": m["name"], "desc": fmt(m, ("power", "extract", "res", "instab", "window", "rate", "filter")),
             "group": next((g for p, g in MOD_GROUPS if k.startswith(p)), "其他")}
            for k, m in MODULES.items()]
    from ..laser import chosen_ship
    return {"ship": current_ship(), "chosen": chosen_ship() is not None, "ships": ships, "heads": heads, "modules": mods,
            "groups": list(dict.fromkeys(g for _, g in MOD_GROUPS))}


@api
def mining_gear():
    return _gear()


@api
def set_mining_gear(ship="mole", loadout=None, reset=False):
    """选船 / 保存这条船的配置（reset=True 恢复出厂配置）"""
    from .. import settings
    from ..data import SHIPS
    from ..laser import clean_loadout
    if ship not in SHIPS:
        raise ValueError("未找到此飞船")
    saved = dict(settings.load().get("mining_loadouts") or {})
    if reset:
        saved.pop(ship, None)
    elif loadout is not None:
        saved[ship] = clean_loadout(ship, loadout)
    settings.update(mining_ship=ship, mining_loadouts=saved)
    _live.gear_rev += 1                     # 正在显示的石头按新配置重算（采矿助手最多 5 秒后重新发布）
    return _gear()


@api
def manual_scan(mass=0, resistance=0, instability=0):
    """手动输入扫描数据：只算破碎方案"""
    from ..laser import recommend
    plans = recommend(float(mass), float(resistance), float(instability))
    return [{"heads": p.names, "short": p.short(), "summary": p.summary(),
             "ratio": p.ratio, "breakable": p.breakable, "comfortable": p.comfortable,
             "throttle": p.throttle if p.breakable else None} for p in plans]


# ================================================================ 游戏里 F8：认出鼠标下的物品
# 业务逻辑已解耦迁移至 sc_mining.tasks.hover（借鉴 MAA Task 架构）
from ..tasks.hover import (
    HOVER_REGION,
    _read_tooltip,
    tooltip_quality,
    _AMOUNT,
    tooltip_row,
    parse_qlabel,
    parse_count,
    cell_labels,
    _is_mineral,
    qty_text,
    hover_once,
    _tier,
    _hover_more,
    _hover_lines,
    _short_buy,
    _last_hover,
)

_hover = _Hover()


# ================================================================ 盘点（F6，2026-10-25 用户要求）
# 开着时鼠标停在游戏库存的格子上、说明框一出来就自动记一格（同一格不重复记）；悬浮窗显示本轮小计。
# 再按 F6，或 60 秒没认到物品，自动结束：和账上对一遍，窗口里确认后才改账（游戏里同一种东西常分好几格，按格加总）


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


_count = _Count()


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
    _SHORT["t"] = 0.0

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


_pos = _Pos()



def start_background():
    """窗口打开时：F8 热键监听、盯游戏日志里的位置、导航时读右上角（第一次打开要先确认免费声明）"""
    from .. import settings
    if not settings.load().get("agreed"):
        return
    _hover.start()
    _pos.start()
    _logwatch.start()
    _game_events.start()
    if not _online.get("loop"):                 # 同意免责声明后也会调一次：只开一个
        _online["loop"] = True
        threading.Thread(target=_online_loop, daemon=True, name="update").start()
        from .. import itemsearch
        itemsearch.warm_up()                     # 搜索索引后台先建好（2026-10-26 优化：第一次搜索从 1–3 秒变 0）
    if not _online.get("fb_retry"):              # 上次没发成的问题反馈：后台补发
        _online["fb_retry"] = True
        from .. import feedback_up
        threading.Thread(target=lambda: feedback_up.retry_pending(_fb_dir()), daemon=True, name="feedback-retry").start()
    if settings.load().get("live_on"):          # 上次关天枢（或重启、升级）时原矿扫描开着：接着扫
        _live.start()
    try:
        from ..perfmon import monitor            # 每分钟记一行资源占用（logs/perf_log.txt）
        monitor.start()
    except Exception:
        pass


@api
def runtime_capture_now():
    """手动立即截取一帧画面，更新实时监控"""
    from ..core.perf import grab_screen
    img = grab_screen()
    bus.update_preview(img, source="manual", force=True)
    bus.runtime_log("手动截取屏幕画面", tag="SCREEN", level="INFO")
    _, meta = bus.get_preview_bytes(full=False)
    return meta


@api
def runtime_clear_logs():
    """清空前端实时运行日志"""
    bus.clear_runtime_logs()
    return {"ok": True}


@api
def hover_trigger():
    """手动触发一次 F8 物品悬停识别"""
    return bus.run_task("hover", hover_once, title="F8物品识别")


# ================================================================ 统一注册 tasks 层的 Web API
from ..tasks import system as _t_system, stock as _t_stock, goals as _t_goals, navigation as _t_nav, hover as _t_hover

for _mod in (_t_system, _t_stock, _t_goals, _t_nav, _t_hover):
    if hasattr(_mod, "API"):
        API.update(_mod.API)
    if hasattr(_mod, "API_FUNCTIONS"):
        for _fn in _mod.API_FUNCTIONS:
            api(_fn)
