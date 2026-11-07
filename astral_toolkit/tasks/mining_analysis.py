"""采矿线程一轮识别要用的分析（目录迁移 R3，章程 §5、§6）：认扫描面板、投票、认雷达信号、拼扫描结果、信号行标目标。

采矿线程在 runtime/workers，不能 import 这里；bootstrap 把本模块当成 MiningAnalysis 接进去。这里只原样转给
mining/screen、mining/signals、mining/mining_area、core/paths（读数文件改没改过）、tasks/goals（信号行标出目标要的矿）、
tasks/mining（扫描结果：破碎方案、精炼、目标，排成窗口和悬浮窗要的样子）：调用时才取（导入时机和以前线程里现 import
一样），不另存状态、不另做缓存。mining/screen 上的几个常数和最近一次的读数（INTERVAL、VOTE_FRAMES、SEARCH、
LAST_RAW、LAST_PANEL）也是每次现取，测试换掉它们照样生效。
"""

from typing import Any


def _screen() -> Any:
    from ..mining import screen

    return screen


def _signals() -> Any:
    from ..mining import signals

    return signals


def interval() -> Any:
    """两帧之间等多久（秒）"""
    return _screen().INTERVAL


def vote_frames() -> Any:
    """投票看最近几帧"""
    return _screen().VOTE_FRAMES


def search() -> Any:
    """在屏幕哪一块找扫描面板（左、上、右、下，按屏幕比例）"""
    return _screen().SEARCH


def analyse(*args: Any, **kwargs: Any) -> Any:
    """一帧画面：(扫描面板读数, 矿袋)"""
    return _screen().analyse(*args, **kwargs)


def last_raw() -> Any:
    """最近一次识别的原始读数（带时间 t）"""
    return _screen().LAST_RAW


def last_panel() -> Any:
    """最近一次找到的面板（cut：被屏幕右边挡住一截）"""
    return _screen().LAST_PANEL


def panel_seen(*args: Any, **kwargs: Any) -> Any:
    """真看到扫描面板了没有（读全了，或认出面板上的字 / 带矿名的成分）"""
    return _screen().panel_seen(*args, **kwargs)


def enqueue_rock(*args: Any, **kwargs: Any) -> Any:
    """一帧读数进投票队列（同一块石头才进）；返回换没换石头"""
    return _screen().enqueue_rock(*args, **kwargs)


def miss_reason(*args: Any, **kwargs: Any) -> Any:
    """面板读不全的原因（被屏幕挡住 / 色差重影）"""
    return _screen().miss_reason(*args, **kwargs)


def vote(*args: Any, **kwargs: Any) -> Any:
    """完整读数投票：(结果, 几帧对不对得上)"""
    return _screen().vote(*args, **kwargs)


def vote_partial(*args: Any, **kwargs: Any) -> Any:
    """面板被挡住一截时的投票（只看质量、抗性、不稳定性）"""
    return _screen().vote_partial(*args, **kwargs)


def find_signatures(*args: Any, **kwargs: Any) -> Any:
    """画面里的雷达信号"""
    return _signals().find_signatures(*args, **kwargs)


def match_signature(*args: Any, **kwargs: Any) -> Any:
    """信号值认不认得（有认不得的才问现在在哪）"""
    return _signals().match_signature(*args, **kwargs)


def describe_all(*args: Any, **kwargs: Any) -> Any:
    """信号那几行字"""
    return _signals().describe_all(*args, **kwargs)


def guesses(*args: Any, **kwargs: Any) -> Any:
    """一个信号值可能是什么矿"""
    return _signals().guesses(*args, **kwargs)


def mark_goal_lines(*args: Any, **kwargs: Any) -> Any:
    """信号行里标出目标要的矿（tasks/goals）"""
    from . import goals

    return goals._mark_goal_lines(*args, **kwargs)


def rocks_stamp() -> Any:
    """石头表改没改过（换了就重发信号）"""
    from ..mining import mining_area

    return mining_area.rocks_stamp()


def mine_file_stamp() -> Any:
    """自己起名记下的信号读数文件改没改过（起了名就重发信号）"""
    from ..core import paths

    return paths.file_stamp(_signals()._mine_file())


def scan_view(*args: Any, **kwargs: Any) -> Any:
    """一块石头的扫描结果（破碎方案、精炼、目标；排成窗口、悬浮窗要的样子，tasks/mining）"""
    from . import mining

    return mining.scan_view(*args, **kwargs)
