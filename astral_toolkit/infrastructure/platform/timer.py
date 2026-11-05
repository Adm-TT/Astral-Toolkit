"""Windows 等待精度（NV-B5 导航帧数）。

系统默认约 15.6 毫秒一跳：Event.wait(0.008)、Tk 的 after(8) 实际要等 16 毫秒左右，导航帧数 20 以上读不满、画不满。
读得快时临时调成 1 毫秒，用完调回。Windows 10 2004 起只影响调了它的进程，不是改系统设置。"""

import sys
import threading

_LOCK = threading.Lock()
_ON = {"on": False}


def _winmm():
    import ctypes

    return ctypes.WinDLL("winmm")


def fine(on):
    """on=True：等待精度调成 1 毫秒；False：调回。同一状态重复调不叠加；不是 Windows 什么都不做；调不了就算了"""
    on = bool(on)
    if sys.platform != "win32":
        return
    with _LOCK:
        if on == _ON["on"]:
            return
        try:
            winmm = _winmm()
            (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
        except Exception:
            return
        _ON["on"] = on
