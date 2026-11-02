"""UI-K0a：新展示流骨架、run_id、终态顺序、旧通道零影响。"""

import queue
import socket
import threading
import time
import urllib.error
import urllib.request


def _reset():
    from astral_toolkit.app import ui_stream

    ui_stream.reset_for_tests()
    return ui_stream


def test_hello_atomic_and_first_increment():
    ui = _reset()
    ui.publish_ui("ui.notice", {"notice": {"notice_id": "old"}})
    hello, q = ui.subscribe(maxsize=10)
    ui.publish_ui("ui.notice", {"notice": {"notice_id": "new"}})
    assert hello["kind"] == "ui.hello"
    assert hello["protocol"] == "ui/1"
    assert hello["ui_seq"] == 1
    msg = q.get(timeout=1)
    ui.mark_dequeued(q)
    assert msg["ui_seq"] == hello["ui_seq"] + 1
    assert msg["notice"]["notice_id"] == "new"
    assert q.empty()


def test_ui_seq_continuous_under_concurrent_publish():
    ui = _reset()
    _, q = ui.subscribe(maxsize=200)

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
    assert seqs == list(range(1, 101))
    assert len({msg["conn"] for msg in msgs}) == 1


def test_full_queue_disconnects_subscription():
    ui = _reset()
    _, q = ui.subscribe(maxsize=1)
    assert ui.is_connected(q)
    ui.publish_ui("ui.notice", {"notice": {"notice_id": "keep"}})
    ui.publish_ui("ui.notice", {"notice": {"notice_id": "drop"}})
    assert not ui.is_connected(q)
    assert q.qsize() == 1
    kept = q.get_nowait()
    assert kept["notice"]["notice_id"] == "keep"


def test_snapshot_and_increment_watermark():
    ui = _reset()
    hello, q = ui.subscribe(maxsize=10)
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
    snap = ui.snapshot(hello["conn"], switches={})
    assert snap["conn"] == hello["conn"]
    assert snap["ui_seq"] >= hello["ui_seq"]
    assert snap["ui_seq"] == 1
    assert [a["activity_id"] for a in snap["activities"]] == ["update:1"]
    first = q.get(timeout=1)
    ui.mark_dequeued(q)
    assert first["ui_seq"] <= snap["ui_seq"]
    ui.publish_ui("ui.notice", {"notice": {"notice_id": "after"}})
    nxt = q.get(timeout=1)
    ui.mark_dequeued(q)
    assert nxt["ui_seq"] == snap["ui_seq"] + 1


def test_activity_end_notice_before_terminal_and_no_revive():
    ui = _reset()
    hello, q = ui.subscribe(maxsize=10)
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
    snap = ui.snapshot(hello["conn"], switches={})
    assert snap["activities"] == []
    assert "upgrade:7" in snap["ended"]
    assert snap["notices"][0]["notice_id"] == notice_id


def test_notice_dismiss_is_authoritative():
    ui = _reset()
    hello, q = ui.subscribe(maxsize=10)
    ui.publish_ui(
        "ui.notice",
        {"notice": {"notice_id": "n1", "dismissed": False}},
    )
    assert ui.dismiss_notice("n1")
    snap = ui.snapshot(hello["conn"], switches={})
    notice = [n for n in snap["notices"] if n["notice_id"] == "n1"][0]
    assert notice["dismissed"] is True
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [e["kind"] for e in events] == ["ui.notice", "ui.notice_dismiss"]


def test_tiles_only_come_from_current_activity():
    ui = _reset()
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
    snap = ui.snapshot(9, switches={"live_on": True})
    tile = [t for t in snap["tiles"] if t["tile_id"] == "mining"][0]
    assert tile["activity_id"] == "mining:1"
    ui.publish_ui(
        "ui.activity_end",
        {"activity_id": "mining:1", "end_reason": "done"},
    )
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
    snap = ui.snapshot(9, switches={"live_on": True})
    tile = [t for t in snap["tiles"] if t["tile_id"] == "mining"][0]
    assert tile["activity_id"] is None


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


def test_update_runs_get_distinct_monotonic_ids():
    ui = _reset()
    from astral_toolkit.app import bus

    with bus._run_seq_lock:
        bus._run_seq = 0
    _, q = ui.subscribe(maxsize=20)
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


def test_old_bus_publish_and_subscribe_unchanged():
    ui = _reset()
    from astral_toolkit.app import bus

    old_q = bus.subscribe()
    try:
        while True:
            try:
                old_q.get_nowait()
            except queue.Empty:
                break
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


def _start_server():
    from astral_toolkit.app.http_server import Handler, Server

    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_old_events_endpoint_is_unchanged():
    from astral_toolkit.app import bus, http_server, ui_stream

    ui_stream.reset_for_tests()
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


def test_new_endpoints_reject_bad_token():
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
