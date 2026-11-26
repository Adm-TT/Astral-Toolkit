"""装配主流程：build 造对象、登记服务，bind_all 接全局绑定，routes / status_sources / start / shutdown"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from ..runtime.workers.count import _Count
from ..app.inputs.hotkeys import HotkeyCommands
from ..runtime.workers.mining import _Live
from ..runtime.workers.navigation import _CamFilter, _Nav, _Steady
from ..app.output import BusOutput
from ..runtime.lifecycle import Lifecycle, StopReport
from ..runtime.results import ResultStore
from .count import _count_analysis, _count_links, _count_live_place, _count_views
from .desktop_app import _ALLOWED_OVERRIDES, DesktopApp
from .inputs import _hotkeys, _hover_links
from .mining import _mining_analysis, _mining_links, _mining_views
from .nav import (
    _game_events,
    _logwatch_service,
    _nav_analysis,
    _nav_links,
    _nav_marker,
    _nav_views,
    _pos_service,
    nav_watches,
)
from .register import _register

if TYPE_CHECKING:
    from ..app.api.router import Api
    from ..tasks.system.common import StatusSources


def build(
    mode: str = "desktop", *, overrides: Mapping[str, Any] | None = None
) -> DesktopApp:
    """造对象、登记服务；desktop 模式最后再做全局绑定。"""
    import sys

    from ..tasks import navigation as navigation_tasks
    from ..tasks import system as system_tasks

    if mode not in ("desktop", "test"):
        raise ValueError(f"mode 只支持 desktop / test：{mode!r}")

    options = dict(overrides or {})
    unknown = set(options) - _ALLOWED_OVERRIDES
    if unknown:
        raise ValueError(f"overrides 不认识的键：{', '.join(sorted(unknown))}")

    lifecycle = options.get("lifecycle")
    if lifecycle is None:
        lifecycle = Lifecycle()

    # 生产只在这里给全局 HTTP 在途写计数接上本 app 的 lifecycle；test 模式不碰全局单例。
    if mode == "desktop":
        from ..app.http_writes import WRITES

        WRITES.bind_closing(lifecycle.is_closing)
        lifecycle.register(WRITES)

    results = options.get("results")
    if results is None:
        results = ResultStore()
    output = options.get("output")
    if output is None:
        output = BusOutput()

    from ..core import settings

    # 常看的设置（调试模式、记号）：一份内存里的，存设置后自动重读（NV-B5）
    view = settings.View()

    # 状态源 sources 要等下面 app 造好才有；位置服务、读日志、反馈键的线程要到
    # lifecycle.start_all 才起，那时已经有了，所以回调里现读。
    def status_now():
        return system_tasks.status(sources)

    def feedback(**kw):
        return system_tasks.feedback_report(sources, **kw)

    # nav_deps 要等导航引擎造好才有，采矿读屏的线程要到 lifecycle.start_all 才起，
    # 所以 where_now / area_now 也在这里现读。
    def where_now():
        return navigation_tasks._where_now(nav_deps)

    def area_now():
        return navigation_tasks._area_now(nav_deps)

    pos = _pos_service(mode, view, status=status_now)
    links = _nav_links(view)
    cam_filter = _CamFilter(log=links.log)
    steady = _Steady()
    game_events = _game_events(pos)
    live = _Live(
        results,
        output=output,
        analysis=_mining_analysis(),
        views=_mining_views(),
        links=_mining_links(options),
        clock=options.get("clock"),
        closing=lifecycle.is_closing,
        where_now=where_now,
        area_now=area_now,
    )
    nav = _Nav(
        pos,
        cam_filter,
        steady,
        results,
        output=output,
        clock=options.get("clock"),
        closing=lifecycle.is_closing,
        marker=_nav_marker(pos, live, mode, view),
        links=links,
        analysis=_nav_analysis(),
        views=_nav_views(),
    )
    halo_watch, here_watch = nav_watches(
        results, output, lifecycle.is_closing, lambda: nav_deps
    )
    nav_deps = navigation_tasks.NavDeps(
        nav=nav,
        pos=pos,
        game_events=game_events,
        results=results,
        halo=halo_watch,
        here=here_watch,
    )
    live_place_src: list[Any] = [None]
    count = _Count(
        results,
        output=output,
        analysis=_count_analysis(),
        views=_count_views(),
        links=_count_links(options, live_place_src=live_place_src),
        enabled=sys.platform == "win32",
        clock=options.get("clock"),
        closing=lifecycle.is_closing,
        worker=options.get("count_worker"),
    )
    hover_links = _hover_links()
    hotkey_commands = HotkeyCommands(
        live=live, count=count, links=hover_links, feedback=feedback, nav=nav_deps
    )
    hotkeys = _hotkeys(hotkey_commands)
    logwatch = _logwatch_service(status_now)

    app = DesktopApp(
        results=results,
        output=output,
        lifecycle=lifecycle,
        live=live,
        nav=nav,
        count=count,
        pos=pos,
        hotkeys=hotkeys,
        hotkey_commands=hotkey_commands,
        game_events=game_events,
        logwatch=logwatch,
        cam_filter=cam_filter,
        steady=steady,
        hover_links=hover_links,
        nav_deps=nav_deps,
        state={"warmups_enabled": True},
    )
    live_place_src[0] = lambda: _count_live_place(app.pos)
    sources = status_sources(app)
    _register(app)
    if mode == "desktop":
        bind_all(app)
    return app


def bind_all(app: DesktopApp, *, replace: bool = False) -> None:
    """把剩下的全局绑定一次接好（盘点冻着、lifecycle_gate、ui_stream、导航数据层的位置线索）；
    tasks 的采矿 / F8 / 系统 / 导航 F 段 B5 起不再绑，由 routes 和引擎构造时直接拿对象。"""
    from ..app import lifecycle_gate, ui_stream
    from ..navigation import navigate as navigate_data
    from ..tasks import count as count_tasks

    _bind_core_to_ui()
    _bind_platform_to_hud()
    navigate_data.HINTS = app.pos.hints
    count_tasks.bind(app.count, replace=replace)
    lifecycle_gate.bind_closing(app.lifecycle.is_closing, replace=replace)
    ui_stream.bind_switches(app.live, app.nav, app.pos, replace=replace)


def _bind_platform_to_hud() -> None:
    """悬浮窗「物品」按 Shift 钉住、按住 Ctrl 不收、挪开就收要读键、读光标：接平台层那一份
    （目录迁移收尾；app 层不直接 import infrastructure，以前 hud_state 自己调 Win32）"""
    from ..app import hud_state
    from ..infrastructure.platform import cursor, keys

    hud_state.set_platform(cursor.pos, keys.down)


def _bind_core_to_ui() -> None:
    """core 不反过来 import 界面（CL-C5）：截图时涂黑悬浮窗要的句柄 / 显示着没有、运行记录推到运行日志面板，都在这里接。
    每次现读悬浮窗模块当时的 HWND / SHOWN；经名字调 bus.runtime_log（测试换掉也照样走到）。
    采矿截图顺手更新截图预览也在这里接（领域层不碰界面，2026-11-26）；经名字调 preview.update_preview"""
    from ..app import bus, overlay, preview
    from ..core import run_records
    from ..infrastructure.platform import capture
    from ..mining import screen as mining_screen

    capture.set_overlay_state(lambda: (overlay.HWND, overlay.SHOWN))
    mining_screen.set_preview_sink(
        lambda img: preview.update_preview(img, source="live")
    )
    run_records.set_ui_sink(
        lambda line, tag="SYS", level="INFO": bus.runtime_log(
            line, tag=tag, level=level
        )
    )


def routes(app: DesktopApp) -> Api:
    """这个 app 的接口表（F 段 B5，架构稿 §12.3「路由直接持有对象」）：不用后台对象的照旧是各 Controller 的 ROUTES；
    要后台对象的由这里把这个 app 的对象交给 Controller 的 bound（采矿：实时读屏；F8：HoverLinks；系统：状态源和启动回调；导航和物品查询的商店导航：NavDeps）。server.main 交给网页服务"""
    from ..app.api import mining as mining_api
    from ..app.api import navigation as navigation_api
    from ..app.api import router
    from ..app.api import system as system_api
    from ..app.api import trade as trade_api
    from ..app.api import vision as vision_api

    return router.Api(
        {
            **router.routes(),
            **mining_api.bound(app.live),
            **navigation_api.bound(app.nav_deps),
            **trade_api.bound(app.nav_deps),
            **vision_api.bound(app.hover_links),
            **system_api.bound(status_sources(app), lambda: start(app)),
        }
    )


def status_sources(app: DesktopApp) -> StatusSources:
    """状态页 / 问题反馈要读的运行状态：每项都是现读，不提前缓存。"""
    from ..tasks.system.common import StatusSources

    return StatusSources(
        live_running=app.live.running,
        live_paused=lambda: app.live.paused,
        nav_target_label=app.nav.target_label,
        nav_space_mode=lambda: app.nav.space_mode,
        pos_reader_active=lambda: app.pos.reader.active,
        pos_label=lambda: app.pos.label,
        pos_system=lambda: app.pos.system,
        game_events_last=lambda: app.game_events.last,
        results=app.results,
    )


def start(app: DesktopApp) -> bool:
    """打开 AT 主窗口时启动后台服务（顺序照旧；由 Lifecycle 统一记账）"""
    from ..core import settings
    from ..tasks import system as _sys

    if not settings.load().get("agreed"):
        return False
    if app.lifecycle.is_closing():
        return False

    _online = getattr(_sys, "_online", None)
    if _online is None:
        _online = {}
        setattr(_sys, "_online", _online)
    app.state["warmups_enabled"] = not _online.get("loop")
    started = app.lifecycle.start_all()

    # feedback-retry 按 B6 决定不登记：只挡新任务，退出时放弃；下次启动 retry_pending 会重试。
    if started and not _online.get("fb_retry") and not app.lifecycle.is_closing():
        _online["fb_retry"] = True
        from ..system import feedback_up

        threading.Thread(
            target=lambda: feedback_up.retry_pending(_sys._fb_dir()),
            daemon=True,
            name="feedback-retry",
        ).start()
    return started


def shutdown(app: DesktopApp, budget: float = 5.0) -> StopReport:
    """退出时薄委托给 lifecycle；返回值就是 StopReport。"""
    return app.lifecycle.stop_all(budget)
