"""定位工作线程（RT-B5b 的 PositionService；R1 起在 runtime/workers/position）：同步读、快照、需求、可停外壳，
以及 R1 接进来的读屏、分析、发布（目录迁移章程 §6）"""

import sys
import threading
import time
from types import SimpleNamespace

from astral_toolkit.runtime.workers import position as posmod


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


def _worker(reader=None, **kw):
    """测试用的定位线程：没给的分析都是「认不出」，不推状态、不写日志"""
    kw.setdefault("foreground", lambda: True)
    kw.setdefault("calibrated", lambda: False)
    kw.setdefault("label_of", lambda location: "")
    kw.setdefault("system_of", lambda g, **k: None)
    kw.setdefault("locate", lambda g, **k: None)
    kw.setdefault("enabled", True)
    return posmod.PositionWorker(_Reader() if reader is None else reader, **kw)


def test_position_service_request_read_and_read_now():
    p = _worker()
    p.request_read_now()
    assert p.reader.next_at == 0.0 and p.reader.misses == 0
    rd = p.read_now(force=True)
    assert p.reader.polled is True
    assert rd.ok_at == 2.0
    assert rd.global_ == (10.0, 20.0, 30.0)
    assert rd.info["location"] == "Location"


def test_position_snapshot_hints_and_demand():
    p = _worker()
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
    w = posmod.LogWatchWorker(read_log=lambda: None)
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


def test_bootstrap_gives_reader_the_debug_switch(monkeypatch):
    """调试模式开关交给读右上角的 Reader（R1 起 Reader 由 bootstrap 造好交给定位线程）"""
    from astral_toolkit import bootstrap
    from astral_toolkit.navigation import displayinfo

    def on():
        return True

    monkeypatch.setattr(bootstrap, "_debug_on", lambda view: on)
    p = bootstrap._pos_service("test", None)
    assert isinstance(p.reader, displayinfo.Reader)
    assert p.reader.debug is on and p.reader.every == 1.0


def test_demand_fps_takes_highest_live_request():
    p = _worker()
    now = time.time()
    assert p.fps_wanted() == 5
    p.set_demand("nav", now + 10, fps=20)
    assert p.fps_wanted() == 20
    p.set_demand("halo", now + 10, fps=10)
    assert p.fps_wanted() == 20
    p.set_demand("x", now + 10, fps=120)
    assert p.fps_wanted() == 30  # 最高 30
    p.set_demand("x", 0)
    assert p.fps_wanted() == 20
    p.set_demand("old", now - 1, fps=25)
    assert p.fps_wanted() == 20
    p.set_demand("nav", now + 10)
    assert p.fps_wanted() == 10
    p.set_demand("halo", now + 10, fps=0)
    assert p.fps_wanted() == 5
    p.set_demand("halo", now + 10, fps=-3)
    assert p.fps_wanted() == 5


def test_tune_sets_read_interval_from_fps():
    p = _worker(reader=SimpleNamespace(every=None, max_gap=None))
    assert p._tune(True, False) == 5
    assert p.reader.every == 0.2
    assert p.reader.max_gap == 60.0

    now = time.time()
    p.set_demand("nav", now + 10, fps=60)  # 要 60 也按 30
    assert p._tune(True, True) == 30
    assert p.reader.every == 1 / 30
    assert p.reader.max_gap == 5.0

    p._tune(False, True)
    assert p.reader.every == 1.0
    p._tune(False, False)
    assert p.reader.every == posmod.PositionWorker.CALIB_EVERY


def test_nap_waits_until_next_read_at_most_50ms():
    p = _worker()
    assert p._nap(False, 0) == 0.2
    assert p._nap(True, 100.0, now=99.0) == 0.05
    assert abs(p._nap(True, 100.0, now=99.99) - 0.01) < 1e-9
    assert p._nap(True, 100.0, now=101.0) == 0.001


def test_fine_timer_switches_once_per_change():
    calls = []
    p = _worker(fine_timer=calls.append)
    p._fine(True)
    p._fine(True)
    p._fine(False)
    p._fine(False)
    assert calls == [True, False]

    _worker()._fine(True)

    def boom(on):
        raise RuntimeError("没有计时器")

    p = _worker(fine_timer=boom)
    p._fine(True)
    p._fine(False)


# ---------------------------------------------------------------- R1：接进来的读屏、分析、发布


def _info(**kw):
    info = {
        "global": [10.0, 20.0, 30.0],
        "zone": "Z",
        "location": "Loc",
        "solar_id": "S",
        "t": 5.0,
        "local": (1.0, 2.0, 3.0),
        "local_ok": True,
        "fast": True,
    }
    info.update(kw)
    return info


def test_absorb_asks_injected_analysis_with_what_the_reader_saw():
    """读到新位置：地点名、星系、离哪最近都问接进来的分析，参数照右上角读到的给；地点变了马上推状态"""
    calls, pubs = [], []
    p = _worker(
        label_of=lambda loc: calls.append(("label", loc)) or "地点甲",
        system_of=lambda g, **k: calls.append(("system", g, k)) or "Stanton",
        locate=lambda g, **k: calls.append(("locate", g, k)) or {"body": "Daymar"},
        publish_status=lambda: pubs.append(1),
    )
    p._absorb(4.0, _info())
    assert calls == [
        ("label", "Loc"),
        (
            "system",
            [10.0, 20.0, 30.0],
            {"zone": "Z", "location": "Loc", "solar_id": "S"},
        ),
        (
            "locate",
            (10.0, 20.0, 30.0),
            {"when": 5.0, "local": (1.0, 2.0, 3.0), "zone": "Z", "local_ok": True},
        ),
    ]
    snap = p.snapshot()
    assert snap.label[1] == "地点甲" and snap.system[1] == "Stanton"
    assert snap.here == {"body": "Daymar"} and snap.read_at == 5.0 and snap.fast is True
    assert pubs == [1, 1]  # 位置变了推一次；地点、星系变了再强推一次
    p._absorb(6.0, _info(t=7.0))  # 同一处、同一地点：一秒内不再推
    assert pubs == [1, 1] and p.snapshot().read_at == 7.0


def test_absorb_survives_system_and_locate_errors():
    """算星系、算离哪最近出错：星系不变，离哪最近写 None（别留着上一处的）"""

    def boom(g, **k):
        raise RuntimeError("坏了")

    p = _worker(label_of=lambda loc: "", system_of=boom, locate=boom)
    p.system = (1.0, "Pyro")
    p.here = {"body": "旧的"}
    p._absorb(4.0, _info())
    assert p.system == (1.0, "Pyro") and p.here is None


class _LoopReader:
    """读一次就叫停的读取器：记下按几秒一次读"""

    def __init__(self, stop, info=None):
        self.stop, self.info = stop, info
        self.ok_at, self.active, self.next_at = 0.0, True, 0.0
        self.every = self.max_gap = None
        self.polls = []

    def poll(self, force=False):
        self.polls.append(self.every)
        self.ok_at = 1.0
        self.stop.set()

    def snapshot(self):
        return self.ok_at, self.info


class _StopOnWait(threading.Event):
    """第一次等就叫停（游戏不在最前面时那下 0.5 秒的等）"""

    def wait(self, timeout=None):
        self.set()
        return True


def _drive(w, timeout=5.0):
    """在后台线程里跑一遍线程循环，最多等 timeout 秒：循环停不下来就叫停、判失败，不把整个测试卡死"""
    errors = []

    def run():
        try:
            w._run()
        except (
            BaseException
        ) as e:  # 线程里没接住的异常也算失败（不然线程死了也像是停了）
            errors.append(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    stuck = t.is_alive()
    w.stop_ev.set()
    t.join(1.0)
    assert not stuck, "线程循环没停下来"
    assert errors == [], errors


def _run_once(info=None, **kw):
    p = _worker(**kw)
    p.reader = _LoopReader(p.stop_ev, info)
    _drive(p)
    return p


def test_loop_treats_foreground_error_as_in_front_and_calibration_error_as_not_ready():
    """判断游戏在不在最前面出错当在（照读）；判断字模学好没有出错当没好（2 秒校准一次）"""

    def boom():
        raise RuntimeError("坏了")

    p = _run_once(foreground=boom, calibrated=boom)
    assert p.reader.polls == [posmod.PositionWorker.CALIB_EVERY]
    p = _run_once(calibrated=lambda: True)
    assert p.reader.polls == [1 / posmod.PositionWorker.BASE_FPS]


def test_loop_pauses_when_game_not_in_front():
    """游戏不在最前面：不读右上角，关掉等待精度"""
    fine = []
    p = _worker(foreground=lambda: False, fine_timer=fine.append)
    p._fine_on = True
    p.stop_ev = _StopOnWait()
    p.reader = _LoopReader(p.stop_ev)
    _drive(p)
    assert p.reader.polls == [] and fine == [False]


def test_loop_logs_read_errors_and_keeps_state():
    """一圈里出错（这里是认地点名出错）写一行到窗口日志，线程不退"""
    lines = []

    def boom(loc):
        raise RuntimeError("认不出")

    p = _worker(label_of=boom, log=lines.append)
    p.reader = _LoopReader(p.stop_ev, _info())
    _drive(p)
    assert lines == ["右上角识别失败：认不出"]


def test_disabled_worker_does_not_start():
    """这台机器读不了右上角（不是 Windows）：start 不起线程"""
    p = _worker(enabled=False)
    p.start()
    assert p.thread is None and p.join(0.0) is True


def test_logwatch_publishes_only_when_place_changes():
    """游戏日志里的地点变了才推状态；读日志出错不退"""
    seq = iter(
        [
            None,
            (1.0, "甲", {}),
            (1.0, "甲", {"x": 1}),
            RuntimeError("坏了"),
            (2.0, "乙", {}),
        ]
    )
    pubs = []
    w = posmod.LogWatchWorker(
        read_log=lambda: None, publish_status=lambda: pubs.append(w.last)
    )

    def read():
        try:
            hit = next(seq)
        except StopIteration:
            w.stop_ev.set()
            return None
        if isinstance(hit, Exception):
            raise hit
        return hit

    w._read_log = read
    w.EVERY = 0
    _drive(w)
    assert pubs == [(1.0, "甲"), (2.0, "乙"), None]


def test_bootstrap_wires_position_analysis_and_bus(monkeypatch):
    """bootstrap 把 tasks/position 的分析、游戏前台判断、推状态和写日志接进定位线程（R1）"""
    from astral_toolkit import bootstrap
    from astral_toolkit.app import bus
    from astral_toolkit.infrastructure.platform import window
    from astral_toolkit.system import showloc
    from astral_toolkit.tasks import position as T

    sent = []
    monkeypatch.setattr(bus, "publish", lambda topic, data: sent.append((topic, data)))
    p = bootstrap._pos_service("test", None, status=lambda: {"s": 1})
    assert (p._label_of, p._system_of, p._locate) == (T.label_of, T.system_of, T.locate)
    assert p._calibrated is T.glyphs_ready and p._foreground is window.foreground
    monkeypatch.setattr(showloc, "game_foreground", lambda: "现取的")
    assert p._foreground() == "现取的"  # 每次现取 showloc 里的，换了函数也用新的
    assert p._enabled is (sys.platform == "win32")
    p._publish(force=True)
    assert p._log is not None
    p._log("右上角识别失败：x")
    assert sent == [
        ("status", {"s": 1}),
        ("log", {"task": "displayinfo", "line": "右上角识别失败：x"}),
    ]
    assert bootstrap._pos_service("test", None)._publish_status is None


def test_tasks_position_forwards_to_navigation(monkeypatch):
    """tasks/position 的几样分析原样转给 navigation / core.capture（参数一个不丢）"""
    from astral_toolkit.core import capture
    from astral_toolkit.navigation import gridtext, navigate
    from astral_toolkit.navigation import position as nav_position
    from astral_toolkit.tasks import position as T

    got = []
    monkeypatch.setattr(
        nav_position, "display_label", lambda loc: got.append(loc) or "名"
    )
    monkeypatch.setattr(nav_position, "from_log", lambda: (1.0, "甲", {}))
    monkeypatch.setattr(
        navigate, "system_of", lambda g, **k: got.append((g, k)) or "Pyro"
    )
    monkeypatch.setattr(
        navigate, "locate", lambda g, **k: got.append((g, k)) or {"b": 1}
    )
    monkeypatch.setattr(capture, "game_area", lambda: {"height": 1440})
    monkeypatch.setattr(gridtext, "ready", lambda h: got.append(h) or True)
    assert T.label_of("Loc") == "名"
    assert T.system_of([1], zone="Z", location="L", solar_id="S") == "Pyro"
    assert T.locate((1,), when=2.0, local=None, zone="Z", local_ok=False) == {"b": 1}
    assert T.glyphs_ready() is True
    assert T.last_log_place() == (1.0, "甲", {})
    assert got == [
        "Loc",
        ([1], {"zone": "Z", "location": "L", "solar_id": "S"}),
        ((1,), {"when": 2.0, "local": None, "zone": "Z", "local_ok": False}),
        1440,
    ]


def test_worker_starts_once_stops_and_restarts():
    """定位线程：起一次只有一个线程（名字 displayinfo、后台线程）；叫停后线程真的退出；停了可以再开"""
    p = _worker(foreground=lambda: False)  # 游戏不在最前面：每圈只等，不读
    p.start()
    first = p.thread
    p.start()
    assert p.thread is first and first is not None
    assert first.name == "displayinfo" and first.daemon
    p.request_stop()
    assert p.join(2.0) is True and not first.is_alive()
    p.start()
    again = p.thread
    assert again is not None and again is not first and again.is_alive()
    p.request_stop()
    assert p.join(2.0) is True
