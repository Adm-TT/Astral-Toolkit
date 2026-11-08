"""库存盘点读屏（_Count；目录迁移 R5 从 app/engines/count 搬来）

会话循环只管线程、暂停、计时、停止和输出通道；这里只写盘点的「一轮」：
读光标、认物品、记格子、出新格 HUD、收尾时算对账。

目录迁移 R5（2026-11-07）：外面的东西都由 bootstrap 接进来，本模块不再经 _T / _H 动态去 tasks、app 取——
一轮要用的分析（analysis：光标在截图上的哪儿、认鼠标指着的物品、收尾时和账上对；tasks/count_analysis 原样转给
trade/inspector、tasks/count）、悬浮窗文字（views：app/presenters/count）、外面的东西（CountLinks：读光标、抓图、
游戏在不在前台、热键名、调试图目录、开始时在哪个地点、悬浮窗短提示、正在退出时不让开始）。
"""

from __future__ import annotations

import sys
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..results import ResultStore
from ..session import SessionLoop, StopInfo, Tick

REVIEW = "count.review"


class CountAnalysis(Protocol):
    """盘点一轮要用的分析（tasks/count_analysis 实现，调用时才去取）"""

    def cursor_on_image(self, img: Any) -> Any:
        """光标在这张截图上的位置"""
        ...

    def read_item(self, img: Any, cursor: Any) -> Any:
        """鼠标指着的物品：{zh, en, quality, qty, unit, sure, craft}；认不出是 None"""
        ...

    def review(self, place: Any, items: Any) -> Any:
        """这轮看到的和账上对：{rows, missing, ...}"""
        ...


@dataclass(frozen=True)
class CountViews:
    """盘点要的排版（app/presenters/count）"""

    # 悬浮窗里的盘点文字：(地点, 这轮记下的物品) → 文字
    hud_text: Callable[[Any, Any], str]


@dataclass(frozen=True)
class CountLinks:
    """盘点线程要的外面的东西（bootstrap 接）"""

    # 读一次光标位置 (x, y)（infrastructure/platform/cursor）
    cursor_pos: Callable[[], tuple[int, int]]
    # 抓一张游戏画面（mining/screen.grab）
    grab: Callable[[], Any]
    # 游戏在不在最前面：True / False，判断不了是 None（tasks/mining）
    foreground: Callable[[], bool | None]
    # 收尾提示里的热键名（设置里的盘点键，读不了就是 F6）；只在锁外调用
    hotkey: Callable[[], str]
    # 这次盘点的调试图放进同一个时间戳目录：开始时绑、结束时解（trade/debug_shots，线程本地）
    debug_bind: Callable[[], None]
    debug_unbind: Callable[[], None]
    # 开始盘点时在哪个库存地点（不知道是空字符串）
    place_now: Callable[[], str]
    # 悬浮窗短提示：(分区, 文字)（app/hud_state）
    note: Callable[[str, str], None]
    # 正在退出时不让开始：要回的错误；不拦是 None（app/lifecycle_gate）
    refuse: Callable[[], dict[str, str] | None]


def _key(r):  # 制造出来的同名东西，各槽品质不一样就分开记
    return (
        (r["en"] or r["zh"]),
        r["quality"],
        r["unit"],
        tuple(x["q"] for x in r.get("craft") or []),
    )


@dataclass
class _CountCtx:
    """一次盘点的全部可变状态：线程重启也换一份新的"""

    items: dict = field(default_factory=dict)
    cells: set = field(default_factory=set)
    prev_pos: tuple[int, int] | None = None
    still_since: float = 0.0
    done_pos: tuple[int, int] | None = None
    tries: int = 0
    logged: str | None = None


class _CountWorker:
    """盘点 Worker：只写业务，不碰线程"""

    name = "count"
    log_tag = "COUNT"
    display_name = "盘点"
    retries = 1
    idle_close: float | None = 60.0
    stale_after: dict[str, float] = {}
    needs_foreground = True
    pause_wait = 0.25
    restart_while_stopping = False
    STILL = 0.35
    loop: Any = None

    def __init__(
        self, analysis: CountAnalysis, views: CountViews, links: CountLinks
    ) -> None:
        self._an = analysis
        self._views = views
        self._links = links

    def hotkey(self) -> str:
        return self._links.hotkey()

    def start_ops(self, session: Any) -> list[tuple[Any, ...]]:
        place = session.payload
        return [
            ("shared", REVIEW, None),
            ("hud.set", "盘点", f"盘点｜{place}"),
            ("record", "COUNT", "触发 F6 盘点", "COUNT"),
            ("bus", "count", {"running": True, "place": place}),
        ]

    def stop_ops(self, session: Any, info: StopInfo) -> list[tuple[Any, ...]]:
        if info.reason in ("user", "shutdown"):
            return [("record", "COUNT", "F6 盘点结束", "COUNT")]
        return []

    def setup(self, session: Any) -> _CountCtx:
        # 调试图：这次盘点的识别都放进同一个时间戳目录（线程本地，setup / teardown 都在会话线程上跑）
        self._links.debug_bind()
        return _CountCtx()

    def tick(self, session: Any, ctx: _CountCtx, now: float) -> Tick:
        pos = self._links.cursor_pos()
        if pos != ctx.prev_pos:
            ctx.prev_pos, ctx.still_since = pos, now
            if (
                ctx.done_pos is not None
                and abs(pos[0] - ctx.done_pos[0]) + abs(pos[1] - ctx.done_pos[1]) > 8
            ):
                ctx.done_pos, ctx.tries = None, 0
            return Tick(0.1)

        if now - ctx.still_since < self.STILL or ctx.done_pos == pos:
            return Tick(0.1)

        img = self._links.grab()
        cursor = self._an.cursor_on_image(img)
        try:
            r = self._an.read_item(img, cursor)
        except Exception as e:
            r = None
            if repr(e) != ctx.logged:
                # 同一种错只记一次：以前吞掉，认不出时日志里看不到原因
                ctx.logged = repr(e)
                self.loop.commit(
                    session,
                    ("log", f"盘点识别出错：{e!r}", "COUNT", "ERROR"),
                )

        ctx.tries += 1
        if r is None or (r["unit"] == "SCU" and not r["qty"]) or not r["sure"]:
            if ctx.tries >= 3:
                ctx.done_pos = pos  # 停在这里认了 3 次都没认出：等鼠标挪开
            return Tick(0.3)

        ctx.done_pos, ctx.tries = pos, 0
        # 同一格重复认到也算「看到」，要在去重之前刷新 60 秒计时
        seen = {"item": now}
        W, H = img.size
        cell = (
            _key(r),
            r["qty"],
            round(cursor[0] / (W * 0.065)),
            round(cursor[1] / (H * 0.11)),
        )
        if cell in ctx.cells:
            return Tick(0.0, seen)

        ctx.cells.add(cell)
        v = ctx.items.setdefault(
            _key(r),
            {
                "zh": r["zh"],
                "en": r["en"],
                "quality": r["quality"],
                "unit": r["unit"],
                "qty": 0,
                "cells": 0,
                "craft": r.get("craft"),
            },
        )
        v["qty"] = round(v["qty"] + r["qty"], 6)
        v["cells"] += 1
        # activity=False：轮询改字不刷新悬浮窗 30 秒空闲计时，也不把已隐藏的再弹出来
        self.loop.commit(
            session,
            (
                "hud.set",
                "盘点",
                self._views.hud_text(session.payload, ctx.items),
                False,
            ),
        )
        return Tick(0.0, seen)

    def on_pause(self, session: Any, ctx: _CountCtx) -> list[tuple[Any, ...]]:
        return []

    def on_resume(
        self, session: Any, ctx: _CountCtx, gap: float
    ) -> list[tuple[Any, ...]]:
        return []

    def on_stale(
        self, session: Any, ctx: _CountCtx, channel: str
    ) -> list[tuple[Any, ...]]:
        return []

    def on_error(self, session: Any, ctx: _CountCtx | None, exc: BaseException) -> None:
        if sys.stderr is None:
            return
        try:
            # 打包版里 stderr 就是 app_log.txt，和现在线程崩溃时 Python 打的一样
            print("盘点出错：", file=sys.stderr)
            traceback.print_exception(
                type(exc), exc, exc.__traceback__, file=sys.stderr
            )
        except Exception:
            pass

    def before_retry(
        self, session: Any, ctx: _CountCtx | None, error: str
    ) -> list[tuple[Any, ...]]:
        return []

    def finish(
        self, session: Any, ctx: _CountCtx | None, info: StopInfo
    ) -> list[tuple[Any, ...]]:
        place = session.payload
        items = ctx.items if ctx is not None else {}
        ops: list[tuple[Any, ...]] = [("hud.clear", "盘点")]
        try:
            review = self._an.review(place, items) if items else None
        except Exception as e:
            review = None
            ops.append(("bus", "log", {"task": "count", "line": f"盘点对账失败：{e}"}))

        ops.append(("shared", REVIEW, review))
        if review:
            n = len([r for r in review["rows"] if r["delta"]]) + len(review["missing"])
            text = (
                f"盘点结束｜{n} 处不一致，需在 AT 中确认" if n else "盘点结束｜数量一致"
            )
            ops.append(("note", "盘点", text, 8))
        else:
            k = info.hotkey or self.hotkey()
            ops.append(("note", "盘点", f"盘点结束｜未识别到物品｜按 {k} 重新开始", 8))
        ops.append(("bus", "count", {"running": False, "review": review}))
        return ops

    def teardown(self, session: Any, ctx: _CountCtx | None) -> None:
        self._links.debug_unbind()


class _Count:
    """兼容外壳（RT-B7 删）：对外接口照旧，里面换成会话循环。
    output、analysis、views、links、enabled（只有 Windows 能开始）都由 bootstrap 给；worker 给了就用给的（测试）"""

    IDLE_CLOSE = 60
    STILL = 0.35

    def __init__(
        self,
        results=None,
        *,
        output,
        analysis,
        views,
        links,
        enabled,
        clock=None,
        closing=None,
        worker=None,
        join_timeout=3.0,
        _loop_factory=None,
    ):
        self._start_lock = threading.Lock()
        self._last_place = ""
        self._links = links
        self._enabled = enabled
        self._worker = (
            worker if worker is not None else _CountWorker(analysis, views, links)
        )
        factory = _loop_factory or SessionLoop
        self.loop = factory(
            self._worker,
            results=results or ResultStore(),
            output=output,
            foreground=links.foreground,
            clock=clock,
            join_timeout=join_timeout,
            closing=closing or (lambda: False),
        )
        self._worker.loop = self.loop

    def running(self):
        return bool(self.loop.running())

    @property
    def place(self):
        return self._last_place

    @property
    def review(self):
        return self.loop.shared_get(REVIEW)

    @review.setter
    def review(self, value):
        self.loop.shared_set(REVIEW, value)

    def take_review(self):
        return self.loop.shared_take(REVIEW)

    def hotkey(self):
        return self._worker.hotkey()

    def start(self):
        refused = self._links.refuse()
        if refused:
            return refused
        with self._start_lock:
            if not self._enabled or self.running():
                return {"running": self.running()}
            place = self._links.place_now()
            if not place:
                self._links.note("盘点", "盘点：当前位置未知｜先在游戏中打开一次库存")
                return {"error": "当前位置未知：先在游戏中打开一次库存"}
            sid = self.loop.start(place)
            if sid is None:
                return {"running": self.running()}
            self._last_place = place
            return {"running": True, "place": place}

    def stop(self):
        sid = self.loop.request_stop_current(StopInfo("user", hotkey=self.hotkey()))
        if sid is not None:
            self.loop.join(session_id=sid)
        return {"running": False}
