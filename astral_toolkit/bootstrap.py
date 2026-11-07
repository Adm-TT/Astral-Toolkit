"""RT-B7：唯一装配入口。

启动时在这里把各部件造好、登记服务、接好 tasks / app 层的全局绑定。
生产只调一次 bind_all；test 模式只造对象和登记，不做全局绑定。
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from .app.engines.count import _Count
from .app.engines.hover import _Hover
from .app.engines.live import _Live
from .runtime.workers.navigation import (
    _CamFilter,
    _Nav,
    _Steady,
    NavAnalysis,
    NavLinks,
    NavViews,
)
from .app.nav_marker import _NavMarker, marker_diag
from .app.output import BusOutput
from .runtime.lifecycle import (
    Lifecycle,
    OneShot,
    Phase,
    ServiceThread,
    SessionLoopService,
    StopReport,
)
from .runtime.results import ResultStore
from .runtime.workers.game_events import GameEventsWorker
from .runtime.workers.position import LogWatchWorker, PositionWorker

if TYPE_CHECKING:
    from .app.api.router import Api
    from .tasks.hover import HoverLinks
    from .tasks.system.common import StatusSources


@dataclass(frozen=True)
class DesktopApp:
    """一次装配出来的全部后台对象；state 只放本 app 自己的少量可变状态。"""

    results: ResultStore
    output: Any
    lifecycle: Lifecycle
    live: Any
    nav: Any
    count: Any
    pos: Any
    hover: Any
    game_events: Any
    logwatch: Any
    cam_filter: Any
    steady: Any
    hover_links: Any
    nav_deps: Any
    state: dict = field(default_factory=dict, compare=False)


_ALLOWED_OVERRIDES = frozenset(
    {
        "results",
        "output",
        "lifecycle",
        "clock",
        "foreground",
        "grab",
        "cursor_pos",
        "count_worker",
    }
)


class _DirectService:
    """把已有 start / request_stop / join（或线程）的对象接成 ManagedService"""

    def __init__(
        self,
        name: str,
        phase: Phase,
        target: Any,
        *,
        start: Callable[[], Any] | None = None,
    ) -> None:
        self.name = name
        self.phase = phase
        self._target = target
        self._start = start
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._start is not None:
            self._start()
            return
        starter = getattr(self._target, "start", None)
        if callable(starter):
            starter()

    def request_stop(self) -> None:
        stopper = getattr(self._target, "request_stop", None)
        if callable(stopper):
            stopper()
            return
        event = getattr(self._target, "stop_ev", None)
        setter = getattr(event, "set", None)
        if callable(setter):
            setter()
            return
        stopper = getattr(self._target, "stop", None)
        if callable(stopper):
            stopper()

    def join(self, timeout: float | None) -> bool:
        joiner = getattr(self._target, "join", None)
        if callable(joiner):
            return bool(joiner(timeout))
        thread = getattr(self._target, "thread", None)
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()


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
    from .app import hud_state
    from .infrastructure.platform import window
    from .navigation import displayinfo

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
    from .infrastructure.platform import timer

    return timer.fine


def _status_publisher(status: Callable[[], Any] | None) -> Callable[[], None] | None:
    """位置、日志里的地点变了推一次状态给窗口（每次现读状态）；没给状态源就不推"""
    if status is None:
        return None
    from .app import bus

    def publish() -> None:
        bus.publish("status", status())

    return publish


def _pos_service(mode: str, view: Any, status=None) -> PositionWorker:
    """位置服务（NV-B5；R1 起线程在 runtime/workers/position，读屏、分析、推状态都在这里接进去）：
    读右上角的 Reader 带上调试模式开关；认地点、算星系、离哪最近、字模学好没有用 tasks/position；
    desktop 读得快时调 Windows 等待精度；只有 Windows 读得了右上角"""
    import sys

    from .app import bus
    from .navigation.displayinfo import Reader
    from .infrastructure.platform import window
    from .tasks import position as position_tasks

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
    from .tasks import position as position_tasks

    return LogWatchWorker(
        read_log=position_tasks.last_log_place, publish_status=_status_publisher(status)
    )


def _nav_links(view: Any) -> NavLinks:
    """导航引擎要用的导航任务函数（NV-B4）：以前经 `_T("navigation")` 动态取，现在在这里接。
    fps：设置页的导航帧数，从内存里的设置取（不读盘），已限在 5–30"""
    from .core import settings
    from .tasks import navigation as navigation_tasks

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
    from .tasks import navigation_analysis

    return navigation_analysis


def _nav_views() -> NavViews:
    """导航线程要的排版（目录迁移 R2）：太空 / 空间站 / 地面三个视图、活动磁贴、右上角读位置的说法，都在 app/presenters/nav"""
    from .app.presenters import nav as present_nav

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

    from .app import bus

    def tail() -> Any:
        from .system.gamelog import EventTail

        return EventTail()

    def publish(event: dict[str, Any]) -> None:
        bus.publish("gamelog", event)

    return GameEventsWorker(
        tail,
        publish,
        enabled=sys.platform == "win32",
        on_qt_arrived=pos.request_read_now,
    )


def _hover_links() -> HoverLinks:
    """F8 要用的物品查询（IQ-B6）：物品卡片和窗口物品查询页同一份（tasks/catalog 用例 + app/presenters/catalog 排版）；
    掉落、玩家市场经 tasks/catalog（Trade 只在那里的市场会话里用，第一次用才造，和以前一样）；
    「可通过维科洛兑换获得」「可制造：有蓝图」经 tasks/wikelo、tasks/crafting，CR-B5"""
    from .app.presenters import catalog as present_catalog
    from .tasks import catalog as catalog_tasks
    from .tasks import crafting as crafting_tasks
    from .tasks import wikelo as wikelo_tasks
    from .tasks.hover import HoverLinks

    def item_card(name="", zh="", id=None, loot=True, exact=False):
        return present_catalog.present_item_info(
            catalog_tasks.get_item_info(name, zh, id, loot, exact)
        )

    return HoverLinks(
        item_card=item_card,
        loot=catalog_tasks.get_item_loot,
        market=catalog_tasks.open_market,
        market_rows=catalog_tasks.market_rows,
        hud_market=catalog_tasks.market_hud_text,
        wikelo_rewards=wikelo_tasks.rewards_for,
        has_blueprint=crafting_tasks.has_blueprint,
    )


def build(
    mode: str = "desktop", *, overrides: Mapping[str, Any] | None = None
) -> DesktopApp:
    """造对象、登记服务；desktop 模式最后再做全局绑定。"""
    from .tasks import navigation as navigation_tasks
    from .tasks import system as system_tasks

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
        from .app.http_writes import WRITES

        WRITES.bind_closing(lifecycle.is_closing)
        lifecycle.register(WRITES)

    results = options.get("results")
    if results is None:
        results = ResultStore()
    output = options.get("output")
    if output is None:
        output = BusOutput()

    from .core import settings

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
        clock=options.get("clock"),
        closing=lifecycle.is_closing,
        foreground=options.get("foreground"),
        grab=options.get("grab"),
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
    nav_deps = navigation_tasks.NavDeps(
        nav=nav, pos=pos, game_events=game_events, results=results
    )
    count = _Count(
        results,
        output=output,
        clock=options.get("clock"),
        closing=lifecycle.is_closing,
        foreground=options.get("foreground"),
        cursor_pos=options.get("cursor_pos"),
        worker=options.get("count_worker"),
    )
    hover_links = _hover_links()
    hover = _Hover(
        live=live, count=count, links=hover_links, feedback=feedback, nav=nav_deps
    )
    logwatch = _logwatch_service(status_now)

    app = DesktopApp(
        results=results,
        output=output,
        lifecycle=lifecycle,
        live=live,
        nav=nav,
        count=count,
        pos=pos,
        hover=hover,
        game_events=game_events,
        logwatch=logwatch,
        cam_filter=cam_filter,
        steady=steady,
        hover_links=hover_links,
        nav_deps=nav_deps,
        state={"warmups_enabled": True},
    )
    sources = status_sources(app)
    _register(app)
    if mode == "desktop":
        bind_all(app)
    return app


def bind_all(app: DesktopApp, *, replace: bool = False) -> None:
    """把剩下的全局绑定一次接好（盘点冻着、lifecycle_gate、ui_stream、导航数据层的位置线索）；
    tasks 的采矿 / F8 / 系统 / 导航 F 段 B5 起不再绑，由 routes 和引擎构造时直接拿对象。"""
    from .app import lifecycle_gate, ui_stream
    from .navigation import navigate as navigate_data
    from .tasks import count as count_tasks

    _bind_core_to_ui()
    navigate_data.HINTS = app.pos.hints
    count_tasks.bind(app.count, replace=replace)
    lifecycle_gate.bind_closing(app.lifecycle.is_closing, replace=replace)
    ui_stream.bind_switches(app.live, app.nav, app.pos, replace=replace)


def _bind_core_to_ui() -> None:
    """core 不反过来 import 界面（CL-C5）：截图时涂黑悬浮窗要的句柄 / 显示着没有、运行记录推到运行日志面板，都在这里接。
    每次现读悬浮窗模块当时的 HWND / SHOWN；经名字调 bus.runtime_log（测试换掉也照样走到）"""
    from .app import bus, overlay
    from .core import capture, run_records

    capture.set_overlay_state(lambda: (overlay.HWND, overlay.SHOWN))
    run_records.set_ui_sink(
        lambda line, tag="SYS", level="INFO": bus.runtime_log(
            line, tag=tag, level=level
        )
    )


def routes(app: DesktopApp) -> Api:
    """这个 app 的接口表（F 段 B5，架构稿 §12.3「路由直接持有对象」）：不用后台对象的照旧是各 Controller 的 ROUTES；
    要后台对象的由这里把这个 app 的对象交给 Controller 的 bound（采矿：实时读屏；F8：HoverLinks；系统：状态源和启动回调；导航和物品查询的商店导航：NavDeps）。server.main 交给网页服务"""
    from .app.api import mining as mining_api
    from .app.api import navigation as navigation_api
    from .app.api import router
    from .app.api import system as system_api
    from .app.api import trade as trade_api
    from .app.api import vision as vision_api

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
    from .tasks.system.common import StatusSources

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
    from .core import settings
    from .tasks import system as _sys

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
        from .system import feedback_up

        threading.Thread(
            target=lambda: feedback_up.retry_pending(_sys._fb_dir()),
            daemon=True,
            name="feedback-retry",
        ).start()
    return started


def shutdown(app: DesktopApp, budget: float = 5.0) -> StopReport:
    """退出时薄委托给 lifecycle；返回值就是 StopReport。"""
    return app.lifecycle.stop_all(budget)


def _warm_search_index() -> None:
    """搜索预热线程里跑的（Q1：线程由装配起，搜索模块 import 时不起）：窗口打开后在后台先把物品搜索索引建好，
    玩家第一次搜不用等；出错不往外抛（搜的时候会再建）"""
    from .tasks.catalog_queries import search as item_search

    try:
        item_search.build_index()
    except Exception:
        pass


def _register(app: DesktopApp) -> None:
    """按现有启动顺序登记；build 时做一次，gate 只控制自动启动。"""
    lock = app.state.get("_register_lock")
    if lock is None:
        lock = threading.Lock()
        app.state["_register_lock"] = lock
    with lock:
        if app.state.get("_registered"):
            return

        from .core import settings
        from .tasks import system as _sys

        online = getattr(_sys, "_online", None)
        if online is None:
            online = {}
            setattr(_sys, "_online", online)

        def live_gate() -> bool:
            return bool(settings.load().get("live_on"))

        def update_gate() -> bool:
            return not online.get("loop")

        def warm_gate() -> bool:
            return bool(app.state.get("warmups_enabled", True))

        def run_update(stop_ev: threading.Event) -> None:
            online["loop"] = True
            try:
                getattr(_sys, "_online_loop")(stop_ev)
            finally:
                online["loop"] = False

        def start_itemsearch() -> threading.Thread:
            thread = threading.Thread(
                target=_warm_search_index, daemon=True, name="search-warmup"
            )
            thread.start()
            return thread

        def start_gamedata() -> threading.Thread:
            from . import gamedata

            return gamedata.warm_up()

        def start_ocr() -> threading.Thread | None:
            try:
                from .ocr import warmup
            except Exception:
                return None
            thread = threading.Thread(target=warmup, daemon=True, name="ocr-warmup")
            thread.start()
            return thread

        app.lifecycle.register(
            _DirectService("hover", Phase.AMBIENT, app.hover, start=app.hover.start)
        )
        app.lifecycle.register(
            _DirectService("pos", Phase.AMBIENT, app.pos, start=app.pos.start)
        )
        app.lifecycle.register(
            _DirectService(
                "logwatch",
                Phase.AMBIENT,
                app.logwatch,
                start=app.logwatch.start,
            )
        )
        app.lifecycle.register(
            _DirectService(
                "game_events",
                Phase.AMBIENT,
                app.game_events,
                start=app.game_events.start,
            )
        )

        app.lifecycle.register(
            ServiceThread("update", Phase.WORKERS, run_update),
            gate=update_gate,
        )
        app.lifecycle.register(
            OneShot(
                "search-warmup",
                Phase.WORKERS,
                factory=start_itemsearch,
            ),
            gate=warm_gate,
        )
        app.lifecycle.register(
            OneShot(
                "gamedata-warmup",
                Phase.WORKERS,
                factory=start_gamedata,
            ),
            gate=warm_gate,
        )

        app.lifecycle.register(
            SessionLoopService(
                "live",
                Phase.SESSIONS,
                app.live.loop,
                start=app.live.start,
            ),
            gate=live_gate,
        )
        app.lifecycle.register(
            SessionLoopService("nav", Phase.SESSIONS, app.nav.loop),
            gate=False,
        )
        app.lifecycle.register(
            SessionLoopService("count", Phase.SESSIONS, app.count.loop),
            gate=False,
        )

        app.lifecycle.register(OneShot("ocr-warmup", Phase.WORKERS, factory=start_ocr))
        try:
            from .core.perfmon import monitor
        except Exception:
            monitor = None
        if monitor is not None:
            app.lifecycle.register(
                _DirectService(
                    "perfmon",
                    Phase.WORKERS,
                    monitor,
                    start=monitor.start,
                )
            )
        app.lifecycle.register(app.live.miss_shots)

        # B6 明确不登记（靠 closing 门 / 进程退出收尾）：
        # - feedback-retry：最长一次网络请求 60 s，退出预算内等不到就放弃
        # - overlay：没有停止入口，随进程退出
        # - tray：server 退出前已 remove
        # - task_runner.run_task 临时任务：按需线程，不纳入常驻服务
        # - 导航 here-watch / halo：B5b 会话内的事
        # - shell-watch / winid：窗口 / 单实例外围
        # - displayinfo-loc：RT-B5b 地点行 OCR 短线程（几百毫秒，daemon）
        app.state["_registered"] = True


__all__ = [
    "DesktopApp",
    "bind_all",
    "build",
    "routes",
    "shutdown",
    "start",
    "status_sources",
]
