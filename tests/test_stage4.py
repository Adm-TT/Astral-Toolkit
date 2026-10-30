"""2026-10-30 重构阶段 4：系统接口走自己的 Controller；services.py 删掉之后的检查也放这里"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SYSTEM_API = ["status", "upgrade_check", "upgrade_online", "upgrade_rollback", "upgrade_mark_stable",
               "legacy_scan", "legacy_import", "legacy_skip", "legacy_quit", "upgrade_apply",
               "upgrade_upload", "upgraded", "export_logs", "feedback_report", "feedback_list",
               "feedback_export", "feedback_clear", "cockpit_check", "overlay_move", "set_settings",
               "update_data", "about_info", "open_source_site", "third_party_licenses", "open_referral",
               "agree", "show", "quit", "runtime_capture_now", "runtime_clear_logs"]


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


def test_system_bridge_roundtrip():
    """只读接口 about_info：走 BackendBridge 和直接调 tasks 结果一样"""
    from sc_mining.app.api.bridge import BackendBridge
    from sc_mining.app.api import router
    from sc_mining.tasks import system as TY
    router.reset()
    got = BackendBridge().call("about_info", {})
    assert got["ok"], got
    assert got["data"] == json.loads(json.dumps(TY.about_info(), ensure_ascii=False, default=str))


def test_system_start_background_uses_engine_manager(monkeypatch):
    """tasks.system.start_background 交给 EngineManager.start_all（以前经 services 转一道）"""
    from sc_mining.app.engines.manager import EngineManager
    from sc_mining.tasks import system as TY
    called = []
    monkeypatch.setattr(EngineManager.get_instance(), "start_all", lambda: called.append(1))
    TY.start_background()
    assert called == [1]