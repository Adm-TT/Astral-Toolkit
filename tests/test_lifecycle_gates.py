"""RT-B6 提交 2：closing 门、HTTP 在途写、miss 截图队列。"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any


def _closing_gate(closing=True):
    from contextlib import contextmanager

    from astral_toolkit.app import lifecycle_gate
    from tests.bootstrap_helpers import restore_bindings, snapshot_bindings

    @contextmanager
    def _bound():
        saved = snapshot_bindings()
        lifecycle_gate.bind_closing(lambda: bool(closing), replace=True)
        try:
            yield
        finally:
            restore_bindings(saved)

    return _bound()


def _read_all(sock):
    chunks = []
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    except OSError:
        pass
    return b"".join(chunks)


class _FakeImage:
    def __init__(self, payload=b"png", *, entered=None, release=None):
        self.payload = payload
        self.entered = entered
        self.release = release

    def save(self, path, format=None):
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(3.0)
        path.write_bytes(self.payload)


def test_closing_gate_f5_f6(monkeypatch):
    from astral_toolkit.app import hud_state
    from astral_toolkit.app.inputs.hotkeys import HotkeyCommands
    from astral_toolkit.tasks import count as count_task
    from astral_toolkit.tasks import mining, navigation
    from tests.bootstrap_helpers import bind_for_test

    class _Toggle:
        prev_stop_pending = False

        def __init__(self):
            self.is_running = False

        def running(self):
            return self.is_running

        def config_changed(self):
            pass

    live: Any = _Toggle()  # 替身：没有 start / stop
    count = _Toggle()
    with _closing_gate(True):
        refused = mining.live_start(live)
        assert isinstance(refused, dict) and refused.get("error") == "正在退出"

        with bind_for_test(count_task, count):
            refused = count_task.count_toggle()
            assert isinstance(refused, dict) and refused.get("error") == "正在退出"

        notes = []
        monkeypatch.setattr(
            hud_state,
            "_note_hud",
            lambda title, text, *a, **k: notes.append((title, text)),
        )
        monkeypatch.setattr(
            navigation, "settings_key", lambda key, default=None: default
        )

        calls = []
        monkeypatch.setattr(
            mining,
            "live_start",
            lambda lv: calls.append(("start", lv is live)) or {"ok": True},
        )
        monkeypatch.setattr(
            mining, "live_stop", lambda lv: calls.append(("stop", lv is live))
        )
        monkeypatch.setattr(
            count_task, "count_toggle", lambda: calls.append("count") or {"ok": True}
        )

        h = HotkeyCommands(live=live, count=count, links=None, feedback=None, nav=None)
        h._toggle_live()
        assert calls == []
        assert notes[-1] == ("采矿助手", "正在退出")

        live.is_running = True
        h._toggle_live()
        assert calls[-1] == ("stop", True)

        count.is_running = False
        h._toggle_count()
        assert "count" not in calls
        assert notes[-1] == ("盘点", "正在退出")

        count.is_running = True
        h._toggle_count()
        assert calls[-1] == "count"


def test_closing_gate_navigation_and_writes(monkeypatch):
    from types import SimpleNamespace

    from astral_toolkit.app.inputs.hotkeys import HotkeyCommands
    from astral_toolkit.tasks import navigation

    deps: Any = SimpleNamespace()
    with _closing_gate(True):
        assert navigation.nav_start(deps, "x").get("error") == "正在退出"
        assert navigation.nav_near(deps, "mine").get("error") == "正在退出"
        assert navigation.mark_here(deps).get("error") == "正在退出"

        h = HotkeyCommands(
            live=SimpleNamespace(running=lambda: False),
            count=SimpleNamespace(running=lambda: False),
            links=None,
            feedback=None,
            nav=None,
        )
        assert h._mark().get("error") == "正在退出"
        assert h._fix().get("error") == "正在退出"
        assert h._ore().get("error") == "正在退出"


def test_http_closing_post_and_get():
    from astral_toolkit.app import http_server

    srv = http_server.Server(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    writes = http_server.WRITES
    writes.bind_closing(lambda: True)
    port = srv.server_address[1]
    try:
        import urllib.request

        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3).read()
        assert html

        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        try:
            request = (
                "POST /api/about_info HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                f"X-Token: {http_server.TOKEN}\r\n"
                "Content-Length: 100\r\n"
                "Connection: close\r\n\r\n"
            )
            sock.sendall(request.encode("ascii"))
            data = _read_all(sock)
        finally:
            sock.close()
        assert b"200" in data.split(b"\r\n", 1)[0]
        assert "正在退出".encode() in data
    finally:
        writes.bind_closing(None)
        srv.shutdown()
        srv.server_close()
        thread.join(2.0)


def test_http_writes_join_waits_and_timeout_reports():
    from astral_toolkit.app.http_writes import HttpWritesService
    from astral_toolkit.runtime.lifecycle import Lifecycle

    service = HttpWritesService(lambda: False)
    assert service.try_begin_write("slow/route")
    result = {}
    waiter = threading.Thread(target=lambda: result.setdefault("ok", service.join(2.0)))
    waiter.start()
    time.sleep(0.05)
    assert "ok" not in result
    service.end_write("slow/route")
    waiter.join(1.0)
    assert result.get("ok") is True
    assert service.active_count == 0

    stuck = HttpWritesService(lambda: False)
    assert stuck.try_begin_write("nav_start")
    assert stuck.try_begin_write("nav_start")
    assert stuck.try_begin_write("live_start")
    lifecycle = Lifecycle()
    lifecycle.register(stuck)
    report = lifecycle.stop_all(0.02)
    record = report.records[0]
    assert record.still_alive
    assert "nav_start" in record.error
    assert "live_start" in record.error
    assert "2" in record.error
    stuck.end_write("nav_start")
    stuck.end_write("nav_start")
    stuck.end_write("live_start")
    assert stuck.join(0.2)


def test_miss_queue_drops_new_and_single_thread(monkeypatch, tmp_path):
    from astral_toolkit.app import bus
    from astral_toolkit.app.miss_shots import MissShotsService

    warns = []
    monkeypatch.setattr(
        bus,
        "runtime_log",
        lambda msg, **kw: warns.append((msg, kw)),
    )

    service = MissShotsService(capacity=4)
    entered = threading.Event()
    release = threading.Event()
    first = _FakeImage(entered=entered, release=release)
    assert service.submit(tmp_path, "first", first, 10)
    assert entered.wait(1.0)
    worker = service.thread

    for index in range(4):
        assert service.submit(tmp_path, f"q{index}", _FakeImage(), 10)
    assert not service.submit(tmp_path, "drop", _FakeImage(), 10)
    assert any("队列已满" in msg and kw.get("level") == "WARN" for msg, kw in warns)

    assert (
        service.thread is worker and worker is not None and worker.is_alive()
    )  # 一直是同一个线程

    release.set()
    service.request_stop()
    assert service.join(2.0)
    assert (tmp_path / "first.png").is_file()
    assert not list(tmp_path.glob("*.tmp"))


def test_miss_queue_atomic_and_trim(tmp_path):
    from astral_toolkit.app.miss_shots import MissShotsService

    service = MissShotsService(capacity=4)
    for index in range(4):
        assert service.submit(tmp_path, f"p{index}", _FakeImage(str(index).encode()), 2)
    service.request_stop()
    assert service.join(2.0)
    assert len(list(tmp_path.glob("*.png"))) == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_miss_queue_stop_timeout_records_dropped(tmp_path):
    from astral_toolkit.app.miss_shots import MissShotsService

    service = MissShotsService(capacity=4)
    entered = threading.Event()
    release = threading.Event()
    assert service.submit(
        tmp_path, "hold", _FakeImage(entered=entered, release=release), 10
    )
    assert entered.wait(1.0)
    assert service.submit(tmp_path, "q0", _FakeImage(), 10)
    assert service.submit(tmp_path, "q1", _FakeImage(), 10)

    service.request_stop()
    assert not service.submit(tmp_path, "late", _FakeImage(), 10)
    assert not service.join(0.05)
    assert "丢弃" in service.last_error
    assert "3" in service.last_error

    release.set()
    assert service.join(2.0)


def test_miss_queue_saves_real_png(tmp_path):
    """真的 PIL 图：写 .tmp 时要写明 PNG 格式（后缀认不出），最后得到能打开的 .png（控制台审查 RT-B6）"""
    from PIL import Image

    from astral_toolkit.app.miss_shots import MissShotsService

    service = MissShotsService()
    assert service.submit(tmp_path, "real", Image.new("RGB", (8, 8)), 10)
    service.request_stop()
    assert service.join(3.0)
    assert Image.open(tmp_path / "real.png").size == (8, 8)
    assert not list(tmp_path.glob("*.tmp"))
