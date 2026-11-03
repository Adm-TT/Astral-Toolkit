"""UI-K0a：新展示流骨架、run_id、终态顺序、旧通道零影响，以及整改回归。"""

import json
import queue
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


_ALL_SWITCHES = {
    "live_on": False,
    "live_running": False,
    "nav_running": False,
    "position_active": False,
    "hover_on": False,
    "overlay_on": False,
}


def _reset(monkeypatch):
    """每条用例开头调：清空新流状态，并把「读运行层开关」换成空（用例结束 monkeypatch 自动还原）。
    需要自定义开关的用例在调完 _reset 之后再 monkeypatch。"""
    from astral_toolkit.app import http_server, ui_stream

    ui_stream.reset_for_tests()
    monkeypatch.setattr(ui_stream, "read_switches", lambda: {})
    ui_stream._QUEUE_MAX = 2000
    ui_stream.ENDED_MAX = 256
    http_server.UI_HEARTBEAT_INTERVAL = 5.0
    return ui_stream


def _subscribe(ui: Any, maxsize: int) -> tuple[dict[str, Any], queue.Queue[Any]]:
    hello, q = ui.subscribe(maxsize=maxsize)
    assert q is not None
    return hello, q


def _next_event(reader: Any, timeout: float = 3) -> dict[str, Any]:
    event = reader.next_event(timeout=timeout)
    assert event is not None, "SSE 事件流提前结束"
    return event


def _drain_all(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            break
    return out


def test_hello_atomic_and_first_increment(monkeypatch):
    ui = _reset(monkeypatch)
    subscriber_count = 12
    publisher_count = 4
    per_publisher = 80
    barrier = threading.Barrier(subscriber_count + publisher_count)
    results: list[tuple[dict[str, Any], queue.Queue[Any] | None] | None] = [
        None
    ] * subscriber_count
    errors = []

    def subscriber(index):
        try:
            barrier.wait(timeout=5)
            results[index] = _subscribe(ui, 10000)
        except Exception as exc:
            errors.append(exc)

    def publisher():
        try:
            barrier.wait(timeout=5)
            for i in range(per_publisher):
                ui.publish_ui(
                    "ui.notice",
                    {"notice": {"notice_id": f"p-{threading.get_ident()}-{i}"}},
                )
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=subscriber, args=(i,)) for i in range(subscriber_count)
    ] + [threading.Thread(target=publisher) for _ in range(publisher_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert not errors, errors
    assert all(item is not None for item in results)
    ui.publish_ui("ui.notice", {"notice": {"notice_id": "after-all-subscribes"}})
    final_seq = ui.snapshot(0)["ui_seq"]

    for item in results:
        assert item is not None
        hello, q = item
        assert hello["kind"] == "ui.hello"
        assert q is not None
        seqs = []
        while True:
            try:
                msg = q.get(timeout=0.1)
            except queue.Empty:
                break
            ui.mark_dequeued(q)
            assert msg["conn"] == hello["conn"]
            seqs.append(msg["ui_seq"])
        assert seqs, "订阅之后至少应收到 finally 发布的一条"
        assert seqs == list(range(hello["ui_seq"] + 1, final_seq + 1))


def test_ui_seq_continuous_under_concurrent_publish(monkeypatch):
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui, 200)

    def worker(base):
        for i in range(25):
            ui.publish_ui("ui.notice", {"notice": {"notice_id": f"{base}-{i}"}})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)

    msgs = [q.get(timeout=1) for _ in range(100)]
    seqs = [msg["ui_seq"] for msg in msgs]
    assert seqs == list(range(hello["ui_seq"] + 1, hello["ui_seq"] + 101))
    assert len({msg["conn"] for msg in msgs}) == 1


def test_full_queue_disconnects_subscription(monkeypatch):
    ui = _reset(monkeypatch)
    _, q = _subscribe(ui, 1)
    assert ui.is_connected(q)
    ui.publish_ui("ui.notice", {"notice": {"notice_id": "keep"}})
    ui.publish_ui("ui.notice", {"notice": {"notice_id": "drop"}})
    assert not ui.is_connected(q)
    assert q.qsize() == 1
    kept = q.get_nowait()
    assert kept["notice"]["notice_id"] == "keep"


def test_snapshot_and_increment_watermark(monkeypatch):
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui, 10)
    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "update:1",
                "kind": "update",
                "state": "running",
                "title": "更新",
            }
        },
    )
    first = q.get(timeout=1)
    ui.mark_dequeued(q)
    assert first["kind"] == "ui.activity"
    assert first["ui_seq"] == hello["ui_seq"] + 1

    snap = ui.snapshot(hello["conn"])
    assert snap["conn"] == hello["conn"]
    assert snap["ui_seq"] == first["ui_seq"]
    assert [a["activity_id"] for a in snap["activities"]] == ["update:1"]
    assert q.empty()

    unchanged = ui.snapshot(hello["conn"])
    assert unchanged["ui_seq"] == snap["ui_seq"]
    assert q.empty()

    ui.publish_ui("ui.notice", {"notice": {"notice_id": "after"}})
    nxt = q.get(timeout=1)
    ui.mark_dequeued(q)
    assert nxt["ui_seq"] == snap["ui_seq"] + 1


def test_activity_end_notice_before_terminal_and_no_revive(monkeypatch):
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui, 10)
    activity = {
        "activity_id": "upgrade:7",
        "kind": "upgrade",
        "state": "running",
        "title": "升级",
    }
    ui.publish_ui("ui.activity", {"activity": activity})
    ui.publish_ui(
        "ui.activity_end",
        {"activity_id": "upgrade:7", "end_reason": "done"},
    )
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [e["kind"] for e in events] == [
        "ui.activity",
        "ui.notice",
        "ui.activity_end",
    ]
    assert events[1]["ui_seq"] < events[2]["ui_seq"]
    notice_id = events[2]["summary_notice_id"]
    assert events[1]["notice"]["notice_id"] == notice_id
    ui.publish_ui("ui.activity", {"activity": activity})
    assert q.empty()
    snap = ui.snapshot(hello["conn"])
    assert snap["activities"] == []
    assert "upgrade:7" in snap["ended"]
    assert snap["notices"][0]["notice_id"] == notice_id


def test_notice_dismiss_is_authoritative_and_hidden_from_snapshot(monkeypatch):
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui, 10)
    ui.publish_ui(
        "ui.notice",
        {"notice": {"notice_id": "n1", "dismissed": False}},
    )
    assert ui.dismiss_notice("n1")
    snap = ui.snapshot(hello["conn"])
    assert [n for n in snap["notices"] if n["notice_id"] == "n1"] == []
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [e["kind"] for e in events] == ["ui.notice", "ui.notice_dismiss"]


def test_tiles_only_come_from_current_activity(monkeypatch):
    ui = _reset(monkeypatch)
    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "mining:1",
                "kind": "mining",
                "state": "running",
                "title": "挖矿",
            }
        },
    )
    ui.set_switches({"live_on": True})
    snap = ui.snapshot(9)
    tile = [t for t in snap["tiles"] if t["tile_id"] == "mining"][0]
    assert tile["activity_id"] == "mining:1"
    ui.publish_ui(
        "ui.activity_end",
        {"activity_id": "mining:1", "end_reason": "done"},
    )
    monkeypatch.setattr(ui, "read_switches", lambda: {"live_on": False})
    ui.refresh_switches()
    ui.publish_ui(
        "ui.tile",
        {
            "tile": {
                "tile_id": "mining",
                "activity_id": "mining:1",
                "on": True,
            }
        },
    )
    snap = ui.snapshot(9)
    tile = [t for t in snap["tiles"] if t["tile_id"] == "mining"][0]
    assert tile["activity_id"] is None
    assert tile["on"] is False


def test_subscribe_refreshes_switches_and_broadcasts_tile(monkeypatch):
    ui = _reset(monkeypatch)
    hello1, q1 = _subscribe(ui, 10)
    monkeypatch.setattr(ui, "read_switches", lambda: {"live_on": True})
    hello2, q2 = _subscribe(ui, 10)

    msg = q1.get(timeout=1)
    ui.mark_dequeued(q1)
    assert msg["kind"] == "ui.tile"
    assert msg["ui_seq"] == hello1["ui_seq"] + 1
    assert hello2["ui_seq"] == msg["ui_seq"]
    assert q2.empty()

    snap = ui.snapshot(hello2["conn"])
    tile = [t for t in snap["tiles"] if t["tile_id"] == "mining"][0]
    assert tile["on"] is True


def test_snapshot_is_read_only_and_set_switches_broadcasts(monkeypatch):
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui, 50)
    before = ui.snapshot(hello["conn"])
    assert before["ui_seq"] == hello["ui_seq"]
    assert before["tiles"] == []
    assert ui.snapshot(hello["conn"]) == before
    assert q.empty()

    ui.set_switches(_ALL_SWITCHES)
    _drain_all(q)
    base_seq = ui.snapshot(hello["conn"])["ui_seq"]
    q_size = q.qsize()
    assert ui.snapshot(hello["conn"])["ui_seq"] == base_seq
    assert ui.snapshot(hello["conn"])["ui_seq"] == base_seq
    assert q.qsize() == q_size

    new_seq = ui.set_switches({"live_on": True})
    assert new_seq == base_seq + 1
    msg = q.get(timeout=1)
    ui.mark_dequeued(q)
    assert msg["kind"] == "ui.tile"
    assert msg["ui_seq"] == new_seq
    assert msg["tile"]["tile_id"] == "mining"
    assert msg["tile"]["on"] is True

    snap = ui.snapshot(hello["conn"])
    assert snap["ui_seq"] == new_seq
    tile = [t for t in snap["tiles"] if t["tile_id"] == "mining"][0]
    assert tile["on"] is True


def test_snapshot_hides_dismissed_notices_and_bounds_ended(monkeypatch):
    ui = _reset(monkeypatch)
    ui.ENDED_MAX = 2
    try:
        for i in range(3):
            ui.publish_ui(
                "ui.activity",
                {
                    "activity": {
                        "activity_id": f"cap:{i}",
                        "kind": "update",
                        "state": "running",
                    }
                },
            )
            ui.publish_ui(
                "ui.activity_end",
                {"activity_id": f"cap:{i}", "end_reason": "done"},
            )
        snap = ui.snapshot(123)
        assert snap["ended"] == ["cap:1", "cap:2"]
        notice_ids = [n["notice_id"] for n in snap["notices"]]
        assert len(notice_ids) == 3
        assert ui.dismiss_notice(notice_ids[0])
        snap2 = ui.snapshot(123)
        assert notice_ids[0] not in [n["notice_id"] for n in snap2["notices"]]
        assert all(not n["dismissed"] for n in snap2["notices"])
    finally:
        ui.ENDED_MAX = 256


def test_drain_and_bye_ends_activities_then_waits_for_queues(monkeypatch):
    ui = _reset(monkeypatch)
    hello, q = _subscribe(ui, 100)
    ui.publish_ui(
        "ui.activity",
        {
            "activity": {
                "activity_id": "update:drain",
                "kind": "update",
                "state": "running",
                "title": "退出测试",
            }
        },
    )

    seen = []
    errors = []
    done = threading.Event()

    def consume():
        try:
            while True:
                msg = q.get(timeout=2)
                ui.mark_dequeued(q)
                seen.append(msg)
                if msg.get("kind") == "ui.bye":
                    break
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=consume)
    thread.start()
    start = time.monotonic()
    sent = ui.drain_and_bye(1.0)
    elapsed = time.monotonic() - start
    assert sent == 1
    assert done.wait(2)
    thread.join(2)
    assert not thread.is_alive()
    assert not errors, errors
    assert elapsed < 0.9
    assert seen[-1]["kind"] == "ui.bye"

    end_event = next(e for e in seen if e.get("kind") == "ui.activity_end")
    assert end_event["activity_id"] == "update:drain"
    assert end_event["end_reason"] == "shutdown"
    end_index = seen.index(end_event)
    notice_id = end_event["summary_notice_id"]
    assert any(
        e.get("kind") == "ui.notice" and e["notice"]["notice_id"] == notice_id
        for e in seen[:end_index]
    )

    before = ui.snapshot(hello["conn"])
    seq = ui.publish_ui("ui.notice", {"notice": {"notice_id": "late"}})
    after = ui.snapshot(hello["conn"])
    assert seq == before["ui_seq"] == after["ui_seq"]
    assert before["activities"] == after["activities"] == []
    assert before["notices"] == after["notices"]
    assert before["notices"]
    assert ui.dismiss_notice(before["notices"][0]["notice_id"]) is False

    closed, q2 = ui.subscribe()
    assert q2 is None
    assert closed["kind"] == "ui.closed"
    assert closed["error"] == "已关闭"


def test_run_task_once_single_flight():
    from astral_toolkit.app import bus

    entered = threading.Event()
    release = threading.Event()

    def work():
        entered.set()
        release.wait(2)
        return "ok"

    task_id = "x_ui_single_flight"
    first = bus.run_task_once(task_id, work, title="单飞测试")
    assert first is not None
    assert entered.wait(2)
    assert bus.run_task_once(task_id, lambda: "no") is None
    release.set()
    first.join(2)
    assert not first.is_alive()
    second = bus.run_task_once(task_id, lambda: "again")
    assert second is not None
    second.join(2)
    assert not second.is_alive()


def test_update_runs_get_distinct_monotonic_ids(monkeypatch):
    ui = _reset(monkeypatch)
    from astral_toolkit.app import bus

    with bus._run_seq_lock:
        bus._run_seq = 0
    _, q = _subscribe(ui, 20)
    for _ in range(2):
        thread = bus.run_task("update", lambda: None, title="更新")
        thread.join(2)
        assert not thread.is_alive()
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    starts = [
        e["activity"]["activity_id"] for e in events if e["kind"] == "ui.activity"
    ]
    ends = [e["activity_id"] for e in events if e["kind"] == "ui.activity_end"]
    assert starts == ["update:1", "update:2"]
    assert ends == starts


def test_update_and_upgrade_paths_use_run_task_once():
    root = Path(__file__).resolve().parents[1]
    cases = [
        ("astral_toolkit/tasks/system/settings.py", "update"),
        ("astral_toolkit/tasks/system/upgrade.py", "upgrade"),
    ]
    for rel, task_id in cases:
        source = (root / rel).read_text(encoding="utf-8")
        pattern = r"run_task_once\s*\(\s*[\"']" + re.escape(task_id) + r"[\"']"
        assert re.search(pattern, source), f"{rel} 的 {task_id} 没走 run_task_once"


def test_old_bus_publish_and_subscribe_unchanged(monkeypatch):
    ui = _reset(monkeypatch)
    from astral_toolkit.app import bus

    old_q = bus.subscribe()
    try:
        _drain_all(old_q)
        bus.publish("x_ui_old_probe", {"v": 1})
        ui.publish_ui("ui.notice", {"notice": {"notice_id": "ui-only"}})
        msgs = []
        while True:
            try:
                msgs.append(old_q.get_nowait())
            except queue.Empty:
                break
        kinds = [msg["kind"] for msg in msgs]
        assert "x_ui_old_probe" in kinds
        assert not any(kind.startswith("ui.") for kind in kinds)
    finally:
        bus.unsubscribe(old_q)


def test_old_bus_not_lost_while_ui_queue_overflows(monkeypatch):
    ui = _reset(monkeypatch)
    from astral_toolkit.app import bus

    old_q = bus.subscribe()
    try:
        _drain_all(old_q)
        _, ui_q = _subscribe(ui, 1)
        with ui._lock:
            for i in range(6):
                ui._send_locked("ui.notice", {"notice": {"notice_id": f"overflow-{i}"}})
        assert not ui.is_connected(ui_q)

        count = 200
        for i in range(count):
            bus.publish("x_ui_old_full_probe", {"i": i})

        got = []
        deadline = time.monotonic() + 3
        while len(got) < count and time.monotonic() < deadline:
            try:
                msg = old_q.get(timeout=0.1)
            except queue.Empty:
                continue
            if msg.get("kind") == "x_ui_old_full_probe":
                got.append(msg)
        assert len(got) == count
    finally:
        bus.unsubscribe(old_q)


def _start_server():
    from astral_toolkit.app.http_server import Handler, Server

    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _SseReader:
    def __init__(self, sock, buf=b""):
        self.sock = sock
        self.buf = buf

    def next_event(self, timeout=3):
        deadline = time.monotonic() + timeout
        while True:
            while b"\n\n" in self.buf:
                block, self.buf = self.buf.split(b"\n\n", 1)
                if block.startswith(b"data: "):
                    return json.loads(block[6:].decode("utf-8"))
            remain = deadline - time.monotonic()
            if remain <= 0:
                raise AssertionError("等待 SSE 事件超时")
            self.sock.settimeout(remain)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                raise AssertionError("等待 SSE 事件超时")
            if not chunk:
                return None
            self.buf += chunk

    def wait_eof(self, timeout=3):
        deadline = time.monotonic() + timeout
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                return False
            self.sock.settimeout(remain)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return False
            except OSError:
                return True
            if not chunk:
                return True
            self.buf += chunk


def _open_ui_stream(port):
    from astral_toolkit.app import http_server

    sock = socket.create_connection(("127.0.0.1", port), timeout=3)
    sock.sendall(
        f"GET /api/ui/events?t={http_server.TOKEN} HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n\r\n".encode()
    )
    sock.settimeout(3)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("SSE 响应头未完成")
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    text = head.decode("latin1")
    assert " 200 " in text
    assert "connection: close" in text.lower()
    return sock, _SseReader(sock, rest)


def test_ui_events_http_hello_increment_and_snapshot_conn(monkeypatch):
    from astral_toolkit.app import http_server

    ui = _reset(monkeypatch)
    srv = _start_server()
    port = srv.server_address[1]
    sock = None
    try:
        sock, reader = _open_ui_stream(port)
        hello = _next_event(reader, timeout=2)
        assert hello["kind"] == "ui.hello"
        assert hello["protocol"] == "ui/1"

        ui.publish_ui("ui.notice", {"notice": {"notice_id": "http-inc"}})
        inc = _next_event(reader, timeout=2)
        assert inc["kind"] == "ui.notice"
        assert inc["ui_seq"] == hello["ui_seq"] + 1
        assert inc["conn"] == hello["conn"]

        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(
            base + f"/api/ui/snapshot?conn={hello['conn']}&t={http_server.TOKEN}",
            timeout=2,
        ) as resp:
            snap = json.loads(resp.read().decode("utf-8"))
        assert snap["conn"] == hello["conn"]
        assert snap["protocol"] == "ui/1"
        assert snap["ui_seq"] == inc["ui_seq"]
    finally:
        if sock is not None:
            sock.close()
        srv.shutdown()
        srv.server_close()


def test_ui_events_refreshes_switches_without_business_events(monkeypatch):
    """没有新的识别或终态事件时，真实 SSE 也会自动刷新后台状态。"""
    ui = _reset(monkeypatch)
    switches = {"live_on": False}
    monkeypatch.setattr(ui, "read_switches", lambda: dict(switches))
    srv = _start_server()
    sock = None
    try:
        sock, reader = _open_ui_stream(srv.server_address[1])
        hello = _next_event(reader)
        assert hello["kind"] == "ui.hello"
        switches["live_on"] = True
        event = _next_event(reader, timeout=2.5)
        assert event["kind"] == "ui.tile"
        assert event["tile"]["on"]
        assert event["ui_seq"] > hello["ui_seq"]
        switches["live_on"] = False
        event2 = _next_event(reader, timeout=2.5)
        assert event2["kind"] == "ui.tile"
        assert not event2["tile"]["on"]
        assert event2["ui_seq"] > event["ui_seq"]
        assert ui.snapshot(hello["conn"])["tiles"][0] == event2["tile"]
    finally:
        if sock is not None:
            sock.close()
        srv.shutdown()
        srv.server_close()


def test_ui_events_http_overflow_then_eof(monkeypatch):
    ui = _reset(monkeypatch)
    ui._QUEUE_MAX = 1
    srv = _start_server()
    port = srv.server_address[1]
    sock = None
    try:
        sock, reader = _open_ui_stream(port)
        hello = _next_event(reader, timeout=2)
        assert hello["kind"] == "ui.hello"

        with ui._lock:
            for i in range(6):
                ui._send_locked("ui.notice", {"notice": {"notice_id": f"overflow-{i}"}})
        assert reader.wait_eof(timeout=3), "队列溢出后应收到 EOF"
        assert not ui._subs
    finally:
        if sock is not None:
            sock.close()
        srv.shutdown()
        srv.server_close()


def test_ui_events_http_bye_then_eof(monkeypatch):
    ui = _reset(monkeypatch)
    srv = _start_server()
    port = srv.server_address[1]
    sock = None
    try:
        sock, reader = _open_ui_stream(port)
        hello = _next_event(reader, timeout=2)
        assert hello["kind"] == "ui.hello"

        assert ui.drain_and_bye(1.0) == 1
        bye = None
        while True:
            msg = _next_event(reader, timeout=3)
            if msg.get("kind") == "ui.bye":
                bye = msg
                break
        assert bye is not None
        assert bye["conn"] == hello["conn"]
        assert bye["ui_seq"] >= hello["ui_seq"]
        assert reader.wait_eof(timeout=3), "bye 后应 EOF"
    finally:
        if sock is not None:
            sock.close()
        srv.shutdown()
        srv.server_close()


def test_ui_heartbeat_uses_injected_interval_and_current_seq(monkeypatch):
    from astral_toolkit.app import http_server

    ui = _reset(monkeypatch)
    http_server.UI_HEARTBEAT_INTERVAL = 0.05
    srv = _start_server()
    port = srv.server_address[1]
    sock = None
    try:
        sock, reader = _open_ui_stream(port)
        hello = _next_event(reader, timeout=2)
        assert hello["kind"] == "ui.hello"

        ui.publish_ui("ui.notice", {"notice": {"notice_id": "hb"}})
        inc = _next_event(reader, timeout=2)
        assert inc["kind"] == "ui.notice"
        assert inc["ui_seq"] == hello["ui_seq"] + 1

        hb = _next_event(reader, timeout=2)
        assert hb["kind"] == "ui.heartbeat"
        assert hb["conn"] == hello["conn"]
        assert hb["ui_seq"] == inc["ui_seq"]
    finally:
        http_server.UI_HEARTBEAT_INTERVAL = 5.0
        if sock is not None:
            sock.close()
        srv.shutdown()
        srv.server_close()


def test_new_endpoints_reject_bad_token(monkeypatch):
    _reset(monkeypatch)
    srv = _start_server()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for path in (
            "/api/ui/events?t=bad",
            "/api/ui/snapshot?conn=1&t=bad",
        ):
            try:
                urllib.request.urlopen(base + path, timeout=2)
                raise AssertionError("应当返回 403")
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
        req = urllib.request.Request(
            base + "/api/ui/dismiss", data=b"{}", method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=2)
            raise AssertionError("应当返回 403")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_old_events_endpoint_is_unchanged(monkeypatch):
    from astral_toolkit.app import bus, http_server, ui_stream

    _reset(monkeypatch)
    srv = _start_server()
    port = srv.server_address[1]
    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
    try:
        head = (
            f"GET /api/events?t={http_server.TOKEN} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n\r\n"
        )
        sock.sendall(head.encode())
        got = b""
        sock.settimeout(2)
        while b"\r\n\r\n" not in got:
            got += sock.recv(1024)
        end = time.time() + 2
        while not bus.clients() and time.time() < end:
            time.sleep(0.01)
        bus.publish("x_ui_http_probe", {"v": 7})
        ui_stream.publish_ui("ui.notice", {"notice": {"notice_id": "http-ui-only"}})
        while b"x_ui_http_probe" not in got:
            got += sock.recv(4096)
        assert b"http-ui-only" not in got
        sock.settimeout(0.2)
        try:
            extra = sock.recv(4096)
        except socket.timeout:
            extra = b""
        assert b"http-ui-only" not in extra
    finally:
        sock.close()
        srv.shutdown()
        srv.server_close()
