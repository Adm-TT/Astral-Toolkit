"""astral_toolkit/tasks/system 门面模块

统一导出系统设置、运行状态、在线升级、问题反馈与关于页的业务逻辑。
"""

import sys

from .about import (
    AGREE_TEXT,
    DATA_SOURCES,
    REFERRAL_URL,
    _data_versions,
    _version,
    about_info,
    agree,
    open_referral,
    open_source_site,
    third_party_licenses,
)
from .common import WIN, StatusSources, _hud, _note_hud, bind
from .feedback import (
    _fb_dir,
    _scrub,
    feedback_clear,
    feedback_export,
    feedback_list,
    feedback_report,
)
from .settings import (
    HOTKEYS,
    _hotkey_values,
    hotkey_conflicts,
    overlay_move,
    quit,
    set_settings,
    show,
    start_background,
    update_data,
)
from .status import _desktop, _gridtext_status, _system_info, export_logs, status
from .upgrade import (
    VPK_PREV,
    _online,
    _online_info,
    _online_loop,
    _online_public,
    _online_task,
    _task_print,
    _vpk_rollback_task,
    upgrade_check,
    upgrade_online,
    upgrade_rollback,
)

__all__ = [
    "status",
    "bind",
    "StatusSources",
    "upgrade_check",
    "upgrade_online",
    "upgrade_rollback",
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
    "start_background",
    "hotkey_conflicts",
    "HOTKEYS",
    "DATA_SOURCES",
    "VPK_PREV",
]


# ---------------------------------------------------------------- 门面动态属性同步（支持测试与动态 monkeypatch）
class _SystemModule(sys.modules[__name__].__class__):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        from . import (
            about as _about,
            common as _common,
            feedback as _feedback,
            settings as _settings,
            upgrade as _upgrade,
        )

        _status_mod = sys.modules.get("astral_toolkit.tasks.system.status")
        for sub in (
            _common,
            _status_mod,
            _settings,
            _upgrade,
            _feedback,
            _about,
        ):
            if sub and hasattr(sub, name):
                setattr(sub, name, value)


sys.modules[__name__].__class__ = _SystemModule
