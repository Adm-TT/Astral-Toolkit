"""游戏窗口的平台读数（NV-B3）：游戏在不在前台、游戏画面区域。导航记号投影用，由 bootstrap 传给导航引擎。

只读窗口状态，不碰游戏、不模拟输入；判断规则还在 system/showloc.py 和 infrastructure/platform/capture.py。
"""

from . import capture as _capture
from ...system import showloc as _showloc


def foreground():
    """最前面的窗口是不是星际公民（system.showloc.game_foreground）"""
    return _showloc.game_foreground()


def game_area():
    """游戏画面区域 {left, top, width, height}（infrastructure.platform.capture.game_area，每 0.5 秒最多查一次窗口位置）"""
    return _capture.game_area()
