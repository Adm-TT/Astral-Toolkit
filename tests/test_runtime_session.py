"""会话循环（设计稿 v3 §2）：状态机、提交边界、确认时机、run flag（RT-B3 遗留②④）

假 Worker + 假时钟，不靠 sleep、不起真读屏。竞争场景（R1–R10）在 test_runtime_session_race.py。
"""

import time

from tests.runtime_fakes import FakeClock, FakeWorker, Gate, make_loop
from astral_toolkit.runtime.results import MINING_SCAN
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


def _started(loop, worker):
    sid = loop.start()
    assert sid is not None and worker.started.wait(WAIT)
    assert _wait_state(loop, RunState.RUNNING), "工作线程没进 RUNNING"
    return sid


def _current_id(loop):
    """收尾用：当前会话号（没有就是 0）"""
    return loop.state().session_id


def _stop(loop, sid, info=None):
    loop.request_stop_current(info or StopInfo("user"))
    return loop.join(session_id=_current_id(loop))


def test_start_creates_session_and_publishes_running_inside_the_lock():
    loop, worker, out = make_loop()
    try:
        sid = _started(loop, worker)
        view = loop.state()
        assert sid == 1 and view.session_id == 1 and view.epoch == 0  # 启动不增 epoch
        assert view.state in (RunState.STARTING, RunState.RUNNING)
        assert loop.running()
        assert out.live_events() == [{"running": True}]
        assert all(r.locked for r in out.ops), "start_ops 必须在锁里套用"
    finally:
        _stop(loop, _current_id(loop))


def test_start_is_idempotent_for_same_payload_and_rejects_a_different_one():
    loop, worker, out = make_loop()
    try:
        sid = loop.start("甲")
        assert worker.started.wait(WAIT)
        assert loop.start("甲") == sid
        assert loop.start("乙") is None
        assert out.live_events() == [{"running": True}]
    finally:
        _stop(loop, _current_id(loop))


def test_start_refused_while_closing():
    closing = {"on": False}
    loop, worker, _ = make_loop(closing=lambda: closing["on"])
    try:
        sid = loop.start()
        assert worker.started.wait(WAIT) and sid is not None
        closing["on"] = True
        assert loop.can_start() is False
        _stop(loop, _current_id(loop))
        assert loop.start() is None
    finally:
        closing["on"] = False
        loop.request_stop_current(StopInfo("user"))


def test_request_stop_does_not_confirm_until_the_thread_exits():
    """「已停止」只由工作线程 finally 发，不在 request_stop 里立刻发"""
    gate = Gate()
    worker = FakeWorker()
    worker.gate = gate
    loop, _, out = make_loop(worker)
    try:
        _started(loop, worker)
        assert gate.entered.wait(WAIT)  # 卡在 tick 里
        loop.request_stop_current(StopInfo("user"))
        out.clear()
        assert loop.state().state is RunState.STOPPING
        assert not loop.running()
        assert out.ops == [], "线程还没退，不该发「已停止」"
        gate.release.set()
        assert loop.join(session_id=_current_id(loop))
        assert out.live_events() == [{"running": False}]
        assert [op[2] for op in out.records()] == ["引擎已停止"]
        assert all(r.locked for r in out.ops if r.op[0] != "record"), (
            "收尾事件在锁里套用；record 是锁后类"
        )
        assert _wait_state(loop, RunState.STOPPED)
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))
        loop.join(session_id=_current_id(loop))


def test_request_stop_is_idempotent_and_confirms_once():
    # 两次按停止时线程得还在：卡在 tick 里按，两次都按完才放（11-06 全量偶发挂过一次：机器忙时第一次按完
    # 假工作线程已经退完、状态变 STOPPED，第二次按成了「没有在跑的会话」，照 dev 又发一次确认）
    gate = Gate()
    worker = FakeWorker()
    worker.gate = gate
    loop, _, out = make_loop(worker)
    try:
        _started(loop, worker)
        assert gate.entered.wait(WAIT)
        out.clear()
        loop.request_stop_current(StopInfo("user"))
        loop.request_stop_current(StopInfo("user"))
        gate.release.set()
        assert loop.join(session_id=_current_id(loop))
        assert worker.last_stop_info.reason == "user"
        assert out.live_events() == [{"running": False}]
        assert len(out.records()) == 1
        # 停了再按：没有在跑的会话，也照 dev 发一次确认（每按一次一次）
        out.clear()
        loop.request_stop_current(StopInfo("user"))
        assert worker.calls[-1][0] == "stop_ops" and worker.calls[-1][1] is None
        assert out.live_events() == [{"running": False}]
    finally:
        gate.release.set()
        loop.request_stop_current(StopInfo("user"))


def test_late_request_stop_for_old_session_is_refused():
    loop, worker, out = make_loop(worker=FakeWorker(restart_while_stopping=True))
    try:
        first = loop.start()
        assert first is not None and worker.started.wait(WAIT)
        session_id = first
        gate_session = loop._current.session  # type: ignore[union-attr]
        loop.request_stop(gate_session, StopInfo("user"))
        loop.join(session_id=session_id)
        second = _started(loop, worker)
        out.clear()
        assert loop.request_stop(gate_session, StopInfo("user")) is False
        assert out.ops == []
        assert loop.state().session_id == second
    finally:
        _stop(loop, loop.state().session_id)


def test_state_view_pending_and_worker_alive():
    """join 超时：会话留在「当前」、状态 STOPPING、stop_timeout 为真；线程退出后转 STOPPED"""
    gate = Gate()
    worker = FakeWorker()
    worker.gate = gate
    loop, _, _ = make_loop(worker, join_timeout=0.02)
    try:
        _started(loop, worker)
        assert gate.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        assert not loop.join(session_id=_current_id(loop)), "线程卡着，join 应该超时"
        view = loop.state()
        assert view.state is RunState.STOPPING and view.worker_alive
        assert view.prev_stop_pending
        assert view.pending == (), "join 超时不把当前会话挪进 pending（v4）"
        assert _wait_until(lambda: loop.state().stop_timeout), "看门狗要标 stop_timeout"
        gate.release.set()
        assert _wait_state(loop, RunState.STOPPED)
        assert _wait_until(lambda: not loop.state().stop_timeout)
        assert not loop.state().worker_alive
    finally:
        gate.release.set()
        loop.join(session_id=_current_id(loop))


def test_join_all_waits_for_pending_and_reports_the_stuck():
    gate = Gate()
    worker = FakeWorker()
    worker.gate = gate
    loop, _, _ = make_loop(worker, join_timeout=0.02)
    try:
        sid = _started(loop, worker)
        assert gate.entered.wait(WAIT)
        loop.request_stop_current(StopInfo("user"))
        still = loop.join_all(0.02)
        assert [p.session_id for p in still] == [sid]
        gate.release.set()
        assert loop.join(session_id=_current_id(loop))
        assert loop.join_all(0.5) == []
    finally:
        gate.release.set()
        loop.join(session_id=_current_id(loop))


def test_commit_accepts_current_session_and_requires_a_stamp_for_a_slot():
    loop, worker, out = make_loop()
    try:
        sid = _started(loop, worker)
        session = worker.session
        stamp = loop.stamp(session, 1.0)
        assert stamp is not None and stamp.session_id == sid
        out.clear()
        assert loop.commit(session, ("bus", "scan", {"rock": "铜"}))
        assert loop.commit(
            session,
            ("bus", "scan", {"rock": "铜"}),
            slot=MINING_SCAN,
            value="铜",
            stamp=stamp,
        )
        assert loop._results.get(MINING_SCAN).value == "铜"  # type: ignore[union-attr]
        assert len(out.published("scan")) == 2
        # 带 slot 却没有 stamp：False，什么都不做
        out.clear()
        assert not loop.commit(session, slot=MINING_SCAN, value="没表")
        assert out.ops == []
    finally:
        _stop(loop, _current_id(loop))


def test_commit_rejects_wrong_session_state_and_old_epoch():
    loop, worker, out = make_loop()
    try:
        _started(loop, worker)
        session = worker.session
        old = loop.stamp(session, 1.0)
        assert old is not None
        loop.config_changed()
        out.clear()
        assert not loop.commit(
            session,
            ("bus", "scan", {"rock": "旧配装"}),
            slot=MINING_SCAN,
            value="旧",
            stamp=old,
        )
        assert out.ops == []
        assert loop._results.get(MINING_SCAN) is None  # type: ignore[attr-defined]
        new = loop.stamp(session, 2.0)
        assert new is not None and new.epoch == old.epoch + 1
        assert loop.commit(
            session,
            ("bus", "scan", {"rock": "新"}),
            slot=MINING_SCAN,
            value="新",
            stamp=new,
        )
    finally:
        _stop(loop, _current_id(loop))


def test_stamp_refused_after_the_session_ended():
    """RT-B3 遗留④：旧线程停完才来取 stamp → None，不生成序号"""
    loop, worker, out = make_loop()
    try:
        _started(loop, worker)
        assert worker.ticked.wait(WAIT), "第一次 tick 还没记下会话"
        session = worker.session
        assert loop.stamp(session, 1.0) is not None
        assert _stop(loop, _current_id(loop)) is True
        out.clear()
        assert loop.stamp(session, 2.0) is None
        assert out.ops == []
    finally:
        loop.request_stop_current(StopInfo("user"))


def test_config_changed_bumps_epoch_and_config_rev():
    loop, worker, _ = make_loop()
    try:
        _started(loop, worker)
        epoch, rev = loop.state().epoch, loop.config_rev
        loop.config_changed()
        assert loop.state().epoch == epoch + 1 and loop.config_rev == rev + 1
    finally:
        _stop(loop, _current_id(loop))


def test_freshness_tracks_each_channel():
    clock = FakeClock()
    worker = FakeWorker(stale_after={"panel": 20.0, "signals": 20.0})
    loop, _, _ = make_loop(worker, clock=clock)
    try:
        _started(loop, worker)
        assert loop.freshness("panel") is Freshness.FRESH  # 尝试开始就记「刚看到」
        assert loop.freshness("signals") is Freshness.FRESH
        assert loop.freshness("nope") is Freshness.EMPTY
    finally:
        _stop(loop, _current_id(loop))


def test_run_flag_is_written_by_the_loop_and_never_backwards():
    saved = []
    flag = RunFlag("live_on", lambda key, value: saved.append((key, value)))
    loop, worker, _ = make_loop(run_flag=flag)
    try:
        _started(loop, worker)
        assert saved == [("live_on", True)]
        loop.request_stop_current(StopInfo("user"))
        assert loop.join(session_id=_current_id(loop))
        assert saved == [("live_on", True), ("live_on", False)]
        # 没有在跑的会话时按停止：期望值已经是 False，不重复写盘（也不会写回 True）
        saved.clear()
        loop.request_stop_current(StopInfo("user"))
        assert saved == []
    finally:
        loop.request_stop_current(StopInfo("user"))


def test_shutdown_stop_does_not_touch_the_run_flag():
    saved = []
    flag = RunFlag("live_on", lambda key, value: saved.append((key, value)))
    loop, worker, _ = make_loop(run_flag=flag)
    try:
        _started(loop, worker)
        loop.request_stop_current(StopInfo("shutdown"))
        assert loop.join(session_id=_current_id(loop))
        assert saved == [("live_on", True)], "shutdown 不改 live_on"
    finally:
        loop.request_stop_current(StopInfo("user"))


def test_lock_held_by_me():
    loop, worker, _ = make_loop()
    assert loop.lock_held_by_me() is False
    with loop._lock:
        assert loop.lock_held_by_me() is True
    assert loop.lock_held_by_me() is False


def test_session_payload_is_immutable_and_used_for_idempotency():
    loop, worker, _ = make_loop()
    try:
        sid = loop.start({"hotkey": "F5"})
        assert worker.started.wait(WAIT)
        session = loop._current.session  # type: ignore[union-attr]
        assert isinstance(session, Session) and session.payload == {"hotkey": "F5"}
        assert session.alive()
        assert loop.start({"hotkey": "F5"}) == sid
    finally:
        _stop(loop, _current_id(loop))


def test_output_records_are_post_lock_and_hud_is_in_lock():
    """run_records / log 是锁后类：套用时锁已经放开"""
    worker = FakeWorker(
        stop_ops_list=[("hud.clear", "信号"), ("record", "FAKE", "停了")]
    )
    loop, _, out = make_loop(worker)
    try:
        _started(loop, worker)
        loop.request_stop_current(StopInfo("user"))
        assert loop.join(session_id=_current_id(loop))
        kinds = [r.op[0] for r in out.ops]
        assert kinds.index("hud.clear") < kinds.index("record")
        assert out.ops[kinds.index("hud.clear")].locked is True
        assert out.ops[kinds.index("record")].locked is False
    finally:
        loop.request_stop_current(StopInfo("user"))
