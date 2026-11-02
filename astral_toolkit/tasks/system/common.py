"""系统任务基础共享层：句柄探针"""

import sys
import threading

WIN = sys.platform == "win32"


def _engines():
    from ...app.engines.manager import EngineManager

    return EngineManager.get_instance()


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
