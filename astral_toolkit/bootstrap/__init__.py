"""RT-B7：唯一装配入口。

启动时在这里把各部件造好、登记服务、接好 tasks / app 层的全局绑定。
生产只调一次 bind_all；test 模式只造对象和登记，不做全局绑定。

2026-11-26 拆成包（只搬家，行为不变）：desktop_app（DesktopApp）、nav / mining / count / inputs（各组后台对象要的东西）、
register（登记后台服务）、assemble（build、bind_all、routes、start、shutdown 装配主流程）。外面照旧写 bootstrap.xxx，名字都从这里转出去。
测试要换掉某个函数里用到的名字，换它所在的那个文件（比如 bootstrap.mining.setting_run_flag），换这里的不起作用。
"""

from .assemble import (
    _bind_core_to_ui,
    bind_all,
    build,
    routes,
    shutdown,
    start,
    status_sources,
)
from .count import _count_analysis, _count_links, _count_views
from .desktop_app import DesktopApp
from .inputs import _hover_links
from .mining import _mining_analysis, _mining_links, _mining_views
from .nav import (
    _fine_timer,
    _game_events,
    _nav_analysis,
    _nav_links,
    _nav_marker,
    _nav_views,
    _pos_service,
    nav_watches,
)

__all__ = [
    "DesktopApp",
    "bind_all",
    "build",
    "routes",
    "shutdown",
    "start",
    "status_sources",
    # 下面这些拆包前就是 bootstrap.xxx 能拿到的，测试和测试夹具照旧这么取
    "_bind_core_to_ui",
    "_count_analysis",
    "_count_links",
    "_count_views",
    "_fine_timer",
    "_game_events",
    "_hover_links",
    "_mining_analysis",
    "_mining_links",
    "_mining_views",
    "_nav_analysis",
    "_nav_links",
    "_nav_marker",
    "_nav_views",
    "_pos_service",
    "nav_watches",
]
