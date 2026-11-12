"""测试 tasks/system 模块化解耦与门面动态代理兼容性"""

import sys

from astral_toolkit.tasks import system as t_sys
from astral_toolkit.tasks.system import (
    about as m_about,
    common as m_common,
    feedback as m_feedback,
    settings as m_settings,
    upgrade as m_upgrade,
)


def test_submodules_exist():
    """所有新抽离的子模块均能直接导入，且门面函数导出正常"""
    assert m_common.WIN is not None
    assert hasattr(m_about, "about_info")
    assert hasattr(m_settings, "set_settings")
    assert hasattr(m_upgrade, "upgrade_check")
    assert hasattr(m_feedback, "feedback_report")

    # status 模块与门面 status 函数兼容性验证
    status_mod = sys.modules.get("astral_toolkit.tasks.system.status")
    assert status_mod is not None
    assert hasattr(status_mod, "status")
    assert callable(t_sys.status)


def test_facade_all_exports():
    """门面 __all__ 中声明的所有公有符号在门面上均存在且可调用/访问"""
    for name in t_sys.__all__:
        assert hasattr(t_sys, name), f"门面缺失公有符号: {name}"


def test_dynamic_setattr_sync_to_submodules():
    """通过门面 monkeypatch 属性时，自动同态同步到对应子模块"""
    # 1. 测试同步到 upgrade._online
    old_online = m_upgrade._online
    try:
        dummy_online = {"info": "mock_test_version"}
        t_sys._online = dummy_online
        assert m_upgrade._online is dummy_online
    finally:
        t_sys._online = old_online

    # 2. 测试同步到 feedback._scrub
    old_scrub = m_feedback._scrub
    try:

        def dummy_scrub(text):
            return "SCRUBBED"

        t_sys._scrub = dummy_scrub
        assert m_feedback._scrub("hello") == "SCRUBBED"
    finally:
        t_sys._scrub = old_scrub

    # 3. 测试同步到 status._gridtext_status
    status_mod = sys.modules.get("astral_toolkit.tasks.system.status")
    old_gt = status_mod._gridtext_status
    try:

        def dummy_gt():
            return {"mock": True}

        t_sys._gridtext_status = dummy_gt
        assert status_mod._gridtext_status() == {"mock": True}
    finally:
        status_mod._gridtext_status = old_gt


def test_hotkey_conflicts_and_about():
    """门面接口调用正常返回"""
    conflicts = t_sys.hotkey_conflicts({})
    assert isinstance(conflicts, list)

    info = t_sys.about_info()
    assert "copyright" in info
    assert "sources" in info


def test_status_reuses_log_position_and_preserves_probe_contract(monkeypatch):
    """状态快照同一轮只读一次游戏日志（以前地点那段还会再读一遍）；status 自己读一次设置、查一次游戏是不是管理员权限开的。
    from_log、game_size 都换成了假的，所以数不到找日志（system.gamelog.find_log）里那次读设置、game_size 那次翻窗口——
    这两样还在，是待做「status() 太重」那条没做完的那半。"""
    from types import SimpleNamespace

    from astral_toolkit.core import settings

    from astral_toolkit.infrastructure.platform import capture
    from astral_toolkit import ocr
    from astral_toolkit.navigation import position
    from astral_toolkit.crafting import stockplaces
    from astral_toolkit.system import showloc
    from astral_toolkit.tasks.system.common import StatusSources

    status_mod = sys.modules["astral_toolkit.tasks.system.status"]
    calls = {"settings": 0, "elevated": 0, "log": 0}
    cfg = {"theme": "light", "trade_capture_key": "F9"}

    def load():
        calls["settings"] += 1
        return dict(cfg)

    def elevated():
        calls["elevated"] += 1
        return True

    def from_log():
        calls["log"] += 1
        return (1000.0, "日志地点", {"sys": "Stanton", "x": 1, "y": 2, "z": 3})

    monkeypatch.setattr(settings, "load", load)
    monkeypatch.setattr(status_mod, "WIN", True)
    monkeypatch.setattr(showloc, "is_admin", lambda: False)
    monkeypatch.setattr(showloc, "game_elevated", elevated)
    monkeypatch.setattr(capture, "game_size", lambda: (1920, 1080))
    monkeypatch.setattr(position, "from_log", from_log)
    monkeypatch.setattr(stockplaces, "match", lambda *args: None)
    monkeypatch.setattr(ocr, "ocr_device", lambda: "CPU")
    monkeypatch.setattr(ocr, "gpu_available", lambda: False)
    monkeypatch.setattr(ocr, "last_ocr_error", lambda: "")
    monkeypatch.setattr(m_about, "_data_versions", lambda: {"pack": "fixture"})
    monkeypatch.setattr(status_mod, "_gridtext_status", lambda: {"ready": True})
    # position.current 和 status 共用 time 模块；固定时钟保证优先级可复现。
    monkeypatch.setattr(status_mod.time, "time", lambda: 1010.0)
    label = [1005.0, "实时地点"]
    sources = StatusSources(
        live_running=lambda: False,
        live_paused=lambda: False,
        nav_target_label=lambda: "",
        nav_space_mode=lambda: False,
        pos_reader_active=lambda: True,
        pos_label=lambda: tuple(label),
        pos_system=lambda: (1005.0, "Pyro"),
        game_events_last=lambda: {"event": (1000.0, "fixture")},
        results=SimpleNamespace(),
    )
    out = status_mod.status(sources)
    # settings 只数 status 自己读的那次（见上面）
    assert calls == {"settings": 1, "elevated": 1, "log": 1}
    assert out["settings"] == cfg
    assert out["hover_key"] == "F9"
    assert out["game_elevated"] is True and out["admin"] is False
    assert out["position"] == {
        "label": "实时地点",
        "minutes": 0,
        "sys": "Pyro",
        "live": True,
    }
    # 旧响应字段仍然保留，优化不缩减接口。
    assert out["game_size"] == (1920, 1080)
    assert out["displayinfo"] is True
    assert out["game_events"] == {"event": "fixture"}
    assert out["gridtext"] == {"ready": True}
    assert {"frozen", "vpk", "ocr_mode", "hotkey_warn", "nav_space"} <= out.keys()

    label[:] = [995.0, "过时地点"]
    out = status_mod.status(sources)
    assert calls == {"settings": 2, "elevated": 2, "log": 2}
    assert out["position"] == {
        "label": "日志地点",
        "minutes": 0,
        "sys": "Stanton",
        "live": False,
    }


def test_status_live_position_without_log(monkeypatch):
    """没有日志地点时仍可使用实时标签，且只查询一次日志。"""
    from astral_toolkit.navigation import position
    from astral_toolkit.core import settings
    from astral_toolkit import ocr
    from astral_toolkit.tasks.system.common import StatusSources

    status_mod = sys.modules["astral_toolkit.tasks.system.status"]
    reads = []
    monkeypatch.setattr(position, "from_log", lambda: reads.append(1))
    monkeypatch.setattr(settings, "load", lambda: {})
    monkeypatch.setattr(status_mod, "WIN", False)
    monkeypatch.setattr(status_mod.time, "time", lambda: 1010.0)
    monkeypatch.setattr(ocr, "ocr_device", lambda: "CPU")
    monkeypatch.setattr(ocr, "gpu_available", lambda: False)
    monkeypatch.setattr(ocr, "last_ocr_error", lambda: "")
    monkeypatch.setattr(m_about, "_data_versions", lambda: {})
    monkeypatch.setattr(status_mod, "_gridtext_status", lambda: {})
    sources = StatusSources(
        live_running=lambda: False,
        live_paused=lambda: False,
        nav_target_label=lambda: "",
        nav_space_mode=lambda: False,
        pos_reader_active=lambda: True,
        pos_label=lambda: (1005.0, "实时地点"),
        pos_system=lambda: (1005.0, "Pyro"),
        game_events_last=lambda: {},
        results=None,
    )
    out = status_mod.status(sources)
    assert len(reads) == 1
    assert out["position"] == {
        "label": "实时地点",
        "minutes": 0,
        "sys": "Pyro",
        "live": True,
    }
