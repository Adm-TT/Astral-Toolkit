"""测试 tasks/system 模块化解耦与门面动态代理兼容性"""

import sys

from sc_mining.tasks import system as t_sys
from sc_mining.tasks.system import (
    about as m_about,
    common as m_common,
    feedback as m_feedback,
    legacy as m_legacy,
    settings as m_settings,
    upgrade as m_upgrade,
)


def test_submodules_exist():
    """所有新抽离的子模块均能直接导入，且门面函数导出正常"""
    assert m_common.WIN is not None
    assert hasattr(m_about, "about_info")
    assert hasattr(m_legacy, "legacy_scan")
    assert hasattr(m_settings, "set_settings")
    assert hasattr(m_upgrade, "upgrade_check")
    assert hasattr(m_feedback, "feedback_report")

    # status 模块与门面 status 函数兼容性验证
    status_mod = sys.modules.get("sc_mining.tasks.system.status")
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
    status_mod = sys.modules.get("sc_mining.tasks.system.status")
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
