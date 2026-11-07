"""直接造采矿线程的测试用（目录迁移 R3 起识别分析、活动磁贴、外面的东西由 bootstrap 接进去）。

用的就是 bootstrap 装配时那三样（_mining_analysis、_mining_views、_mining_links），和生产一样：分析原样转给
mining/screen、mining/signals、tasks/mining 等；抓图、游戏在不在前台、热键名、日志和截图目录、让读位置让出识别引擎
都是用的时候才去那几个模块取——测试换那边的函数、常数（先造线程再换也一样）都生效；没出结果的画面交给新造的
MissShotsService；设置里的 live_on 照旧写（要换就在造线程之前换 bootstrap.setting_run_flag）。活动磁贴接的是
造的时候 app/presenters/mining.activity 那个函数。没给 output 用 BusOutput；grab / foreground 给了就用给的。
"""

from astral_toolkit import bootstrap
from astral_toolkit.runtime.workers import mining as livemod
from astral_toolkit.app.output import BusOutput


def links(*, grab=None, foreground=None):
    return bootstrap._mining_links({"grab": grab, "foreground": foreground})


def live(results=None, *, grab=None, foreground=None, **kwargs):
    """_Live(results=None, *, output, analysis, views, links, clock=None, closing=None, where_now=None, area_now=None)"""
    kwargs.setdefault("output", BusOutput())
    kwargs.setdefault("analysis", bootstrap._mining_analysis())
    kwargs.setdefault("views", bootstrap._mining_views())
    if kwargs.get("links") is None:
        kwargs["links"] = links(grab=grab, foreground=foreground)
    return livemod._Live(results, **kwargs)
