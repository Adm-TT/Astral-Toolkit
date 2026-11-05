"""库存盘点读屏（_Count）

会话循环只管线程、暂停、计时、停止和输出通道；这里只写盘点的「一轮」：
读光标、认物品、记格子、出新格 HUD、收尾时算对账。

2026-10-30 重构阶段 4 删了 services.py，用到的任务模块运行时才取，避免互相 import：
_T("mining").xxx = tasks/mining.py，_H().xxx = app/hud_state.py，
_T("count")._read_item / _count_review = tasks/count.py。
"""

from __future__ import annotations

import importlib
import sys
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from ...runtime.results import ResultStore
from ...runtime.session import SessionLoop, StopInfo, Tick
from ..output import BusOutput

WIN = sys.platform == "win32"
REVIEW = "count.review"


def _T(name):
    """astral_toolkit.tasks 里的模块（运行时才取，避免互相 import）"""
    return importlib.import_module(f"astral_toolkit.tasks.{name}")


def _H():
    from .. import hud_state

    return hud_state


def _foreground():
    """游戏在不在最前面：判断不了返回 None，照常跑"""
    return _T("mining")._game_front()


def _hotkey_now():
    """收尾提示里的热键名；只在锁外调用"""
    try:
        return _T("navigation").settings_key("count_key", "F6")
    except Exception:
        return "F6"


def _win_cursor_pos() -> tuple[int, int]:
    """读一次 Windows 光标位置；导入本模块时不碰 Win32"""
    import ctypes
    from ctypes import wintypes

    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def _key(r):  # 制造出来的同名东西，各槽品质不一样就分开记
    return (
        (r["en"] or r["zh"]),
        r["quality"],
        r["unit"],
        tuple(x["q"] for x in r.get("craft") or []),
    )


def _hud_text(place, items) -> str:
    """悬浮窗里的盘点文字：最近 8 项，品质为空时不带 Q"""
    lines = [f"盘点｜{place}"]
    for v in list(items.values())[-8:]:
        q = "" if v["quality"] is None else f" Q{v['quality']}"
        lines.append(
            f"{v['zh'] or v['en']}{q} ×{v['cells']}  "
            f"{_T('hover').qty_text(v['qty'], v['unit'])}"
        )
    return "\n".join(lines)


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

    def __init__(self, cursor_pos: Callable[[], tuple[int, int]] | None = None) -> None:
        self._cursor_pos = cursor_pos or _win_cursor_pos

    def hotkey(self) -> str:
        return _hotkey_now()

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
        return _CountCtx()

    def tick(self, session: Any, ctx: _CountCtx, now: float) -> Tick:
        pos = self._cursor_pos()
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

        from ...mining.screen import grab
        from ...trade import console as C

        img = grab()
        cursor = C._cursor_on_image(img)
        try:
            r = _T("count")._read_item(img, cursor)
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
        self.loop.commit(
            session, ("hud.set", "盘点", _hud_text(session.payload, ctx.items))
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
            review = _T("count")._count_review(place, items) if items else None
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
        return None


class _Count:
    """兼容外壳（RT-B7 删）：对外接口照旧，里面换成会话循环"""

    IDLE_CLOSE = 60
    STILL = 0.35

    def __init__(
        self,
        results=None,
        output=None,
        *,
        clock=None,
        closing=None,
        foreground=None,
        cursor_pos=None,
        worker=None,
        join_timeout=3.0,
        _loop_factory=None,
    ):
        self._start_lock = threading.Lock()
        self._last_place = ""
        self._worker = worker if worker is not None else _CountWorker(cursor_pos)
        factory = _loop_factory or SessionLoop
        self.loop = factory(
            self._worker,
            results=results or ResultStore(),
            output=output or BusOutput(),
            foreground=foreground or _foreground,
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
        from ..lifecycle_gate import closing_error

        refused = closing_error()
        if refused:
            return refused
        with self._start_lock:
            if not WIN or self.running():
                return {"running": self.running()}
            from ...crafting import stockplaces as SP

            here = SP.current_place()
            place = (
                here["label"]
                if here
                else _T("stock")._place_of(
                    _T("trade").trade().db.get("last_location", "") or ""
                )[0]
            )
            if not place:
                _H()._note_hud("盘点", "盘点：当前位置未知｜先在游戏中打开一次库存")
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
