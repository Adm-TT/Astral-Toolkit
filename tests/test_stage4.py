"""2026-10-30 重构阶段 4：系统接口走自己的 Controller；services.py 删掉之后的检查也放这里"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SYSTEM_API = [
    "status",
    "upgrade_check",
    "upgrade_online",
    "upgrade_rollback",
    "upgrade_mark_stable",
    "legacy_scan",
    "legacy_import",
    "legacy_skip",
    "legacy_quit",
    "upgrade_apply",
    "upgrade_upload",
    "upgraded",
    "export_logs",
    "feedback_report",
    "feedback_list",
    "feedback_export",
    "feedback_clear",
    "overlay_move",
    "set_settings",
    "update_data",
    "about_info",
    "open_source_site",
    "third_party_licenses",
    "open_referral",
    "agree",
    "show",
    "quit",
    "runtime_capture_now",
    "runtime_clear_logs",
]


def test_system_controller_routes():
    """系统的每个接口名都由 app/api/system.py 接，名单和 Controller 的 ROUTES 一个不多一个不少"""
    from sc_mining.app.api import router, system as CY

    router.reset()
    r = router.routes()
    for name in _SYSTEM_API:
        assert r[name].__module__ == "sc_mining.app.api.system", name
    assert sorted(CY.ROUTES) == sorted(_SYSTEM_API)


def test_system_tasks_no_services():
    """tasks/system.py 不再反过来引用 app.services"""
    text = (ROOT / "sc_mining" / "tasks" / "system.py").read_text(encoding="utf-8")
    for bad in ("app import services", "_services()", "@api"):
        assert bad not in text, bad


def test_system_router_roundtrip():
    """只读接口 about_info：走 router 和直接调 tasks 结果一样"""
    from sc_mining.app.api import router
    from sc_mining.tasks import system as TY

    router.reset()
    got = router.call("about_info", {})
    assert got["ok"], got
    assert got["data"] == json.loads(
        json.dumps(TY.about_info(), ensure_ascii=False, default=str)
    )


def test_system_start_background_uses_engine_manager(monkeypatch):
    """tasks.system.start_background 交给 EngineManager.start_all（以前经 services 转一道）"""
    from sc_mining.app.engines.manager import EngineManager
    from sc_mining.tasks import system as TY

    called = []
    monkeypatch.setattr(
        EngineManager.get_instance(), "start_all", lambda: called.append(1)
    )
    TY.start_background()
    assert called == [1]


# ---------------------------------------------------------------- 阶段 4 第二段：services.py 删掉之后
# 删之前 services._API_NAMES 的名单（109 个，2026-10-30 从 services.py 抄下来），每个都要有 Controller 接
_OLD_API_NAMES = [
    "about_info",
    "agree",
    "count_apply",
    "count_cancel",
    "count_state",
    "count_toggle",
    "craft_browse",
    "craft_detail",
    "craft_effect",
    "craft_mix",
    "craft_search",
    "craft_slots_for",
    "craft_stats",
    "export_logs",
    "feedback_clear",
    "feedback_export",
    "feedback_list",
    "feedback_report",
    "goal_add",
    "goal_finish",
    "goal_finish_preview",
    "goal_prices",
    "goal_stock_add",
    "goal_update",
    "goals",
    "halo_options",
    "halo_pin",
    "halo_routes",
    "halo_unpin",
    "hover_trigger",
    "item_info",
    "item_loot",
    "item_search",
    "legacy_import",
    "legacy_quit",
    "legacy_scan",
    "legacy_skip",
    "live_start",
    "live_stop",
    "manual_scan",
    "market_lookup",
    "market_prices",
    "mineral_info",
    "mineral_search",
    "mining_gear",
    "nav_mode",
    "nav_near",
    "nav_plan",
    "nav_refresh",
    "nav_search",
    "nav_shop",
    "nav_site",
    "nav_start",
    "nav_stop",
    "open_referral",
    "open_source_site",
    "ore_delete",
    "ore_go",
    "ore_list",
    "ore_record",
    "ore_restore",
    "overlay_move",
    "quit",
    "runtime_capture_now",
    "runtime_clear_logs",
    "scan_view",
    "search",
    "set_mining_gear",
    "set_settings",
    "show",
    "sig_name",
    "sig_names",
    "status",
    "stock",
    "stock_add",
    "stock_add_named",
    "stock_bin_delete",
    "stock_bin_save",
    "stock_keep_custom",
    "stock_ledger",
    "stock_move",
    "stock_out",
    "stock_place_add",
    "stock_places",
    "stock_prices",
    "stock_relocate",
    "stock_reserve",
    "stock_set_qty",
    "stock_set_quality",
    "stock_suggest",
    "stock_undo",
    "third_party_licenses",
    "trade",
    "update_data",
    "upgrade_apply",
    "upgrade_check",
    "upgrade_mark_stable",
    "upgrade_online",
    "upgrade_rollback",
    "upgrade_upload",
    "upgraded",
    "waypoint_add",
    "waypoint_delete",
    "waypoint_from_text",
    "waypoint_preview",
    "waypoints",
    "wikelo_detail",
    "wikelo_search",
]


def test_all_api_names_routed():
    """原来 services 能调的接口，现在 router 里都有（每个都由 app/api/ 下某个 Controller 接）"""
    from sc_mining.app.api import router

    router.reset()
    r = router.routes()
    assert (
        len(_OLD_API_NAMES) == len(set(_OLD_API_NAMES)) == 108
    )  # 109 个减去 cockpit_check（自动跑删了，控制台第 5 批）
    missing = [n for n in _OLD_API_NAMES if n not in r]
    assert not missing, missing
    for n in _OLD_API_NAMES:
        assert r[n].__module__.startswith("sc_mining.app.api."), (n, r[n].__module__)


def test_no_services_module():
    """services.py 删了：import 不到；sc_mining/ 下没有代码再引用它"""
    import importlib
    import sys

    sys.modules.pop("sc_mining.app.services", None)
    try:
        importlib.import_module("sc_mining.app.services")
    except ImportError:
        pass
    else:
        raise AssertionError("sc_mining.app.services 还能 import")
    bad = []
    for f in sorted((ROOT / "sc_mining").rglob("*.py")):
        text = f.read_text(encoding="utf-8")
        for s in ("app import services", "app.services"):
            if s in text:
                bad.append((str(f.relative_to(ROOT)), s))
    assert not bad, bad


def test_feedback_scrub_personal_info(monkeypatch, tmp_path):
    """反馈包里的日志、情况.json：AT / 数据 / userdata 文件夹换成占位符，别的 C:\\Users\\<名字> 也抹掉，网址里的口令换掉
    （S5 审查 2026-10-31：日志尾巴原样进反馈包、默认自动上传，会带出 Windows 用户名）"""
    from sc_mining.core import paths
    from sc_mining.tasks import system as t_sys

    root = tmp_path / "AT"
    monkeypatch.setattr(paths, "ROOT", root)
    monkeypatch.setattr(paths, "USER", root / "userdata")
    monkeypatch.setattr(paths, "DATA", root / "data")
    import json

    s = t_sys._scrub(
        f"→ {root / 'data' / 'uex.json'}\n读不到 {root / 'userdata' / 'x.json'}\n"
        "C:\\Users\\Some Body\\AppData\\Local\\Temp\\tmpab12\\a.zip\n"
        + json.dumps({"p": "C:\\Users\\bob\\x", "q": str(root / "data")})
        + "\n"
        "http://127.0.0.1:5000/#t=AbCdEf123456789_-xyz  /api/events?token=ZZZZZZZZZZ12"
    )
    assert str(tmp_path) not in s and json.dumps(str(tmp_path))[1:-1] not in s
    assert "Some Body" not in s and "bob" not in s
    assert "AbCdEf123456789" not in s and "ZZZZZZZZZZ12" not in s
    assert (
        "<DATA>" in s
        and "<USERDATA>" in s
        and "<token>" in s
        and "质量" in t_sys._scrub("质量 123")
    )
    assert "5f20" not in t_sys._scrub(
        json.dumps({"p": "C:\\Users\\张三\\x"})
    )  # 中文用户名被 json 转义成 \uXXXX
