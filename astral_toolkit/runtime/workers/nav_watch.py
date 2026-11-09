"""导航的两个小后台会话（2026-11-09 从 tasks/navigation 自己起的 daemon 线程搬来）：

- halo：挂着小行星带方案时每 0.3 秒核对一次（读右上角实时坐标、剪贴板里的 /showlocation）；
  方案取下或换了就自己结束；
- here：点了「用当前位置新建」后等剪贴板出现 /showlocation 坐标，存好或超时就自己结束。

线程、停止、退出时等线程退都交给 SessionLoop（和导航、采矿、盘点一样，退出时由 lifecycle 停；正在退出时不再开新的）。
每一轮做什么还在 tasks/navigation，由 bootstrap 接成 WatchSteps 传进来，本模块不 import tasks。
输出（悬浮窗、导航日志、总线）照旧由那几个函数自己发：它们按 _HALO 的方案代次 / _HERE 的名字判断结果还算不算，
不走 loop.commit（这两个会话没有活动磁贴、没有「已停止」提示：stop_ops 都是空的）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..results import ResultStore
from ..session import RunState, Session, SessionLoop, StopInfo, Tick


@dataclass(frozen=True)
class WatchSteps:
    """一个小后台每一轮做什么（bootstrap 接 tasks/navigation 的函数）

    Attributes:
        setup: setup(payload) → 这次会话的状态（会话开始时在工作线程里调一次）
        step: step(payload, state) → True 表示做完了（会话自己结束），False 接着下一轮
        wait: 两轮之间等多久（秒）；停止时立刻醒
    """

    setup: Callable[[Any], Any]
    step: Callable[[Any, Any], bool]
    wait: float


class _WatchWorker:
    """SessionLoop 的 Worker：只转调 WatchSteps；step 说做完了就按 done 停掉自己这个会话"""

    retries: int = 3
    stale_after: dict[str, float] = {}
    needs_foreground: bool = (
        False  # 游戏不在前台也照样核对 / 等坐标（以前的线程就不管前台）
    )
    restart_while_stopping: bool = (
        True  # 换方案时旧的一轮卡住了也能开新的（旧结果按方案代次作废）
    )
    log_tag: str = "NAV"
    loop: Any = None

    def __init__(self, name: str, display_name: str, steps: WatchSteps) -> None:
        self.name = name
        self.display_name = display_name
        self._steps = steps

    @property
    def idle_close(self) -> float | None:
        return None

    @property
    def pause_wait(self) -> float:
        return self._steps.wait

    def hotkey(self) -> str:
        return ""

    def start_ops(self, session: Session) -> list[tuple[Any, ...]]:
        return []

    def stop_ops(
        self, session: Session | None, info: StopInfo
    ) -> list[tuple[Any, ...]]:
        return []

    def setup(self, session: Session) -> Any:
        return self._steps.setup(session.payload)

    def tick(self, session: Session, ctx: Any, now: float) -> Tick:
        if self._steps.step(session.payload, ctx):
            self.loop.request_stop(session, StopInfo("done"))
            return Tick(0.0)
        return Tick(self._steps.wait)

    def on_pause(self, session: Session, ctx: Any) -> list[tuple[Any, ...]]:
        return []

    def on_resume(
        self, session: Session, ctx: Any, gap: float
    ) -> list[tuple[Any, ...]]:
        return []

    def on_stale(
        self, session: Session, ctx: Any, channel: str
    ) -> list[tuple[Any, ...]]:
        return []

    def on_error(self, session: Session, ctx: Any, exc: BaseException) -> None:
        return None

    def before_retry(
        self, session: Session, ctx: Any, error: str
    ) -> list[tuple[Any, ...]]:
        return []

    def finish(
        self, session: Session, ctx: Any, info: StopInfo
    ) -> list[tuple[Any, ...]]:
        return []

    def teardown(self, session: Session, ctx: Any) -> None:
        return None


class NavWatch:
    """一个小后台的起停外壳：start 开（同一份 payload 已经在跑就是它）、replace 换一份；
    loop 交给 lifecycle（SessionLoopService），退出时按会话停、等线程退"""

    def __init__(
        self,
        name: str,
        display_name: str,
        steps: WatchSteps,
        *,
        results: ResultStore,
        output: Any,
        closing: Callable[[], bool] | None = None,
        clock: Callable[[], float] | None = None,
        join_timeout: float = 2.0,
    ) -> None:
        self._closing = closing if closing is not None else (lambda: False)
        self._worker = _WatchWorker(name, display_name, steps)
        self.loop: Any = SessionLoop(
            self._worker,
            results=results,
            output=output,
            foreground=lambda: True,
            clock=clock,
            join_timeout=join_timeout,
            closing=self._closing,
        )

    def running(self) -> bool:
        """会话在跑（做完了、在收尾的不算）"""
        return bool(self.loop.running())

    def start(self, payload: Any = None) -> int | None:
        """开会话；同一份 payload 已经在跑就是它。上一个刚做完、线程还在收尾：等它退了再开。
        正在退出（或换不下来）返回 None"""
        sid = self.loop.start(payload)
        if sid is None and not self._closing():
            st = self.loop.state()
            if st.state is RunState.STOPPING and st.session_id:
                self.loop.join(session_id=st.session_id)
                sid = self.loop.start(payload)
        return sid

    def replace(self, payload: Any) -> int | None:
        """换成新的一份：先停当前的（等它这一轮做完，一般不到 0.3 秒；超时也照样开新的），再开"""
        sid = self.loop.request_stop_current(StopInfo("replaced"))
        if sid is not None:
            self.loop.join(session_id=sid)
        return self.start(payload)
