"""会话循环的计时和出错处理（设计稿 v3 §2.2、§2.3）：暂停冻结、活动时钟、自动关闭、过期、重试、看门狗

假 Worker + 假时钟 + 「每轮放行的闸」卡时机，不靠 sleep 凑时间、不起真读屏。
"""

import time

from tests.runtime_fakes import FakeClock, FakeWorker, Gate, TickGate, make_loop
from astral_toolkit.runtime.session import Freshness, RunState, StopInfo

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


def _current_id(loop):
    """收尾用：当前会话号（没有就是 0）"""
    return loop.state().session_id


def _start(loop, worker):
    sid = loop.start()
    assert sid is not None and worker.started.wait(WAIT)
    assert _wait_until(
        lambda: loop.state().state in (RunState.RUNNING, RunState.PAUSED)
    ), "工作线程没起来"
    return sid


def test_pause_freezes_idle_and_stale_timers():
    """切出游戏那段既不算过期也不算自动关闭；回来后按扣掉暂停的时间接着算"""
    clock = FakeClock()
    front = {"on": True}
    worker = FakeWorker(
        needs_foreground=True,
        idle_close=10.0,
        stale_after={"panel": 5.0},
        observed_now={"panel"},
        wait=0.01,
    )
    gate = TickGate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, clock=clock, foreground=lambda: front["on"])
    try:
        sid = _start(loop, worker)
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
        assert ("on_pause", sid) in worker.calls and len(gaps) == 1
        assert 999 < gaps[0] < 1001, gaps
        assert not [c for c in worker.calls if c[0] == "on_stale"], "暂停那段不算过期"
        assert worker.finished == [], "暂停那段也不算自动关闭"
        assert loop.freshness("panel") is Freshness.FRESH
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.step()
        loop.join(session_id=_current_id(loop))


def test_idle_close_is_read_outside_the_loop_lock():
    """采矿助手的 idle_close 是读设置的属性：会话循环在锁外取，锁里不读文件（审查 2026-11-08）"""
    held = []

    class Worker(FakeWorker):
        @property
        def idle_close(self):
            held.append(bool(self.loop is not None and self.loop.lock_held_by_me()))
            return 10.0

        @idle_close.setter
        def idle_close(self, value):
            pass

    clock = FakeClock()
    worker = Worker(wait=0.01)
    gate = TickGate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, clock=clock)
    worker.loop = loop
    try:
        _start(loop, worker)
        gate.wait()
        for _ in range(3):
            assert not _step_or_finish(worker, gate, clock, 1.0)
        assert held and not any(held), held
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.step()
        loop.join(session_id=_current_id(loop))


def test_idle_close_uses_the_latest_of_all_channels(monkeypatch):
    """只有雷达信号、没有扫描面板时，120 秒也不该自动关闭（dev 是 max(面板, 信号)）"""
    clock = FakeClock()
    worker = FakeWorker(idle_close=10.0, wait=0.01)
    gate = TickGate()
    worker.gate = gate
    saved = []
    from astral_toolkit.runtime.session import RunFlag

    loop, _, out = make_loop(
        worker,
        clock=clock,
        run_flag=RunFlag("live_on", lambda k, v: saved.append((k, v))),
    )
    try:
        _start(loop, worker)
        gate.wait()
        worker.observed_now = {"signals"}
        for _ in range(20):  # 20 秒只有信号
            assert not _step_or_finish(worker, gate, clock, 1.0)
        assert worker.finished == [], "只有信号不应该自动关闭"
        worker.observed_now = set()
        finished = False
        for _ in range(20):
            if _step_or_finish(worker, gate, clock, 1.0):
                finished = True
                break
        assert finished and worker.finished == ["idle"]
        assert _wait_state(loop, RunState.STOPPED)
        assert saved == [("live_on", True), ("live_on", False)]
        assert out.live_events()[-1] == {"running": False}
        assert worker.last_stop_info.reason == "idle"
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.step()
        loop.join(session_id=_current_id(loop))


def test_stale_fires_once_per_channel():
    clock = FakeClock()
    worker = FakeWorker(stale_after={"panel": 5.0}, observed_now={"panel"}, wait=0.01)
    gate = TickGate()
    worker.gate = gate
    loop, _, out = make_loop(worker, clock=clock)
    try:
        sid = _start(loop, worker)
        gate.wait()
        _step(gate, clock, 1.0)
        assert loop.freshness("panel") is Freshness.FRESH
        worker.observed_now = set()  # 面板没了
        _step(gate, clock, 6.0)
        assert ("on_stale", sid, "panel") in worker.calls
        assert loop.freshness("panel") is Freshness.STALE
        _step(gate, clock, 1.0)  # 还是没看到：不再触发
        assert len([c for c in worker.calls if c[0] == "on_stale"]) == 1
        worker.observed_now = {"panel"}  # 又看到了
        _step(gate, clock, 0.1)
        assert loop.freshness("panel") is Freshness.FRESH
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.step()
        loop.join(session_id=_current_id(loop))
        assert out is not None


def test_retry_restarts_the_idle_timer():
    """重试不重置空闲计时的话：空闲 110 秒 → 抛错 → 重试后 1 秒就被关（v1 的 bug）"""
    clock = FakeClock()
    worker = FakeWorker(idle_close=10.0, fail_at=6, wait=0.01)
    gate = TickGate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, clock=clock)
    try:
        sid = _start(loop, worker)
        gate.wait()
        for _ in range(5):  # 空闲 5 秒
            assert not _step_or_finish(worker, gate, clock, 1.0)
        # 第 6 秒抛错 → 重试（等 1 秒真实时间），空闲计时重新起算
        assert not _step_or_finish(worker, gate, clock, 1.0)
        assert _wait_until(
            lambda: sum(1 for c in worker.calls if c[0] == "setup") >= 2, 5
        )
        assert _wait_until(
            lambda: any(c[0] == "tick" and c[1] == sid for c in worker.calls), 5
        )
        # 重试后重新起算：再过 9 秒（总共 15 秒 > 10）也不该关；不重置的话第 11 秒就关了
        for _ in range(9):
            assert not _step_or_finish(worker, gate, clock, 1.0), worker.finished
        assert worker.finished == []
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.step()
        loop.join(session_id=_current_id(loop))


def test_errors_clear_hud_in_lock_and_retry_then_finish(monkeypatch):
    """前两次重试套 before_retry（锁内），第 3 次走 error 收尾、live_on 置 False"""
    from astral_toolkit.runtime.session import RunFlag

    saved = []
    worker = FakeWorker(fail_times=3, retries=3, wait=0.01)
    worker.retry_ops_list = [("hud.clear", "信号")]
    loop, _, out = make_loop(
        worker, run_flag=RunFlag("live_on", lambda k, v: saved.append((k, v)))
    )
    try:
        sid = loop.start()
        assert sid is not None and _wait_state(loop, RunState.FAILED)
        assert [c[1] for c in worker.calls if c[0] == "on_error"] == [sid, sid, sid]
        clears = [r for r in out.ops if r.op[0] == "hud.clear"]
        assert len(clears) == 2 and all(r.locked for r in clears)
        assert worker.finished == ["error"]
        assert saved == [("live_on", True), ("live_on", False)]
        view = loop.state()
        assert view.last_error == "坏了" and view.stop_reason == "error"
        assert ("finish", sid, "error") in worker.calls
    finally:
        loop.request_stop_current(StopInfo("user"))


def test_setup_failure_counts_as_a_failed_attempt():
    worker = FakeWorker(setup_fail_times=1, retries=2, wait=0.01)
    loop, _, _ = make_loop(worker)
    try:
        sid = loop.start()
        assert sid is not None
        assert _wait_until(
            lambda: any(c[0] == "tick" and c[1] == sid for c in worker.calls), 5
        ), worker.calls
        assert [c for c in worker.calls if c[0] == "on_error"]
        # 失败的那次没有 ctx：teardown 也必须能收
        assert loop.state().state is RunState.RUNNING
    finally:
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=_current_id(loop))


def test_finish_runs_before_teardown_and_writes_after_stop():
    gate = Gate()
    worker = FakeWorker()
    worker.finish_gate = gate
    loop, _, _ = make_loop(worker)
    try:
        sid = _start(loop, worker)
        loop.request_stop_current(StopInfo("user"))
        assert gate.entered.wait(WAIT)  # finish 卡住了
        assert worker.calls[-1][0] == "finish"
        assert ("teardown", sid) not in worker.calls
        gate.release.set()
        assert loop.join(session_id=_current_id(loop))
        calls = [c[0] for c in worker.calls]
        assert calls.index("finish") < calls.index("teardown")
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))


def test_join_timeout_leaves_stopping_then_worker_exit_marks_stopped():
    gate = Gate()
    worker = FakeWorker()
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        _start(loop, worker)
        assert gate.entered.wait(WAIT)
        out.clear()
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=_current_id(loop)), (
            "线程卡在 tick 里，join 应该超时"
        )
        view = loop.state()
        assert view.state is RunState.STOPPING and view.worker_alive
        assert view.prev_stop_pending
        assert out.live_events() == [{"running": False}], "join 超时这条路径要发确认"
        gate.release.set()  # 旧线程这时才退出
        assert _wait_state(loop, RunState.STOPPED)
        assert out.live_events() == [{"running": False}], "退出时不再发第二次"
        assert not loop.state().stop_timeout
        assert loop.join(session_id=_current_id(loop))
    finally:
        gate.release.set()
        loop.join(session_id=_current_id(loop))


def test_worker_that_never_exits_only_gets_stop_timeout_not_failed():
    """线程没退就不进 FAILED：状态留 STOPPING、stop_timeout 为真，只记一条 record"""
    gate = Gate()
    worker = FakeWorker()
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        _start(loop, worker)
        assert gate.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=_current_id(loop))
        assert _wait_until(lambda: loop.state().stop_timeout, 5)
        view = loop.state()
        assert view.state is RunState.STOPPING, "线程还活着，不能标 FAILED"
        assert view.worker_alive and view.prev_stop_pending
        assert view.last_error is None
        assert _wait_until(lambda: out.records(), 5)
        assert any("停止超时" in op[2] for op in out.records())
    finally:
        gate.release.set()
        loop.join(session_id=_current_id(loop))


def test_old_worker_cannot_end_the_new_session():
    """停止超时中再开：新会话正常跑，旧线程出来后既不清新会话的计时也不结束它"""
    clock = FakeClock()
    worker = FakeWorker(idle_close=10.0, wait=0.01, restart_while_stopping=True)
    gate = TickGate()
    worker.gate = gate
    loop, _, out = make_loop(worker, clock=clock, join_timeout=0.02)
    try:
        first = _start(loop, worker)
        gate.wait()
        clock.advance(11.0)  # 旧会话已经到该自动关闭的时候
        old_session = worker.session
        old_thread = loop._current.thread  # type: ignore[union-attr]
        worker.gate = None  # 新会话不受闸影响
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=first), "旧线程还卡着，join 应该超时"
        second = loop.start()
        assert second is not None and _wait_state(loop, RunState.RUNNING)
        assert loop.state().prev_stop_pending
        assert any("上次停止还没结束" in op[1] for op in out.logs())
        gate.step()  # 旧线程这才从 tick 里出来
        assert old_thread.join(WAIT) is None and not old_thread.is_alive()
        assert loop.request_stop(old_session, StopInfo("idle")) is False
        assert loop.state().state is RunState.RUNNING
        assert not [c for c in worker.calls if c[0] == "on_stale"]
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.step()
        loop.join(session_id=loop.state().session_id)


def test_shutdown_keeps_the_run_flag_and_confirms_once():
    saved = []
    from astral_toolkit.runtime.session import RunFlag

    loop, worker, out = make_loop(
        run_flag=RunFlag("live_on", lambda k, v: saved.append((k, v)))
    )
    try:
        _start(loop, worker)
        out.clear()
        loop.request_stop_current(StopInfo("shutdown"))
        assert loop.join(session_id=_current_id(loop))
        assert saved == [("live_on", True)], "退出不改 live_on"
        assert out.ops == [], "shutdown 收尾什么都不发（stop_ops 空）"
    finally:
        loop.request_stop_current(StopInfo("user"))


def test_slow_tick_uses_the_observation_time():
    """tick 在 t=0 观测、卡到 t=130 才返回：返回后立刻判自动关闭 / 过期（2-3）"""
    # 自动关闭：观测时刻是 0，返回时活动时钟正好 130，超过 120 的限值 → 立刻关
    clock = FakeClock(start=0.0)
    worker = FakeWorker(idle_close=120.0, wait=0.01, observed={"panel": 0.0})
    gate = Gate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, clock=clock)
    try:
        _start(loop, worker)
        assert gate.entered.wait(WAIT)
        clock.advance(130.0)  # tick 还卡着，很久以后才返回
        gate.release.set()
        assert _wait_until(lambda: worker.finished == ["idle"], 5), worker.finished
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=_current_id(loop))

    # 过期：同样从 0 卡到 130 秒，返回后立刻标 stale（不是从返回时刻重新算）
    clock = FakeClock(start=0.0)
    worker = FakeWorker(stale_after={"panel": 5.0}, wait=0.01, observed={"panel": 0.0})
    gate = Gate()
    worker.gate = gate
    loop, _, _ = make_loop(worker, clock=clock)
    try:
        sid = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        clock.advance(130.0)
        gate.release.set()
        assert _wait_until(lambda: ("on_stale", sid, "panel") in worker.calls, 5)
        assert loop.freshness("panel") is Freshness.STALE
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=_current_id(loop))
