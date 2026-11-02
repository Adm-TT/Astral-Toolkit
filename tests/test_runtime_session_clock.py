"""会话循环的计时和出错处理（设计稿 §2.3、§7.4）：暂停冻结、活动时钟、自动关闭、过期、重试、看门狗

假 Worker + 假时钟 + 「每轮放行的闸」卡时机，不靠 sleep 凑时间、不起真读屏。
"""

import time

from tests.runtime_fakes import FakeClock, FakeWorker, TickGate, make_loop
from astral_toolkit.runtime.results import MINING_SCAN
from astral_toolkit.runtime.session import Freshness, RunState

WAIT = 10


def _wrap_finish(worker, ops):
    """换成自定义收尾输出，但仍记一笔 finished（判断是哪一种收尾）"""
    original = worker.finish_ops

    def finish(session, reason):
        original(session, reason)
        return ops

    worker.finish_ops = finish  # type: ignore[method-assign]


def _wait_until(predicate, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return False


def _wait_state(loop, state, timeout=WAIT):
    return _wait_until(lambda: loop.state().state is state, timeout)


def _step(gate, clock, seconds=0.0):
    """推一下时钟、放一轮 tick，等下一轮到闸"""
    clock.advance(seconds)
    gate.step()
    gate.wait()


def _step_or_finish(worker, gate, clock, seconds=1.0):
    """放一轮：要么下一轮到闸（返回 False），要么会话结束了（返回 True）"""
    clock.advance(seconds)
    gate.step()
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if worker.finished:
            return True
        if gate.arrived.acquire(timeout=0.005):
            return False
    raise AssertionError("既没结束也没到下一轮")


def test_pause_freezes_idle_and_stale_timers():
    """切出游戏那段既不算过期也不算自动关闭；回来后按扣掉暂停的时间接着算"""
    clock = FakeClock()
    front = {"on": True}
    worker = FakeWorker(
        needs_foreground=True,
        idle_close=10.0,
        stale_after=5.0,
        seen=frozenset({MINING_SCAN}),
        wait=0.01,
    )
    gate = TickGate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, clock=clock, foreground=lambda: front["on"])
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        gate.wait()
        _step(gate, clock, 1.0)
        _step(gate, clock, 1.0)
        front["on"] = False  # 切到别的窗口
        gate.step()
        assert _wait_state(loop, RunState.PAUSED)
        clock.advance(1000.0)  # 暂停里真实时间照样走
        front["on"] = True
        gate.wait()  # 回到游戏，下一轮 tick 到闸
        assert loop.state().state is RunState.RUNNING
        gaps = [c[2] for c in worker.calls if c[0] == "on_resume"]
        assert ("on_pause", 1) in worker.calls and len(gaps) == 1
        assert 999 < gaps[0] < 1001, gaps
        assert not [c for c in worker.calls if c[0] == "on_stale"], "暂停那段不算过期"
        assert worker.finished == [], "暂停那段也不算自动关闭"
        assert loop.freshness(MINING_SCAN) is Freshness.FRESH
    finally:
        loop.request_stop("user")
        gate.step()
        loop.join()


def test_idle_close_ends_the_session_and_turns_the_flag_off(monkeypatch):
    """太久没看到面板 / 信号：自己关掉，事件在锁内发，live_on 置 False，收尾提示最后一条"""
    from astral_toolkit.core import settings

    saved = []
    monkeypatch.setattr(settings, "update", lambda **kw: saved.append(kw))
    clock = FakeClock()
    worker = FakeWorker(idle_close=10.0, active=False, wait=0.01)
    gate = TickGate()
    worker.gate = gate
    _wrap_finish(
        worker,
        [
            ("bus", "live", {"running": False, "auto_off": True}),
            ("note", "采矿助手", "采矿助手已关闭"),
        ],
    )
    loop, _, out = make_loop(worker, clock=clock, settings_flag="live_on")
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        gate.wait()
        for _ in range(20):
            if _step_or_finish(worker, gate, clock, 1.0):
                break
        assert worker.finished == ["idle"]
        assert _wait_state(loop, RunState.STOPPED)
        assert ("on_stop", 1, "idle") in worker.calls
        assert saved == [{"live_on": False}]
        assert out.published("live")[-1] == (
            "live",
            {"running": False, "auto_off": True},
        )
        assert out.calls[-1].op == "note_hud"
        assert all(
            c.locked for c in out.calls if c.op in ("publish", "hud_clear", "note_hud")
        ), "收尾事件和提示都在锁里发"
    finally:
        loop.request_stop("user")
        gate.step()
        loop.join()


def test_stale_marks_the_slot_and_calls_the_worker():
    clock = FakeClock()
    worker = FakeWorker(stale_after=5.0, seen=frozenset({MINING_SCAN}), wait=0.01)
    gate = TickGate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, clock=clock)
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        gate.wait()
        _step(gate, clock, 1.0)
        assert loop.freshness(MINING_SCAN) is Freshness.FRESH
        worker.seen = frozenset()  # 面板没了
        _step(gate, clock, 6.0)
        assert ("on_stale", 1, MINING_SCAN) in worker.calls
        assert loop.freshness(MINING_SCAN) is Freshness.STALE
        worker.seen = frozenset({MINING_SCAN})  # 又看到了
        _step(gate, clock, 1.0)
        assert loop.freshness(MINING_SCAN) is Freshness.FRESH
        assert len([c for c in worker.calls if c[0] == "on_stale"]) == 1
    finally:
        loop.request_stop("user")
        gate.step()
        loop.join()


def test_errors_clear_the_hud_in_lock_and_retry():
    """前两次出错：锁内清 HUD、重新 setup 再跑；第 3 次正常就不算失败"""
    worker = FakeWorker(fail_times=2, wait=0.01)
    loop, _, out = make_loop(worker)
    try:
        loop.start()
        assert worker.ticked.wait(WAIT), "重试以后没跑起来"
        assert loop.state().state is RunState.RUNNING
        assert worker.calls.count(("setup", 1)) == 3
        assert [c[1] for c in worker.calls if c[0] == "on_error"] == [0, 1]
        clears = [c for c in out.calls if c.op == "hud_clear"]
        assert len(clears) == 2 and all(c.locked for c in clears)
        assert worker.finished == []
    finally:
        loop.request_stop("user")
        loop.join()


def test_last_error_finishes_the_session_and_turns_the_flag_off(monkeypatch):
    from astral_toolkit.core import settings

    saved = []
    monkeypatch.setattr(settings, "update", lambda **kw: saved.append(kw))
    worker = FakeWorker(fail_times=3, retries=3, wait=0.01)
    _wrap_finish(worker, [("bus", "live", {"running": False, "error": "坏了"})])
    loop, _, out = make_loop(worker, settings_flag="live_on")
    try:
        loop.start()
        assert _wait_state(loop, RunState.FAILED)
        view = loop.state()
        assert view.last_error == "坏了" and view.stop_reason == "error"
        assert worker.finished == ["error"]
        assert saved == [{"live_on": False}]
        assert out.published("live")[-1] == (
            "live",
            {"running": False, "error": "坏了"},
        )
        assert ("teardown", 1) in worker.calls
        assert not loop.running()
    finally:
        loop.join()


def test_join_timeout_leaves_stopping_then_worker_exit_marks_stopped():
    worker = FakeWorker(wait=0.01)
    gate = TickGate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, join_timeout=0.02)
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        gate.wait()
        loop.request_stop("user")
        assert not loop.join(), "线程卡在 tick 里，join 应该超时"
        view = loop.state()
        assert view.state is RunState.STOPPING and view.worker_alive
        gate.step()  # 旧线程这时才退出
        assert _wait_state(loop, RunState.STOPPED)
        assert loop.join()
        assert not loop.state().worker_alive
    finally:
        gate.step()
        loop.join(1)


def test_worker_that_never_exits_becomes_failed_after_three_timeouts(monkeypatch):
    from astral_toolkit.core import run_records

    records = []
    monkeypatch.setattr(run_records, "record", lambda *a, **k: records.append((a, k)))
    worker = FakeWorker(wait=0.01)
    gate = TickGate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, join_timeout=0.02)
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        gate.wait()
        loop.request_stop("user")
        assert not loop.join()
        assert _wait_state(loop, RunState.FAILED)
        view = loop.state()
        assert view.last_error == "stop_timeout" and view.stop_reason == "stop_timeout"
        assert view.worker_alive, "旧线程还在跑：状态要能显示仍有待结束工作"
        assert records and "停止超时" in records[0][0][1]
    finally:
        gate.step()
        loop.join(1)


def test_old_worker_cannot_end_the_new_session(monkeypatch):
    """停止超时中再开：新会话正常跑，旧线程出来后既不清新会话的计时也不结束它"""
    from astral_toolkit.core import settings

    saved = []
    monkeypatch.setattr(settings, "update", lambda **kw: saved.append(kw))
    clock = FakeClock()
    worker = FakeWorker(idle_close=10.0, wait=0.01, restart_while_stopping=True)
    gate = TickGate()
    worker.gate = gate
    loop, _, out = make_loop(
        worker, clock=clock, settings_flag="live_on", join_timeout=0.02
    )
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        gate.wait()
        clock.advance(11.0)  # 旧会话已经到该自动关闭的时候
        old = worker.session
        old_thread = loop._thread
        late = loop.stamp(old, 1.0)  # 旧线程手里还攥着一张表
        worker.gate = None  # 新会话不受闸影响
        loop.request_stop("user")
        assert not loop.join(), "旧线程还卡着，join 应该超时"
        loop.start()
        assert _wait_state(loop, RunState.RUNNING)
        view = loop.state()
        assert view.prev_stop_pending
        assert (
            len(
                [
                    c
                    for c in out.calls
                    if c.op == "log" and "上次停止还没结束" in c.args[0]
                ]
            )
            == 1
        ), "「上次停止还没结束」只记一次"
        gate.step()  # 旧线程这才从 tick 里出来
        assert old_thread is not None and old_thread.join(WAIT) is None
        assert not old_thread.is_alive()
        assert loop._stop_session(old, "idle") is False
        assert not loop.commit(
            old,
            ("bus", "scan", {"rock": "旧"}),
            slot=MINING_SCAN,
            value="旧",
            stamp=late,
        ), "旧线程迟到的结果不能提交"
        assert loop.state().state is RunState.RUNNING
        assert saved == []
        assert not [c for c in worker.calls if c[0] == "on_stale"]
    finally:
        loop.request_stop("user")
        gate.step()
        loop.join()
