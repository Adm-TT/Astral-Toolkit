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


# ================================================================ 基础 HUD 与按键状态（2026-10-30 阶段 0 搬到 hud_state.py，这里保留原名）
from .hud_state import (  # noqa: E402,F401
    _hud, _off, _note_hud, _cursor, _key_down, item_key_pressed, _item_hud,
    ITEM_HUD_SECONDS, ITEM_AWAY_PX, ITEM_AWAY_AFTER, _ITEM_MODE, _ITEM_SEQ, _OFF_TOLD,
)


# ================================================================ 后台引擎实例（Engines）
# 2026-10-30 阶段 0：实例由 engines/manager.py 的 EngineManager 建，这里保留原名
from .engines.nav import _Steady, _CamFilter, _Nav, _GameEvents  # noqa: E402,F401
from .engines.live import _Live  # noqa: E402,F401
from .engines.hover import _Hover  # noqa: E402,F401
from .engines.count import _Count  # noqa: E402,F401
from .engines.pos import _Pos, _LogWatch  # noqa: E402,F401
from .engines.manager import EngineManager  # noqa: E402

_M = EngineManager.get_instance()
_game_events = _M.game_events
_nav = _M.nav
_live = _M.live
_pos = _M.pos
_count = _M.count
_hover = _M.hover
_cam_filter = _M.cam_filter
_steady = _M.steady
_logwatch = _M.logwatch


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


# ================================================================ 运行时后台服务与诊断
def start_background():
    """打开天枢主窗口时启动后台服务：热键监听、定时查更新、搜索索引预热、未发送反馈补发、原矿扫描续跑
    （2026-10-30 阶段 0：内容搬到 EngineManager.start_all）"""
    _M.start_all()


# 2026-10-30 阶段 4：搬到 app/api/system.py，这里保留原名
from .api.system import runtime_capture_now, runtime_clear_logs  # noqa: E402,F401


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
