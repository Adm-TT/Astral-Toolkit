"""少占电脑资源，别拖慢游戏

- AT 自己的进程（窗口和后台辅助）都降成「低于正常」优先级：游戏要用 CPU 时让着游戏
- 你按 F8 这种「等着看结果」的识别临时用正常优先级跑完（boost）；识别插队和引擎本身在 ocr/runtime.py
- 截图在 core/capture.py
"""

import contextlib
import sys
import threading


def lower_priority():
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(
            k32.GetCurrentProcess(), 0x00004000
        )  # BELOW_NORMAL_PRIORITY_CLASS
    except Exception:
        pass


_boost = {"n": 0, "lock": threading.Lock()}


@contextlib.contextmanager
def boost():
    """你在等结果的那一下（F8）：临时恢复正常优先级，跑完马上降回去。
    平时 AT 是「低于正常」优先级，游戏占满 CPU 时识别会被挤得很慢"""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    k32 = ctypes.windll.kernel32
    with _boost["lock"]:
        _boost["n"] += 1
        if _boost["n"] == 1:
            k32.SetPriorityClass(
                k32.GetCurrentProcess(), 0x00000020
            )  # NORMAL_PRIORITY_CLASS
    try:
        yield
    finally:
        with _boost["lock"]:
            _boost["n"] -= 1
            if _boost["n"] == 0:
                k32.SetPriorityClass(
                    k32.GetCurrentProcess(), 0x00004000
                )  # BELOW_NORMAL_PRIORITY_CLASS
