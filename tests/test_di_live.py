"""实时读右上角不卡顿（老大 11-03 实测诊断：一分钟里 25 秒耗在识别引擎，坐标 / 镜头方向停几秒，导航记号收起、转向不跟手）：
①字模几秒前还读得出、这一帧读不出（亮光扫过字）：不换识别引擎，0.2 秒后再试字模；
②地点那一行的识别引擎放到后台小线程，读位置的线程不等它"""

import threading
import time
from types import SimpleNamespace

import numpy as np
from PIL import Image


def _live(monkeypatch, D, ready=True):
    piece = Image.new("RGB", (870, 316))
    monkeypatch.setattr(
        "astral_toolkit.infrastructure.platform.capture.grab_region",
        lambda region: piece,
    )
    monkeypatch.setattr(
        "astral_toolkit.infrastructure.platform.capture.game_area",
        lambda: {"left": 0, "top": 0, "width": 2560, "height": 1440},
    )
    monkeypatch.setattr("astral_toolkit.navigation.gridtext.ready", lambda h: ready)
    monkeypatch.setattr(D, "_diag", lambda *a, **k: None)
    monkeypatch.setattr(D, "yielding", lambda: False)


def test_grid_miss_retries_grid_instead_of_ocr(monkeypatch):
    from astral_toolkit.navigation import displayinfo as D

    _live(monkeypatch, D)
    full = []
    monkeypatch.setattr(D, "_grid_read", lambda piece, h: None)
    monkeypatch.setattr(
        D, "_full_read", lambda piece, h=None: full.append(1) or D.parse([])
    )
    monkeypatch.setattr(D, "_layout", {"at": 0.0, "boxes": None})
    D._GRID_OK["at"] = time.time()  # 字模刚读出来过
    info = D.read()
    assert info["grid_miss"] and info["fast"] and not info["global"] and not full
    D._GRID_OK["at"] = time.time() - D.GRID_GRACE - 1  # 好几秒都读不出：照旧换识别引擎
    info = D.read()
    assert full and not info["fast"] and not info.get("grid_miss")
    D._GRID_OK["at"] = 0.0


def test_reader_writes_diagnostics_only_in_debug_mode(monkeypatch):
    from astral_toolkit.navigation import displayinfo

    monkeypatch.setattr("astral_toolkit.system.showloc.game_foreground", lambda: True)
    calls = []

    def fake_read(*, allow_yield=True, diag=False):
        calls.append(diag)
        return {"global": None, "fast": True}

    monkeypatch.setattr(displayinfo, "read", fake_read)
    flag = [False]
    reader = displayinfo.Reader(every=0.2, debug=lambda: flag[0])
    reader.poll(force=True)
    assert calls[-1] is False
    flag[0] = True
    reader.poll(force=True)
    assert calls[-1] is True

    no_debug = displayinfo.Reader(every=0.2, debug=None)
    no_debug.poll(force=True)
    assert calls[-1] is False

    def boom():
        raise RuntimeError("boom")

    broken = displayinfo.Reader(every=0.2, debug=boom)
    broken.poll(force=True)
    assert calls[-1] is False


def test_read_calls_diag_only_when_asked(monkeypatch):
    from astral_toolkit.navigation import displayinfo

    monkeypatch.setattr(
        displayinfo, "_GRID_OK", {"at": 0.0}
    )  # read 会改它：换成新字典，测完还原
    monkeypatch.setattr(
        "astral_toolkit.infrastructure.platform.capture.grab_region",
        lambda region: Image.new("RGB", (400, 100)),
    )
    monkeypatch.setattr(
        "astral_toolkit.infrastructure.platform.capture.game_area",
        lambda: {"left": 0, "top": 0, "width": 1920, "height": 1080},
    )
    monkeypatch.setattr("astral_toolkit.navigation.gridtext.ready", lambda h: True)
    monkeypatch.setattr("astral_toolkit.navigation.gridtext.note", lambda ok: None)
    calls = []
    monkeypatch.setattr(displayinfo, "_diag", lambda *args, **kwargs: calls.append(1))
    mode = {"miss": False}
    good = {**displayinfo.parse([]), "global": (1.0, 2.0, 3.0)}

    def grid_read(piece, screen_h):
        return None if mode["miss"] else dict(good)

    monkeypatch.setattr(displayinfo, "_grid_read", grid_read)

    assert "grid_miss" not in displayinfo.read()
    assert calls == []
    info = displayinfo.read(diag=True)
    assert calls == [1]
    assert info["global"] == (1.0, 2.0, 3.0)

    mode["miss"] = True
    displayinfo._GRID_OK["at"] = time.time()
    assert displayinfo.read()["grid_miss"] is True
    assert calls == [1]
    info = displayinfo.read(diag=True)
    assert calls == [1, 1]
    assert info["grid_miss"] is True

    mode["miss"] = False
    before = len(calls)
    displayinfo.read(img=Image.new("RGB", (1920, 1080)), diag=True)
    assert len(calls) == before


def test_grid_miss_reader_retries_fast(monkeypatch):
    """Reader 拿到字模没读出的那一帧：按快速读的间隔（0.2 秒）再试，不按识别引擎的 2 秒"""
    from astral_toolkit.navigation import displayinfo as D

    monkeypatch.setattr(
        D,
        "read",
        lambda allow_yield=True, diag=False: {
            **D.parse([]),
            "fast": True,
            "grid_miss": True,
        },
    )
    monkeypatch.setattr("astral_toolkit.system.showloc.game_foreground", lambda: True)
    r = D.Reader(every=0.2)
    t0 = time.time()
    r.poll()
    assert r.next_at - t0 < 0.5


def test_location_ocr_runs_in_background(monkeypatch):
    from astral_toolkit.navigation import displayinfo as D, gridtext

    monkeypatch.setattr(
        gridtext, "_for", lambda h: SimpleNamespace(g=SimpleNamespace(lh=13))
    )
    fed = []
    monkeypatch.setattr(gridtext, "feed", lambda arr, rows, h: fed.append(rows))
    started, release = threading.Event(), threading.Event()

    def slow(img):
        started.set()
        release.wait(5)
        return ("Current player location : Stanton2 Orison (LZ : Stanton2 Orison)", 0.9)

    monkeypatch.setattr("astral_toolkit.ocr.read_line", slow)
    monkeypatch.setattr(D, "_known_place", lambda loc: True)
    D._loc.update(hash=None, text="旧地点", at=0.0, top=None, cand=None)
    D._LOC_JOB.clear()
    D._LOC_JOB["busy"] = False
    piece = Image.new("RGB", (870, 316))
    arr = np.asarray(piece)
    D._TL.live = True
    try:
        t0 = time.time()
        got = D._ocr_location(piece, arr, 280, 1440, key="loc v1")
        assert got == "旧地点" and time.time() - t0 < 0.5  # 没等识别引擎
        assert started.wait(2)
        release.set()
        for _ in range(50):
            if "done" in D._LOC_JOB:
                break
            time.sleep(0.02)
        got = D._ocr_location(piece, arr, 280, 1440, key="loc v1")
        assert (
            got.startswith("Stanton2 Orison") and fed
        )  # 下次进来收结果、学字模在读屏线程
    finally:
        D._TL.live = False
        release.set()
        D._loc.update(hash=None, text="", at=0.0, top=None, cand=None)
        D._LOC_JOB.clear()
        D._LOC_JOB["busy"] = False


def test_grid_miss_still_yields_to_mining(monkeypatch):
    """采矿助手要让路时：字模读不出照旧返回「让路」（Reader 记让路时间、隔一会再试），不当成快速读失败狂试（独立审查 11-03）"""
    from astral_toolkit.navigation import displayinfo as D

    _live(monkeypatch, D)
    monkeypatch.setattr(D, "yielding", lambda: True)
    monkeypatch.setattr(D, "_grid_read", lambda piece, h: None)
    D._GRID_OK["at"] = time.time()
    info = D.read()
    assert info.get("yielded") and not info.get("grid_miss")
    D._GRID_OK["at"] = 0.0


def test_marker_keeps_last_camdir_for_one_frame():
    """坐标有、这一帧镜头方向没读出：1 秒内读到的接着用，记号不闪；超过 1 秒才收起，并记下收起原因（老大 11-03 实测）"""
    from astral_toolkit.app import nav_marker

    hud, diag = [], []
    pos = SimpleNamespace(current=(0.0, None, None))
    positions = SimpleNamespace(snapshot=lambda: SimpleNamespace(current=pos.current))
    marker = nav_marker._NavMarker(
        positions,
        mining_running=lambda: False,
        foreground=lambda: True,
        game_area=lambda: {"left": 0, "top": 0, "width": 2560, "height": 1440},
        last_fov=lambda: None,
        settings=lambda: {"nav_marker": True, "fov_axis": "v"},
        hud=lambda: SimpleNamespace(marker=hud.append),
        diag=diag.append,
    )
    tgt = {"space": True, "n": "1", "x": 1.0, "y": 0.0, "z": 0.0}
    state = {"here": {}}
    now = time.time()
    g = (0.0, 0.0, 0.0)
    pos.current = (now, g, {"camdir": (0.0, 0.0, -90.0), "fov": 70.0, "t": now})
    shown = marker.tick(tgt, {}, state, None)
    assert shown == now and hud[-1] is not None
    pos.current = (now + 0.3, g, {"t": now + 0.3})  # 这帧镜头方向没读出
    shown = marker.tick(tgt, {}, state, shown)
    assert shown == now + 0.3 and hud[-1] is not None and not diag
    pos.current = (now + 1.5, g, {"t": now + 1.5})  # 超过 1 秒还是没有
    assert marker.tick(tgt, {}, state, shown) is None
    assert hud[-1] is None and diag == ["没有镜头方向"]


def test_fast_reads_are_scheduled_from_read_start(monkeypatch):
    """字模读的按开始读的时间排下一次：读一次 15 毫秒、30 帧时还是每 1/30 秒一次；识别引擎照旧从读完算起
    （老大 11-05 实测 60 档只读到约 31 次）"""
    from astral_toolkit.navigation import displayinfo as D

    clock = [100.0]
    monkeypatch.setattr(D, "time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr("astral_toolkit.system.showloc.game_foreground", lambda: True)
    kind = {"fast": True, "global": True}

    def fake_read(allow_yield=True, diag=False):
        clock[0] += 0.015  # 读一次 15 毫秒
        g = (1.0, 2.0, clock[0] * 1000) if kind["global"] else None
        return {**D.parse([]), "global": g, "fast": kind["fast"]}

    monkeypatch.setattr(D, "read", fake_read)
    r = D.Reader(every=1 / 30)
    r.poll(force=True)
    assert abs(r.next_at - (100.0 + 1 / 30)) < 1e-9  # 从开始读算起
    kind["global"] = False  # 字模这帧没读出（也是快读）
    clock[0] = 150.0
    r.poll(force=True)
    assert abs(r.next_at - (150.0 + 1 / 30)) < 1e-9
    kind["fast"] = False  # 识别引擎没读到：照旧从读完算起，至少隔 2 秒
    clock[0] = 200.0
    r.poll(force=True)
    assert abs(r.next_at - (200.015 + 2.0)) < 1e-9
