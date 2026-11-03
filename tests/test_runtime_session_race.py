"""会话隔离与停止的竞争场景（整改单 §4 R1–R10）：全部走 start / request_stop / join 真实路径

假 Worker + 假时钟 + 线程栅栏卡时机，不靠 sleep。每条测试的名字就是它卡住的那个交错。
"""

import threading
import time

from tests.runtime_fakes import FakeClock, FakeWorker, Gate, make_loop
from astral_toolkit.runtime.results import MINING_SCAN, ResultStore
from astral_toolkit.runtime.session import (
    Freshness,
    RunFlag,
    RunState,
    StopInfo,
)

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


def _value(results, slot):
    e = results.get(slot)
    return e.value if e is not None else None


def _thread_alive(loop, session_id):
    with loop._lock:
        run = loop._find_locked(session_id)
        return bool(run is not None and run.thread.is_alive())


def _start(loop, worker, payload=None):
    sid = loop.start(payload)
    assert sid is not None and worker.started.wait(WAIT)
    assert _wait_until(
        lambda: loop.state().state in (RunState.RUNNING, RunState.PAUSED)
    ), "工作线程没起来"
    return sid


class _Committer(FakeWorker):
    """每一轮提交一个结果：用来观察迟到结果会不会覆盖新会话"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.values = []

    def tick(self, session, ctx, now):
        from astral_toolkit.runtime.session import Tick

        self.session = session
        self.calls.append(("tick", session.id, now))
        self.ticks.append(now)
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
        self.ticked.set()
        return Tick(0.02, {})


class _ErrorWorker(FakeWorker):
    """出错收尾时把 error 带进 live 事件（看是哪个会话的错误）"""

    def stop_ops(self, session, info):
        self.calls.append(
            ("stop_ops", None if session is None else session.id, info.reason)
        )
        self.last_stop_info = info
        if info.reason == "error":
            return [
                ("bus", "live", {"running": False, "error": info.error}),
                ("record", "FAKE", "引擎已停止", "", "", "INFO"),
            ]
        return [("bus", "live", {"running": False})]


def test_join_of_a_stuck_session_is_not_fooled_by_a_finished_one():
    """join(A) 只能等 A：B 已经退出了也不能拿 B 的线程当 A 回了"""
    gate = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    worker.gate = gate
    loop, _, _ = make_loop(worker, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        old = loop._current.session  # type: ignore[union-attr]
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a)
        worker.gate = None
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        # B 正常停掉；A 还卡着。join(A) 必须还是 False
        assert (
            loop.request_stop(old, StopInfo("user")) is False
        )  # 旧会话的停止命令不管用
        loop.request_stop_current(StopInfo("user"))
        assert loop.join(session_id=sid_b)
        assert not loop.join(session_id=sid_a, timeout=0.05), "A 还卡在 tick 里"
        gate.release.set()
        assert loop.join(session_id=sid_a, timeout=WAIT)
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.release.set()
        loop.join(session_id=loop.state().session_id)


def test_r1_join_waits_only_its_own_session():
    """T1 停 A（A 卡在 tick 里）→ T1 join(A) 超时 → T2 开 B → T1 再 join(A)：等的是 A，B 一直是 RUNNING"""
    gate = Gate()
    worker = _Committer(restart_while_stopping=True)
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a), "A 卡着，join 应该超时"
        worker.gate = None
        sid_b = loop.start()
        assert sid_b is not None and sid_b != sid_a
        assert _wait_state(loop, RunState.RUNNING)
        assert [p.session_id for p in loop.state().pending] == [sid_a]
        out.clear()
        assert not loop.join(session_id=sid_a, timeout=0.02), "join 等的是 A，A 还卡着"
        assert loop.state().state is RunState.RUNNING, "B 不受影响"
        gate.release.set()
        assert loop.join(session_id=sid_a, timeout=WAIT)
        assert loop.state().state is RunState.RUNNING
        assert loop.state().session_id == sid_b
        # 确认已在 join 超时时发过（表 d）；被取代后不再发、也不再记「已被新会话取代」
        assert not [op for op in out.hud() if op[0] == "hud.clear"]
        assert not any("已被新会话取代" in op[2] for op in out.records())
        assert (
            len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid_a]) == 1
        )
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.release.set()
        loop.join(session_id=loop.state().session_id)


def test_restart_only_after_join_timeout():
    """R14：join 超时前按开始被拒；超时后能取代；已有一个活着的 pending 时再拒"""
    gate_a = Gate()
    gate_b = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    worker.gate = gate_a
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate_a.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        # ① join 超时前：按开始被拒，状态不动、没有新会话、没有「已开新会话」
        out.clear()
        assert loop.start() is None
        assert loop.state().state is RunState.STOPPING
        assert loop.state().session_id == sid_a
        assert not [op for op in out.records() if "已开新会话" in op[2]]
        # ② join 超时后：能开，A 进 pending
        assert not loop.join(session_id=sid_a)
        worker.gate = None
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        assert [p.session_id for p in loop.state().pending] == [sid_a]
        assert len([op for op in out.records() if "已开新会话" in op[2]]) == 1
        # ③ 已有一个活着的旧线程在收尾：B 停止超时后按开始被拒
        gate_b = Gate()
        worker.gate = gate_b
        assert gate_b.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_b)
        worker.gate = None
        assert loop.start() is None, "同时只能有一个旧线程在收尾"
        assert loop.state().state is RunState.STOPPING
        assert loop.state().session_id == sid_b
        gate_b.release.set()  # B 退出，A 还卡着：这时再开才该记「上次停止还没结束」
        assert _wait_state(loop, RunState.STOPPED)
        sid_c = loop.start()
        assert sid_c is not None and _wait_state(loop, RunState.RUNNING)
        assert any("已开新会话" in op[2] for op in out.records())
        gate_a.release.set()
        assert _wait_until(lambda: not loop.state().pending, 5)
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=sid_c)
    finally:
        gate_a.release.set()
        gate_b.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_r2_stop_timeout_and_each_pending_session_has_its_own_watchdog():
    """v4：A 停止超时留在「当前」；开 B 才把 A 移进 pending（superseded）；
    B 停止超时也只标 stop_timeout、不标 FAILED；每条记录一个看门狗"""
    gate_a, gate_b = Gate(), Gate()
    worker = FakeWorker(restart_while_stopping=True)
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        worker.gate = gate_a
        sid_a = _start(loop, worker)
        assert gate_a.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a)
        assert loop.state().state is RunState.STOPPING
        assert _wait_until(lambda: loop.state().stop_timeout, 5)
        assert loop.state().pending == (), "join 超时不移动当前会话"
        worker.gate = gate_b
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        assert [p.session_id for p in loop.state().pending] == [sid_a]
        assert gate_b.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_b)
        assert loop.state().state is RunState.STOPPING
        assert _wait_until(lambda: loop.state().stop_timeout, 5)
        # A 一直不退：A 那条被自己的看门狗标 stop_timeout，只记一条 record
        assert _wait_until(lambda: loop._pending[sid_a].stop_timeout, 5)  # type: ignore[union-attr]
        assert _wait_until(lambda: any("停止超时" in op[2] for op in out.records()), 5)
        assert loop.state().state is not RunState.FAILED
        # 同一会话连续两次 join 超时：看门狗只有一个、不会多记超时 record
        before = len([op for op in out.records() if "停止超时" in op[2]])
        assert not loop.join(session_id=sid_a)
        assert not loop.join(session_id=sid_a)
        gate_b.release.set()
        assert _wait_state(loop, RunState.STOPPED)
        assert len([op for op in out.records() if "停止超时" in op[2]]) <= before + 1
        # A 退出后 pending 清空，C 能开（B 停止超时已在当前，不会再积一个活线程）
        gate_a.release.set()
        assert _wait_until(lambda: not loop.state().pending, 5)
        worker.gate = None
        sid_c = loop.start()
        assert sid_c is not None and _wait_state(loop, RunState.RUNNING)
        assert sid_c not in (sid_a, sid_b)
        loop.request_stop_current(StopInfo("user"))
        assert loop.join(session_id=sid_c)
    finally:
        gate_a.release.set()
        gate_b.release.set()
        loop.request_stop_current(StopInfo("user"))


def test_r3_watchdog_rechecks_alive_under_lock():
    """看门狗等到线程退出才拿锁复查：不得标 stop_timeout（真实 join 超时启动看门狗）"""
    gate = Gate()
    worker = FakeWorker()
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        sid = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid), "线程卡着，join 应该超时"
        assert loop.state().stop_timeout is False
        gate.release.set()  # 线程在看门狗复查前退出
        assert _wait_until(lambda: not loop.state().worker_alive, 5)
        assert loop.state().stop_timeout is False, "线程已经退了，不能标停止超时"
        assert not any("停止超时" in op[2] for op in out.records())
        assert _wait_state(loop, RunState.STOPPED)
    finally:
        gate.release.set()
        loop.join(session_id=loop.state().session_id)


def test_r4_old_session_cannot_pause_or_resume_new():
    """A 卡在前台调用的返回点：停 A 开 B 后才拿到「切出」/「回来」，B 都不受影响"""
    gate_out = Gate()  # A 第一次：切出
    gate_back = Gate()  # A 第二次：回来（这时 A 已经被停、B 已经在跑）
    calls = {"n": 0}

    def foreground():
        calls["n"] += 1
        if calls["n"] == 1:
            gate_out.hold()
            return False  # A 读到「切出」→ 进暂停
        if calls["n"] == 2:
            gate_back.hold()
            return True  # A 读到「回来」→ 但那时它已经被停了
        return True  # B 一直在前台

    worker = FakeWorker(needs_foreground=True, restart_while_stopping=True)
    loop, _, out = make_loop(worker, foreground=foreground, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate_out.entered.wait(WAIT)
        gate_out.release.set()
        assert _wait_state(loop, RunState.PAUSED)
        assert gate_back.entered.wait(WAIT), "A 又进前台判断"
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a)
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        out.clear()
        gate_back.release.set()  # A 这才拿到「回来」
        assert _wait_until(lambda: not _thread_alive(loop, sid_a), 5)
        assert loop.state().state is RunState.RUNNING, "B 不能被旧会话改状态"
        assert loop.state().session_id == sid_b
        assert not [c for c in worker.calls if c[0] == "on_resume"]
        assert out.ops == [], "旧会话的 resume op 一个都不能发"
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate_out.release.set()
        gate_back.release.set()
        loop.join(session_id=loop.state().session_id)


def test_r5_old_tick_does_not_touch_new_session_timers():
    """A 卡在 tick 返回前（观测时刻 0.0）→ 停 A 开 B（钟 0.5）→ A 带 observed 返回：B 的过期计时不变"""
    clock = FakeClock()
    gate = Gate()
    worker = FakeWorker(
        stale_after={"panel": 2.0}, restart_while_stopping=True, wait=0.01
    )
    worker.gate = gate
    worker.observed = {
        "panel": 0.0
    }  # A 的观测时刻（`_start` 之前定好，栅栏里也改不掉）
    loop, _, out = make_loop(worker, clock=clock, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        clock.advance(0.5)  # A 卡着的时候时间往前走
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a)
        worker.gate = None
        worker.observed = {}
        sid_b = loop.start()  # B 的活动时钟从 0 起（此时钟 0.5）
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        out.clear()
        gate.release.set()  # A 带着 observed=0.0 返回
        assert _wait_until(lambda: not _thread_alive(loop, sid_a), 5)
        # B 自己什么都没看到：活动时钟 1.9 秒（< 2.0）还该是新鲜的。
        # 若 A 的观测时刻写进 B 的计时（换算成 -0.5），B 会提前过期。
        clock.advance(1.9)
        assert loop.freshness("panel") is Freshness.FRESH, (
            "A 的 observed 不能改 B 的计时"
        )
        assert ("on_stale", sid_b, "panel") not in worker.calls
        clock.advance(0.2)  # 活动 2.1 > 2.0 → 这才该过期
        assert _wait_until(lambda: ("on_stale", sid_b, "panel") in worker.calls, 5)
        assert loop.freshness("panel") is Freshness.STALE
        assert loop.state().session_id == sid_b
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.release.set()
        loop.join(session_id=loop.state().session_id)


def test_r6_error_text_belongs_to_its_session():
    """A、B 先后出错（v4 里 A 出错用尽必须等它退出才能开 B，所以不是交错）：
    B 的 live 事件里 error 是 B 的、A 的错误恰好发一次"""
    worker = _ErrorWorker(retries=1, wait=0.01)
    loop, _, out = make_loop(worker)
    try:
        out.clear()
        worker.failure = "A 坏了"
        worker.fail_times = 1
        sid_a = loop.start()
        assert sid_a is not None and _wait_state(loop, RunState.FAILED)
        assert out.live_events()[-1]["error"] == "A 坏了"
        worker.failure = "B 坏了"
        worker.fail_times = 1
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.FAILED)
        assert out.live_events()[-1]["error"] == "B 坏了"
    finally:
        loop.request_stop_current(StopInfo("user"))


def test_r7_run_flag_never_written_backwards():
    """A 自动关闭、写 flag 卡住（join 已超时）后开 B、再停 B：迟到的 True 不覆盖 False，最终是 False"""
    gate = Gate()
    saved = []

    def write(key, value):
        if value is False:
            gate.hold()  # A 的 False 卡在写盘里
        saved.append(value)

    clock = FakeClock()
    worker = FakeWorker(idle_close=5.0, wait=0.01, restart_while_stopping=True)
    loop, _, out = make_loop(worker, clock=clock, run_flag=RunFlag("live_on", write))
    try:
        sid_a = _start(loop, worker)
        clock.advance(6.0)  # A 该自动关闭了
        assert gate.entered.wait(WAIT)  # A 的 False 卡在写盘里
        assert not loop.join(session_id=sid_a)  # join 超时（线程卡在写盘里）
        started = threading.Event()
        holder = {}

        def starter():
            holder["sid"] = loop.start()  # 被 flag 锁挡在写盘那一步
            started.set()

        t = threading.Thread(target=starter, daemon=True)
        t.start()
        assert _wait_until(lambda: loop.state().state is RunState.RUNNING, 5)
        assert not started.is_set(), (
            "start() 应该被 flag 锁挡在写盘那一步（不能先写完再被覆盖）"
        )
        stopped = threading.Event()

        def stopper():
            holder["stop"] = loop.request_stop_current(StopInfo("user"))
            stopped.set()

        t2 = threading.Thread(target=stopper, daemon=True)
        t2.start()
        assert _wait_until(lambda: loop._flag_want is False, 5)
        gate.release.set()  # A 的 False 这才写进去；B 的两次写都按最新期望值
        assert started.wait(WAIT) and stopped.wait(WAIT)
        assert _wait_until(lambda: not loop.state().worker_alive, 5)
        assert saved == [True, False], saved
        assert loop._flag_want is False
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_r8_stopped_confirmation_once_per_session():
    """v4 §2.3「确认次数」表 a–h：每种情况的 stop_ops 次数和「已被新会话取代」record 次数写死"""
    # a 按停止，线程 3 秒内退出：stop_ops 一次
    loop, worker, out = make_loop()
    sid = _start(loop, worker)
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)
    assert len(out.live_events()) == 1
    # 按停止前会先锁外算一次「没有会话」的 stop_ops（2-6），所以按 c[1] 认这次会话
    assert [c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid] == [
        ("stop_ops", sid, "user")
    ]

    # b 按停止，join 超时：超时路径发一次；线程后来退出不再发第二次
    gate = Gate()
    worker = FakeWorker()
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    sid = _start(loop, worker)
    assert gate.entered.wait(WAIT)
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert not loop.join(session_id=sid)
    assert len(out.live_events()) == 1
    gate.release.set()
    assert _wait_state(loop, RunState.STOPPED)
    assert len(out.live_events()) == 1, "线程退出时不再发第二次"

    # c 同 b，确认发出后又开了 B：A 只发一次，B 不受影响
    gate = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    sid_a = _start(loop, worker)
    assert gate.entered.wait(WAIT)
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert not loop.join(session_id=sid_a)
    assert len(out.live_events()) == 1
    worker.gate = None
    sid_b = loop.start()
    assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
    gate.release.set()
    assert _wait_until(lambda: not _thread_alive(loop, sid_a), 5)
    assert len([e for e in out.live_events() if e.get("running") is False]) == 1, (
        "A 的确认已经在 join 超时时发过"
    )
    assert not [op for op in out.records() if "取代" in op[2]]
    loop.request_stop_current(StopInfo("user"))
    loop.join(session_id=sid_b)

    # d 按停止、join 已超时后开新会话：1 次（join 超时时发的），被取代后不再发
    gate = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    sid_a = _start(loop, worker)
    assert gate.entered.wait(WAIT)
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert not loop.join(session_id=sid_a)
    worker.gate = None
    sid_b = loop.start()
    assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
    gate.release.set()
    assert _wait_until(lambda: not _thread_alive(loop, sid_a), 5)
    assert len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid_a]) == 1
    assert not [op for op in out.records() if "取代" in op[2]]
    loop.request_stop_current(StopInfo("user"))
    loop.join(session_id=sid_b)

    # d′ 没人 join 的自停（idle）卡在收尾：看门狗标 stop_timeout 后才能开 B；
    #    旧会话 0 次 stop_ops、退出时记 1 条「已被新会话取代」（3-1 按字面路径）
    gate = Gate()
    clock = FakeClock()
    worker = FakeWorker(idle_close=5.0, wait=0.01, restart_while_stopping=True)
    real_finish = worker.finish

    def finish(session, ctx, info):
        gate.hold()  # 线程卡在 finish 里：没人 join，也没有 stop_ops
        return real_finish(session, ctx, info)

    worker.finish = finish  # type: ignore[method-assign]
    loop, _, out = make_loop(worker, clock=clock, join_timeout=0.02)
    sid_a = _start(loop, worker)
    clock.advance(6.0)  # A 自动关闭
    assert gate.entered.wait(WAIT), "A 应该卡在收尾"
    # 不 join：自停时循环自己起看门狗，3×join_timeout 后标 stop_timeout
    assert _wait_until(lambda: loop.state().stop_timeout, 5)
    out.clear()
    sid_b = loop.start()  # d′：看门狗已标超时 → 允许取代
    assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
    assert [p.session_id for p in loop.state().pending] == [sid_a]
    assert loop.can_start() is False, "还有旧线程在收尾，不能再开"
    gate.release.set()  # 放行 A
    assert _wait_until(lambda: not _thread_alive(loop, sid_a), 5)
    assert _wait_until(lambda: [op for op in out.records() if "取代" in op[2]], 5)
    assert len([op for op in out.records() if "取代" in op[2]]) == 1
    assert not [c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid_a]
    assert _wait_until(lambda: not loop.state().pending, 5), "A 退出后 pending 要清空"
    loop.request_stop_current(StopInfo("user"))
    loop.join(session_id=sid_b)

    # e 没有会话时按停止：每按一次一次
    loop, worker, out = make_loop()
    loop.request_stop_current(StopInfo("user"))
    loop.request_stop_current(StopInfo("user"))
    assert len([c for c in worker.calls if c[0] == "stop_ops"]) == 2
    assert len(out.live_events()) == 2

    # f 退出（shutdown）有会话：stop_ops 空列表，等于什么都不发
    loop, worker, out = make_loop()
    sid = _start(loop, worker)
    out.clear()
    assert loop.request_shutdown() == sid
    assert loop.join(session_id=sid)
    assert out.ops == [], "shutdown 收尾不发任何事件"
    assert [c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid] == [
        ("stop_ops", sid, "shutdown")
    ]

    # g 退出，没有会话：0 次
    loop, worker, out = make_loop()
    assert loop.request_shutdown() is None
    assert worker.calls == []
    assert out.ops == []

    # h 自动关闭 / 出错用尽：各一次（finally）
    clock = FakeClock()
    loop, worker, out = make_loop(
        worker=FakeWorker(idle_close=5.0, wait=0.01), clock=clock
    )
    sid = _start(loop, worker)
    clock.advance(6.0)
    assert _wait_until(lambda: worker.finished, 5)
    assert _wait_until(lambda: any(c[0] == "stop_ops" for c in worker.calls), 5), (
        "自动关闭的收尾要走 confirm"
    )
    assert len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid]) == 1
    assert worker.finished == ["idle"]
    loop.join(session_id=sid)

    loop, worker, out = make_loop(worker=FakeWorker(fail_times=3, retries=3, wait=0.01))
    out.clear()
    sid = loop.start()
    assert sid is not None and _wait_state(loop, RunState.FAILED)
    assert len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid]) == 1
    assert worker.finished == ["error"]


def test_r9_late_stop_does_not_stop_the_new_session():
    """拿着 A 的 Session 迟到调用 request_stop（B 已在跑）：返回 False，B 不受影响"""
    gate = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        old_session = loop._current.session  # type: ignore[union-attr]
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a)
        worker.gate = None
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        out.clear()
        assert loop.request_stop(old_session, StopInfo("user")) is False
        assert out.ops == []
        assert loop.state().state is RunState.RUNNING
        gate.release.set()
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.release.set()
        loop.join(session_id=loop.state().session_id)


def test_r10_hook_ops_after_stop_are_dropped():
    """on_resume 还在跑时停止：返回的 paused=False / record 全部丢掉"""
    front = {"on": False}
    gate = Gate()
    worker = FakeWorker(needs_foreground=True)
    worker.resume_gate = gate
    worker.resume_ops = [
        ("bus", "live", {"running": True, "paused": False}),
        ("record", "FAKE", "采矿助手已继续", "", "", "INFO"),
    ]
    loop, _, out = make_loop(worker, foreground=lambda: front["on"])
    sid = None
    try:
        sid = _start(loop, worker)
        assert _wait_state(loop, RunState.PAUSED)
        front["on"] = True  # 回到游戏 → on_resume 卡在栅栏里
        assert gate.entered.wait(WAIT)
        out.clear()
        loop.request_stop_current(StopInfo("user"))  # 回调还没返回就停
        gate.release.set()
        assert loop.join(session_id=sid)
        assert {"running": True, "paused": False} not in out.live_events()
        assert not [op for op in out.records() if op[2] == "采矿助手已继续"]
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        if sid is not None:
            loop.join(session_id=sid)


def test_pure_output_commit_is_blocked_after_stop():
    """停止后只有输出的 commit 也被挡（竞争形式）"""
    loop, worker, out = make_loop()
    try:
        sid = _start(loop, worker)
        session = worker.session
        loop.request_stop_current(StopInfo("user"))
        out.clear()
        assert not loop.commit(session, ("bus", "log", {"task": "live"}))
        assert out.ops == []
        assert loop.join(session_id=sid)
    finally:
        loop.request_stop_current(StopInfo("user"))


def test_results_store_is_not_shared_between_sessions():
    """A 提交过结果，停掉开 B：B 的第一份结果照收（不比 seq），旧会话的迟到提交进不来"""
    results = ResultStore()
    worker = _Committer()
    loop, _, _ = make_loop(worker, results=results)
    try:
        sid_a = _start(loop, worker)
        assert _wait_until(
            lambda: (
                results.get(MINING_SCAN) is not None
                and _value(results, MINING_SCAN) == f"会话{sid_a}"
            ),
            5,
        )
        old = loop._current.session  # type: ignore[union-attr]
        loop.request_stop_current(StopInfo("user"))
        assert loop.join(session_id=sid_a)
        sid_b = _start(loop, worker)
        assert _wait_until(
            lambda: (
                results.get(MINING_SCAN) is not None
                and _value(results, MINING_SCAN) == f"会话{sid_b}"
            ),
            5,
        )
        assert not loop.commit(
            old,
            ("bus", "scan", {"rock": "旧"}),
            slot=MINING_SCAN,
            value="旧",
            stamp=None,
        )
    finally:
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_r11_shutdown_without_session_emits_nothing():
    """从未开启 / 已停止时 request_shutdown：不清 HUD、不发事件、不写 record"""
    loop, worker, out = make_loop()
    assert loop.request_shutdown() is None
    assert out.ops == [] and worker.calls == []
    # 已停止之后再退出：同样不发
    sid = _start(loop, worker)
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)
    out.clear()
    worker.calls.clear()
    assert loop.request_shutdown() is None
    assert out.ops == [] and worker.calls == []


def test_r12_setup_failure_paths():
    """setup 抛：第一次抛第二次成功 / 三次全抛 FAILED / 抛的同时外部停止不卡状态 / finish 抛照常收尾"""
    # 1) 第一次抛、第二次成功
    worker = FakeWorker(setup_fail_times=1, retries=2, wait=0.01)
    loop, _, out = make_loop(worker)
    try:
        sid = loop.start()
        assert sid is not None and _wait_until(
            lambda: any(c[0] == "tick" and c[1] == sid for c in worker.calls), 5
        )
        assert loop.state().state is RunState.RUNNING
        assert any("HOOK_ERROR setup" in op[1] for op in out.logs())
        assert [c for c in worker.calls if c[0] == "on_error"]
    finally:
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)

    # 2) 三次全抛 → FAILED、live 带 error、日志有 ERROR
    worker = _ErrorWorker(setup_fail_times=3, retries=3, wait=0.01)
    loop, _, out = make_loop(worker)
    out.clear()
    sid = loop.start()
    assert sid is not None and _wait_state(loop, RunState.FAILED)
    assert out.live_events()[-1]["error"]
    assert any(op[1].startswith("ERROR ") for op in out.logs())
    loop.request_stop_current(StopInfo("user"))

    # 3) setup 抛的同时外部按停止：状态不卡在 STARTING / RUNNING / STOPPING
    worker = FakeWorker(setup_fail_times=99, retries=3, wait=0.01)
    loop, _, _ = make_loop(worker)
    sid = loop.start()
    assert sid is not None
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid, timeout=5)
    assert loop.state().state in (RunState.STOPPED, RunState.FAILED)

    # 4) finish 抛异常：记 HOOK_ERROR，照样收尾、照样发「已停止」
    worker = FakeWorker(wait=0.01)

    def boom(session, ctx, info):
        raise RuntimeError("finish 坏了")

    worker.finish = boom  # type: ignore[method-assign]
    loop, _, out = make_loop(worker)
    sid = _start(loop, worker)
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)
    assert loop.state().state is RunState.STOPPED
    assert any("HOOK_ERROR finish" in op[1] for op in out.logs())
    assert out.live_events() == [{"running": False}]

    # 5) setup 抛错的同时按开启：不另开新会话，回的是同一个会话号；最终状态不卡
    worker = FakeWorker(setup_fail_times=1, retries=2, wait=0.01)
    loop, _, _ = make_loop(worker)
    sid = loop.start()
    assert sid is not None
    assert loop.start() == sid, "还在 STARTING：按开启应该回同一个会话"
    assert loop.state().session_id == sid
    assert _wait_state(loop, RunState.RUNNING)
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)


def test_finish_returning_a_bad_op_still_finishes():
    """finish 返回非法 op：记 HOOK_ERROR、当空列表，状态照常到 STOPPED、确认照常发一次（2-4）"""
    worker = FakeWorker(wait=0.01)
    worker.finish = lambda session, ctx, info: [("nope", 1)]  # type: ignore[method-assign]
    loop, _, out = make_loop(worker)
    sid = _start(loop, worker)
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)
    assert loop.state().state is RunState.STOPPED
    assert out.live_events() == [{"running": False}]
    assert any("HOOK_ERROR finish" in op[1] for op in out.logs())


def test_hook_error_log_is_written_outside_the_lock():
    """start_ops 返回非法 op：HOOK_ERROR 是锁后类，只能在放锁之后写（2-5）"""
    worker = FakeWorker()
    worker.start_ops = lambda session: [("nope",)]  # type: ignore[method-assign]
    loop, _, out = make_loop(worker)
    out.clear()
    sid = loop.start()
    assert sid is not None
    bad = [r for r in out.ops if r.op[0] == "log" and "HOOK_ERROR" in r.op[1]]
    assert bad, out.kinds()
    assert all(r.locked is False for r in bad), "锁后类 op 不能在持锁时执行"
    loop.request_stop_current(StopInfo("user"))
    loop.join(session_id=sid)


def test_no_session_stop_confirms_before_a_later_start():
    """没有会话时按停止再开新会话：确认先发（线性化），新会话的 HUD 不被清（2-6）"""
    loop, worker, out = make_loop()
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert len([c for c in worker.calls if c[0] == "stop_ops" and c[1] is None]) == 1
    assert out.live_events() == [{"running": False}]
    out.clear()
    sid = loop.start()
    assert sid is not None and _wait_state(loop, RunState.RUNNING)
    assert out.live_events() == [{"running": True}], "停止的确认不能落到新会话上"
    assert not [op for op in out.hud() if op[0] == "hud.clear"]
    loop.request_stop_current(StopInfo("user"))
    loop.join(session_id=sid)


def test_start_during_finish_output_does_not_orphan():
    """收尾还在锁外发 record 时线程仍活着：此时按开启不能造出一个没人管的线程（2-2）"""
    gate = Gate()
    loop, worker, out = make_loop()
    real_apply = out.apply

    def apply(op):
        if op[0] == "record":
            gate.hold()  # 卡在收尾的锁后类输出
        real_apply(op)

    out.apply = apply
    try:
        sid = _start(loop, worker)
        loop.request_stop_current(StopInfo("user"))
        assert gate.entered.wait(WAIT)
        assert loop.state().worker_alive, "线程还卡在收尾输出里"
        assert loop.start() is None, "收尾还没完，按开启必须被拒"
        assert loop.state().session_id == sid
        gate.release.set()
        assert _wait_state(loop, RunState.STOPPED)
        assert loop.start() is not None, "收尾完了就能开"
        assert loop.state().worker_alive  # 只有新会话一个线程活
        assert [p.session_id for p in loop.state().pending] == []
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_hooks_returning_none_or_a_generator_do_not_break_the_machine():
    """3-3：start_ops / stop_ops / finish 返回 None 或生成器：状态机照常走完、记 HOOK_ERROR、确认次数正确"""
    from astral_toolkit.runtime.session import StopInfo

    worker = FakeWorker(wait=0.01)
    worker.start_ops = lambda session: None  # type: ignore[method-assign]
    worker.stop_ops = lambda session, info: None  # type: ignore[method-assign]
    worker.finish = lambda session, ctx, info: None  # type: ignore[method-assign]
    loop, _, out = make_loop(worker)
    sid = _start(loop, worker)
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)
    assert loop.state().state is RunState.STOPPED
    assert (
        len([r for r in out.ops if r.op[0] == "log" and "HOOK_ERROR" in r.op[1]]) >= 2
    )

    # 生成器：op 不能被悄悄吞掉
    worker = FakeWorker(wait=0.01)
    worker.start_ops = lambda session: (
        op for op in [("bus", "live", {"running": True})]
    )  # type: ignore[method-assign]
    loop, _, out = make_loop(worker)
    out.clear()
    sid = loop.start()
    assert sid is not None and _wait_state(loop, RunState.RUNNING)
    assert out.live_events() == [{"running": True}], "生成器里的 op 也要发出来"
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)


def test_pending_thread_stays_visible_until_it_really_exits():
    """3-4①：被取代的旧线程发收尾输出时仍算在 pending；放行后清空，期间 can_start 拒绝"""
    gate_finish = Gate()
    gate_out = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    real_finish = worker.finish

    def finish(session, ctx, info):
        gate_finish.hold()
        return [*real_finish(session, ctx, info), ("log", "收尾", "FAKE")]

    worker.finish = finish  # type: ignore[method-assign]
    loop, _, out = make_loop(worker, join_timeout=0.02)
    real_apply = out.apply
    blocked = {"on": False}

    def apply(op):
        if blocked["on"] and op[0] == "log":
            gate_out.hold()  # 卡在收尾的锁后类输出
        real_apply(op)

    out.apply = apply
    try:
        sid_a = _start(loop, worker)
        loop.request_stop_current(StopInfo("user"))
        assert gate_finish.entered.wait(WAIT)
        assert not loop.join(session_id=sid_a)
        worker.gate = None
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        assert [p.session_id for p in loop.state().pending] == [sid_a]
        assert loop.can_start() is False, "旧线程还活着，不能再开"
        assert loop.state().worker_alive
        blocked["on"] = True
        gate_finish.release.set()  # A 走到 finally，卡在收尾输出里
        assert gate_out.entered.wait(WAIT)
        assert [p.session_id for p in loop.state().pending] == [sid_a], (
            "线程还在发收尾输出：必须还算在 pending 里"
        )
        assert loop.can_start() is False
        gate_out.release.set()
        assert _wait_until(lambda: not loop.state().pending, 5)
        assert loop.state().state is RunState.RUNNING
    finally:
        gate_finish.release.set()
        gate_out.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_superseded_during_finish_output_leaves_no_residue():
    """3-4②：当前会话在收尾输出期间被取代：放行后不留 pending、不多记「已开新会话」"""
    gate_out = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    loop, _, out = make_loop(worker, join_timeout=0.02)
    real_apply = out.apply
    blocked = {"on": False}

    def apply(op):
        if blocked["on"] and op[0] == "record":
            gate_out.hold()  # 卡在当前分支的收尾 record
        real_apply(op)

    out.apply = apply
    try:
        sid_a = _start(loop, worker)
        blocked["on"] = True
        loop.request_stop_current(StopInfo("user"))
        assert gate_out.entered.wait(WAIT), "收尾 record 应该卡住"
        assert not loop.join(session_id=sid_a)  # join 超时
        sid_b = loop.start()  # A 被取代，移进 pending
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        gate_out.release.set()  # A 走到最后一步
        assert _wait_until(lambda: not loop.state().pending, 5), "A 退出后不能残留"
        assert len([op for op in out.records() if "已开新会话" in op[2]]) == 1, (
            "只记一条，不能重复"
        )
        assert loop.state().state is RunState.RUNNING
        assert loop.state().session_id == sid_b
    finally:
        gate_out.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_start_after_stopped_thread_is_not_superseded():
    """已经写 STOPPED、线程还没退完：按开始直接开新会话，不进 pending、不记取代"""
    gate = Gate()
    worker = FakeWorker(wait=0.01)
    loop, _, out = make_loop(worker, join_timeout=0.02)
    old_hook = loop._finish_hook
    loop._finish_hook = gate.hold
    try:
        sid_a = _start(loop, worker)
        loop.request_stop_current(StopInfo("user"))
        assert gate.entered.wait(WAIT)
        assert loop.state().state is RunState.STOPPED
        assert loop.state().current_alive
        out.clear()
        sid_b = loop.start()
        assert sid_b is not None and sid_b != sid_a
        assert _wait_state(loop, RunState.RUNNING)
        assert loop.state().pending == ()
        assert not any("上次停止还没结束" in op[2] for op in out.records())
        assert (
            len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid_a]) == 1
        )
        gate.release.set()
        assert loop.state().session_id == sid_b
        loop.request_stop_current(StopInfo("user"))
        assert loop.join(session_id=sid_b)
    finally:
        loop._finish_hook = old_hook
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_join_of_a_running_session_only_times_out():
    """3-5：RUNNING 时 join 超时不起看门狗、不标停止超时；之后按停止 → 超时前 start 被拒、超时后能开"""
    gate = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        assert not loop.join(session_id=sid_a), "RUNNING 时 join 只应该超时"
        assert loop.state().stop_timeout is False
        assert loop.state().state is RunState.RUNNING
        assert not any("停止超时" in op[2] for op in out.records())
        assert loop.can_start() is False
        # 现在按停止：join 超时前按开始被拒
        loop.request_stop_current(StopInfo("user"))
        assert loop.start() is None
        assert not loop.join(session_id=sid_a)
        worker.gate = None
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        assert (
            len([c for c in worker.calls if c[0] == "stop_ops" and c[1] == sid_a]) == 1
        )
        gate.release.set()
        assert _wait_until(lambda: not loop.state().pending, 5)
        assert loop.state().state is RunState.RUNNING
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)
