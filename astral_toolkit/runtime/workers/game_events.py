"""读游戏日志里的量子、管辖区、禁火区、重生事件的附属线程（2026-10-27；目录迁移 R2 从 app/engines/nav._GameEvents 搬来）：
每 0.5 秒看一次新事件，记下每种最近一次，推给窗口；量子一到就调注入的回调（让定位马上读一次）。
读日志（system/gamelog.EventTail，线程开始时才造）、推窗口（总线「gamelog」）、是不是 Windows 都由 bootstrap 接进来。
"""

import threading
import time
from typing import Any, Callable


class GameEventsWorker:
    """tail：线程开始时调一次，造读日志的东西（有 poll() → [(时间, 种类, 值)]）；publish：推一条事件给窗口；
    enabled：只有 Windows 起线程；on_qt_arrived：量子到达时调（出错不退）"""

    def __init__(
        self,
        tail: Callable[[], Any],
        publish: Callable[[dict[str, Any]], Any],
        *,
        enabled: bool,
        on_qt_arrived: Callable[[], None] | None = None,
    ) -> None:
        self.thread: threading.Thread | None = None
        self.last: dict[str, tuple[float, Any]] = {}
        self.arrived_at: float = 0.0
        self.stop_ev = threading.Event()
        self.on_qt_arrived = on_qt_arrived
        self._tail = tail
        self._publish = publish
        self._enabled = enabled

    def start(self) -> None:
        if self._enabled and (self.thread is None or not self.thread.is_alive()):
            self.stop_ev.clear()
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="game-events"
            )
            self.thread.start()

    def request_stop(self) -> None:
        self.stop_ev.set()

    def join(self, timeout: float | None = None) -> bool:
        thread = self.thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        tail = self._tail()
        while not self.stop_ev.is_set():
            try:
                for t, k, v in tail.poll():
                    self.last[k] = (t, v)
                    if k == "qt_arrived":
                        self.arrived_at = time.time()
                        if self.on_qt_arrived is not None:
                            try:
                                self.on_qt_arrived()
                            except Exception:
                                pass
                    self._publish({"kind": k, "value": v, "t": t})
            except Exception:
                pass
            if self.stop_ev.wait(0.5):
                break
