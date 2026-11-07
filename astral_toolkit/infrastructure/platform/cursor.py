"""光标位置的平台读数（目录迁移 R5，从 app/engines/count 拆出来）：盘点线程隔 0.1 秒读一次鼠标在哪。

只读光标，不碰游戏、不模拟输入；由 bootstrap 接给盘点线程（runtime/workers/count）。
"""


def pos() -> tuple[int, int]:
    """读一次 Windows 光标位置（GetCursorPos）；用的时候才碰 Win32，导入本模块不碰"""
    import ctypes
    from ctypes import wintypes

    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)
