"""导航、位置、游戏日志这一组后台对象要的东西：在这里接好交给 runtime/workers"""

from __future__ import annotations

from typing import Any, Callable

from ..runtime.workers.navigation import (
    NavAnalysis,
    NavLinks,
    NavViews,
)
from ..app.nav_marker import _NavMarker, marker_diag
from ..runtime.results import ResultStore
from ..runtime.workers.game_events import GameEventsWorker
from ..runtime.workers.nav_watch import NavWatch, WatchSteps
from ..runtime.workers.position import LogWatchWorker, PositionWorker


def _no_hud() -> None:
    """test 模式的导航记号不接真悬浮窗（测试不许碰屏幕上的窗口）"""
    return None


def _debug_on(view: Any) -> Callable[[], bool]:
    """调试模式开没开（NV-B5）：问内存里的设置（core.settings.View），不读盘；设置页一改，下一次问就是新的"""

    def on() -> bool:
        return bool(view.get("debug_mode", False))

    return on


def _debug_only(fn: Callable[..., Any], on: Callable[[], bool]) -> Callable[..., None]:
    """调试模式开着才调 fn（NV-B5：诊断日志只在调试模式写；关着时连字符串都不拼）"""

    def call(*args: Any) -> None:
        if on():
            fn(*args)

    return call


def _nav_marker(pos: Any, live: Any, mode: str, view: Any) -> _NavMarker:
    """导航 HUD 记号要的东西（NV-B3）：以前 tasks/mining 自己去找，现在在这里一次接好。
    view：core.settings.View，设置从内存取；记号收起原因只在调试模式写（NV-B5）"""
    from ..app import hud_state
    from ..infrastructure.platform import window
    from ..navigation import displayinfo

    return _NavMarker(
        pos,
        mining_running=live.running,
        foreground=window.foreground,
        game_area=window.game_area,
        last_fov=displayinfo.last_fov,
        settings=view.all,
        hud=hud_state._hud if mode == "desktop" else _no_hud,
        diag=_debug_only(marker_diag, _debug_on(view)),
    )


def _fine_timer(mode: str) -> Callable[[bool], None] | None:
    """读得快时调高 Windows 等待精度（导航帧数，NV-B5）：只给 desktop；test 模式不碰系统计时"""
    if mode != "desktop":
        return None
    from ..infrastructure.platform import timer

    return timer.fine


def _status_publisher(status: Callable[[], Any] | None) -> Callable[[], None] | None:
    """位置、日志里的地点变了推一次状态给窗口（每次现读状态）；没给状态源就不推"""
    if status is None:
        return None
    from ..app import bus

    def publish() -> None:
        bus.publish("status", status())

    return publish


def _pos_service(mode: str, view: Any, status=None) -> PositionWorker:
    """位置服务（NV-B5；R1 起线程在 runtime/workers/position，读屏、分析、推状态都在这里接进去）：
    读右上角的 Reader 带上调试模式开关；认地点、算星系、离哪最近、字模学好没有用 tasks/position；
    desktop 读得快时调 Windows 等待精度；只有 Windows 读得了右上角"""
    import sys

    from ..app import bus
    from ..navigation.displayinfo import Reader
    from ..infrastructure.platform import window
    from ..tasks import position as position_tasks

    def log(line: str) -> None:
        bus.publish("log", {"task": "displayinfo", "line": line})

    return PositionWorker(
        Reader(every=1.0, debug=_debug_on(view)),
        foreground=window.foreground,  # 每次现取 showloc.game_foreground（原来线程开始时才 import）
        calibrated=position_tasks.glyphs_ready,
        label_of=position_tasks.label_of,
        system_of=position_tasks.system_of,
        locate=position_tasks.locate,
        publish_status=_status_publisher(status),
        log=log,
        fine_timer=_fine_timer(mode),
        enabled=sys.platform == "win32",
    )


def _logwatch_service(status=None) -> LogWatchWorker:
    """游戏日志位置跟踪（R1 起线程在 runtime/workers/position）：读日志用 tasks/position，地点变了推状态"""
    from ..tasks import position as position_tasks

    return LogWatchWorker(
        read_log=position_tasks.last_log_place, publish_status=_status_publisher(status)
    )


def _nav_links(view: Any) -> NavLinks:
    """导航引擎要用的导航任务函数（NV-B4）：以前经 `_T("navigation")` 动态取，现在在这里接。
    fps：设置页的导航帧数，从内存里的设置取（不读盘），已限在 5–30"""
    from ..core import settings
    from ..tasks import navigation as navigation_tasks

    return NavLinks(
        log=navigation_tasks._wp_log,
        fix_key_hint=navigation_tasks.fix_key_hint,
        place_row=navigation_tasks._place_row,
        setting=navigation_tasks.settings_key,
        fps=lambda: settings.nav_fps(view.get("nav_fps")),
        trace=navigation_tasks.nav_log,
    )


def _nav_analysis() -> NavAnalysis:
    """导航线程一轮要用的分析（目录迁移 R2）：tasks/navigation_analysis 这个模块（原样转给 navigation/navigate）"""
    from ..tasks import navigation_analysis

    return navigation_analysis


def _nav_views() -> NavViews:
    """导航线程要的排版（目录迁移 R2）：太空 / 空间站 / 地面三个视图、活动磁贴、右上角读位置的说法，都在 app/presenters/nav"""
    from ..app.presenters import nav as present_nav

    return NavViews(
        space=present_nav.space_view_of,
        station=present_nav.station_view_of,
        ground=present_nav.ground_view_of,
        activity=present_nav.activity,
        tip=present_nav.nav_tip,
        di_help=present_nav.DI_HELP,
    )


def _game_events(pos: Any) -> GameEventsWorker:
    """游戏日志事件（目录迁移 R2 起线程在 runtime/workers/game_events）：读日志用 system/gamelog（线程开始时才造），
    推窗口走总线「gamelog」，量子到达让定位马上读一次；只有 Windows 起线程"""
    import sys

    from ..app import bus

    def tail() -> Any:
        from ..system.gamelog import EventTail

        return EventTail()

    def publish(event: dict[str, Any]) -> None:
        bus.publish("gamelog", event)

    return GameEventsWorker(
        tail,
        publish,
        enabled=sys.platform == "win32",
        on_qt_arrived=pos.request_read_now,
    )


def nav_watches(
    results: ResultStore,
    output: Any,
    closing: Callable[[], bool],
    deps_now: Callable[[], Any],
) -> tuple[NavWatch, NavWatch]:
    """导航的两个小后台会话（2026-11-09，原来 tasks/navigation 自己起 daemon 线程）：halo（挂着小行星带方案时核对）、
    here-watch（「用当前位置新建」等 /showlocation）。每一轮做什么用 tasks/navigation 的函数；
    deps_now 现取 NavDeps（它要等这两个造好才有）"""
    from ..tasks import navigation as navigation_tasks

    halo = NavWatch(
        "halo",
        "小行星带核对",
        WatchSteps(
            setup=lambda _payload: navigation_tasks._halo_state(deps_now()),
            step=lambda _payload, st: navigation_tasks._halo_step(deps_now(), st),
            wait=navigation_tasks.HALO_WAIT,
        ),
        results=results,
        output=output,
        closing=closing,
    )
    here = NavWatch(
        "here-watch",
        "路标等坐标",
        WatchSteps(
            setup=lambda _payload: navigation_tasks._here_state(),
            step=lambda _payload, st: navigation_tasks._here_step(deps_now(), st),
            wait=0.0,  # 一轮里 wait_new_coords 自己等 1 秒
        ),
        results=results,
        output=output,
        closing=closing,
    )
    return halo, here
