"""重构阶段 3（2026-10-30）：采矿、F8 识别、F6 盘点的接口走自己的 Controller，tasks 不再反向引用 services"""
from pathlib import Path

MINING = ("scan_view", "live_start", "live_stop", "mining_gear", "set_mining_gear", "manual_scan")
VISION = ("hover_trigger", "count_toggle", "count_state", "count_apply", "count_cancel")


def test_mining_vision_controller_routes():
    from sc_mining.app.api import router
    from sc_mining.app.api import mining, vision
    router.reset()
    r = router.routes()
    for name in MINING:
        assert r[name].__module__ == "sc_mining.app.api.mining", name
        assert r[name] is mining.ROUTES[name]
    for name in VISION:
        assert r[name].__module__ == "sc_mining.app.api.vision", name
        assert r[name] is vision.ROUTES[name]
    assert set(mining.ROUTES) == set(MINING)          # 一个不多一个不少
    assert set(vision.ROUTES) == set(VISION)


def test_mining_vision_tasks_no_services():
    root = Path(__file__).resolve().parent.parent / "sc_mining" / "tasks"
    for f in ("mining.py", "hover.py", "count.py"):
        text = (root / f).read_text(encoding="utf-8")
        for bad in ("app import services", "_services()", "@api"):
            assert bad not in text, f"{f} 里还有 {bad}"


def test_mining_vision_bridge_roundtrip():
    import json
    from sc_mining.app.api.bridge import BackendBridge
    from sc_mining.tasks import mining as M
    b = BackendBridge().call("mining_gear")
    direct = json.loads(json.dumps(M.mining_gear(), ensure_ascii=False, default=str))
    assert b["ok"] is True and b["data"] == direct
