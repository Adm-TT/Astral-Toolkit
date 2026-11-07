"""RT-K1 甲：框架日志按引擎标、读前台窗口后复查停止。"""

import time

from astral_toolkit.app.engines.count import _CountWorker
from astral_toolkit.app.engines.live import _Live
from astral_toolkit.runtime.workers.navigation import _NavWorker
from astral_toolkit.runtime.session import RunState, StopInfo
from tests.runtime_fakes import FakeClock, FakeWorker, Gate, make_loop

WAIT = 10


def _wait_until(predicate, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return False


def _wait_state(loop, state, timeout=WAIT):
    return _wait_until(lambda: loop.state().state is state, timeout)


def _start(loop, worker):
    sid = loop.start()
    assert sid is not None and worker.started.wait(WAIT)
    assert _wait_until(
        lambda: loop.state().state in (RunState.RUNNING, RunState.PAUSED)
    ), "工作线程没起来"
    return sid


def _has_record(out, tag, *, prefix=None, text=None):
    for op in out.records():
        if op[1] != tag:
            continue
        if prefix is not None and op[2].startswith(prefix):
            return True
        if text is not None and op[2] == text:
            return True
    return False


def _has_log(out, tag, prefix):
    return any(op[2] == tag and op[1].startswith(prefix) for op in out.logs())


def test_k1_1_nav_framework_logs_and_records_use_nav_tag():
    """看门狗超时、上次停止没结束、被新会话取代：都标 NAV /「导航」"""
    gate = Gate()
    clock = FakeClock()
    worker = FakeWorker(
        name="nav",
        log_tag="NAV",
        display_name="导航",
        idle_close=5.0,
        restart_while_stopping=True,
        wait=0.01,
    )
    worker.finish_gate = gate
    loop, _, out = make_loop(worker, clock=clock, join_timeout=0.02)
    sid_b = None
    try:
        sid_a = _start(loop, worker)
        clock.advance(6.0)  # A 自动关闭，卡在 finish
        assert gate.entered.wait(WAIT), "A 没停在收尾"
        assert loop.state().state is RunState.STOPPING
        assert _wait_until(lambda: _has_record(out, "NAV", prefix="导航停止超时"), 5), (
            out.records()
        )
        assert _wait_until(lambda: loop.state().stop_timeout, 5)

        sid_b = loop.start()  # 看门狗已标超时：允许取代
        assert sid_b is not None and sid_b != sid_a
        assert _wait_state(loop, RunState.RUNNING)
        assert [p.session_id for p in loop.state().pending] == [sid_a]
        assert any(
            op[1] == "上次停止还没结束，已开新会话" and op[2] == "NAV"
            for op in out.logs()
        )
        assert _has_record(out, "NAV", prefix="导航上次停止")

        gate.release.set()  # 放行 A：收尾时发现已被取代
        assert _wait_until(
            lambda: _has_record(out, "NAV", text="导航引擎已停止（已被新会话取代）"),
            5,
        ), out.records()
        assert _wait_until(lambda: not loop.state().pending, 5)
        assert loop.state().session_id == sid_b
        assert loop.state().state is RunState.RUNNING
        assert not any(op[1] == "MINING" for op in out.records())
        assert not any(op[2] == "MINING" for op in out.logs())
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_k1_1_nav_hook_and_setup_errors_use_nav_tag():
    """钩子抛错、setup 失败：HOOK_ERROR / ERROR 也标 NAV"""
    worker = FakeWorker(name="nav", log_tag="NAV", display_name="导航")

    def boom(session):
        raise RuntimeError("hook 坏了")

    worker.start_ops = boom  # type: ignore[method-assign]
    loop, _, out = make_loop(worker)
    sid = None
    try:
        sid = loop.start()
        assert sid is not None
        assert _wait_until(lambda: _has_log(out, "NAV", "HOOK_ERROR"), 5), out.logs()
        assert not any(op[2] == "MINING" for op in out.logs())
    finally:
        loop.request_stop_current(StopInfo("user"))
        if sid is not None:
            loop.join(session_id=sid)

    worker = FakeWorker(
        name="nav",
        log_tag="NAV",
        display_name="导航",
        setup_fail_times=3,
        retries=3,
        wait=0.01,
    )
    loop, _, out = make_loop(worker)
    sid = loop.start()
    assert sid is not None
    try:
        assert _wait_until(lambda: _has_log(out, "NAV", "ERROR "), 5), out.logs()
        assert _wait_state(loop, RunState.FAILED)
        assert not any(op[2] == "MINING" for op in out.logs())
    finally:
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=sid)


def test_k1_1_missing_log_tag_and_display_name_fall_back_to_name():
    """没写 log_tag / display_name：标签用 name 的大写，中文名也用标签"""
    worker = FakeWorker(name="bare", log_tag="", display_name="")

    def boom(session):
        raise RuntimeError("hook 坏了")

    worker.start_ops = boom  # type: ignore[method-assign]
    loop, _, out = make_loop(worker)
    sid = None
    try:
        assert loop._log_tag == "BARE"
        assert loop._display_name == "BARE"
        sid = loop.start()
        assert sid is not None
        assert _wait_until(lambda: _has_log(out, "BARE", "HOOK_ERROR"), 5), out.logs()
    finally:
        loop.request_stop_current(StopInfo("user"))
        if sid is not None:
            loop.join(session_id=sid)


def test_k1_1_real_engine_class_attributes():
    assert _Live.log_tag == "MINING"
    assert _Live.display_name == "采矿助手"
    assert _NavWorker.log_tag == "NAV"
    assert _NavWorker.display_name == "导航"
    assert _CountWorker.log_tag == "COUNT"
    assert _CountWorker.display_name == "盘点"


def _n4_once(after_foreground):
    gate = Gate()
    calls = {"n": 0}

    def foreground():
        calls["n"] += 1
        if calls["n"] == 2:
            gate.hold()
            return after_foreground
        return True

    worker = FakeWorker(needs_foreground=True, wait=0.01)
    loop, _, _out = make_loop(worker, foreground=foreground, join_timeout=0.2)
    sid = None
    try:
        sid = _start(loop, worker)
        assert gate.entered.wait(WAIT), "没进第二次读前台"
        assert loop.state().state is RunState.RUNNING
        before = len(worker.ticks)
        loop.request_stop_current(StopInfo("user"))
        assert loop.state().state is RunState.STOPPING
        gate.release.set()
        assert loop.join(session_id=sid), "线程没在超时内退出"
        assert _wait_state(loop, RunState.STOPPED)
        assert not [c for c in worker.calls if c[0] == "on_pause"]
        assert len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid]) == 1
        return worker, sid, before
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        if sid is not None:
            loop.join(session_id=sid)


def test_k1_3_stop_during_foreground_read_does_not_pause_or_tick():
    """读前台窗口期间被停（RT-K1 / N4）：回 True 不再多 tick 一次（N4 的回归测试，改回去会挂）；
    回 False 不进暂停（_enter_pause 本来就挡已停的会话，这一半只守着不退化）"""
    worker, sid, _before = _n4_once(False)
    assert not [c for c in worker.calls if c[0] == "on_pause"]
    assert len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid]) == 1

    worker, sid, before = _n4_once(True)
    assert len(worker.ticks) == before, "被停后不该再 tick"
    assert not [c for c in worker.calls if c[0] == "on_pause"]
    assert len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid]) == 1
