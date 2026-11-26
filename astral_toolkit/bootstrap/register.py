"""按启动顺序把后台服务登记进 lifecycle（build 时做一次）"""

from __future__ import annotations

import threading
from typing import Any, Callable

from ..runtime.lifecycle import (
    OneShot,
    Phase,
    ServiceThread,
    SessionLoopService,
)

from .desktop_app import DesktopApp


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


def _warm_search_index() -> None:
    """搜索预热线程里跑的（Q1：线程由装配起，搜索模块 import 时不起）：窗口打开后在后台先把物品搜索索引建好，
    玩家第一次搜不用等；出错不往外抛（搜的时候会再建）"""
    from ..tasks.catalog_queries import search as item_search

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

        from ..core import settings
        from ..tasks import system as _sys

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
            from .. import gamedata

            return gamedata.warm_up()

        def start_ocr() -> threading.Thread | None:
            try:
                from ..ocr import warmup
            except Exception:
                return None
            thread = threading.Thread(target=warmup, daemon=True, name="ocr-warmup")
            thread.start()
            return thread

        app.lifecycle.register(
            # 热键线程（目录迁移 R4 起在 runtime/workers/hotkeys）；服务名照旧叫 hover，退出记录里一直这么叫
            _DirectService("hover", Phase.AMBIENT, app.hotkeys, start=app.hotkeys.start)
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
        # 导航的两个小后台会话（2026-11-09 起登记）：点了才开，退出时停、等线程退
        app.lifecycle.register(
            SessionLoopService("halo", Phase.SESSIONS, app.nav_deps.halo.loop),
            gate=False,
        )
        app.lifecycle.register(
            SessionLoopService("here-watch", Phase.SESSIONS, app.nav_deps.here.loop),
            gate=False,
        )

        app.lifecycle.register(OneShot("ocr-warmup", Phase.WORKERS, factory=start_ocr))
        try:
            from ..core.perfmon import monitor
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
        # - shell-watch / winid：窗口 / 单实例外围
        # - displayinfo-loc：RT-B5b 地点行 OCR 短线程（几百毫秒，daemon）
        app.state["_registered"] = True
