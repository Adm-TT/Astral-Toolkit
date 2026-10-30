"""窗口调用的功能接口与聚合网关（Gateway Facade）

本模块是前端 Web RPC 与后台任务调度层的统一门面：
1. 维护 API 路由分发字典 (API)，统一对外暴露接口；
2. 聚合管理后台守护引擎实例（_live, _nav, _pos, _hover, _count 等）；
3. 纯业务逻辑已全部分解至 sc_mining.tasks 独立任务层：
   - tasks.system: 系统信息、在线更新、日志导出、问题反馈
   - tasks.trade: 物品查询、交易市场、矿物精炼
   - tasks.stock: 仓库库存、货架库位、出入库台账
   - tasks.goals: 制造蓝图、目标规划、Wikelo 特殊兑换
   - tasks.navigation: 路标添加/预览、折跃光环航线、/showlocation
   - tasks.mining: 采矿装备、激光头加成、扫描破碎、实时 HUD
   - tasks.hover: F8 物品悬停识别、说明框解析、角标提取
   - tasks.count: F6 仓库物品盘点对账
"""
import math
from pathlib import Path
import re
import sys
import threading
import time

from . import bus

WIN = sys.platform == "win32"
API = {}


def api(fn):
    """API 路由注册装饰器（名字即为 HTTP RPC 路径 /api/<fn_name>）"""
    API[fn.__name__] = fn
    return fn


# ================================================================ 基础 HUD 与按键状态
def _hud():
    try:
        from .overlay import hud
        return hud()
    except Exception:
        return None


_ITEM_SEQ = [0]
ITEM_HUD_SECONDS = 60
_OFF_TOLD = set()


def _off(feature):
    """这个功能有没有被远程关掉（latest.json 的 disabled，update_check.disabled）"""
    try:
        from ..update import update_check
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
    """悬浮窗上一条短提示，secs 秒后自己收起"""
    h = _hud()
    if not h:
        return
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


ITEM_AWAY_PX = 160
ITEM_AWAY_AFTER = 1.5
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
    """按下物品识别键那一刻：记下鼠标位置与 Shift 状态"""
    _ITEM_MODE.update(pinned=_key_down(0x10), origin=_cursor(), shown_at=time.time())


def _item_hud(text, secs=ITEM_HUD_SECONDS):
    """悬浮窗「物品」分区：鼠标移开自动收起（按住 Ctrl 不收，Shift+F8 钉住）"""
    h = _hud()
    if not h:
        return
    _ITEM_SEQ[0] += 1
    my = _ITEM_SEQ[0]
    h.set("物品", text)
    _ITEM_MODE["shown_at"] = time.time()
    if _ITEM_MODE["pinned"]:
        return

    def watch():
        import ctypes
        try:
            h_px = ctypes.windll.user32.GetSystemMetrics(1) or 1080
        except Exception:
            h_px = 1080
        away = ITEM_AWAY_PX * max(1.0, h_px / 1080)
        end = time.time() + secs
        while _ITEM_SEQ[0] == my and time.time() < end:
            time.sleep(0.1)
            o, c = _ITEM_MODE["origin"], _cursor()
            if (o and c and time.time() - _ITEM_MODE["shown_at"] >= ITEM_AWAY_AFTER and not _key_down(0x11)
                    and math.dist(o, c) > away):
                break
            if _key_down(0x11):
                end = max(end, time.time() + 1)
        if _ITEM_SEQ[0] == my:
            h_cur = _hud()
            if h_cur:
                h_cur.clear("物品")
    threading.Thread(target=watch, daemon=True, name="item-hud").start()


# ================================================================ 后台引擎实例（Engines）
from .engines.nav import _Steady, _CamFilter, _Nav, _GameEvents
from .engines.live import _Live
from .engines.hover import _Hover
from .engines.count import _Count
from .engines.pos import _Pos, _LogWatch

_game_events = _GameEvents()
_nav = _Nav()
_live = _Live()
_pos = _Pos()
_count = _Count()
_hover = _Hover()
_cam_filter = _CamFilter()
_steady = _Steady()
_logwatch = _LogWatch()


# ================================================================ 动态挂载并 Re-export 全部 Tasks 任务层
from ..tasks import (
    system as _t_system,
    trade as _t_trade,
    stock as _t_stock,
    goals as _t_goals,
    navigation as _t_nav,
    mining as _t_mining,
    hover as _t_hover,
    count as _t_count,
)

_TASK_OWNERSHIP = [
    (_t_system, {
        "status", "_gridtext_status", "_version", "_upgrade_found", "_online_info", "_online_loop",
        "_online_public", "upgrade_check", "_online_task", "upgrade_online", "upgrade_rollback",
        "_task_print", "_vpk_rollback_task", "upgrade_mark_stable", "_upgrade_task", "_drop_upload",
        "legacy_scan", "legacy_import", "legacy_skip", "legacy_quit", "upgrade_apply",
        "upgrade_receive", "_sweep_uploads", "upgrade_upload", "upgraded", "_data_versions",
        "_desktop", "_system_info", "export_logs", "_fb_dir", "feedback_report", "feedback_list",
        "feedback_export", "feedback_clear", "cockpit_check", "overlay_move", "set_settings",
        "update_data", "about_info", "open_source_site", "third_party_licenses", "open_referral",
        "agree", "show", "quit", "HOTKEYS", "_online", "_hotkey_values", "hotkey_conflicts",
        "_FB_LAST", "_ORE_LAST"
    }),
    (_t_trade, {
        "WIKI_TYPE_ZH", "search", "item_search", "_wiki_cat", "_zh_of", "item_info",
        "item_loot", "nav_shop", "trade", "market_lookup", "market_prices", "_market_rows",
        "mineral_search", "_mine_nav", "mineral_info"
    }),
    (_t_stock, {
        "MODE_ZH", "LEDGER_TYPES", "scu_amount", "_qlabel", "_amount_text", "_stock_kind",
        "_place_of", "_place_for", "_raw_amount", "_all_batches", "_history_view", "_bins",
        "_price_index", "_row_value", "stock", "stock_add", "craft_slots_for", "stock_add_named",
        "stock_suggest", "stock_set_quality", "stock_undo", "_row_key", "stock_out",
        "stock_set_qty", "stock_move", "stock_relocate", "stock_keep_custom", "stock_places",
        "stock_place_add", "stock_bin_save", "stock_bin_delete", "stock_reserve", "stock_ledger",
        "stock_prices"
    }),
    (_t_goals, {
        "_gkey", "goal_short", "_goal_for", "_goal_text", "_mark_goal_lines", "crafting_zh",
        "_goals_view", "goals", "goal_add", "goal_update", "goal_stock_add", "craft_effect",
        "goal_prices", "craft_search", "craft_browse", "craft_detail", "_craft_struct",
        "craft_stats", "craft_mix", "goal_finish_preview", "goal_finish", "wikelo_search",
        "wikelo_detail", "_SHORT", "_wk_cache", "_bp_cache"
    }),
    (_t_nav, {
        "_places", "POS_FRESH", "_WHERE", "_AREA", "AREA_MAX_AGE", "HERE_WAIT", "_HERE",
        "_HALO", "QT_SPEED", "LIVE_STALE", "DI_HELP", "_place_row", "nav_search", "nav_near",
        "nav_site", "nav_plan", "nav_start", "nav_mode", "sig_name", "sig_names", "nav_stop",
        "nav_refresh", "waypoints", "waypoint_add", "waypoint_preview", "waypoint_from_text",
        "_where_now", "_area_now", "fix_key_hint", "settings_key", "_wp_log", "_save_here",
        "_take_here_name", "_saved", "_start_here_watch", "mark_here", "_coord_desc",
        "ore_record", "ore_list", "ore_delete", "ore_restore", "ore_go", "halo_options",
        "halo_routes", "halo_pin", "halo_unpin", "_halo_watch", "halo_check", "fix_here",
        "_surface_limit", "waypoint_delete"
    }),
    (_t_mining, {
        "_mark_hud", "_marker_on", "MARKER_STALE", "_MK_CFG", "_marker_tick", "_nav_log",
        "_space_view", "_station_view", "_nav_view", "_game_front", "scu_text",
        "_station_bonus", "_lots", "_lots_hud", "scan_view", "live_start", "live_stop",
        "_gear_summary", "_gear", "mining_gear", "set_mining_gear", "manual_scan",
        "MOD_GROUPS", "STAT_ZH"
    }),
    (_t_hover, {
        "HOVER_REGION", "HOVER_REGIONS", "get_hover_regions", "_read_tooltip", "tooltip_quality", "_AMOUNT", "tooltip_row",
        "parse_qlabel", "parse_count", "cell_labels", "_is_mineral", "qty_text",
        "hover_once", "_tier", "_hover_more", "_hover_lines", "_short_buy", "_last_hover"
    }),
    (_t_count, {
        "_read_item", "_kl", "_count_review", "count_toggle", "count_state", "count_apply",
        "count_cancel"
    }),
]

for _mod, _symbols in _TASK_OWNERSHIP:
    for _name in _symbols:
        if hasattr(_mod, _name):
            globals()[_name] = getattr(_mod, _name)


class _Facade(type(sys)):
    """给 services 设值（测试 monkeypatch、运行时改开关）同步到真正用它的任务模块，
    不然只改了这里的副本，任务模块照旧用老的（2026-10-30 合并 NGU 重构：6 个测试因此失败，
    其中反馈导出直接写到了真桌面）"""
    def __setattr__(self, name, value):
        old = self.__dict__.get(name, _MISSING)
        super().__setattr__(name, value)
        for mod, symbols in _TASK_OWNERSHIP:
            if name in symbols or (old is not _MISSING and getattr(mod, name, _MISSING) is old):
                setattr(mod, name, value)


_MISSING = object()
sys.modules[__name__].__class__ = _Facade


# ================================================================ 运行时后台服务与诊断
def start_background():
    """打开天枢主窗口时启动后台服务：热键监听、定时查更新、搜索索引预热、未发送反馈补发、原矿扫描续跑"""
    from ..core import settings
    if not settings.load().get("agreed"):
        return
    _hover.start()
    _pos.start()
    _logwatch.start()
    _game_events.start()
    _online = getattr(sys.modules[__name__], "_online", {})
    if not _online.get("loop"):
        _online["loop"] = True
        threading.Thread(target=_online_loop, daemon=True, name="update").start()
        from ..crafting import itemsearch
        itemsearch.warm_up()
    if not _online.get("fb_retry"):
        _online["fb_retry"] = True
        from ..system import feedback_up
        threading.Thread(target=lambda: feedback_up.retry_pending(_fb_dir()), daemon=True, name="feedback-retry").start()
    if settings.load().get("live_on"):
        _live.start()
    try:
        from ..core import perf
        threading.Thread(target=perf.rapidocr, daemon=True, name="ocr-warmup").start()
    except Exception:
        pass
    try:
        from ..core.perfmon import monitor
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


# ================================================================ 统一注册全量 Web API 路由表
_API_NAMES = {
    # System
    "status", "upgrade_check", "upgrade_online", "upgrade_rollback", "upgrade_mark_stable",
    "legacy_scan", "legacy_import", "legacy_skip", "legacy_quit", "upgrade_apply",
    "upgrade_upload", "upgraded", "export_logs", "feedback_report", "feedback_list",
    "feedback_export", "feedback_clear", "cockpit_check", "overlay_move", "set_settings",
    "update_data", "about_info", "open_source_site", "third_party_licenses", "open_referral",
    "agree", "show", "quit",
    # Trade
    "search", "item_search", "item_info", "item_loot", "nav_shop", "trade", "market_lookup",
    "market_prices", "mineral_search", "mineral_info",
    # Stock
    "stock", "stock_add", "craft_slots_for", "stock_add_named", "stock_suggest",
    "stock_set_quality", "stock_undo", "stock_out", "stock_set_qty", "stock_move",
    "stock_relocate", "stock_keep_custom", "stock_places", "stock_place_add",
    "stock_bin_save", "stock_bin_delete", "stock_reserve", "stock_ledger", "stock_prices",
    # Goals
    "goal_finish_preview", "goal_finish", "wikelo_search", "wikelo_detail", "goals",
    "goal_add", "goal_update", "goal_stock_add", "craft_effect", "goal_prices",
    "craft_search", "craft_browse", "craft_detail", "craft_stats", "craft_mix",
    # Navigation
    "nav_search", "nav_near", "nav_site", "nav_plan", "nav_start", "nav_mode",
    "sig_name", "sig_names", "nav_stop", "nav_refresh", "waypoints", "waypoint_add",
    "waypoint_preview", "waypoint_from_text", "waypoint_delete", "ore_record",
    "ore_list", "ore_delete", "ore_restore", "ore_go", "halo_options", "halo_routes",
    "halo_pin", "halo_unpin",
    # Mining
    "scan_view", "live_start", "live_stop", "mining_gear", "set_mining_gear", "manual_scan",
    # Hover
    "hover_trigger",
    # Count
    "count_toggle", "count_state", "count_apply", "count_cancel",
    # Runtime
    "runtime_capture_now", "runtime_clear_logs",
}

for _name in _API_NAMES:
    _fn = globals().get(_name)
    if _fn and callable(_fn):
        API[_name] = _fn
