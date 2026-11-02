"""会话循环的竞争场景（设计稿 §5 RT-B4 一行、架构稿 §11.2）：假时钟 + 线程栅栏，不靠 sleep

① A 慢、停、马上开 B：A 的结果不覆盖 B、不点亮悬浮窗
② 配装变化（epoch+1）后旧 epoch 的结果被拒
③ 切出游戏期间自动关闭和过期计时冻结，回来后按扣掉暂停的时间算
④ 自动关闭只结束自己的会话（关闭途中开了新会话，新会话不受影响）
⑤ 停止超时 → STOPPING(worker_alive) → 旧线程退出 → STOPPED；一直不退 → FAILED
⑥ 停止超时中再开：新会话正常、旧线程迟到结果被拒、prev_stop_pending 为真、那条日志出现一次
⑦ 出错重试：前 2 次锁内清 HUD 再重来，第 3 次走 error 收尾、live_on 置 False
⑧ start / request_stop 重复调用幂等

③⑤⑦ 在 test_runtime_session_clock.py 里有更细的版本；这里从「竞争」角度各跑一遍，
每个场景都能在实现退化时变红（见 RT-B4 台账的变异核对）。
"""

import time

from tests.runtime_fakes import FakeClock, FakeWorker, Gate, TickGate, make_loop
from astral_toolkit.runtime.results import MINING_SCAN, ResultStore
from astral_toolkit.runtime.session import Freshness, RunState, Tick

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


class _Committer(FakeWorker):
    """每一轮提交一个结果：用来观察迟到结果会不会覆盖新会话"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.values = []

    def tick(self, session, now):
        if self.gate is not None:
            self.gate.hold()
        stamp = self.loop.stamp(session, now)
        if stamp is not None:
            value = f"会话{session.id}"
            self.values.append(value)
            self.loop.commit(
                session,
                ("bus", "scan", {"rock": value}),
                slot=MINING_SCAN,
                value=value,
                stamp=stamp,
            )
        return Tick(0.02, True, frozenset())


def test_1_slow_worker_stopped_then_new_session_is_not_overwritten():
    """① A 还在算，停掉，马上开 B：A 算完的结果被拒，B 的不被覆盖"""
    gate = Gate()
    worker = _Committer()
    worker.gate = gate
    results = ResultStore()
    loop, _, out = make_loop(worker, results=results)
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        assert gate.entered.wait(WAIT)  # A 卡在算里
        loop.request_stop("user")
        loop._thread = None  # 等价于 join 立刻返回（真实现里是 3 秒超时后交给看门狗）
        worker.gate = None  # B 不受闸影响
        loop.start()
        assert _wait_until(lambda: results.get(MINING_SCAN) is not None)
        assert results.get(MINING_SCAN).value == "会话2"  # type: ignore[union-attr]
        gate.release.set()  # A 这才算完，来提交
        published = [
            c.args[1]["rock"]
            for c in out.calls
            if c.op == "publish" and c.args[0] == "scan"
        ]
        assert published == ["会话2"], published
        assert results.get(MINING_SCAN).value == "会话2"  # type: ignore[union-attr]
    finally:
        loop.request_stop("user")
        loop.join()


def test_2_epoch_change_rejects_results_captured_before_it():
    """② 配装变了（epoch+1）：之前取的 stamp 全部作废，之后取的照常"""
    worker = FakeWorker(wait=0.02)
    results = ResultStore()
    loop, _, out = make_loop(worker, results=results)
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        session = worker.session
        old = loop.stamp(session, 1.0)
        assert old is not None
        loop.config_changed()
        out.clear()
        assert not loop.commit(
            session,
            ("bus", "scan", {"rock": "旧配装"}),
            slot=MINING_SCAN,
            value="旧配装",
            stamp=old,
        )
        assert out.published("scan") == [] and results.get(MINING_SCAN) is None
        new = loop.stamp(session, 2.0)
        assert new is not None and new.epoch == old.epoch + 1
        assert loop.commit(
            session,
            ("bus", "scan", {"rock": "新配装"}),
            slot=MINING_SCAN,
            value="新配装",
            stamp=new,
        )
        assert results.get(MINING_SCAN).value == "新配装"  # type: ignore[union-attr]
    finally:
        loop.request_stop("user")
        loop.join()


def test_3_foreground_pause_freezes_idle_and_stale_until_resume():
    """③ 切出游戏：自动关闭和过期都冻结；回来按扣掉暂停段时间接着算"""
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
        clock.advance(1.0)
        gate.step()
        gate.wait()
        front["on"] = False
        gate.step()  # 这一轮结束就切出去了
        assert _wait_state(loop, RunState.PAUSED)
        clock.advance(1000.0)
        front["on"] = True
        gate.wait()  # 回来，下一轮 tick 到闸
        assert loop.state().state is RunState.RUNNING
        gaps = [c[2] for c in worker.calls if c[0] == "on_resume"]
        assert gaps and 999 < gaps[0] < 1001
        assert worker.finished == []
        assert not [c for c in worker.calls if c[0] == "on_stale"]
        assert loop.freshness(MINING_SCAN) is Freshness.FRESH
    finally:
        loop.request_stop("user")
        gate.step()
        loop.join()


def test_4_auto_off_only_ends_its_own_session(monkeypatch):
    """④ 自动关闭途中开了新会话：旧会话的收尾不结束新会话，也不清新会话的计时"""
    from astral_toolkit.core import settings

    saved = []
    monkeypatch.setattr(settings, "update", lambda **kw: saved.append(kw))
    clock = FakeClock()
    worker = FakeWorker(idle_close=10.0, wait=0.01, restart_while_stopping=True)
    gate = TickGate()
    worker.gate = gate
    loop, _, _ = make_loop(
        worker, clock=clock, settings_flag="live_on", join_timeout=0.02
    )
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        gate.wait()
        clock.advance(11.0)  # 旧会话该自动关闭了
        old = worker.session
        worker.gate = None
        loop.request_stop("user")
        assert not loop.join()
        loop.start()  # 旧线程还卡着，采矿照常开新会话
        assert _wait_state(loop, RunState.RUNNING)
        assert loop._stop_session(old, "idle") is False
        assert loop.state().state is RunState.RUNNING and saved == []
        gate.step()
    finally:
        loop.request_stop("user")
        gate.step()
        loop.join()


def test_5_stop_timeout_walks_stopping_to_stopped_or_failed(monkeypatch):
    """⑤ 停止超时：先留 STOPPING(worker_alive)，旧线程退出转 STOPPED；一直不退 → FAILED(stop_timeout)"""
    from astral_toolkit.core import run_records

    records = []
    monkeypatch.setattr(run_records, "record", lambda *a, **k: records.append(a))
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
        view = loop.state()
        assert view.state is RunState.STOPPING and view.worker_alive
        gate.step()
        assert _wait_state(loop, RunState.STOPPED)
    finally:
        loop.request_stop("user")
        gate.step()
        loop.join()

    worker2 = FakeWorker(wait=0.01)
    gate2 = TickGate()
    worker2.gate = gate2
    loop2, _, _ = make_loop(worker2, join_timeout=0.02)
    try:
        loop2.start()
        assert worker2.started.wait(WAIT)
        gate2.wait()
        loop2.request_stop("user")
        assert not loop2.join()
        assert _wait_state(loop2, RunState.FAILED)
        view = loop2.state()
        assert view.last_error == "stop_timeout" and view.worker_alive
        assert records and "停止超时" in records[-1][1]
    finally:
        gate2.step()
        loop2.join(1)


def test_6_restart_while_stopping_keeps_new_session_and_rejects_late_results():
    """⑥ 停止超时中再开：新会话正常、旧线程迟到结果被拒、prev_stop_pending 为真、日志只记一次"""
    clock = FakeClock()
    worker = FakeWorker(wait=0.01, restart_while_stopping=True)
    gate = TickGate()
    worker.gate = gate
    loop, _, out = make_loop(worker, clock=clock, join_timeout=0.02)
    try:
        loop.start()
        assert worker.started.wait(WAIT)
        gate.wait()
        old = worker.session
        late = loop.stamp(old, 1.0)
        worker.gate = None
        loop.request_stop("user")
        assert not loop.join()
        loop.start()
        assert _wait_state(loop, RunState.RUNNING)
        assert loop.state().prev_stop_pending
        assert (
            len(
                [
                    c
                    for c in out.calls
                    if c.op == "log" and "上次停止还没结束" in c.args[0]
                ]
            )
            == 1
        )
        gate.step()  # 旧线程这才退出
        assert not loop.commit(
            old,
            ("bus", "scan", {"rock": "旧"}),
            slot=MINING_SCAN,
            value="旧",
            stamp=late,
        )
        assert loop.state().state is RunState.RUNNING
    finally:
        loop.request_stop("user")
        gate.step()
        loop.join()


def test_7_retry_clears_hud_in_lock_then_error_turns_the_flag_off(monkeypatch):
    """⑦ 前 2 次锁内清 HUD 再重来；第 3 次走 error 收尾、live_on 置 False"""
    from astral_toolkit.core import settings

    saved = []
    monkeypatch.setattr(settings, "update", lambda **kw: saved.append(kw))
    worker = FakeWorker(fail_times=3, retries=3, wait=0.01)
    loop, _, out = make_loop(worker, settings_flag="live_on")
    try:
        loop.start()
        assert _wait_state(loop, RunState.FAILED)
        assert [c[1] for c in worker.calls if c[0] == "on_error"] == [0, 1, 2]
        clears = [c for c in out.calls if c.op == "hud_clear"]
        assert len(clears) == 2 and all(c.locked for c in clears)
        assert worker.finished == ["error"]
        assert saved == [{"live_on": False}]
        assert loop.state().last_error == "坏了"
    finally:
        loop.join()


def test_8_start_and_request_stop_are_idempotent():
    """⑧ 重复 start / 重复 request_stop：只有一个会话、收尾只做一次"""
    worker = FakeWorker(wait=0.01)
    loop, _, out = make_loop(worker)
    try:
        first = loop.start()
        assert first is not None
        assert worker.started.wait(WAIT)
        assert loop.start() == first and loop.start() == first
        assert out.live_events() == [{"running": True}]
        loop.request_stop("user")
        loop.request_stop("user")
        assert loop.join()
        assert worker.finished == ["user"]
        assert loop.request_stop("user") is None  # 停了再按也不出事
        assert loop.join()
        # 停了再开：新会话号、照常发 running=True
        second = loop.start()
        assert second is not None and second > first
        assert loop.join() is not None
    finally:
        loop.request_stop("user")
        loop.join()
