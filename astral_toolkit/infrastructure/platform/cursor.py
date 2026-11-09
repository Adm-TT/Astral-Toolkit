"""光标位置的平台读数（目录迁移 R5，从 app/engines/count 拆出来）：盘点线程隔 0.1 秒读一次鼠标在哪；
目录迁移收尾起悬浮窗「物品」挪开就收（app/hud_state）也用它。都由 bootstrap 接。

只读光标，不碰游戏、不模拟输入。全项目读光标只有 infrastructure/platform/capture.cursor_pos 一份（截图换算也用它），这里转过去，
和 window 转 infrastructure/platform/capture 一样。
"""


def pos() -> tuple[int, int]:
    """读一次光标位置 (x, y)（infrastructure/platform/capture.cursor_pos）；用的时候才碰 Win32，导入本模块不碰；读不了照样抛出去"""
    from .capture import cursor_pos

    return cursor_pos()
