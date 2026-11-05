"""RT-B5b：导航外层、Worker 纯函数输出、拒绝路径、锁序与 bind 无副作用的显式断言"""

import threading
import time
from types import SimpleNamespace
from typing import Any

from astral_toolkit.app.engines import nav as navmod
from astral_toolkit.runtime.session import RunState, Session, StopAttempt, StopInfo


class _FakePos:
    def __init__(self):
        self.current: tuple[Any, Any, Any] = (time.time(), None, None)
        self.latest: tuple[Any, Any, Any] = (0.0, None, None)
        self.read_at = 0.0
        self.reader_active = False
        self.reader_ok_at = 0.0
        self.calls = []
        self.demand = []
        self.fps = []
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

    def set_demand(self, key, until, fps=None):
        self.demand.append((key, until))
        self.fps.append(fps)

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


def _make_nav(monkeypatch, marker=None, links=None):
    pos = _FakePos()
    loop_holder = {}
    nav = navmod._Nav(
        pos,
        _FakeCam(),
        None,
        None,
        output=object(),
        marker=marker,
        links=links,
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


def test_marker_draws_under_marker_lock_after_commit():
    pos = _FakePos()
    lock = threading.Lock()
    seen = {}

    class Marker:
        def tick(self, target, data, state, mk_seen, ref):
            seen["locked"] = lock.locked()
            return 42

        def clear(self):
            return None

    worker = navmod._NavWorker(pos, _FakeCam(), lock, marker=Marker())
    session = Session(
        1, threading.Event(), navmod.NavPayload({"n": "X"}, {"key": "x"}, True)
    )
    ctx = SimpleNamespace(mk_seen=None)
    got = worker._marker_after_commit(session, ctx, "t", {}, {}, None)
    assert got == 42
    assert seen["locked"] is True


def test_stop_clears_marker_under_marker_lock(monkeypatch):
    class Marker:
        def __init__(self):
            self.clears = []
            self.ticks = 0
            self.lock: Any = None

        def tick(self, target, data, state, shown, ref=None):
            self.ticks += 1
            return None

        def clear(self):
            self.clears.append(self.lock.locked())

    marker = Marker()
    nav, _pos, _loop = _make_nav(monkeypatch, marker=marker)
    marker.lock = nav.marker_lock
    nav.stop()
    assert marker.clears == [True]
    assert marker.ticks == 0


def test_nav_without_marker_never_touches_hud(monkeypatch):
    from astral_toolkit.app import hud_state

    calls = []

    def fake_hud():
        calls.append(True)
        return None

    monkeypatch.setattr(hud_state, "_hud", fake_hud)
    nav, _pos, _loop = _make_nav(monkeypatch)
    nav.start(
        {"n": "X", "b": "Daymar", "t": "Planet", "qt": 0},
        target_row={"key": "x"},
        space_mode=False,
    )
    nav.stop()
    assert calls == []
    assert isinstance(nav._marker, navmod._NoMarker)


def test_navigation_bind_required():
    from astral_toolkit.tasks import navigation as nt
    from tests.bootstrap_helpers import restore_bindings, snapshot_bindings

    saved = snapshot_bindings()
    try:
        nt._nav = nt._pos = nt._game_events = nt._results = None
        try:
            nt._deps()
        except RuntimeError as exc:
            assert "未绑定" in str(exc)
        else:
            raise AssertionError("未绑定时应抛 RuntimeError")
    finally:
        restore_bindings(saved)


def test_nav_start_does_not_record_when_start_rejected(monkeypatch):
    from astral_toolkit.core import run_records
    from astral_toolkit.tasks import navigation as nt
    from tests.bootstrap_helpers import bind_for_test

    records = []

    class N:
        target = None
        space_mode = False

        def start(self, target, target_row=None, space_mode=None):
            return navmod.NavStart(None, "busy_stopping")

    monkeypatch.setattr(nt, "_place_row", lambda p: {"key": "k"})
    monkeypatch.setattr(run_records, "record", lambda *a, **k: records.append(a))
    nt._places["k"] = {"b": "Daymar", "t": "Planet", "n": "X", "qt": 0}
    with bind_for_test(nt, N(), object(), object(), object()):
        assert nt.nav_start("k") == {"error": "导航正在停止，请稍候"}
        assert records == []


def test_nav_stop_timeout_message(monkeypatch):
    from astral_toolkit.core import run_records
    from astral_toolkit.tasks import navigation as nt
    from tests.bootstrap_helpers import bind_for_test

    class N:
        def stop(self):
            return StopAttempt(1, False, True)

    monkeypatch.setattr(run_records, "record", lambda *a, **k: None)
    with bind_for_test(nt, N(), object(), object(), object()):
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


class _RecordingLinks:
    def __init__(self):
        self.logs = []
        self.hints = 0
        self.placed = []
        self.settings = []

    def log(self, msg):
        self.logs.append(msg)

    def fix_key_hint(self):
        self.hints += 1
        return "F9", "一键定位：按 F9"

    def place_row(self, target):
        self.placed.append(target)
        return {"key": "x", "label": "目标A"}

    def setting(self, key, default):
        self.settings.append((key, default))
        return default


class _CommitLoop:
    def __init__(self):
        self.commits = []

    def commit(self, session, *ops):
        self.commits.append((session, ops))
        return True


def test_worker_uses_injected_links(monkeypatch):
    links = _RecordingLinks()
    wired = navmod.NavLinks(
        log=links.log,
        fix_key_hint=links.fix_key_hint,
        place_row=links.place_row,
        setting=links.setting,
    )
    nav, _pos, _loop = _make_nav(monkeypatch, links=wired)
    target = {"n": "X", "b": "Daymar", "t": "Planet", "qt": 0}
    result = nav.start(target)
    assert result.status == "started"
    assert links.placed == [target]
    assert links.settings == [("nav_mode", "auto")]

    from astral_toolkit.navigation import navigate as n

    worker = navmod._NavWorker(_FakePos(), _FakeCam(), threading.Lock(), links=wired)
    commit_loop = _CommitLoop()
    worker.loop = commit_loop
    payload = navmod.NavPayload(target, {"key": "x", "label": "目标A"}, True)
    session = Session(2, threading.Event(), payload)
    ctx = navmod._NavCtx(2, payload)
    monkeypatch.setattr(n, "label", lambda value: "目标A")
    monkeypatch.setattr(
        n,
        "fix_guide",
        lambda fixes, tgt, prev_arrived=False: {
            "same_system": True,
            "direct": 123,
            "arrived": False,
            "city": None,
            "close": False,
            "deviation": None,
            "delta": None,
            "eta": None,
            "qt": None,
            "aim": None,
        },
    )
    monkeypatch.setattr(n, "fix_text", lambda f, key: f"按 {key} 定位")
    fixed = worker._apply_fix(session, ctx, (1000.0, 2000.0, 3000.0), "clip")
    assert fixed is not None
    assert commit_loop.commits
    assert links.hints == 1
    assert any("太空导航定位" in msg for msg in links.logs)

    worker.on_error(session, ctx, ValueError("坏了"))
    assert any("导航出错" in msg for msg in links.logs)


def test_cam_filter_logs_through_injected_log():
    messages = []
    cam_filter = navmod._CamFilter(log=messages.append)
    assert cam_filter.check((30, 0, 90), fast=True) == (30, 0, 90)
    assert cam_filter.check((-30, 0, 90), fast=True) is None
    assert cam_filter.check((-30, 0, 90), fast=True) is None
    assert cam_filter.check((-30, 0, 90), fast=True) == (-30, 0, 90)
    assert messages and "连着 3 帧字模读数一致" in messages[-1]

    quiet = navmod._CamFilter()
    assert quiet.check((30, 0, 90), fast=True) == (30, 0, 90)
    assert quiet.check((-30, 0, 90), fast=True) is None
    assert quiet.check((-30, 0, 90), fast=True) is None
    assert quiet.check((-30, 0, 90), fast=True) == (-30, 0, 90)


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


def test_space_steer_follows_camera_while_hovering(monkeypatch):
    """停着不动（坐标没变）转机头：转向提示要跟着新一帧的镜头方向重算，不能冻在上一帧（负责人 2026-11-03 截图：右转 43° 实际该左转 14°）"""
    from astral_toolkit.navigation import navigate as n

    monkeypatch.setattr(n, "load", lambda: {"bodies": {}, "pois": [], "points": []})
    monkeypatch.setattr(n, "locate", lambda *a, **k: {"inside": False, "body": None})
    monkeypatch.setattr(n, "read_clipboard", lambda: "")
    monkeypatch.setattr(
        navmod, "_space_view", lambda g, t, d: {"space": True, "arrived": False}
    )
    monkeypatch.setattr(n, "space_text", lambda g, t, d: "直线 13.8 km")
    huds = []

    class Loop:
        def commit(self, session, *ops):
            huds.extend(op[2] for op in ops if op[0] == "hud.set")
            return True

    tgt = {
        "space": True,
        "n": "1",
        "zh": "1",
        "x": 8163217.9574,
        "y": 18591209.2105,
        "z": -4278.6308,
    }
    g = (8163210720.5, 18591214824.5, -4288975.1)
    now = time.time()
    pos = _FakePos()
    pos.latest = (now, g, {"t": now, "camdir": (76.0, -26.0, 161.0)})
    pos.current = pos.latest
    pos.reader_active = True
    worker = navmod._NavWorker(pos, _FakeCam(), threading.Lock())
    worker.loop = Loop()
    session = Session(1, threading.Event(), navmod.NavPayload(tgt, tgt, False))
    ctx = navmod._NavCtx(1, session.payload)
    ctx.data = n.load()
    ctx.first = False
    ctx.state["here"] = {}  # 不走「刚开始用 current」那条
    worker.tick(session, ctx, now)
    assert "左转 14°" in huds[-1], huds[-1]

    later = now + 1.0
    pos.current = (
        later,
        g,
        {"t": later, "camdir": (75.0, -41.0, 165.0)},
    )  # 坐标没变、镜头转了
    worker.tick(session, ctx, later)
    assert "直飞" in huds[-1], huds[-1]
    n_before = len(huds)
    worker.tick(session, ctx, later + 0.1)  # 同一帧不重复处理
    assert len(huds) == n_before + 1 and huds[-1] == huds[-2]


def _ground_worker(pos, links=None):
    class Loop:
        def __init__(self):
            self.ops = []

        def commit(self, session, *ops):
            self.ops.append(ops)
            return True

    worker = navmod._NavWorker(pos, _FakeCam(), threading.Lock(), links=links)
    worker.loop = Loop()
    payload = navmod.NavPayload({"n": "X", "b": "B"}, {"key": "x"}, False)
    session = Session(1, threading.Event(), payload)
    ctx = navmod._NavCtx(1, payload)
    return worker, session, ctx


def test_ground_first_tick_and_status_use_di_help(monkeypatch):
    """地面导航：第一圈的帮助文字、一直读不到时的状态都用 DI_HELP（NV-B4 常量搬进引擎后锁住文字）"""
    from astral_toolkit.navigation import navigate as n

    assert navmod.DI_HELP == (
        "未检测到右上角位置信息：在游戏中按 ~ 打开控制台，输入 r_DisplayInfo 2 后回车"
    )
    for name, value in (
        ("label", lambda t: "目标"),
        ("load", lambda: {}),
        ("read_clipboard", lambda: ""),
        ("parse_clip", lambda clip: None),
    ):
        monkeypatch.setattr(n, name, value)
    worker, session, ctx = _ground_worker(_FakePos())
    assert worker._first_tick(session, ctx) is True
    first = [op for op in worker.loop.ops[0] if op[0] == "bus"][0][2]
    assert first["help"] == navmod.DI_HELP

    ctx.first = False
    worker._ground_tick(session, ctx, time.time())
    assert ctx.state["status"] == navmod.DI_HELP + "（或在聊天框输入 /showlocation）"


def test_ground_tick_uses_current_frame_only_within_live_stale(monkeypatch):
    """刚开导航时用位置服务的「当前一帧」：3 秒以内的才用，旧了就等新读数（NV-B4 LIVE_STALE 搬进引擎后锁住）"""
    from astral_toolkit.navigation import navigate as n

    class _Located(Exception):
        pass

    located = []

    def locate(*a, **k):
        located.append(a)
        raise _Located

    for name, value in (
        ("locate", locate),
        ("label", lambda t: "目标"),
        ("read_clipboard", lambda: ""),
        ("parse_clip", lambda clip: None),
    ):
        monkeypatch.setattr(n, name, value)
    assert navmod.LIVE_STALE == 3.0
    for age, used in ((2.5, True), (5.0, False)):
        located.clear()
        now = time.time()
        pos = _FakePos()
        pos.current = (now - age, (1.0, 2.0, 3.0), {"t": now - age})
        worker, session, ctx = _ground_worker(pos)
        ctx.data = {}
        ctx.first = False
        ctx.seen_cur = pos.current[0]  # 同一坐标的新一帧那条已经处理过
        try:
            worker._ground_tick(session, ctx, now)
        except _Located:
            pass
        assert bool(located) is used, age


def test_ground_tick_logs_nav_line_only_when_position_changes(monkeypatch):
    """地面导航：坐标变了才记一行导航日志；停着只转镜头（同一坐标的新一帧）不记（NV-B4 nav_log 搬进引擎后锁住）"""
    from astral_toolkit.navigation import navigate as n

    logs = []
    monkeypatch.setattr(navmod, "nav_log", lambda here, info, view: logs.append(here))
    monkeypatch.setattr(
        navmod,
        "_nav_view",
        lambda here, goal, data, steady=None, prev=None: {
            "bearing": 10.0,
            "arrived": False,
        },
    )
    for name, value in (
        ("locate", lambda g, **k: {"x": g[0], "y": g[1], "z": g[2], "body": "B"}),
        ("is_city", lambda t: False),
        ("is_space", lambda t: False),
        ("near_text", lambda here, data: ""),
        ("_short", lambda *a: "短"),
        ("label", lambda t: "目标"),
        ("read_clipboard", lambda: ""),
        ("parse_clip", lambda clip: None),
    ):
        monkeypatch.setattr(n, name, value)
    now = time.time()
    pos = _FakePos()
    g = (1.0, 2.0, 3.0)
    pos.latest = (now, g, {"t": now})
    pos.current = pos.latest
    worker, session, ctx = _ground_worker(pos)
    ctx.data = {}
    ctx.first = False
    ctx.state["here"] = {}  # 不走「刚开始用 current」那条
    worker._ground_tick(session, ctx, now)
    assert len(logs) == 1
    pos.current = (now + 1.0, g, {"t": now + 1.0})  # 坐标没变，读到了新一帧
    worker._ground_tick(session, ctx, now + 1.0)
    assert len(logs) == 1
    pos.latest = (now + 2.0, (4.0, 5.0, 6.0), {"t": now + 2.0})  # 坐标变了
    pos.current = pos.latest
    worker._ground_tick(session, ctx, now + 2.0)
    assert len(logs) == 2


def _fps_links(fps):
    return navmod.NavLinks(
        log=lambda msg: None,
        fix_key_hint=lambda: ("", ""),
        place_row=lambda target: None,
        setting=lambda key, default: default,
        fps=fps,
    )


def _patch_no_position(monkeypatch):
    from astral_toolkit.navigation import navigate as n

    monkeypatch.setattr(n, "label", lambda target: "目标")
    monkeypatch.setattr(n, "load", lambda: {})
    monkeypatch.setattr(n, "read_clipboard", lambda: "")
    monkeypatch.setattr(n, "parse_clip", lambda clip: None)


def test_ground_wait_follows_fps_setting():
    values = [5]
    worker, _, _ = _ground_worker(_FakePos(), links=_fps_links(lambda: values[0]))
    assert abs(worker._ground_wait() - 0.1) < 1e-9
    values[0] = 10
    assert abs(worker._ground_wait() - 0.05) < 1e-9
    values[0] = 60
    assert abs(worker._ground_wait() - 0.5 / 60) < 1e-9

    worker, _, _ = _ground_worker(_FakePos(), links=_fps_links(lambda: "abc"))
    assert abs(worker._ground_wait() - 0.1) < 1e-9

    def boom():
        raise ValueError("坏帧数")

    worker, _, _ = _ground_worker(_FakePos(), links=_fps_links(boom))
    assert abs(worker._ground_wait() - 0.1) < 1e-9


def test_ground_tick_tells_pos_the_fps_and_follows_changes(monkeypatch):
    _patch_no_position(monkeypatch)
    box = [30]
    pos = _FakePos()
    worker, session, ctx = _ground_worker(pos, links=_fps_links(lambda: box[0]))
    ctx.first = False
    ctx.data = {}
    now = time.time()

    tick = worker._ground_tick(session, ctx, now)
    assert pos.fps == [30]
    assert pos.demand[-1] == ("nav", float("inf"))
    assert abs(tick.wait - 0.5 / 30) < 1e-9

    worker._ground_tick(session, ctx, now + 0.1)
    assert pos.fps == [30]

    box[0] = 60
    tick = worker._ground_tick(session, ctx, now + 0.2)
    assert pos.fps == [30, 60]
    assert abs(tick.wait - 0.5 / 60) < 1e-9


def test_ground_tick_reads_clipboard_by_time_not_by_ticks(monkeypatch):
    from astral_toolkit.navigation import navigate as n

    reads = []

    def read():
        reads.append(1)
        return ""

    _patch_no_position(monkeypatch)
    monkeypatch.setattr(n, "read_clipboard", read)
    worker, session, ctx = _ground_worker(_FakePos())
    ctx.first = False
    ctx.data = {}
    now = time.time()
    worker._ground_tick(session, ctx, now)
    assert len(reads) == 1
    worker._ground_tick(session, ctx, now + 0.1)
    assert len(reads) == 1
    worker._ground_tick(session, ctx, now + 0.2)
    assert len(reads) == 1
    worker._ground_tick(session, ctx, now + 0.35)
    assert len(reads) == 2


def test_nav_log_at_most_every_0_2_seconds(monkeypatch):
    from astral_toolkit.navigation import navigate as n

    logs = []
    monkeypatch.setattr(navmod, "nav_log", lambda here, info, view: logs.append(here))
    monkeypatch.setattr(
        navmod,
        "_nav_view",
        lambda here, goal, data, steady=None, prev=None: {
            "bearing": 10.0,
            "arrived": False,
        },
    )
    for name, value in (
        ("locate", lambda g, **k: {"x": g[0], "y": g[1], "z": g[2], "body": "B"}),
        ("is_city", lambda t: False),
        ("is_space", lambda t: False),
        ("near_text", lambda here, data: ""),
        ("_short", lambda *a: "短"),
        ("label", lambda t: "目标"),
        ("read_clipboard", lambda: ""),
        ("parse_clip", lambda clip: None),
    ):
        monkeypatch.setattr(n, name, value)
    now = time.time()
    pos = _FakePos()
    worker, session, ctx = _ground_worker(pos)
    ctx.data = {}
    ctx.first = False
    ctx.state["here"] = {}

    pos.latest = (now, (1.0, 2.0, 3.0), {"t": now})
    pos.current = pos.latest
    worker._ground_tick(session, ctx, now)
    assert len(logs) == 1

    pos.latest = (now + 0.1, (4.0, 5.0, 6.0), {"t": now + 0.1})
    pos.current = pos.latest
    worker._ground_tick(session, ctx, now + 0.1)
    assert len(logs) == 1

    pos.latest = (now + 0.3, (7.0, 8.0, 9.0), {"t": now + 0.3})
    pos.current = pos.latest
    worker._ground_tick(session, ctx, now + 0.3)
    assert len(logs) == 2


def test_start_asks_fps_only_for_live_mode(monkeypatch):
    nav, pos, _loop = _make_nav(monkeypatch, links=_fps_links(lambda: 20))
    target = {"n": "X", "b": "Daymar", "t": "Planet", "qt": 0}
    row = {"key": "x", "label": "X"}

    assert nav.start(target, target_row=row, space_mode=False).status == "started"
    assert pos.fps[-1] == 20
    assert nav.start(target, target_row=row, space_mode=True).status == "started"
    assert pos.fps[-1] is None
