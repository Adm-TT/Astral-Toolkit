"""重构阶段 3（2026-10-30）：采矿、F8 识别、F6 盘点的接口走自己的 Controller，tasks 不再反向引用 services"""

from pathlib import Path

MINING_STATIC = (
    "scan_view",
    "mining_gear",
    "manual_scan",
)
MINING_BOUND = (
    "live_start",
    "live_stop",
    "set_mining_gear",
    "set_mining_gadgets",
)
MINING = MINING_STATIC + MINING_BOUND
VISION_STATIC = ("count_toggle", "count_state", "count_apply", "count_cancel")
VISION_BOUND = ("hover_trigger",)
VISION = VISION_STATIC + VISION_BOUND


def test_mining_vision_controller_routes():
    from astral_toolkit.app.api import router
    from astral_toolkit.app.api import mining, vision

    router.reset()
    r = router.routes()
    for name in MINING_STATIC:
        assert r[name].__module__ == "astral_toolkit.app.api.mining", name
        assert r[name] is mining.ROUTES[name]
    mining_bound = mining.bound(object())
    for name in MINING_BOUND:
        assert mining_bound[name].__module__ == "astral_toolkit.app.api.mining", name
    for name in VISION_STATIC:
        assert r[name].__module__ == "astral_toolkit.app.api.vision", name
        assert r[name] is vision.ROUTES[name]
    vision_bound = vision.bound(object())
    for name in VISION_BOUND:
        assert vision_bound[name].__module__ == "astral_toolkit.app.api.vision", name
    assert set(mining.ROUTES) == set(MINING_STATIC)  # 一个不多一个不少
    assert set(mining_bound) == set(MINING_BOUND)
    assert not set(mining.ROUTES) & set(mining_bound)
    assert set(mining.ROUTES) | set(mining_bound) == set(MINING)
    assert set(vision.ROUTES) == set(VISION_STATIC)
    assert set(vision_bound) == set(VISION_BOUND)
    assert not set(vision.ROUTES) & set(vision_bound)
    assert set(vision.ROUTES) | set(vision_bound) == set(VISION)


def test_mining_vision_tasks_no_services():
    root = Path(__file__).resolve().parent.parent / "astral_toolkit" / "tasks"
    for f in ("mining.py", "hover.py", "count.py"):
        text = (root / f).read_text(encoding="utf-8")
        for bad in ("app import services", "_services()", "@api"):
            assert bad not in text, f"{f} 里还有 {bad}"


def test_mining_vision_router_roundtrip():
    import json
    from astral_toolkit.app.api import router
    from astral_toolkit.tasks import mining as M

    b = router.call("mining_gear")
    direct = json.loads(json.dumps(M.mining_gear(), ensure_ascii=False, default=str))
    assert b["ok"] is True and b["data"] == direct
