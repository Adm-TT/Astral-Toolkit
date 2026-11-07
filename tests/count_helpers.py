"""直接造盘点线程的测试用（目录迁移 R5 起分析、排版、外面的东西由 bootstrap 接进去）。

用的就是 bootstrap 装配时那三样（_count_analysis、_count_views、_count_links），和生产一样：分析原样转给
trade/inspector、tasks/count；悬浮窗文字用 app/presenters/count（数量写法现取 tasks/hover.qty_text）；抓图、
游戏在不在前台、热键名、调试图目录、开始时在哪、悬浮窗短提示、正在退出都是用的时候才去那几个模块取——测试换那边的
函数（先造再换也一样）都生效。没给 output 用 BusOutput；cursor_pos / foreground 给了就用给的；enabled 默认开着
（测试不看是不是 Windows）。
"""

from astral_toolkit import bootstrap
from astral_toolkit.runtime.workers import count as countmod
from astral_toolkit.app.output import BusOutput


def links(*, cursor_pos=None, foreground=None):
    return bootstrap._count_links({"cursor_pos": cursor_pos, "foreground": foreground})


def worker(*, cursor_pos=None, foreground=None):
    return countmod._CountWorker(
        bootstrap._count_analysis(),
        bootstrap._count_views(),
        links(cursor_pos=cursor_pos, foreground=foreground),
    )


def count(results=None, *, cursor_pos=None, foreground=None, **kwargs):
    """_Count(results=None, *, output, analysis, views, links, enabled, clock=None, closing=None, worker=None, ...)"""
    kwargs.setdefault("output", BusOutput())
    kwargs.setdefault("analysis", bootstrap._count_analysis())
    kwargs.setdefault("views", bootstrap._count_views())
    kwargs.setdefault("enabled", True)
    if kwargs.get("links") is None:
        kwargs["links"] = links(cursor_pos=cursor_pos, foreground=foreground)
    return countmod._Count(results, **kwargs)
