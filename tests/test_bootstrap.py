"""RT-B7：bootstrap 装配、绑定规则和任务层无单例的检查。"""

from __future__ import annotations

import threading
import time
from typing import Any
from types import SimpleNamespace

from PIL import Image

from astral_toolkit import bootstrap
from astral_toolkit.app import lifecycle_gate
from astral_toolkit.app.engines import count as count_engine
from astral_toolkit.app.engines import live as live_engine
from astral_toolkit.crafting import stockplaces
from astral_toolkit.mining import screen as mining_screen
from astral_toolkit.mining import signals as mining_signals
from astral_toolkit.mining.parse import Scan
from astral_toolkit.runtime.session import RunFlag, RunState
from astral_toolkit.tasks import count as count_tasks
from astral_toolkit.tasks import mining as mining_tasks
from astral_toolkit.tasks import navigation as nav_tasks
from astral_toolkit.tasks import system as system_tasks
from astral_toolkit.tasks.system import common as system_common
from tests.bootstrap_helpers import (
    restore_bindings,
    snapshot_bindings,
    app_for_test,
)
from tests.runtime_fakes import FakeClock, FakeWorker, RecordingOutput


def _assert_error(exc_type, text, fn):
    try:
        fn()
    except exc_type as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"没有抛出 {exc_type.__name__}")


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _names_in(value, depth=0):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _names_in(key, depth + 1)
            yield from _names_in(item, depth + 1)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _names_in(item, depth + 1)
        return
    if isinstance(value, str):
        yield value
        return
    try:
        name = getattr(value, "name", None)
    except Exception:
        name = None
    if isinstance(name, str):
        yield name
    if depth >= 2:
        return
    try:
        attrs = vars(value).values()
    except TypeError:
        return
    for attr in attrs:
        if attr is value:
            continue
        if isinstance(attr, (str, dict, list, tuple, set, frozenset)) or hasattr(
            attr, "name"
        ):
            yield from _names_in(attr, depth + 1)


def _registered_names(lifecycle):
    names = set()
    try:
        values = list(vars(lifecycle).values())
    except TypeError:
        values = []
    for attr in ("_services", "services", "_entries", "entries", "_order"):
        try:
            values.append(getattr(lifecycle, attr))
        except Exception:
            pass
    for value in values:
        names.update(_names_in(value))
    return names


def test_build_test_does_not_touch_globals_or_start_threads():
    before_bindings = snapshot_bindings()
    # 按线程对象比、只看多出来的：前面测试留下的后台线程恰好在这期间结束不算
    before_threads = set(threading.enumerate())
    app = bootstrap.build("test")
    try:
        assert snapshot_bindings() == before_bindings
        new_threads = set(threading.enumerate()) - before_threads
        assert not new_threads, [thread.name for thread in new_threads]
        names = _registered_names(app.lifecycle)
        assert {"live", "nav", "count"} <= names, names
        assert "http-writes" not in names, names
    finally:
        try:
            bootstrap.shutdown(app, budget=0.2)
        except Exception:
            pass


def test_build_desktop_binds_everything_to_this_app(monkeypatch):
    """桌面版装配（server.main 第一步，早于网页服务）：tasks / app 层全部绑到这一个 app，
    HTTP 在途写计数登记进它的 lifecycle、closing 也接到它（最低验收「绑定早于服务启动」的另一半）"""
    from astral_toolkit.app import ui_stream
    from astral_toolkit.app.http_writes import WRITES
    from astral_toolkit.navigation import navigate

    saved = snapshot_bindings()
    monkeypatch.setattr(WRITES, "_closing", WRITES._closing)  # 测完恢复
    try:
        # 桌面版只绑一次（不带 replace）：先全部清空，像刚启动的进程
        restore_bindings({key: (m, n, None) for key, (m, n, _) in saved.items()})
        app = bootstrap.build("desktop")
        try:
            assert mining_tasks._live is app.live
            assert mining_tasks._positions is app.pos
            assert nav_tasks._nav is app.nav and nav_tasks._pos is app.pos
            assert nav_tasks._game_events is app.game_events
            assert nav_tasks._results is app.results
            assert count_tasks._count is app.count
            status = system_common._status
            assert status is not None and status.results is app.results
            assert callable(system_common._start)
            assert lifecycle_gate._CLOSING == app.lifecycle.is_closing
            sources = ui_stream._SOURCES
            assert sources is not None
            assert (sources.live, sources.nav, sources.pos) == (
                app.live,
                app.nav,
                app.pos,
            )
            assert navigate.HINTS == app.pos.hints
            assert WRITES._closing == app.lifecycle.is_closing
            assert "http-writes" in _registered_names(app.lifecycle)
        finally:
            bootstrap.shutdown(app, budget=0.5)
    finally:
        restore_bindings(saved)


def test_build_rejects_bad_mode_and_unknown_overrides():
    _assert_error(ValueError, "mode", lambda: bootstrap.build("prod"))
    _assert_error(
        ValueError,
        "overrides",
        lambda: bootstrap.build("test", overrides={"unknown": 1}),
    )


def test_bind_all_and_task_binds_refuse_second_binding():
    before = snapshot_bindings()
    with app_for_test() as app:
        _assert_error(RuntimeError, "已绑定", lambda: bootstrap.bind_all(app))
        _assert_error(
            RuntimeError,
            "已绑定",
            lambda: mining_tasks.bind(app.live, app.pos),
        )
        _assert_error(RuntimeError, "已绑定", lambda: count_tasks.bind(app.count))
        _assert_error(
            RuntimeError,
            "已绑定",
            lambda: nav_tasks.bind(app.nav, app.pos, app.game_events, app.results),
        )
        _assert_error(
            RuntimeError,
            "已绑定",
            lambda: system_tasks.bind(bootstrap.status_sources(app), lambda: False),
        )
    assert snapshot_bindings() == before


def test_unbound_modules_raise_and_gate_stays_open():
    saved = snapshot_bindings()
    try:
        mining_tasks._live = None
        mining_tasks._positions = None
        _assert_error(RuntimeError, "未绑定", mining_tasks.live_start)

        count_tasks._count = None
        _assert_error(RuntimeError, "未绑定", count_tasks.count_state)

        nav_tasks._nav = None
        nav_tasks._pos = None
        nav_tasks._game_events = None
        nav_tasks._results = None
        _assert_error(RuntimeError, "未绑定", nav_tasks._need)

        system_common._status = None
        system_common._start = None
        _assert_error(RuntimeError, "未绑定", system_tasks.status)
        _assert_error(RuntimeError, "未绑定", system_tasks.start_background)

        lifecycle_gate._CLOSING = None
        assert lifecycle_gate.is_closing() is False
        assert lifecycle_gate.closing_error() is None
    finally:
        restore_bindings(saved)


class _Grabber:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return Image.new("RGB", (1920, 1080))


def test_mining_session_starts_and_stops_with_fake_screen(monkeypatch):
    real_grab_calls = []

    def fail_grab(*args, **kwargs):
        real_grab_calls.append(True)
        raise AssertionError("碰了真截屏")

    monkeypatch.setattr(mining_screen, "grab", fail_grab)
    # 识别换成「画面里什么都没有」：这里只测会话循环用的是注入的截屏 / 前台 / 时钟；
    # 真识别第一次要加载模型（几秒），单独跑这个文件时会拖过收尾预算
    monkeypatch.setattr(
        mining_screen, "analyse", lambda img: (Scan(), ({}, None, None))
    )
    monkeypatch.setattr(mining_signals, "find_signatures", lambda img: [])
    # 会话循环开 / 停时会写设置里的 live_on：换成只记录、不落盘的 RunFlag，别动真设置
    flag_writes = []
    monkeypatch.setattr(
        live_engine,
        "setting_run_flag",
        lambda key: RunFlag(key, lambda k, v: flag_writes.append((k, v))),
    )
    grabber = _Grabber()
    with app_for_test(
        foreground=lambda: True,
        grab=grabber,
        clock=FakeClock(),
        output=RecordingOutput(),
    ) as app:
        sid = app.live.start()
        assert sid is not None
        assert _wait_until(lambda: app.live.loop.state().state == RunState.RUNNING)
        assert _wait_until(lambda: grabber.calls > 0)
        attempt = app.live.stop()
        assert attempt.session_id == sid
        assert app.live.running() is False
        assert grabber.calls > 0
    assert not real_grab_calls
    assert flag_writes and flag_writes[-1] == ("live_on", False)


def test_count_session_uses_fake_worker(monkeypatch):
    monkeypatch.setattr(count_engine, "WIN", True)
    monkeypatch.setattr(stockplaces, "current_place", lambda: {"label": "测试站"})
    worker = FakeWorker(name="count")
    with app_for_test(
        foreground=lambda: True,
        clock=FakeClock(),
        output=RecordingOutput(),
        count_worker=worker,
    ) as app:
        result = app.count.start()
        assert result.get("running") is True, result
        assert _wait_until(app.count.running)
        app.count.stop()
        assert app.count.running() is False
        calls = [call[0] for call in worker.calls]
        assert "start_ops" in calls
        assert "stop_ops" in calls
        assert "finish" in calls
        assert worker.loop is app.count.loop
        loop_worker = getattr(app.count.loop, "worker", None)
        if loop_worker is None:
            loop_worker = getattr(app.count.loop, "_worker", None)
        assert loop_worker is worker


def test_test_app_restores_previous_bindings():
    saved = snapshot_bindings()
    try:
        mining_tasks._live = None
        mining_tasks._positions = None
        before = snapshot_bindings()
        with app_for_test() as app:
            assert mining_tasks._live is app.live
            assert mining_tasks._positions is app.pos
        assert snapshot_bindings() == before
        assert mining_tasks._live is None
        assert mining_tasks._positions is None

        # 只看绑定是不是原样恢复，用不着真引擎
        a_live: Any = SimpleNamespace(name="A-live")
        a_pos: Any = SimpleNamespace(name="A-pos")
        mining_tasks.bind(a_live, a_pos, replace=True)
        with_a = snapshot_bindings()
        with app_for_test() as app:
            assert mining_tasks._live is app.live
            assert mining_tasks._positions is app.pos
        assert snapshot_bindings() == with_a
        assert mining_tasks._live is a_live
        assert mining_tasks._positions is a_pos
    finally:
        restore_bindings(saved)
