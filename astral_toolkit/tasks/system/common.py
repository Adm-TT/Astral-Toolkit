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


_status: StatusSources | None = None
_start: Callable[[], bool] | None = None
_UNBOUND = "tasks.system 未绑定：先调用 bind(sources, start_background)"


def bind(
    sources: StatusSources,
    start_background: Callable[[], bool],
    *,
    replace: bool = False,
) -> None:
    """组装处调用一次；两个参数一起绑，没绑之前 status / feedback / 设置页启动都不工作"""
    global _status, _start
    if (_status is not None or _start is not None) and not replace:
        raise RuntimeError(
            "tasks.system 已绑定：生产只绑一次；测试用 replace=True 并在用完后恢复"
        )
    _status, _start = sources, start_background


def _need_status() -> StatusSources:
    sources = _status
    if sources is None:
        raise RuntimeError(_UNBOUND)
    return sources


def _need_start() -> Callable[[], bool]:
    start = _start
    if start is None:
        raise RuntimeError(_UNBOUND)
    return start


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
