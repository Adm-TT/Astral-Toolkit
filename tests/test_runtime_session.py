"""会话循环（设计稿 §2）：状态机、提交边界（RT-B3 遗留②④）

假 Worker + 假时钟，不靠 sleep、不起真读屏。计时相关的竞争场景在 test_runtime_session_race.py。
"""

import time

from tests.runtime_fakes import FakeWorker, make_loop
from astral_toolkit.runtime.results import MINING_SCAN, MINING_SIGNALS
from astral_toolkit.runtime.session import Freshness, RunState

WAIT = 10


def _started(loop, worker):
    sid = loop.start()
    assert worker.started.wait(WAIT), "工作线程没起来"
    return sid


def _wait_until(predicate, timeout=WAIT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return False


def test_start_creates_a_session_and_publishes_running_inside_the_lock():
    loop, worker, out = make_loop()
    try:
        sid = _started(loop, worker)
        view = loop.state()
        assert sid == 1 and view.session_id == 1
        assert view.state in (RunState.STARTING, RunState.RUNNING)
        assert loop.running()
        assert out.live_events() == [{"running": True}]
        assert all(c.locked for c in out.calls if c.op == "publish")
    finally:
        loop.request_stop("user")
        loop.join()


def test_start_while_running_is_idempotent():
    loop, worker, out = make_loop()
    try:
        sid = _started(loop, worker)
        assert loop.start() == sid
        assert loop.start() == sid
        assert out.live_events() == [{"running": True}]
    finally:
        loop.request_stop("user")
        loop.join()


def test_request_stop_applies_finish_ops_inside_the_lock():
    worker = FakeWorker()
    worker.finish_ops = lambda session, reason: [  # type: ignore[method-assign]
        ("hud.clear", "信号"),
        ("bus", "scan_hint", {"why": "", "text": ""}),
        ("bus", "live", {"running": False}),
    ]
    loop, _, out = make_loop(worker)
    try:
        _started(loop, worker)
        out.clear()
        loop.request_stop("user")
        assert loop.join()
        assert loop.state().state == RunState.STOPPED
        assert not loop.running()
        assert [(c.op, c.args) for c in out.calls] == [
            ("hud_clear", ("信号",)),
            ("publish", ("scan_hint", {"why": "", "text": ""})),
            ("publish", ("live", {"running": False})),
        ]
        assert all(c.locked for c in out.calls), "收尾事件必须在锁里发（RT-B3 遗留②）"
    finally:
        loop.request_stop("user")
        loop.join()


def test_request_stop_twice_finishes_once():
    loop, worker, out = make_loop()
    try:
        _started(loop, worker)
        loop.request_stop("user")
        loop.join()
        out.clear()
        loop.request_stop("user")
        assert loop.join()
        assert out.calls == []
        assert worker.finished == ["user"]
    finally:
        loop.join()


def test_commit_accepts_result_of_current_session_and_applies_ops_in_lock():
    loop, worker, out = make_loop()
    try:
        _started(loop, worker)
        session = worker.session
        stamp = loop.stamp(session, 1.0)
        assert stamp is not None and stamp.session_id == session.id
        out.clear()
        assert loop.commit(
            session,
            ("bus", "scan", {"rock": "铜"}),
            slot=MINING_SCAN,
            value="铜",
            stamp=stamp,
        )
        entry = loop._results.get(MINING_SCAN)  # type: ignore[attr-defined]
        assert entry is not None and entry.value == "铜"
        assert out.published("scan") == [("scan", {"rock": "铜"})]
        assert all(c.locked for c in out.calls)
    finally:
        loop.request_stop("user")
        loop.join()


def test_commit_rejects_finished_session_and_old_epoch():
    loop, worker, out = make_loop()
    try:
        _started(loop, worker)
        old = worker.session
        old_stamp = loop.stamp(old, 1.0)
        loop.request_stop("user")
        loop.join()
        out.clear()
        assert not loop.commit(old, slot=MINING_SCAN, value="迟到", stamp=old_stamp)
        # 停了马上开新会话：旧会话的东西一条都不发
        _started(loop, worker)
        assert not loop.commit(
            old,
            ("bus", "scan", {"rock": "旧"}),
            slot=MINING_SCAN,
            value="旧",
            stamp=old_stamp,
        )
        assert out.published("scan") == []
        assert loop._results.get(MINING_SCAN) is None  # type: ignore[attr-defined]
        # 新会话取 stamp，配装一变，旧 epoch 作废
        new = worker.session
        stamp = loop.stamp(new, 2.0)
        loop.config_changed()
        assert not loop.commit(
            new,
            ("bus", "scan", {"rock": "旧配装"}),
            slot=MINING_SCAN,
            value="旧配装",
            stamp=stamp,
        )
        assert out.published("scan") == []
    finally:
        loop.request_stop("user")
        loop.join()


def test_stamp_is_refused_after_the_session_ended():
    """RT-B3 遗留④：旧线程停完才来取 stamp —— 第一层在循环这里挡住，不生成序号"""
    loop, worker, out = make_loop()
    try:
        _started(loop, worker)
        session = worker.session
        assert loop.stamp(session, 1.0) is not None
        loop.request_stop("user")
        loop.join()
        out.clear()
        assert loop.stamp(session, 2.0) is None
        assert out.calls == []
    finally:
        loop.join()


def test_config_changed_bumps_epoch_for_later_stamps():
    loop, worker, _ = make_loop()
    try:
        _started(loop, worker)
        first = loop.state().epoch
        loop.config_changed()
        assert loop.state().epoch == first + 1
        assert loop.stamp(worker.session, 1.0).epoch == first + 1  # type: ignore[union-attr]
    finally:
        loop.request_stop("user")
        loop.join()


def test_only_outputs_commit_needs_the_current_session():
    loop, worker, out = make_loop()
    try:
        _started(loop, worker)
        session = worker.session
        assert loop.commit(session, ("log", "一行日志", "LIVE"))
        assert out.calls[-1].op == "log"
        loop.request_stop("user")
        loop.join()
        assert not loop.commit(session, ("log", "迟到", "LIVE"))
    finally:
        loop.join()


def test_state_view_reports_worker_alive_and_stop_reason():
    loop, worker, _ = make_loop()
    try:
        _started(loop, worker)
        assert _wait_until(lambda: loop.state().worker_alive)
        assert loop.state().stop_reason is None
        loop.request_stop("user")
        loop.join()
        view = loop.state()
        assert not view.worker_alive and view.stop_reason == "user"
        assert view.state == RunState.STOPPED
    finally:
        loop.join()


def test_freshness_starts_empty_and_tracks_slots():
    loop, worker, _ = make_loop()
    try:
        _started(loop, worker)
        assert loop.freshness(MINING_SCAN) is Freshness.EMPTY
        assert loop.freshness(MINING_SIGNALS) is Freshness.EMPTY
    finally:
        loop.request_stop("user")
        loop.join()
