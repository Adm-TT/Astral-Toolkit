"""新界面的页面能力表和运行状态信号灯（2026-11-19）"""

import ast
from pathlib import Path

from astral_toolkit.tasks.system import ui_manifest as M

API = Path(__file__).resolve().parent.parent / "astral_toolkit" / "app" / "api"


def _registered():
    """接口层登记的全部接口名：各文件 ROUTES 的键，加上 bound() 返回的那张表的键（要后台对象的接口）"""
    names = set()
    for f in API.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        names.add(k.value)
    return names


def test_ready_blocks_only_name_registered_routes():
    have = _registered()
    assert {"nav_search", "status", "ui_health", "ui_capabilities"} <= have
    for page, blocks in M.PAGES.items():
        for name, (state, routes) in blocks.items():
            assert state in (M.READY, M.SOON), (page, name)
            if state == M.READY:
                assert routes, (page, name)  # 说有就得说清用哪些接口
                assert set(routes) <= have, (page, name, set(routes) - have)
            else:
                assert routes == (), (page, name)  # 还没有的不许挂接口名


def test_blocks_do_not_name_routes_that_are_not_page_apis():
    """接口表里有、但不是给页面取数用的两个：trade 返回内部对象，scan_view 要传扫描对象（R354 核对 2026-11-23）"""
    used = {
        r
        for blocks in M.PAGES.values()
        for _s, routes in blocks.values()
        for r in routes
    }
    assert not used & {"trade", "scan_view"}


def test_capabilities_shape_and_page_states():
    out = M.capabilities()
    assert out["version"] == M.VERSION
    pages = out["pages"]
    assert set(pages) == set(M.PAGES)
    assert pages["query"]["state"] == "ready"  # 全有
    assert pages["atlas"]["state"] == "soon"  # 全没有
    assert pages["collect"]["state"] == "partial"  # 有的有、有的没有
    assert pages["collect"]["blocks"]["live_assist"] == {"state": "ready"}
    assert pages["collect"]["blocks"]["refine"] == {"state": "soon", "text": "即将上线"}
    # 老大 11-19 定的几处位置
    assert pages["action"]["blocks"]["mining_gear"]["state"] == "ready"
    assert pages["panel"]["blocks"]["goals"]["state"] == "ready"
    assert "goals" not in pages  # 目标清单不单独成页


_GOOD = {
    "data": {"pack": "2026.11.13", "loc": "v1"},
    "ocr_error": "",
    "ocr_mode": "cpu",
    "gpu_available": False,
    "hotkey_warn": [],
    "game_size": (2560, 1440),
    "admin": False,
    "game_elevated": False,
}


def _levels(st):
    out = M.health(st)
    return out["level"], {i["key"]: i["level"] for i in out["items"]}


def test_health_green_when_everything_is_fine():
    level, items = _levels(_GOOD)
    assert level == "ok"
    assert set(items.values()) == {"ok"}
    assert _levels({**_GOOD, "game_size": None})[0] == "ok"  # 游戏没开：不算毛病


def test_health_yellow_and_red():
    assert _levels({**_GOOD, "data": {"pack": "", "loc": "v1"}}) == (
        "error",
        {"data_pack": "error", "loc": "ok", "ocr": "ok", "hotkeys": "ok"},
    )
    level, items = _levels({**_GOOD, "data": {"pack": "p", "loc": ""}})
    assert (level, items["loc"]) == ("warn", "warn")
    level, items = _levels({**_GOOD, "ocr_error": "boom"})
    assert (level, items["ocr"]) == ("error", "error")
    level, items = _levels({**_GOOD, "ocr_mode": "gpu"})  # 选了显卡但用不了
    assert (level, items["ocr"]) == ("warn", "warn")
    assert _levels({**_GOOD, "ocr_mode": "gpu", "gpu_available": True})[0] == "ok"
    level, items = _levels({**_GOOD, "hotkey_warn": ["F8"]})
    assert (level, items["hotkeys"]) == ("warn", "warn")
    level, items = _levels({**_GOOD, "game_size": (1600, 900)})
    assert (level, items["game_size"]) == ("warn", "warn")
    level, items = _levels({**_GOOD, "game_elevated": True})
    assert (level, items["admin"]) == ("warn", "warn")
    assert _levels({**_GOOD, "game_elevated": True, "admin": True})[0] == "ok"
    # 红比黄重
    assert _levels({**_GOOD, "ocr_error": "x", "hotkey_warn": ["F8"]})[0] == "error"


def test_health_texts_follow_the_wording_rules():
    bad = {
        "data": {},
        "ocr_mode": "gpu",
        "hotkey_warn": ["F8"],
        "game_size": (1280, 720),
        "game_elevated": True,
    }
    for it in M.health(bad)["items"] + M.health(_GOOD)["items"]:
        assert it["text"]
        assert not any(w in it["text"] for w in "你我他您请"), it


def test_api_exposes_both(monkeypatch):
    from astral_toolkit.app.api import router, system

    assert router.routes()["ui_capabilities"]() == M.capabilities()
    monkeypatch.setattr(system._t, "status", lambda sources, **kw: dict(_GOOD))
    bound = system.bound(object(), lambda: None)
    assert bound["ui_health"]()["level"] == "ok"
