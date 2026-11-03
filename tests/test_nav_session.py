"""RT-B5b：导航外层、Worker 纯函数输出、拒绝路径、锁序与 bind 无副作用的显式断言"""

import threading
import time
from types import SimpleNamespace

from astral_toolkit.app.engines import nav as navmod
from astral_toolkit.runtime.session import RunState, Session, StopAttempt, StopInfo


class _FakePos:
    def __init__(self):
        self.current = (time.time(), None, None)
        self.latest = (0.0, None, None)
        self.read_at = 0.0
        self.reader_active = False
        self.reader_ok_at = 0.0
        self.calls = []
        self.demand = []
        self.hint = {"zone": "", "location": "", "solar_id": ""}

    def snapshot(self):
        return SimpleNamespace(
            current=self.current,
            latest=self.latest,
            read_at=self.read_at,
            reader_active=self.reader_active,
            reader_ok_at=self.reader_ok_at,
        )

    def request_read_now(self):
        self.calls.append("read")

    def set_demand(self, key, until):
        self.demand.append((key, until))

    def hints(self, max_age=5.0):
        return dict(self.hint)


class _FakeCam:
    def check(self, cam, fast=False):
        return cam


class _FakeLoop:
    def __init__(self, worker, **kwargs):
        self.worker = worker
        self.kwargs = kwargs
        self.session_id = 0
        self.state_val = RunState.STOPPED
        self.prev_stop_pending = False
        self.joined = []
        self.started = []
        self.stop_calls = []
        self.none_stop_calls = []
        self.reject_start = False
        self.join_result = True
        self.assert_not_fix_locked = None

    def state(self):
        return SimpleNamespace(
            state=self.state_val,
            session_id=self.session_id,
            prev_stop_pending=self.prev_stop_pending,
            current_alive=self.state_val
            in (
                RunState.STARTING,
                RunState.RUNNING,
                RunState.PAUSED,
                RunState.STOPPING,
            ),
            stop_timeout=False,
            pending=(),
        )

    def running(self):
        return self.state_val in (
            RunState.STARTING,
            RunState.RUNNING,
            RunState.PAUSED,
        )

    def request_stop_current(self, info):
        self._check_lock()
        self.stop_calls.append(info)
        if self.state_val in (
            RunState.STARTING,
            RunState.RUNNING,
            RunState.PAUSED,
            RunState.STOPPING,
        ):
            self.state_val = RunState.STOPPING
            return self.session_id
        self.none_stop_calls.append(info)
        return None

    def request_shutdown(self):
        self._check_lock()
        return self.request_stop_current(StopInfo("shutdown"))

    def join(self, timeout=None, *, session_id):
        self._check_lock()
        self.joined.append(session_id)
        if self.join_result:
            self.state_val = RunState.STOPPED
            self.prev_stop_pending = False
        return self.join_result

    def start(self, payload):
        self._check_lock()
        if self.reject_start:
            return None
        self.session_id += 1
        self.started.append(payload)
        self.state_val = RunState.RUNNING
        self.prev_stop_pending = False
        return self.session_id

    def _check_lock(self):
        if self.assert_not_fix_locked is not None:
            assert not self.assert_not_fix_locked.locked()


def _make_nav(monkeypatch):
    pos = _FakePos()
    loop_holder = {}
    nav = navmod._Nav(
        pos,
        _FakeCam(),
        None,
        None,
        output=object(),
        _loop_factory=lambda worker, **kw: loop_holder.setdefault(
            "loop", _FakeLoop(worker, **kw)
        ),
    )
    loop = loop_holder["loop"]
    loop.assert_not_fix_locked = nav.fix_lock
    return nav, pos, loop


def test_stop_ops_compat_user_and_error():
    pos = _FakePos()
    worker = navmod._NavWorker(pos, _FakeCam(), threading.Lock())
    row = {"key": "x", "label": "目标"}
    session = Session(9, threading.Event(), navmod.NavPayload({"n": "X"}, row, False))

    assert worker.stop_ops(session, StopInfo("user")) == [
        ("hud.clear", "导航"),
        ("bus", "nav", {"active": False}),
    ]

    bus_op, hud_op = worker.stop_ops(session, StopInfo("error", "坏了"))
    assert bus_op == (
        "bus",
        "nav",
        {
            "active": True,
            "target": row,
            "here": None,
            "msgs": [],
            "status": "导航出错：坏了（重新开始导航试试）",
            "help": "",
        },
    )
    assert hud_op == ("hud.set", "导航", "导航出错：坏了")


def test_start_success_sets_shell_and_demand_without_fix_lock(monkeypatch):
    nav, pos, loop = _make_nav(monkeypatch)
    target = {"n": "X", "b": "Daymar", "t": "Planet", "qt": 0}
    row = {"key": "x", "label": "X"}
    result = nav.start(target, target_row=row, space_mode=False)
    assert result.status == "started"
    assert result.session_id == 1
    assert nav.target is target and nav.space_mode is False
    assert pos.demand[-1] == ("nav", float("inf"))
    assert "read" in pos.calls
    assert loop.started[0].target_row is row


def test_start_rejects_while_stopping_and_keeps_target(monkeypatch):
    nav, pos, loop = _make_nav(monkeypatch)
    loop.state_val = RunState.STOPPING
    loop.prev_stop_pending = True
    loop.session_id = 7
    result = nav.start(
        {"n": "X", "b": "Daymar", "t": "Planet", "qt": 0},
        target_row={"key": "x"},
        space_mode=False,
    )
    assert result.status == "busy_stopping"
    assert nav.target is None
    assert loop.started == []


def test_add_fix_rejects_old_session(monkeypatch):
    nav, pos, loop = _make_nav(monkeypatch)
    nav.target = {"n": "X", "b": "Daymar", "t": "Planet", "qt": 0}
    nav.space_mode = True
    loop.session_id = 5
    loop.state_val = RunState.RUNNING
    assert nav.add_fix((1, 2, 3), "clip", session=4) is None


def test_marker_draws_under_marker_lock_after_commit(monkeypatch):
    pos = _FakePos()
    lock = threading.Lock()
    worker = navmod._NavWorker(pos, _FakeCam(), lock)
    session = Session(
        1, threading.Event(), navmod.NavPayload({"n": "X"}, {"key": "x"}, True)
    )
    seen = {}

    class M:
        @staticmethod
        def _marker_tick(target, data, state, mk_seen, ref):
            seen["locked"] = lock.locked()
            return 42

    monkeypatch.setattr(navmod, "_T", lambda name: M)
    ctx = SimpleNamespace(mk_seen=None)
    got = worker._marker_after_commit(session, ctx, "t", {}, {}, None)
    assert got == 42
    assert seen["locked"] is True


def test_navigation_bind_required():
    from astral_toolkit.tasks import navigation as nt

    old = nt._nav, nt._pos, nt._game_events, nt._results
    try:
        nt._nav = nt._pos = nt._game_events = nt._results = None
        try:
            nt._engines()
        except RuntimeError as exc:
            assert "未绑定" in str(exc)
        else:
            raise AssertionError("未绑定时应抛 RuntimeError")
    finally:
        nt._nav, nt._pos, nt._game_events, nt._results = old


def test_nav_start_does_not_record_when_start_rejected(monkeypatch):
    from astral_toolkit.core import run_records
    from astral_toolkit.tasks import navigation as nt

    records = []

    class N:
        target = None
        space_mode = False

        def start(self, target, target_row=None, space_mode=None):
            return navmod.NavStart(None, "busy_stopping")

    monkeypatch.setattr(nt, "_nav", N())
    monkeypatch.setattr(nt, "_pos", object())
    monkeypatch.setattr(nt, "_game_events", object())
    monkeypatch.setattr(nt, "_results", object())
    monkeypatch.setattr(nt, "_place_row", lambda p: {"key": "k"})
    monkeypatch.setattr(run_records, "record", lambda *a, **k: records.append(a))
    nt._places["k"] = {"b": "Daymar", "t": "Planet", "n": "X", "qt": 0}
    assert nt.nav_start("k") == {"error": "导航正在停止，请稍候"}
    assert records == []


def test_nav_stop_timeout_message(monkeypatch):
    from astral_toolkit.core import run_records
    from astral_toolkit.tasks import navigation as nt

    class N:
        def stop(self):
            return StopAttempt(1, False, True)

    monkeypatch.setattr(nt, "_nav", N())
    monkeypatch.setattr(nt, "_pos", object())
    monkeypatch.setattr(nt, "_game_events", object())
    monkeypatch.setattr(nt, "_results", object())
    monkeypatch.setattr(run_records, "record", lambda *a, **k: None)
    assert nt.nav_stop() == {
        "ok": True,
        "stopping": True,
        "message": "正在停止导航，旧线程还没退出",
    }


def _fix_worker():
    import threading

    from astral_toolkit.app.engines import nav as nav_mod
    from astral_toolkit.runtime.session import Session

    worker = nav_mod._NavWorker(object(), nav_mod._CamFilter(), threading.Lock())
    payload = nav_mod.NavPayload({"key": "x"}, {"key": "x"}, True)
    session = Session(7, threading.Event(), payload)
    ctx = nav_mod._NavCtx(7, payload)
    return worker, session, ctx


def test_fix_request_error_does_not_kill_nav():
    """一次 F9 定位抛异常：只算这次无效，tick 不往外抛（不触发导航重试 / 出错关闭）"""
    worker, session, ctx = _fix_worker()

    def boom(*a, **k):
        raise ValueError("坏坐标")

    worker._apply_fix = boom  # pyright: ignore[reportAttributeAccessIssue]
    req = worker.enqueue_fix(7, (1.0, 2.0, 3.0), None)
    worker._process_fix_requests(session, ctx)
    assert req.done.is_set() and req.result is None


def test_fix_request_cancelled_is_not_applied():
    """调用方等超时撤回的请求：tick 之后拿到也不应用（返回「无效」后导航不能又更新）"""
    worker, session, ctx = _fix_worker()
    called = []
    worker._apply_fix = lambda *a, **k: called.append(a) or {"ok": True}  # pyright: ignore[reportAttributeAccessIssue]
    req = worker.enqueue_fix(7, (1.0, 2.0, 3.0), None)
    assert worker.cancel_fix(req)
    worker._process_fix_requests(session, ctx)
    assert not called and req.result is None
    req2 = worker.enqueue_fix(7, (1.0, 2.0, 3.0), None)
    worker._process_fix_requests(session, ctx)
    assert called and req2.result == {"ok": True}
    assert not worker.cancel_fix(req2)  # 已处理过的不能再撤回
