"""RT-B5b：PositionService 的同步读、快照、需求与可停外壳"""

import time

from astral_toolkit.app.engines import pos as posmod


class _Reader:
    def __init__(self):
        self.active = True
        self.ok_at = 1.0
        self.next_at = 99.0
        self.misses = 9
        self.polled = None

    def poll(self, force=False):
        self.polled = force
        self.ok_at = 2.0

    def snapshot(self):
        return (
            2.0,
            {
                "global": (10.0, 20.0, 30.0),
                "zone": "Zone",
                "location": "Location",
                "solar_id": "S",
                "fast": True,
            },
        )


def test_position_service_request_read_and_read_now():
    p = posmod._Pos()
    p.reader = _Reader()
    p.request_read_now()
    assert p.reader.next_at == 0.0 and p.reader.misses == 0
    rd = p.read_now(force=True)
    assert p.reader.polled is True
    assert rd.ok_at == 2.0
    assert rd.global_ == (10.0, 20.0, 30.0)
    assert rd.info["location"] == "Location"


def test_position_snapshot_hints_and_demand():
    p = posmod._Pos()
    now = time.time()
    p.current = (
        now,
        (1.0, 2.0, 3.0),
        {"zone": "Z", "location": "L", "solar_id": "S"},
    )
    p.latest = p.current
    p.label = (now, "地点")
    p.system = (now, "星系")
    p.here = {"body": "Daymar"}
    snap = p.snapshot()
    assert snap.current == p.current
    assert snap.label == (now, "地点")
    assert snap.here == {"body": "Daymar"}
    assert p.hints() == {"zone": "Z", "location": "L", "solar_id": "S"}
    p.set_demand("nav", now + 10)
    assert p._navigating() is True
    p.set_demand("nav", 0)
    assert p._navigating() is False


def test_logwatch_start_stop_shell(monkeypatch):
    import threading

    w = posmod._LogWatch()
    release = threading.Event()
    monkeypatch.setattr(w, "_run", release.wait)
    w.start()
    first = w.thread
    w.start()
    assert w.thread is first
    w.request_stop()
    release.set()
    assert w.join(1.0) is True


def test_game_events_shell_and_callback():
    called = []
    ev = __import__(
        "astral_toolkit.app.engines.nav", fromlist=["_GameEvents"]
    )._GameEvents(on_qt_arrived=lambda: called.append(1))
    assert ev.on_qt_arrived is not None
    ev.request_stop()
    assert ev.join(0.0) is True
