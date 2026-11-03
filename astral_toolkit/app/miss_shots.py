"""RT-B6 提交 2：miss 截图单线程有界队列。

- 容量 4，满了丢新图并 runtime_log WARN，不阻塞识别
- 写 <name>.tmp 再 os.replace 成 .png
- 线程只在第一次有图要存时起
- request_stop 后不再收新图；join 预算内写完，超时记丢弃张数
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from ..runtime.lifecycle import Phase


class MissShotsService:
    name = "miss-shots"
    phase = Phase.WORKERS

    def __init__(self, capacity: int = 4) -> None:
        self.capacity = max(1, int(capacity))
        self._cond = threading.Condition()
        self._pending: deque[tuple[Path, str, Any, int]] = deque()
        self._thread: threading.Thread | None = None
        self._thread_done = True
        self._busy = False
        self._stopping = False
        self._abandoned = False
        self.dropped = 0
        self.last_error = ""

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    @property
    def queue_size(self) -> int:
        with self._cond:
            return len(self._pending)

    def start(self) -> None:
        return None

    def submit(self, directory: Path, stamp: str, img: Any, keep: int) -> bool:
        full = False
        with self._cond:
            if self._stopping or self._abandoned:
                self.dropped += 1
                return False
            if len(self._pending) >= self.capacity:
                self.dropped += 1
                full = True
            else:
                self._pending.append((directory, stamp, img, int(keep)))
                if self._thread is None or not self._thread.is_alive():
                    self._thread_done = False
                    self._thread = threading.Thread(
                        target=self._worker, daemon=True, name=self.name
                    )
                    self._thread.start()
                self._cond.notify()
                return True
        if full:
            from . import bus

            bus.runtime_log(
                f"miss 截图队列已满（容量 {self.capacity}），丢弃新图",
                tag="LIVE",
                level="WARN",
            )
        return False

    def request_stop(self) -> None:
        with self._cond:
            self._stopping = True
            self._cond.notify_all()

    def join(self, timeout: float | None) -> bool:
        deadline = (
            None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        )
        with self._cond:
            while not self._thread_done:
                if deadline is None:
                    self._cond.wait()
                    continue
                left = deadline - time.monotonic()
                if left <= 0:
                    queued = len(self._pending)
                    busy = 1 if self._busy else 0
                    if queued:
                        self.dropped += queued
                        self._pending.clear()
                    self._abandoned = True
                    self.last_error = f"miss 截图未写完：丢弃 {queued + busy} 张"
                    self._cond.notify_all()
                    return False
                self._cond.wait(left)
            self.last_error = ""
            return True

    def _worker(self) -> None:
        try:
            while True:
                with self._cond:
                    while (
                        not self._pending and not self._stopping and not self._abandoned
                    ):
                        self._cond.wait()
                    if self._abandoned:
                        if self._pending:
                            self.dropped += len(self._pending)
                            self._pending.clear()
                        self._thread_done = True
                        self._cond.notify_all()
                        return
                    if not self._pending:
                        self._thread_done = True
                        self._cond.notify_all()
                        return
                    directory, stamp, img, keep = self._pending.popleft()
                    self._busy = True
                try:
                    self._write(directory, stamp, img, keep)
                except Exception:
                    pass
                finally:
                    with self._cond:
                        self._busy = False
                        if self._abandoned:
                            if self._pending:
                                self.dropped += len(self._pending)
                                self._pending.clear()
                            self._thread_done = True
                            self._cond.notify_all()
                            return
                        self._cond.notify_all()
        finally:
            with self._cond:
                self._busy = False
                self._thread_done = True
                self._cond.notify_all()

    def _write(self, directory: Path, stamp: str, img: Any, keep: int) -> None:
        final = directory / f"{stamp}.png"
        tmp = directory / f"{stamp}.tmp"
        try:
            img.save(tmp, format="PNG")  # 后缀是 .tmp，PIL 按后缀认不出格式，要写明
            os.replace(tmp, final)
            files = sorted(directory.glob("*.png"), key=lambda f: f.stat().st_mtime)
            old_files = files[:-keep] if keep > 0 else files
            for old in old_files:
                old.unlink()
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass


__all__ = ["MissShotsService"]
