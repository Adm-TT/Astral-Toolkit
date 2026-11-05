"""RT-B6 提交 2：HTTP 在途写计数服务。

鉴权通过、长度合法、路径为 /api/* 的 POST 在开始读 body 前登记；退出时等计数归零。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ..runtime.lifecycle import Phase


class HttpWritesService:
    """记录 /api/* POST 的在途数量；退出时等它们归零。"""

    name = "http-writes"
    phase = Phase.HTTP_WRITES

    def __init__(self, closing: Callable[[], bool] | None = None) -> None:
        self._cond = threading.Condition(threading.RLock())
        self._active: dict[str, int] = {}
        self._closing = closing
        self.last_error = ""

    def bind_closing(self, closing: Callable[[], bool] | None) -> None:
        with self._cond:
            self._closing = closing

    def _is_closing(self) -> bool:
        closing = self._closing
        if closing is None:
            from .lifecycle_gate import is_closing

            return is_closing()
        try:
            return bool(closing())
        except Exception:
            return False

    def try_begin_write(self, name: str) -> bool:
        """判 closing 和计数 +1 在同一把锁里。"""
        name = str(name or "?")
        with self._cond:
            if self._is_closing():
                return False
            self._active[name] = self._active.get(name, 0) + 1
            self.last_error = ""
            return True

    def end_write(self, name: str) -> None:
        name = str(name or "?")
        with self._cond:
            count = self._active.get(name, 0) - 1
            if count > 0:
                self._active[name] = count
            else:
                self._active.pop(name, None)
            self._cond.notify_all()

    @property
    def active_count(self) -> int:
        with self._cond:
            return sum(self._active.values())

    def _format_error(self) -> str:
        parts = [f"{name}×{count}" for name, count in sorted(self._active.items())]
        return "在途写未结束：" + "，".join(parts)

    def start(self) -> None:
        return None

    def request_stop(self) -> None:
        return None

    def join(self, timeout: float | None) -> bool:
        deadline = (
            None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        )
        with self._cond:
            while self._active:
                if deadline is None:
                    self._cond.wait()
                    continue
                left = deadline - time.monotonic()
                if left <= 0:
                    self.last_error = self._format_error()
                    return False
                self._cond.wait(left)
            self.last_error = ""
            return True


WRITES = HttpWritesService()

__all__ = ["HttpWritesService", "WRITES"]
