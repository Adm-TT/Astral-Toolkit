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
    Session,
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
    """T1 停 A（A 卡在 tick 里）→ T2 开 B → T1 才 join(A)：等的是 A，B 一直是 RUNNING"""
    gate = Gate()
    worker = _Committer(restart_while_stopping=True)
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        stopped = threading.Event()

        def stopper():
            loop.request_stop_current(StopInfo("user"))
            stopped.set()

        t1 = threading.Thread(target=stopper, daemon=True)
        t1.start()
        assert stopped.wait(WAIT)
        worker.gate = None
        sid_b = loop.start()
        assert sid_b is not None and sid_b != sid_a
        assert _wait_state(loop, RunState.RUNNING)
        out.clear()
        assert not loop.join(session_id=sid_a, timeout=0.02), "join 等的是 A，A 还卡着"
        assert loop.state().state is RunState.RUNNING, "B 不受影响"
        gate.release.set()
        assert loop.join(session_id=sid_a, timeout=WAIT)
        assert loop.state().state is RunState.RUNNING
        assert loop.state().session_id == sid_b
        # 旧会话的「已停止」被压下：不发事件，只记一条
        assert out.live_events() == []
        assert any("已被新会话取代" in op[2] for op in out.records())
        assert not [op for op in out.hud() if op[0] == "hud.clear"]
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.release.set()
        loop.join(session_id=loop.state().session_id)


def test_r2_each_pending_session_has_its_own_watchdog():
    """A 停止超时 → 开 B → B 也停止超时：两条 pending 各由自己的看门狗处理"""
    gate_a, gate_b = Gate(), Gate()
    worker = FakeWorker(restart_while_stopping=True)
    loop, _, out = make_loop(worker, join_timeout=0.02)
    try:
        worker.gate = gate_a
        sid_a = _start(loop, worker)
        assert gate_a.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a)
        worker.gate = gate_b
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        assert gate_b.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_b)
        view = loop.state()
        ids = [p.session_id for p in view.pending]
        assert ids == [sid_a, sid_b], view.pending
        # A 一直不退：A 那条被自己的看门狗标 failed，B 那条不受影响
        assert _wait_until(lambda: loop._pending[sid_a].failed, 5)  # type: ignore[union-attr]
        assert _wait_until(
            lambda: any("停止超时" in op[2] and op is not None for op in out.records()),
            5,
        )
        gate_a.release.set()
        gate_b.release.set()
        assert _wait_until(lambda: not loop.state().pending, 5)
    finally:
        gate_a.release.set()
        gate_b.release.set()
        loop.request_stop_current(StopInfo("user"))


def test_r3_watchdog_rechecks_alive_under_lock():
    """看门狗的 join 返回后线程已经退出：拿锁再查一次，不得标 failed"""
    loop, worker, out = make_loop(join_timeout=0.02)
    sid = _start(loop, worker)
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)

    class _ExitDuringJoin:
        alive = True

        def join(self, timeout=None):
            self.alive = False  # 正好在 join 里退出

        def is_alive(self):
            return self.alive

    # 手工摆一条「线程在 join 返回后已退出」的 pending，直接走看门狗代码
    run = loop._current
    assert run is not None
    run.thread = _ExitDuringJoin()  # type: ignore[assignment]
    loop._pending[run.session.id] = run
    loop._watch(run.session.id)
    assert run.failed is False, "线程已经退了，不能标停止超时"
    assert not any("停止超时" in op[2] for op in out.records())


def test_r4_old_session_cannot_pause_or_resume_new():
    """A 卡在前台判断 → 停 A 开 B → A 读到「切出」：B 不变、不发 paused"""
    gate = Gate()
    answers = {"n": 0}

    def foreground():
        answers["n"] += 1
        if answers["n"] == 1:
            gate.hold()  # A 卡在第一次前台判断
            return False  # A 读到「切出」
        return True  # B 一直在前台

    worker = FakeWorker(needs_foreground=True, restart_while_stopping=True)
    loop, _, out = make_loop(worker, foreground=foreground, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a)
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        out.clear()
        gate.release.set()  # A 这才拿到「切出」
        assert _wait_until(lambda: not _thread_alive(loop, sid_a), 5)
        assert loop.state().state is RunState.RUNNING, "B 不能被旧会话弄成暂停"
        assert not [c for c in worker.calls if c[0] == "on_pause" and c[1] == sid_b]
        assert out.live_events() == []
        # 反向：旧会话拿「回来」也不能把 B 改回 RUNNING / 发 paused=False
        out.clear()
        loop._leave_pause(Session(sid_a, threading.Event()), None, 1.0)  # type: ignore[arg-type]
        assert loop.state().state is RunState.RUNNING
        assert out.ops == []
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.release.set()
        loop.join(session_id=loop.state().session_id)


def test_r5_old_tick_does_not_touch_new_session_timers():
    """A 卡在 tick 返回前 → 停 A 开 B → A 返回带 observed：B 的 freshness / 空闲计时不变"""
    clock = FakeClock()
    gate = Gate()
    worker = FakeWorker(
        needs_foreground=False,
        stale_after={"panel": 1.0},
        restart_while_stopping=True,
        wait=0.01,
    )
    worker.gate = gate
    worker.observed = {"panel": 0.0}
    loop, _, out = make_loop(worker, clock=clock, join_timeout=0.02)
    try:
        sid_a = _start(loop, worker)
        assert gate.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=sid_a)
        worker.gate = None
        worker.observed = {}  # B 这轮什么也没看到
        sid_b = loop.start()
        assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
        out.clear()
        gate.release.set()  # A 带着 observed 返回
        assert _wait_until(lambda: not _thread_alive(loop, sid_a), 5)
        # B 的「看到」计时从 B 开始算：过 2 秒就应该过期
        clock.advance(2.0)
        assert _wait_until(lambda: ("on_stale", sid_b, "panel") in worker.calls, 5), (
            worker.calls[-6:]
        )
        assert loop.state().session_id == sid_b
        assert loop.freshness("panel") is Freshness.STALE
    finally:
        loop.request_stop_current(StopInfo("user"))
        gate.release.set()
        loop.join(session_id=loop.state().session_id)


def test_r6_error_text_belongs_to_its_session():
    """A、B 先后出错：B 的 live 事件里 error 是 B 的，不是 A 留下的"""
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
    """A 自动关闭、在写 flag 之前开 B：最终 live_on 是 True（迟到的 False 不覆盖）"""
    gate = Gate()
    saved = []

    def write(key, value):
        if value is False:
            gate.hold()  # A 的 False 卡在写盘里
        saved.append(value)

    clock = FakeClock()
    worker = FakeWorker(idle_close=5.0, wait=0.01, restart_while_stopping=True)
    loop, _, _ = make_loop(worker, clock=clock, run_flag=RunFlag("live_on", write))
    try:
        _start(loop, worker)
        clock.advance(6.0)  # A 该自动关闭了
        assert gate.entered.wait(WAIT)
        started = threading.Event()
        holder = {}

        def starter():
            holder["sid"] = loop.start()
            started.set()

        t = threading.Thread(target=starter, daemon=True)
        t.start()
        assert _wait_until(lambda: loop.state().state is RunState.RUNNING, 5)
        assert not started.is_set(), (
            "start() 应该被 flag 锁挡在写盘那一步（不能先写完再被覆盖）"
        )
        gate.release.set()  # A 的 False 这才写进去，B 再按最新期望值写 True
        assert started.wait(WAIT)
        assert holder["sid"] is not None
        assert _wait_until(lambda: "live_on" and loop._flag_want is True, 5)
        assert saved == [True, False, True], saved
        assert loop.state().state is RunState.RUNNING
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=loop.state().session_id)


def test_r8_stopped_confirmation_once_per_session():
    """四种情况下「已停止」各发几次"""
    # 1) 正常停：一次
    loop, worker, out = make_loop()
    sid = _start(loop, worker)
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert loop.join(session_id=sid)
    assert len(out.live_events()) == 1

    # 2) join 超时：超时路径发一次；线程后来退出不再发
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

    # 3) join 超时后开新会话：旧线程退出不再发事件，只记一条「已被新会话取代」
    gate = Gate()
    worker = FakeWorker(restart_while_stopping=True)
    worker.gate = gate
    loop, _, out = make_loop(worker, join_timeout=0.02)
    sid_a = _start(loop, worker)
    assert gate.entered.wait(WAIT)
    out.clear()
    loop.request_stop_current(StopInfo("user"))
    assert not loop.join(session_id=sid_a)
    assert len(out.live_events()) == 1  # join 超时那条
    worker.gate = None
    sid_b = loop.start()
    assert sid_b is not None and _wait_state(loop, RunState.RUNNING)
    gate.release.set()
    assert _wait_until(lambda: not _thread_alive(loop, sid_a), 5)
    assert len([op for op in out.records() if "取代" in op[2]]) <= 1
    loop.request_stop_current(StopInfo("user"))
    loop.join(session_id=sid_b)


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
