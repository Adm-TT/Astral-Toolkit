"""后台服务生命周期：统一起停、按阶段收尾、给出停止报告（RT-B6 提交 1）

阶段（0–5）：
0 CLOSING       正在退出
1 SESSIONS      live / nav / count
2 AMBIENT       hover / pos / logwatch / game_events
3 WORKERS       update / 预热 / perfmon / miss 截图（提交 2）
4 HTTP_WRITES   HTTP 在途写（提交 2）
5 FINAL         展示流 / HTTP
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, NamedTuple, Protocol, runtime_checkable


class Phase(IntEnum):
    CLOSING = 0
    SESSIONS = 1
    AMBIENT = 2
    WORKERS = 3
    HTTP_WRITES = 4
    FINAL = 5


@runtime_checkable
class ManagedService(Protocol):
    name: str
    phase: Phase

    def start(self) -> None: ...

    def request_stop(self) -> None: ...

    def join(self, timeout: float | None) -> bool: ...


class StopRecord(NamedTuple):
    """一个服务的停止结果。join 返回 True 表示已经退出。"""

    name: str
    phase: Phase
    ok: bool
    still_alive: bool
    error: str
    secs: float


@dataclass
class StopReport:
    """stop_all 的结果；records 顺序就是实际 request_stop / join 的顺序"""

    records: list[StopRecord] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def items(self) -> list[StopRecord]:
        return self.records

    @property
    def entries(self) -> list[StopRecord]:
        return self.records

    @property
    def ok(self) -> bool:
        return all(record.ok for record in self.records)

    @property
    def still_alive(self) -> list[StopRecord]:
        return [record for record in self.records if record.still_alive]

    @property
    def still_alive_count(self) -> int:
        return sum(1 for record in self.records if record.still_alive)

    @property
    def success_count(self) -> int:
        return sum(1 for record in self.records if record.ok)

    @property
    def summary(self) -> str:
        return (
            f"退出完成：{len(self.records)} 项，{self.success_count} 成功，"
            f"{self.still_alive_count} 仍存活，用时 {self.elapsed:.1f} s"
        )

    def __iter__(self) -> Iterator[StopRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)


def _write_run_record(text: str) -> None:
    """写运行记录；测试会替换这个函数，生产环境任何异常都不影响退出"""
    try:
        from ..core import run_records

        run_records.record("SYSTEM", text, ui_tag="SYS")
    except Exception:
        pass


def _emit_report(report: StopReport) -> None:
    for record in report.records:
        state = (
            "仍存活" if record.still_alive else ("已停止" if record.ok else "有错误")
        )
        detail = (
            f"phase={int(record.phase)} still_alive={record.still_alive} "
            f"secs={record.secs:.2f}s"
        )
        if record.error:
            detail += f"；{record.error}"
        _write_run_record(f"退出：{record.name} {state}（{detail}）")
    _write_run_record(report.summary)


class ServiceThread:
    """while 型服务外壳：target 自己负责循环；给了 interval 时把它当 run_once 反复调用"""

    def __init__(
        self,
        name: str,
        phase: Phase,
        target: Callable[..., None],
        *,
        interval: float | None = None,
        daemon: bool = True,
    ) -> None:
        self.name = name
        self.phase = phase
        self._target = target
        self._interval = interval
        self._daemon = daemon
        self._stop_ev = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_ev.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=self._daemon, name=self.name
        )
        self._thread.start()

    def _run(self) -> None:
        if self._interval is None:
            self._target(self._stop_ev)
            return
        while not self._stop_ev.is_set():
            self._target()
            if self._stop_ev.wait(float(self._interval)):
                break

    def request_stop(self) -> None:
        self._stop_ev.set()

    def join(self, timeout: float | None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()


class OneShot:
    """一次性后台任务；request_stop 空操作，join 等线程，未起过也算已结束"""

    def __init__(
        self,
        name: str,
        phase: Phase,
        thread: threading.Thread | None = None,
        *,
        factory: Callable[[], threading.Thread | None] | None = None,
    ) -> None:
        self.name = name
        self.phase = phase
        self._thread = thread
        self._factory = factory
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        thread = self._thread
        if thread is None and self._factory is not None:
            thread = self._factory()
            self._thread = thread
        if thread is not None and thread.ident is None:
            thread.start()

    def request_stop(self) -> None:
        return None

    def join(self, timeout: float | None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()


class SessionLoopService:
    """SessionLoop 的服务外壳：request_shutdown + join_all"""

    def __init__(
        self,
        name: str,
        phase: Phase,
        loop: Any,
        *,
        start: Callable[[], Any] | None = None,
    ) -> None:
        self.name = name
        self.phase = phase
        self._loop = loop
        self._start = start
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._start is not None:
            self._start()

    def request_stop(self) -> None:
        self._loop.request_shutdown()

    def join(self, timeout: float | None) -> bool:
        left = float("inf") if timeout is None else max(0.0, float(timeout))
        result = self._loop.join_all(left)
        if isinstance(result, bool):
            return result
        return not result


class Lifecycle:
    """所有后台服务的总管：登记、按登记顺序启动、按阶段停止"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_lock = threading.Lock()
        self._closing = threading.Event()
        self._services: list[
            tuple[ManagedService, Callable[[], bool] | bool | None]
        ] = []
        self._stop_report: StopReport | None = None

    @property
    def closing(self) -> bool:
        return self._closing.is_set()

    def is_closing(self) -> bool:
        return self._closing.is_set()

    def register(
        self,
        service: ManagedService,
        gate: Callable[[], bool] | bool | None = None,
    ) -> None:
        """gate 只决定 start_all 是否自动启动；停止始终按登记表走"""
        with self._lock:
            self._services.append((service, gate))

    def start_all(self) -> bool:
        """按登记顺序启动；开头和每项前查 closing。返回是否完整走完"""
        if self.is_closing():
            return False
        with self._lock:
            services = list(self._services)
        for service, gate in services:
            if self.is_closing():
                return False
            if gate is not None:
                try:
                    allowed = gate() if callable(gate) else bool(gate)
                except Exception as exc:
                    _write_run_record(f"启动门失败：{service.name}：{exc!r}")
                    continue
                if not allowed:
                    continue
            try:
                service.start()
            except Exception as exc:
                _write_run_record(f"启动失败：{service.name}：{exc!r}")
        return True

    def stop_all(self, budget: float = 5.0) -> StopReport:
        """先置 closing；逐阶段“全部 request_stop → 按登记顺序 join”。幂等"""
        self._closing.set()
        with self._stop_lock:
            if self._stop_report is not None:
                return self._stop_report

            started = time.monotonic()
            deadline = started + max(0.0, float(budget))
            with self._lock:
                services = list(self._services)

            records: list[StopRecord] = []
            for phase in Phase:
                batch = [
                    (service, gate)
                    for service, gate in services
                    if int(service.phase) == int(phase)
                ]
                if not batch:
                    continue

                stop_at: dict[int, float] = {}
                errors: dict[int, str] = {}
                for index, (service, _gate) in enumerate(batch):
                    stop_at[index] = time.monotonic()
                    try:
                        service.request_stop()
                    except Exception as exc:
                        errors[index] = f"request_stop: {exc!r}"

                for index, (service, _gate) in enumerate(batch):
                    remaining = max(0.0, deadline - time.monotonic())
                    error = errors.get(index, "")
                    try:
                        exited = bool(service.join(remaining))
                    except Exception as exc:
                        exited = False
                        part = f"join: {exc!r}"
                        error = f"{error}；{part}" if error else part
                    if not exited:
                        try:
                            detail = getattr(service, "last_error", "")
                        except Exception:
                            detail = ""
                        if detail:
                            part = str(detail)
                            error = f"{error}；{part}" if error else part
                    secs = time.monotonic() - stop_at.get(index, started)
                    records.append(
                        StopRecord(
                            name=service.name,
                            phase=phase,
                            ok=exited and not error,
                            still_alive=not exited,
                            error=error,
                            secs=secs,
                        )
                    )

            report = StopReport(records, time.monotonic() - started)
            self._stop_report = report
            _emit_report(report)
            return report


__all__ = [
    "Lifecycle",
    "ManagedService",
    "OneShot",
    "Phase",
    "ServiceThread",
    "SessionLoopService",
    "StopRecord",
    "StopReport",
]
