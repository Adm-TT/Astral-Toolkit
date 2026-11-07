"""直接造导航线程的测试用（目录迁移 R2 起导航分析、排版由 bootstrap 接进去）。

默认接真的分析（tasks/navigation_analysis，原样转给 navigation/navigate，测试换 navigate 上的函数照样生效）
和真的排版；排版每次现取 app/presenters/nav 上的函数，测试换那边的函数（先造线程再换也一样）都生效。
没给 links 时用 QUIET_LINKS，只是导航日志那一行照旧现取 tasks/navigation.nav_log（以前线程里直接调它）。
"""

import dataclasses

from astral_toolkit.runtime.workers import navigation as navmod
from astral_toolkit.app.output import BusOutput
from astral_toolkit.app.presenters import nav as present_nav
from astral_toolkit.tasks import navigation as navigation_tasks
from astral_toolkit.tasks import navigation_analysis


def views():
    return navmod.NavViews(
        space=lambda *a, **k: present_nav.space_view_of(*a, **k),
        station=lambda *a, **k: present_nav.station_view_of(*a, **k),
        ground=lambda *a, **k: present_nav.ground_view_of(*a, **k),
        activity=lambda *a, **k: present_nav.activity(*a, **k),
        tip=lambda *a, **k: present_nav.nav_tip(*a, **k),
        di_help=present_nav.DI_HELP,
    )


def links():
    return dataclasses.replace(
        navmod.QUIET_LINKS, trace=lambda *a: navigation_tasks.nav_log(*a)
    )


def _fill(kwargs, links_given):
    kwargs.setdefault("analysis", navigation_analysis)
    kwargs.setdefault("views", views())
    if not links_given and kwargs.get("links") is None:
        kwargs["links"] = links()
    return kwargs


def worker(*args, **kwargs):
    """_NavWorker(positions, cam_filter, marker_lock, results=None, marker=None, links=None, *, analysis, views)"""
    return navmod._NavWorker(*args, **_fill(kwargs, len(args) >= 6))


def nav(*args, **kwargs):
    """_Nav(positions, cam_filter, steady, results=None, *, output, analysis, views, ...)：没给 output 用 BusOutput"""
    kwargs.setdefault("output", BusOutput())
    return navmod._Nav(*args, **_fill(kwargs, False))
