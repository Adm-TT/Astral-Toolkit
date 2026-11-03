"""后台引擎容器（2026-10-30 重构阶段 0，NGU 设计 4.5 节）

把原来 services.py 建的引擎实例、services.start_background() 的内容、
server.main() 结尾收尾的几步原样搬到这里，逻辑没改。
阶段 4 删了 services.py：要用引擎的地方直接 EngineManager.get_instance().live / .nav / .pos ……
"""

import threading
from typing import Any, Callable

from ...runtime.lifecycle import (
    Lifecycle,
    OneShot,
    Phase,
    ServiceThread,
    SessionLoopService,
    StopReport,
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


class _CountService:
    """B5a 前的最小盘点外壳：stop() 后必须 join thread，不能只看 running=False"""

    name = "count"
    phase = Phase.SESSIONS

    def __init__(self, count: Any) -> None:
        self._count = count

    def start(self) -> None:
        return None

    def request_stop(self) -> None:
        running = getattr(self._count, "running", None)
        if callable(running) and not running():
            return
        stopper = getattr(self._count, "stop", None)
        if callable(stopper):
            stopper()

    def join(self, timeout: float | None) -> bool:
        thread = getattr(self._count, "thread", None)
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()


class EngineManager:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """全程序只有一个（单例）"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        from .nav import _Steady, _CamFilter, _Nav, _GameEvents
        from .live import _Live
        from .hover import _Hover
        from .count import _Count
        from .pos import _Pos, _LogWatch
        from ...runtime.results import ResultStore

        self.lifecycle = Lifecycle()
        self._register_lock = threading.Lock()
        self._registered = False
        self._warmups_enabled = True

        self.results = ResultStore()
        self.pos = _Pos()
        self.cam_filter = _CamFilter()
        self.steady = _Steady()
        self.game_events = _GameEvents(on_qt_arrived=self.pos.request_read_now)
        self.nav = _Nav(
            self.pos,
            self.cam_filter,
            self.steady,
            self.results,
            closing=self.lifecycle.is_closing,
        )
        self.live = _Live(self.results, closing=self.lifecycle.is_closing)
        self.count = _Count()
        self.hover = _Hover()
        self.logwatch = _LogWatch()

        # B5b 过渡：B7 移到 bootstrap。只在组装末尾写一次，导入 tasks.navigation 不再有副作用。
        from ...navigation import navigate as navigate_data
        from ...tasks import navigation as navigation_tasks

        navigate_data.HINTS = self.pos.hints
        navigation_tasks.bind(self.nav, self.pos, self.game_events, self.results)

    def start_all(self):
        """打开 AT 主窗口时启动后台服务（顺序照旧；由 Lifecycle 统一记账）"""
        from ...core import settings
        from ...tasks import (
            system as _sys,
        )  # _online / _online_loop / _fb_dir 在 tasks.system（测试直接换这里的）

        if not settings.load().get("agreed"):
            return False
        if self.lifecycle.is_closing():
            return False

        _online = getattr(_sys, "_online", None)
        if _online is None:
            _online = {}
            setattr(_sys, "_online", _online)
        self._warmups_enabled = not _online.get("loop")
        self._ensure_registered()
        started = self.lifecycle.start_all()

        # feedback-retry 按 B6 决定不登记：只挡新任务，退出时放弃；下次启动 retry_pending 会重试。
        if started and not _online.get("fb_retry") and not self.lifecycle.is_closing():
            _online["fb_retry"] = True
            from ...system import feedback_up

            threading.Thread(
                target=lambda: feedback_up.retry_pending(_sys._fb_dir()),
                daemon=True,
                name="feedback-retry",
            ).start()
        return started

    def _ensure_registered(self):
        """按现有启动顺序登记；只在第一次调用时做。gate 只控制自动启动。"""
        if self._registered:
            return
        with self._register_lock:
            if self._registered:
                return

            from ...core import settings
            from ...crafting import itemsearch
            from ...tasks import system as _sys

            online = getattr(_sys, "_online", None)
            if online is None:
                online = {}
                setattr(_sys, "_online", online)

            def live_gate() -> bool:
                return bool(settings.load().get("live_on"))

            def update_gate() -> bool:
                return not online.get("loop")

            def warm_gate() -> bool:
                return self._warmups_enabled

            def run_update(stop_ev: threading.Event) -> None:
                online["loop"] = True
                try:
                    getattr(_sys, "_online_loop")(stop_ev)
                finally:
                    online["loop"] = False

            def start_itemsearch() -> threading.Thread:
                return itemsearch.warm_up()

            def start_gamedata() -> threading.Thread:
                from ... import gamedata

                return gamedata.warm_up()

            def start_ocr() -> threading.Thread | None:
                try:
                    from ...ocr import warmup
                except Exception:
                    return None
                thread = threading.Thread(target=warmup, daemon=True, name="ocr-warmup")
                thread.start()
                return thread

            self.lifecycle.register(
                _DirectService(
                    "hover", Phase.AMBIENT, self.hover, start=self.hover.start
                )
            )
            self.lifecycle.register(
                _DirectService("pos", Phase.AMBIENT, self.pos, start=self.pos.start)
            )
            self.lifecycle.register(
                _DirectService(
                    "logwatch",
                    Phase.AMBIENT,
                    self.logwatch,
                    start=self.logwatch.start,
                )
            )
            self.lifecycle.register(
                _DirectService(
                    "game_events",
                    Phase.AMBIENT,
                    self.game_events,
                    start=self.game_events.start,
                )
            )

            self.lifecycle.register(
                ServiceThread("update", Phase.WORKERS, run_update),
                gate=update_gate,
            )
            self.lifecycle.register(
                OneShot(
                    "search-warmup",
                    Phase.WORKERS,
                    factory=start_itemsearch,
                ),
                gate=warm_gate,
            )
            self.lifecycle.register(
                OneShot(
                    "gamedata-warmup",
                    Phase.WORKERS,
                    factory=start_gamedata,
                ),
                gate=warm_gate,
            )

            self.lifecycle.register(
                SessionLoopService(
                    "live",
                    Phase.SESSIONS,
                    self.live.loop,
                    start=self.live.start,
                ),
                gate=live_gate,
            )
            self.lifecycle.register(
                SessionLoopService("nav", Phase.SESSIONS, self.nav.loop),
                gate=False,
            )
            self.lifecycle.register(_CountService(self.count), gate=False)

            self.lifecycle.register(
                OneShot("ocr-warmup", Phase.WORKERS, factory=start_ocr)
            )
            try:
                from ...core.perfmon import monitor
            except Exception:
                monitor = None
            if monitor is not None:
                self.lifecycle.register(
                    _DirectService(
                        "perfmon",
                        Phase.WORKERS,
                        monitor,
                        start=monitor.start,
                    )
                )

            # B6 明确不登记（靠 closing 门 / 进程退出收尾）：
            # - feedback-retry：最长一次网络请求 60 s，退出预算内等不到就放弃
            # - overlay：没有停止入口，随进程退出
            # - tray：server 退出前已 remove
            # - bus.run_task 临时任务：按需线程，不纳入常驻服务
            # - 导航 here-watch / halo：B5b 会话内的事
            # - shell-watch / winid：窗口 / 单实例外围
            # - displayinfo-loc：RT-B5b 地点行 OCR 短线程（几百毫秒，daemon）
            self._registered = True

    def stop_all(self, budget: float = 5.0) -> StopReport:
        """退出时薄委托给 lifecycle；返回值就是 StopReport"""
        return self.lifecycle.stop_all(budget)
