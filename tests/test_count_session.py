"""RT-B5a：盘点接会话循环（并发、停止重开、暂停计时、输出边界）"""

import io
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

from astral_toolkit import bootstrap
from astral_toolkit.app import lifecycle_gate
from astral_toolkit.runtime.workers import count as count_mod
from astral_toolkit.app.presenters import count as present_count
from astral_toolkit.crafting import stockplaces
from astral_toolkit.runtime.session import RunState, Session, StopInfo
from astral_toolkit.tasks import navigation
from tests import count_helpers
from tests.runtime_fakes import FakeClock, RecordingOutput

WAIT = 5.0


def _wait_until(predicate, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _wait_state(loop, state, timeout=WAIT):
    return _wait_until(lambda: loop.state().state is state, timeout)


def _moving_cursor():
    n = 0

    def cursor():
        nonlocal n
        n += 1
        return (n, 0)

    return cursor


def _patch_count_start(monkeypatch):
    monkeypatch.setattr(lifecycle_gate, "closing_error", lambda: None)
    monkeypatch.setattr(stockplaces, "current_place", lambda: {"label": "测试站"})
    monkeypatch.setattr(navigation, "settings_key", lambda key, default=None: default)


def _item():
    return {
        "zh": "铁矿",
        "en": "Iron",
        "quality": None,
        "unit": "个",
        "qty": 5,
        "sure": True,
        "craft": None,
    }


def _image():
    return SimpleNamespace(size=(1000, 1000))


class _CommitRecorder:
    def __init__(self):
        self.ops = []

    def commit(self, session, *ops):
        self.ops.extend(ops)
        return True


class _CountingLoop:
    """假 loop：只接一次 start；第二次如果真被调到时会让断言看到 start_calls=2"""

    def __init__(self):
        self.start_calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self._running = False
        self._lock = threading.Lock()

    def running(self):
        return self._running

    def start(self, payload):
        with self._lock:
            self.start_calls += 1
            n = self.start_calls
        if n == 1:
            self.entered.set()
            assert self.release.wait(WAIT)
            self._running = True
            return 1
        self._running = True
        return 2


def test_two_starts_only_one_session(monkeypatch):
    _patch_count_start(monkeypatch)
    loop = _CountingLoop()

    def factory(worker, **kwargs):
        return loop

    count = count_helpers.count(_loop_factory=factory)
    barrier = threading.Barrier(2)
    results = {}

    def run(i):
        barrier.wait(WAIT)
        try:
            results[i] = count.start()
        except Exception as exc:  # noqa: BLE001 —— 线程里的异常带回主线程看
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(2)]
    try:
        for thread in threads:
            thread.start()
        assert loop.entered.wait(WAIT)
        loop.release.set()
        for thread in threads:
            thread.join(WAIT)
        assert all(not thread.is_alive() for thread in threads)
        assert loop.start_calls == 1
        values = list(results.values())
        assert len(values) == 2
        assert not [v for v in values if isinstance(v, BaseException)]
        assert (
            sum(1 for v in values if isinstance(v, dict) and v.get("place") == "测试站")
            == 1
        )
        assert sum(1 for v in values if v == {"running": True}) == 1
    finally:
        loop.release.set()
        for thread in threads:
            thread.join(WAIT)


def test_stop_then_start_waits_for_old_finish(monkeypatch):
    _patch_count_start(monkeypatch)
    out = RecordingOutput()
    count = count_helpers.count(
        output=out,
        foreground=lambda: True,
        cursor_pos=_moving_cursor(),
        clock=FakeClock(),
    )
    out.bind(count.loop)
    original_finish = count._worker.finish
    entered = threading.Event()
    release = threading.Event()
    state = {"held": False, "calls": 0}

    def finish(session, ctx, info):
        state["calls"] += 1
        if not state["held"]:
            state["held"] = True
            entered.set()
            assert release.wait(WAIT)
        return original_finish(session, ctx, info)

    monkeypatch.setattr(count._worker, "finish", finish)
    try:
        assert count.start() == {"running": True, "place": "测试站"}
        assert _wait_state(count.loop, RunState.RUNNING)
        sid = count.loop.request_stop_current(StopInfo("user", hotkey="F6"))
        assert sid is not None
        assert entered.wait(WAIT)

        before = len(out.ops)
        assert count.start() == {"running": False}
        assert len(out.ops) == before, "停止中按 F6 不能再发一组开始输出"

        release.set()
        assert count.loop.join(WAIT, session_id=sid) is True
        assert count.loop.state().state is RunState.STOPPED
        assert state["calls"] == 1

        a_ops = [r.op for r in out.ops]
        assert sum(1 for op in a_ops if op[0] == "hud.clear" and "盘点" in op[1:]) == 1
        assert (
            sum(
                1
                for op in a_ops
                if op[0] == "note" and op[1] == "盘点" and "盘点结束" in op[2]
            )
            == 1
        )

        # B 的 start_ops 必须排在 A 的收尾之后
        count.loop.shared_set(count_mod.REVIEW, {"old": 1})
        mark = len(out.ops)
        assert count.start() == {"running": True, "place": "测试站"}
        assert _wait_state(count.loop, RunState.RUNNING)
        assert count.loop.shared_get(count_mod.REVIEW) is None
        new = [r.op for r in out.ops[mark:]]
        assert ("hud.set", "盘点", "盘点｜测试站") in new
        assert ("bus", "count", {"running": True, "place": "测试站"}) in new
        assert not [op for op in new if op[0] == "hud.clear"]
        assert not [op for op in new if op[0] == "note"]
    finally:
        release.set()
        if count.running():
            sid2 = count.loop.request_stop_current(StopInfo("user", hotkey="F6"))
            if sid2 is not None:
                count.loop.join(WAIT, session_id=sid2)
        count.loop.join_all(WAIT)


def test_idle_close_deducts_pause(monkeypatch):
    _patch_count_start(monkeypatch)
    clock = FakeClock()
    front = {"on": True}
    out = RecordingOutput()
    count = count_helpers.count(
        output=out,
        foreground=lambda: front["on"],
        cursor_pos=_moving_cursor(),
        clock=clock,
    )
    out.bind(count.loop)
    sid = None
    try:
        assert count.start() == {"running": True, "place": "测试站"}
        sid = count.loop.state().session_id
        assert _wait_state(count.loop, RunState.RUNNING)

        front["on"] = False
        assert _wait_state(count.loop, RunState.PAUSED)
        clock.advance(120.0)

        front["on"] = True
        assert _wait_state(count.loop, RunState.RUNNING)
        assert _wait_until(lambda: not count.loop.running(), timeout=0.2) is False, (
            "暂停的 120 秒不能算自动关闭"
        )

        clock.advance(59.0)
        assert _wait_until(lambda: not count.loop.running(), timeout=0.2) is False
        clock.advance(2.0)
        assert _wait_until(lambda: not count.loop.running(), timeout=WAIT)
        assert count.loop.join(WAIT, session_id=sid) is True
        assert count.loop.state().state is RunState.STOPPED
        assert count.loop.state().stop_reason == "idle"
        assert "F6 盘点结束" not in [op[2] for op in out.records() if len(op) > 2]
    finally:
        if count.running():
            sid2 = count.loop.request_stop_current(StopInfo("user", hotkey="F6"))
            if sid2 is not None:
                count.loop.join(WAIT, session_id=sid2)
        count.loop.join_all(WAIT)


def test_same_cell_refreshes_seen_but_hud_once(monkeypatch):
    from astral_toolkit.mining import screen
    from astral_toolkit.tasks import count as count_task
    from astral_toolkit.trade import inspector

    current = {
        "pos": (100, 100),
        "cursor": (100, 100),
        "result": _item(),
    }
    monkeypatch.setattr(screen, "grab", _image)
    monkeypatch.setattr(inspector, "_cursor_on_image", lambda img: current["cursor"])
    monkeypatch.setattr(count_task, "_read_item", lambda img, cursor: current["result"])
    monkeypatch.setattr(
        present_count,
        "hud_text",
        lambda place, items, qty_text: f"HUD {place} {len(items)}",
    )

    loop = _CommitRecorder()
    worker = count_helpers.worker(cursor_pos=lambda: current["pos"])
    worker.loop = loop
    session = SimpleNamespace(payload="测试站")
    ctx = worker.setup(session)

    assert worker.tick(session, ctx, 0.0).observed == {}
    first = worker.tick(session, ctx, 0.4)
    assert first.observed == {"item": 0.4}
    assert sum(1 for op in loop.ops if op[0] == "hud.set") == 1

    # 挪到同一格（曼哈顿距离 > 8，会解除 done_pos，但格号一样）
    current["pos"] = (101, 109)
    current["cursor"] = (101, 109)
    assert worker.tick(session, ctx, 0.5).observed == {}
    again = worker.tick(session, ctx, 1.0)
    assert again.observed == {"item": 1.0}
    assert sum(1 for op in loop.ops if op[0] == "hud.set") == 1

    # 光标在动：不算看到
    current["pos"] = (300, 300)
    current["cursor"] = (300, 300)
    assert worker.tick(session, ctx, 1.1).observed == {}

    # 认不出：也不算看到
    current["result"] = None
    assert worker.tick(session, ctx, 1.6).observed == {}


def test_review_runs_outside_loop_lock(monkeypatch):
    _patch_count_start(monkeypatch)
    from astral_toolkit.mining import screen
    from astral_toolkit.tasks import count as count_task
    from astral_toolkit.trade import inspector

    clock = FakeClock()
    out = RecordingOutput()
    current = {"pos": (100, 100), "cursor": (100, 100)}
    calls = []
    review = {
        "place": "测试站",
        "rows": [{"delta": 0}],
        "missing": [],
        "at": "",
        "revision": 0,
    }
    cursor_calls = {"n": 0}
    settled = threading.Event()

    def cursor():
        cursor_calls["n"] += 1
        if cursor_calls["n"] >= 2:
            settled.set()
        return (100, 100)

    monkeypatch.setattr(screen, "grab", _image)
    monkeypatch.setattr(inspector, "_cursor_on_image", lambda img: current["cursor"])
    monkeypatch.setattr(count_task, "_read_item", lambda img, cursor: _item())
    count = count_helpers.count(
        output=out,
        foreground=lambda: True,
        cursor_pos=cursor,
        clock=clock,
    )
    out.bind(count.loop)

    def fake_review(place, items):
        assert not count.loop.lock_held_by_me()
        calls.append((place, dict(items)))
        return review

    monkeypatch.setattr(count_task, "_count_review", fake_review)
    sid = None
    try:
        assert count.start() == {"running": True, "place": "测试站"}
        sid = count.loop.state().session_id
        assert _wait_state(count.loop, RunState.RUNNING)
        assert settled.wait(WAIT)
        clock.advance(0.4)
        assert _wait_until(lambda: sum(1 for r in out.ops if r.op[0] == "hud.set") >= 2)

        out.clear()
        assert count.stop() == {"running": False}
        assert calls and calls[0][0] == "测试站"
        assert count.review is review
        ops = [r.op for r in out.ops]
        assert ops[0] == ("hud.clear", "盘点")
        assert ops[1][0] == "note" and ops[1][3] == 8
        assert ops[2] == (
            "bus",
            "count",
            {"running": False, "review": review},
        )
    finally:
        if count.running():
            count.stop()
        if sid is not None:
            count.loop.join(WAIT, session_id=sid)


def test_start_ops_exact():
    worker = count_helpers.worker()
    session = Session(7, threading.Event(), "测试站")
    assert worker.start_ops(session) == [
        ("shared", count_mod.REVIEW, None),
        ("hud.set", "盘点", "盘点｜测试站"),
        ("record", "COUNT", "触发 F6 盘点", "COUNT"),
        ("bus", "count", {"running": True, "place": "测试站"}),
    ]


def test_location_unknown_only_note(monkeypatch):
    _patch_count_start(monkeypatch)
    from astral_toolkit.app import hud_state
    from astral_toolkit.tasks import stock, trade

    calls = []
    notes = []

    class _Loop:
        def running(self):
            return False

        def start(self, payload):
            calls.append(payload)
            return 1

    def factory(worker, **kwargs):
        return _Loop()

    monkeypatch.setattr(stockplaces, "current_place", lambda: None)
    monkeypatch.setattr(stock, "_place_of", lambda location: ("", None))
    monkeypatch.setattr(
        trade, "trade", lambda: SimpleNamespace(db={"last_location": ""})
    )
    monkeypatch.setattr(
        hud_state,
        "_note_hud",
        lambda section, text, *args, **kwargs: notes.append((section, text)),
    )

    count = count_helpers.count(_loop_factory=factory)
    assert count.start() == {
        "error": "当前位置未知：请到 AT 库存页选择盘点地点，或在游戏中打开一次库存",
        "need_place": True,
    }
    assert notes == [("盘点", "盘点：当前位置未知｜请到 AT 库存页选择盘点地点")]
    assert calls == []


def test_hud_text_last_eight_and_quality(monkeypatch):
    from astral_toolkit.tasks import hover

    monkeypatch.setattr(hover, "qty_text", lambda qty, unit: f"{qty}{unit}")
    items = {}
    for i in range(10):
        items[i] = {
            "zh": f"物{i}",
            "en": f"Item{i}",
            "quality": 3 if i == 8 else None,
            "unit": "个",
            "qty": i,
            "cells": 1,
        }

    lines = bootstrap._count_views().hud_text("测试站", items).splitlines()
    assert lines[0] == "盘点｜测试站"
    assert len(lines) == 9
    assert lines[1] == "物2 ×1  2个"
    assert "物8 Q3 ×1  8个" in lines
    assert lines[-1] == "物9 ×1  9个"


def test_error_log_deduplicates(monkeypatch):
    from astral_toolkit.mining import screen
    from astral_toolkit.tasks import count as count_task
    from astral_toolkit.trade import inspector

    current = {
        "pos": (100, 100),
        "cursor": (100, 100),
        "exc": RuntimeError("坏"),
    }
    monkeypatch.setattr(screen, "grab", _image)
    monkeypatch.setattr(inspector, "_cursor_on_image", lambda img: current["cursor"])

    def read(img, cursor):
        raise current["exc"]

    monkeypatch.setattr(count_task, "_read_item", read)
    loop = _CommitRecorder()
    worker = count_helpers.worker(cursor_pos=lambda: current["pos"])
    worker.loop = loop
    session = SimpleNamespace(payload="测试站")
    ctx = worker.setup(session)

    def tick(pos, now):
        current["pos"] = pos
        current["cursor"] = pos
        return worker.tick(session, ctx, now)

    err1 = current["exc"]
    tick((100, 100), 0.0)
    tick((100, 100), 0.4)
    tick((100, 100), 0.5)
    logs = [op for op in loop.ops if op[0] == "log"]
    assert len(logs) == 1
    assert logs[0] == (
        "log",
        f"盘点识别出错：{err1!r}",
        "COUNT",
        "ERROR",
    )

    tick((200, 200), 0.6)
    current["exc"] = ValueError("新")
    err2 = current["exc"]
    tick((200, 200), 1.0)
    logs = [op for op in loop.ops if op[0] == "log"]
    assert len(logs) == 2
    assert logs[1] == (
        "log",
        f"盘点识别出错：{err2!r}",
        "COUNT",
        "ERROR",
    )


def test_finish_notes_and_review_error(monkeypatch):
    from astral_toolkit.tasks import count as count_task

    worker = count_helpers.worker()
    session = SimpleNamespace(payload="测试站")
    ctx = count_mod._CountCtx()
    ctx.items = {"x": {}}
    impl = {"fn": lambda place, items: {}}
    monkeypatch.setattr(
        count_task, "_count_review", lambda place, items: impl["fn"](place, items)
    )

    mismatch = {"rows": [{"delta": 1}, {"delta": 0}], "missing": [{}]}
    impl["fn"] = lambda place, items: mismatch
    ops = worker.finish(session, ctx, StopInfo("user", hotkey="F7"))
    assert [op for op in ops if op[0] == "note"] == [
        ("note", "盘点", "盘点结束｜2 处不一致，需在 AT 中确认", 8)
    ]

    same = {"rows": [{"delta": 0}], "missing": []}
    impl["fn"] = lambda place, items: same
    ops = worker.finish(session, ctx, StopInfo("user", hotkey="F7"))
    assert [op for op in ops if op[0] == "note"] == [
        ("note", "盘点", "盘点结束｜数量一致", 8)
    ]

    def fail(place, items):
        raise AssertionError("空 ctx 不该算账")

    impl["fn"] = fail
    ops = worker.finish(session, None, StopInfo("idle", hotkey="F7"))
    assert ops == [
        ("hud.clear", "盘点"),
        ("shared", count_mod.REVIEW, None),
        ("note", "盘点", "盘点结束｜未识别到物品｜按 F7 重新开始", 8),
        ("bus", "count", {"running": False, "review": None}),
    ]

    def boom(place, items):
        raise RuntimeError("算账坏了")

    impl["fn"] = boom
    ops = worker.finish(session, ctx, StopInfo("user", hotkey="F7"))
    assert ops == [
        ("hud.clear", "盘点"),
        (
            "bus",
            "log",
            {"task": "count", "line": "盘点对账失败：算账坏了"},
        ),
        ("shared", count_mod.REVIEW, None),
        ("note", "盘点", "盘点结束｜未识别到物品｜按 F7 重新开始", 8),
        ("bus", "count", {"running": False, "review": None}),
    ]


def test_stop_ops_exact():
    worker = count_helpers.worker()
    end = [("record", "COUNT", "F6 盘点结束", "COUNT")]
    assert worker.stop_ops(None, StopInfo("user")) == end
    assert worker.stop_ops(None, StopInfo("shutdown")) == end
    assert worker.stop_ops(None, StopInfo("idle")) == []
    assert worker.stop_ops(None, StopInfo("error")) == []


def test_error_finish_and_traceback(monkeypatch):
    _patch_count_start(monkeypatch)
    from astral_toolkit.mining import screen

    clock = FakeClock()
    out = RecordingOutput()
    cursor_calls = {"n": 0}
    settled = threading.Event()

    def cursor():
        cursor_calls["n"] += 1
        if cursor_calls["n"] >= 2:
            settled.set()
        return (100, 100)

    def boom():
        raise RuntimeError("截图坏了")

    monkeypatch.setattr(screen, "grab", boom)
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    count = count_helpers.count(
        output=out,
        foreground=lambda: True,
        cursor_pos=cursor,
        clock=clock,
    )
    out.bind(count.loop)
    sid = None
    try:
        assert count.start() == {"running": True, "place": "测试站"}
        sid = count.loop.state().session_id
        assert _wait_state(count.loop, RunState.RUNNING)
        assert settled.wait(WAIT)
        out.clear()
        clock.advance(0.4)
        assert _wait_state(count.loop, RunState.FAILED)
        assert count.loop.join(WAIT, session_id=sid) is True

        ops = [r.op for r in out.ops]
        assert ("hud.clear", "盘点") in ops
        assert [op for op in ops if op[0] == "note" and op[1] == "盘点"]
        assert [
            op
            for op in ops
            if op
            == (
                "bus",
                "count",
                {"running": False, "review": None},
            )
        ]
        assert not [op for op in ops if op[0] == "record" and op[2] == "F6 盘点结束"]
        text = stderr.getvalue()
        assert "盘点出错" in text
        assert "Traceback" in text and "截图坏了" in text
    finally:
        if count.running():
            count.stop()
        count.loop.join_all(WAIT)


def test_cursor_injection(monkeypatch):
    """给了 cursor_pos 就用给的，不读真光标（目录迁移 R5 起真光标在 infrastructure/platform/cursor）"""
    from astral_toolkit.infrastructure.platform import cursor as cursor_platform

    def boom():
        raise AssertionError("不该读真光标")

    monkeypatch.setattr(cursor_platform, "pos", boom)
    loop = _CommitRecorder()
    worker = count_helpers.worker(cursor_pos=lambda: (1, 2))
    worker.loop = loop
    session = SimpleNamespace(payload="测试站")
    ctx = worker.setup(session)
    tick = worker.tick(session, ctx, 0.0)
    assert tick.wait == 0.1


def test_bind_required_and_state():
    from astral_toolkit.tasks import count as count_task
    from tests.bootstrap_helpers import restore_bindings, snapshot_bindings

    saved = snapshot_bindings()
    try:
        count_task._count = None
        for fn in (
            count_task.count_toggle,
            count_task.count_state,
            count_task.count_apply,
            count_task.count_cancel,
        ):
            try:
                fn()
            except RuntimeError as exc:
                assert "未绑定" in str(exc)
            else:
                raise AssertionError("未绑定时应抛 RuntimeError")

        fake = SimpleNamespace(
            running=lambda: True,
            place="测试站",
            review={"ok": 1},
        )
        count_task.bind(fake)
        assert count_task.count_state() == {
            "running": True,
            "place": "测试站",
            "review": {"ok": 1},
        }
    finally:
        restore_bindings(saved)


def test_review_shared_store_and_cancel(monkeypatch):
    from astral_toolkit.app import bus
    from astral_toolkit.tasks import count as count_task
    from tests.bootstrap_helpers import bind_for_test

    count = count_helpers.count(
        foreground=lambda: True,
        cursor_pos=lambda: (1, 2),
    )
    loop = count.loop
    loop.shared_set("x", {"a": 1})
    assert loop.shared_get("x") == {"a": 1}
    assert loop.shared_take("x") == {"a": 1}
    assert loop.shared_get("x") is None

    count.review = {"r": 1}
    assert loop.shared_get(count_mod.REVIEW) == {"r": 1}
    assert count.review == {"r": 1}
    assert count.take_review() == {"r": 1}
    assert loop.shared_get(count_mod.REVIEW) is None

    count.review = {"r": 2}
    calls = []
    monkeypatch.setattr(bus, "publish", lambda *args: calls.append(args))
    with bind_for_test(count_task, count):
        assert count_task.count_cancel() == {"ok": True}
        assert calls == [("count", {"running": False, "review": None})]
        assert loop.shared_get(count_mod.REVIEW) is None


def test_app_registers_count_as_session_loop_service():
    """lifecycle 里的 count 是 SessionLoopService、在 SESSIONS 阶段、管的就是 app.count.loop。"""
    from astral_toolkit.runtime.lifecycle import Phase, SessionLoopService
    from tests.bootstrap_helpers import app_for_test

    with app_for_test() as app:
        entries = [
            (service, gate)
            for service, gate in app.lifecycle._services
            if service.name == "count"
        ]
        assert len(entries) == 1
        service, gate = entries[0]
        assert gate is False
        assert isinstance(service, SessionLoopService)
        assert service.phase is Phase.SESSIONS
        assert service._loop is app.count.loop


def _fake_links(**over):
    """假的 CountLinks：屏幕光标 (100, 100)、热键名 F9、在「测试站」；调试图绑 / 解和悬浮窗短提示记进 rec"""
    rec = []
    base: dict[str, Any] = dict(
        cursor_pos=lambda: (100, 100),
        grab=_image,
        foreground=lambda: True,
        hotkey=lambda: "F9",
        debug_bind=lambda: rec.append("bind"),
        debug_unbind=lambda: rec.append("unbind"),
        place_now=lambda: "测试站",
        note=lambda section, text: rec.append(("note", section, text)),
        refuse=lambda: None,
    )
    base.update(over)
    return count_mod.CountLinks(**base), rec


def test_worker_uses_analysis_views_and_links():
    """目录迁移 R5：一轮里认物品、记格子用的是分析给的「光标在截图上的位置」，不是屏幕上的光标；悬浮窗文字走接进来的
    排版；调试图目录开始时绑、结束时解；收尾时没带热键名就现取接进来的"""
    links, rec = _fake_links()
    reads = []
    analysis: Any = SimpleNamespace(
        cursor_on_image=lambda img: (650, 1100),
        read_item=lambda img, cursor: reads.append(cursor) or _item(),
        review=lambda place, items: None,
    )
    views = count_mod.CountViews(hud_text=lambda place, items: f"{place}:{len(items)}")
    worker = count_mod._CountWorker(analysis, views, links)
    loop = _CommitRecorder()
    worker.loop = loop
    session = SimpleNamespace(payload="测试站")
    ctx = worker.setup(session)
    assert rec == ["bind"]
    worker.tick(session, ctx, 0.0)
    worker.tick(session, ctx, 0.4)
    assert reads == [(650, 1100)]
    assert [op for op in loop.ops if op[0] == "hud.set"] == [
        ("hud.set", "盘点", "测试站:1")
    ]
    # 格号按截图上的位置算：650 / (1000 × 0.065)、1100 / (1000 × 0.11)
    assert [cell[2:] for cell in ctx.cells] == [(10, 10)]
    ops = worker.finish(session, None, StopInfo("idle"))
    assert ("note", "盘点", "盘点结束｜未识别到物品｜按 F9 重新开始", 8) in ops
    worker.teardown(session, ctx)
    assert rec == ["bind", "unbind"]


def test_start_refused_while_closing_or_not_windows():
    """正在退出时不让开始（回接进来的那句、不碰会话）；不是 Windows（enabled 关着）只回「没在跑」；
    都不拦就按接进来的地点开始"""
    starts = []

    class _Loop:
        def running(self):
            return False

        def start(self, payload):
            starts.append(payload)
            return 1

    def factory(worker, **kwargs):
        return _Loop()

    links, _ = _fake_links(refuse=lambda: {"error": "正在退出"})
    closing = count_helpers.count(links=links, _loop_factory=factory)
    assert closing.start() == {"error": "正在退出"}
    links, _ = _fake_links()
    off = count_helpers.count(links=links, enabled=False, _loop_factory=factory)
    assert off.start() == {"running": False}
    assert starts == []
    on = count_helpers.count(links=links, _loop_factory=factory)
    assert on.start() == {"running": True, "place": "测试站"}
    assert starts == ["测试站"] and on.place == "测试站"
