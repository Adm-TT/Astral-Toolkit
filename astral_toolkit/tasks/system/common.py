"""系统任务基础共享层：句柄探针"""

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

WIN = sys.platform == "win32"


@dataclass(frozen=True)
class StatusSources:
    """状态页 / 问题反馈要读的运行状态：每项都是无参函数，调用时现读（bootstrap 填）"""

    live_running: Callable[[], bool]
    live_paused: Callable[[], bool]
    nav_target_label: Callable[[], str]
    nav_space_mode: Callable[[], bool]
    pos_reader_active: Callable[[], bool]
    pos_label: Callable[[], Any]
    pos_system: Callable[[], Any]
    game_events_last: Callable[[], Any]
    results: Any


def _hud():
    try:
        from ...app.overlay import hud

        return hud()
    except Exception:
        return None


def _note_hud(section, text, secs=6):
    """悬浮窗上一条短提示，secs 秒后自己收起"""
    h = _hud()
    if h is None:
        return
    if hasattr(h, "note"):
        h.note(text, secs)
        return
    h.set(section, text)

    def gone():
        if getattr(_hud(), "sections", {}).get(section) == text:
            _hud().clear(section)

    t = threading.Timer(secs, gone)
    t.daemon = True
    t.start()
