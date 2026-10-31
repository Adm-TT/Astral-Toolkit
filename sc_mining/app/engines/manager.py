"""后台引擎容器（2026-10-30 重构阶段 0，NGU 设计 4.5 节）

把原来 services.py 建的引擎实例、services.start_background() 的内容、
server.main() 结尾收尾的几步原样搬到这里，逻辑没改。
阶段 4 删了 services.py：要用引擎的地方直接 EngineManager.get_instance().live / .nav / .pos ……
"""

import threading


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

        self.game_events = _GameEvents()
        self.nav = _Nav()
        self.live = _Live()
        self.pos = _Pos()
        self.count = _Count()
        self.hover = _Hover()
        self.cam_filter = _CamFilter()
        self.steady = _Steady()
        self.logwatch = _LogWatch()

    def start_all(self):
        """打开天枢主窗口时启动后台服务：热键监听、定时查更新、搜索索引预热、未发送反馈补发、原矿扫描续跑
        （原来的 services.start_background()，原样搬来）"""
        from ...core import settings
        from ...tasks import (
            system as _sys,
        )  # _online / _online_loop / _fb_dir 在 tasks.system（测试直接换这里的）

        if not settings.load().get("agreed"):
            return
        self.hover.start()
        self.pos.start()
        self.logwatch.start()
        self.game_events.start()
        _online = getattr(_sys, "_online", {})
        if not _online.get("loop"):
            _online["loop"] = True
            threading.Thread(
                target=_sys._online_loop, daemon=True, name="update"
            ).start()
            from ...crafting import itemsearch

            itemsearch.warm_up()
        if not _online.get("fb_retry"):
            _online["fb_retry"] = True
            from ...system import feedback_up

            threading.Thread(
                target=lambda: feedback_up.retry_pending(_sys._fb_dir()),
                daemon=True,
                name="feedback-retry",
            ).start()
        if settings.load().get("live_on"):
            self.live.start()
        try:
            from ...core import perf

            threading.Thread(
                target=perf.rapidocr, daemon=True, name="ocr-warmup"
            ).start()
        except Exception:
            pass
        try:
            from ...core.perfmon import monitor

            monitor.start()
        except Exception:
            pass

    def stop_all(self):
        """退出时停线程（原来 server.main() 结尾 finally 里的那几步，原样搬来）"""
        try:
            self.live.stop_ev.set()
            self.nav.stop_ev.set()
            from ...system import gpu_ocr

            gpu_ocr.shutdown()
        except Exception:
            pass
