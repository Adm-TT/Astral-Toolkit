"""新界面要的两样（2026-11-19，方案 docs/superpowers/specs/2026-11-19-newui-backend-align.md）

1. 页面能力表 capabilities()：新界面的每一页、每一块，后端现在有（ready），还是先占位（soon，页面上写「即将上线」）。
   老大 11-19 定：套新壳子、不加新功能；没有的照样显示、放占位。页面照这张表显示，不自己写死。
   以后做完一块，把这里那一行从 SOON 改成 READY、填上它用的接口名。
2. 运行状态信号灯 health(status)：把运行状态接口（status）里的几项汇总成一盏灯——绿 ok、黄 warn、红 error，
   点开能看到每一项。只读 status 已经有的东西，不另做检查。

页名、块名是后端先起的，新界面接进来时和页面那边对一遍。
"""

from typing import Any

READY, PARTIAL, SOON = "ready", "partial", "soon"
SOON_TEXT = "即将上线"
VERSION = 1

# 页 → 块 → (状态, 这一块用到的接口名)。READY 的块必须列接口名，而且都得真的注册了（tests/test_ui_manifest.py 看着）
PAGES: dict[str, dict[str, tuple[str, tuple[str, ...]]]] = {
    "query": {  # 查询
        "items": (READY, ("search", "item_search", "item_info", "item_loot")),
        "add_goal": (READY, ("goal_add",)),
    },
    "craft": {  # 制造
        "blueprints": (
            READY,
            (
                "craft_search",
                "craft_browse",
                "craft_detail",
                "craft_stats",
                "craft_effect",
                "craft_mix",
            ),
        ),
        "wikelo": (READY, ("wikelo_search", "wikelo_detail")),
    },
    "nav": {  # 导航
        "route": (
            READY,
            (
                "nav_search",
                "nav_plan",
                "nav_start",
                "nav_stop",
                "nav_refresh",
                "nav_mode",
            ),
        ),
        "multi_stop": (SOON, ()),  # 多个途经点
        "places": (READY, ("nav_search", "nav_site")),
        "waypoints": (
            READY,
            (
                "waypoints",
                "waypoint_add",
                "waypoint_preview",
                "waypoint_from_text",
                "waypoint_delete",
            ),
        ),
        "waypoint_notes": (SOON, ()),  # 路标备注
        # 地点补丁：自己的路标导出成文件、装别人给的补丁（2026-11-19）
        "patches": (
            READY,
            (
                "patch_export",
                "patch_import",
                "patch_list",
                "patch_toggle",
                "patch_delete",
            ),
        ),
        "belt": (READY, ("halo_options", "halo_routes", "halo_pin", "halo_unpin")),
    },
    "collect": {  # 收集
        "scan_mining": (
            READY,
            ("mineral_search", "mineral_info", "sig_name", "sig_names"),
        ),
        "scan_gather": (SOON, ()),  # 采集
        "scan_salvage": (SOON, ()),  # 打捞
        # 实时采矿助手：开关在「信号扫描」磁贴和这一页的扫描工具里，两处是同一个（老大 11-19）。
        # 读屏出来的结果走实时事件，不是接口；scan_view 要传扫描对象，不是「取最近一次扫描」，所以不列（R354 核对指出）
        "live_assist": (READY, ("live_start", "live_stop", "manual_scan")),
        "refine": (SOON, ()),  # 精炼订单
        "records": (
            READY,
            ("ore_record", "ore_list", "ore_delete", "ore_restore", "ore_go"),
        ),
    },
    "stock": {  # 仓库：库存归另一条线，这里只登记现在有的接口
        "inventory": (
            READY,
            (
                "stock",
                "stock_add",
                "stock_add_named",
                "stock_suggest",
                "stock_set_qty",
                "stock_set_quality",
                "stock_out",
                "stock_undo",
                "stock_ledger",
                "stock_prices",
            ),
        ),
        "places": (
            READY,
            (
                "stock_places",
                "stock_place_add",
                "stock_bin_save",
                "stock_bin_delete",
                "stock_move",
                "stock_relocate",
            ),
        ),
        "count": (
            READY,
            ("count_toggle", "count_state", "count_apply", "count_cancel"),
        ),
        "categories": (SOON, ()),  # 九类页签、颜色分档、待核
        "favorites": (SOON, ()),
        "sort": (SOON, ()),
        "equip": (SOON, ()),
        "sell": (SOON, ()),
    },
    "action": {  # 行动 /「本次搭配」面板
        "loadout_personal": (SOON, ()),
        "loadout_ship": (SOON, ()),
        # 采矿船这类资源收集船的配置在「飞船」页签里（老大 11-19）：矿头、模组、小工具、人数、关注的矿现在就有
        "mining_gear": (
            READY,
            (
                "mining_gear",
                "set_mining_gear",
                "set_mining_gadgets",
                "set_mining_focus",
            ),
        ),
        "multitool": (SOON, ()),  # 「多功能」那块里牵引模块等，后端还没有
        "activity": (SOON, ()),
        "carry_list": (SOON, ()),
    },
    "trade": {  # 交易行
        # 商店价在物品详情里（item_info 的 buy / sell）；market_* 是玩家行情汇总，不是商店报价。
        # trade 这个接口返回的是内部对象、不是给页面用的数据，不列（R354 核对指出）
        "shop_prices": (
            READY,
            ("item_info", "market_lookup", "market_prices", "nav_shop"),
        ),
        "player_listings": (SOON, ()),
        "sell": (SOON, ()),
    },
    "atlas": {"all": (SOON, ())},  # 图鉴
    "settings": {  # 设置
        "general": (READY, ("status", "set_settings")),
        "start_page": (SOON, ()),
        "sort": (SOON, ()),
        "data_update": (READY, ("update_data",)),
        "data_export": (SOON, ()),
        "diagnostics": (
            READY,
            (
                "export_logs",
                "feedback_report",
                "feedback_list",
                "feedback_export",
                "feedback_clear",
                "runtime_capture_now",
                "runtime_clear_logs",
            ),
        ),
        "upgrade": (READY, ("upgrade_check", "upgrade_online", "upgrade_rollback")),
        "about": (READY, ("about_info", "third_party_licenses")),
    },
    "panel": {  # 控制面板
        "activity": (READY, ("status",)),
        # 目标清单不单独成页，只在控制面板和要用到它的页面里显示（老大 11-19）
        "goals": (
            READY,
            (
                "goals",
                "goal_add",
                "goal_update",
                "goal_finish",
                "goal_finish_preview",
                "goal_stock_add",
                "goal_prices",
            ),
        ),
        "signal_scan": (READY, ("live_start", "live_stop")),
        "health": (READY, ("ui_health",)),
    },
}


def _page_state(blocks: dict[str, tuple[str, tuple[str, ...]]]) -> str:
    states = {s for s, _ in blocks.values()}
    if states == {READY}:
        return READY
    if states == {SOON}:
        return SOON
    return PARTIAL


def capabilities() -> dict[str, Any]:
    """页面能力表 → {"version", "pages": {页: {"state", "blocks": {块: {"state"[, "text"]}}}}}"""
    pages: dict[str, Any] = {}
    for page, blocks in PAGES.items():
        out: dict[str, Any] = {}
        for name, (state, _routes) in blocks.items():
            out[name] = (
                {"state": state, "text": SOON_TEXT}
                if state == SOON
                else {"state": state}
            )
        pages[page] = {"state": _page_state(blocks), "blocks": out}
    return {"version": VERSION, "pages": pages}


OK, WARN, ERROR = "ok", "warn", "error"
_RANK = {OK: 0, WARN: 1, ERROR: 2}
MIN_GAME_HEIGHT = 1080  # 游戏画面比这矮，认字会不准


def health(status: dict[str, Any]) -> dict[str, Any]:
    """运行状态（tasks.system.status 的返回）→ {"level", "items": [{"key", "level", "text"}]}。
    红：有功能用不了；黄：能用，但有事要处理；绿：都正常。level 取各项里最重的"""
    items: list[dict[str, str]] = []

    def add(key: str, level: str, text: str) -> None:
        items.append({"key": key, "level": level, "text": text})

    data = status.get("data") or {}
    if data.get("pack"):
        add("data_pack", OK, "数据包已就绪")
    else:
        add("data_pack", ERROR, "数据包还没下载：在设置里更新数据")
    if data.get("loc"):
        add("loc", OK, "汉化包已就绪")
    else:
        add(
            "loc",
            WARN,
            "汉化包还没下载，物品和地点的中文名可能对不上：在设置里更新数据",
        )

    if status.get("ocr_error"):
        add("ocr", ERROR, f"文字识别出错：{status['ocr_error']}")
    elif status.get("ocr_mode") == "gpu" and not status.get("gpu_available"):
        add("ocr", WARN, "显卡识别用不了，已改用处理器")
    else:
        add("ocr", OK, "文字识别正常")

    if status.get("hotkey_warn"):
        add("hotkeys", WARN, "有热键撞了，排在后面的那个不生效：在设置里改")
    else:
        add("hotkeys", OK, "热键正常")

    size = status.get("game_size")
    if size and size[1] < MIN_GAME_HEIGHT:
        add(
            "game_size",
            WARN,
            f"游戏画面高 {size[1]}，低于 {MIN_GAME_HEIGHT} 时识别会不准",
        )

    if status.get("game_elevated") and not status.get("admin"):
        add("admin", WARN, "游戏是用管理员身份开的，AT 不是：热键可能没反应")

    level = max((i["level"] for i in items), key=_RANK.__getitem__)
    return {"level": level, "items": items}
