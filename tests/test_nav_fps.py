"""NV-B5：导航帧数的设置、界面、悬浮窗合并与 Windows 等待精度。"""

from types import SimpleNamespace
from typing import Any

from astral_toolkit.app import overlay
from astral_toolkit.core import settings


def test_nav_fps_value_is_clamped():
    assert settings.DEFAULTS["nav_fps"] == 5
    for value in (None, "abc", float("nan"), float("inf")):
        assert settings.nav_fps(value) == 5
    assert settings.nav_fps(3) == 5
    assert settings.nav_fps(7.6) == 8
    assert settings.nav_fps("30") == 30
    assert settings.nav_fps(100) == 30
    assert settings.nav_fps(45) == 30


def test_set_settings_saves_clamped_nav_fps_and_restyles(monkeypatch, tmp_path):
    import astral_toolkit.tasks.system.settings as system_settings
    from astral_toolkit import bootstrap
    from astral_toolkit.tasks.system.settings import set_settings
    from tests.bootstrap_helpers import app_for_test

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    restyles = []

    class Hud:
        def restyle(self):
            restyles.append(True)

    monkeypatch.setattr(system_settings, "_hud", lambda: Hud())
    # set_settings 存完会推一次状态：换成只记下状态源的，不去初始化识别引擎（显卡）
    seen = []
    monkeypatch.setattr(
        "astral_toolkit.tasks.system.status.status",
        lambda sources: seen.append(sources) or {"marker": 1},
    )
    sent = []
    monkeypatch.setattr(
        system_settings.bus, "publish", lambda kind, data: sent.append((kind, data))
    )
    with app_for_test() as app:
        sources = bootstrap.status_sources(app)
        assert set_settings(sources, nav_fps=100)["nav_fps"] == 30
        assert set_settings(sources, nav_fps=3)["nav_fps"] == 5
        assert restyles
        assert settings.load()["nav_fps"] == 5
    # F 段 B5c：每次改完推的状态，用的是传进来的这份状态源
    assert seen == [sources, sources]
    assert sent.count(("status", {"marker": 1})) == 2


def test_settings_page_has_nav_fps_control():
    from astral_toolkit.core import paths

    js = (paths.CODE / "app" / "web" / "app.js").read_text(encoding="utf-8")
    assert 'segH("nav-fps"' in js
    assert '["#nav-fps", "nav_fps"]' in js
    assert '["30", "30"]' in js and '["15", "15"]' in js
    assert '["60", "60"]' not in js  # 老大 11-05 改成 5–30


def _hud_for_tick(monkeypatch) -> Any:
    monkeypatch.setattr(overlay, "ENABLED", False)
    h: Any = overlay.Hud()  # 假根、假设置都挂在实例上：类型按 Any

    class Root:
        def __init__(self):
            self.after_ms = []

        def after(self, ms, fn):
            self.after_ms.append(ms)
            return None

    h.root = Root()
    h.ok = True
    h._settings = lambda: (1.0, 0.72)
    return h


def test_overlay_draws_only_latest_marker_once_per_tick(monkeypatch):
    h = _hud_for_tick(monkeypatch)
    draws = []
    h._marker_render = lambda: draws.append(1)
    for _ in range(3):
        h._q.put("marker")
    h._tick()
    assert len(draws) == 1


def test_overlay_ticks_faster_while_marker_shown(monkeypatch):
    h = _hud_for_tick(monkeypatch)
    h._fresh = {}
    h.mk_data = None
    h._tick()
    assert h.root.after_ms[-1] == 100

    h.mk_data = {"x": 1}
    h._fps = 30
    h._tick()
    assert h.root.after_ms[-1] == 16

    h._fps = 20
    h._tick()
    assert h.root.after_ms[-1] == 25

    h._fps = 5
    h._tick()
    assert h.root.after_ms[-1] == 100


def test_platform_fine_timer_is_idempotent(monkeypatch):
    from astral_toolkit.infrastructure.platform import timer

    monkeypatch.setattr(timer, "_ON", {"on": False})
    monkeypatch.setattr(timer, "sys", SimpleNamespace(platform="win32"))
    calls = []

    class Winmm:
        def timeBeginPeriod(self, value):
            calls.append(("begin", value))

        def timeEndPeriod(self, value):
            calls.append(("end", value))

    monkeypatch.setattr(timer, "_winmm", lambda: Winmm())
    timer.fine(True)
    timer.fine(True)
    timer.fine(False)
    timer.fine(False)
    assert calls == [("begin", 1), ("end", 1)]
    assert timer._ON["on"] is False

    monkeypatch.setattr(timer, "sys", SimpleNamespace(platform="linux"))
    timer.fine(True)
    assert calls == [("begin", 1), ("end", 1)]
    assert timer._ON["on"] is False

    monkeypatch.setattr(timer, "sys", SimpleNamespace(platform="win32"))

    def boom():
        raise RuntimeError("没有 winmm")

    monkeypatch.setattr(timer, "_winmm", boom)
    timer.fine(True)
    assert timer._ON["on"] is False


def test_position_loop_reads_at_requested_fps_and_switches_fine_timer(monkeypatch):
    """位置线程：字模好了按要的帧数读；读得比平时快时打开等待精度，停下关掉（控制台补：_run 的接线）"""
    import time

    from astral_toolkit.app.engines import pos as posmod

    monkeypatch.setattr("astral_toolkit.system.showloc.game_foreground", lambda: True)
    monkeypatch.setattr("astral_toolkit.navigation.gridtext.ready", lambda h: True)
    monkeypatch.setattr(
        "astral_toolkit.core.capture.game_area",
        lambda: {"left": 0, "top": 0, "width": 1920, "height": 1080},
    )
    fine = []
    p = posmod._Pos(fine_timer=fine.append)
    seen = []

    class Reader:
        ok_at = 0.0
        active = False
        next_at = 0.0
        every = 0.0
        max_gap = 0.0

        def poll(self, force=False):
            seen.append(self.every)
            self.next_at = time.time() + self.every
            if len(seen) >= 3:
                p.stop_ev.set()

        def snapshot(self):
            return 0.0, None

    p.reader = Reader()
    p.set_demand("nav", float("inf"), fps=30)
    p._run()
    assert seen == [1 / 30] * 3
    assert fine == [True, False]


def test_first_tick_waits_by_fps_while_waiting_for_position(monkeypatch):
    """还没拿到第一个位置时：地面导航也按帧数等，手动定位照旧 0.3 秒（控制台补）"""
    import threading

    from astral_toolkit.app.engines import nav as navmod
    from astral_toolkit.runtime.session import Session

    links = navmod.NavLinks(
        log=lambda msg: None,
        fix_key_hint=lambda: ("", ""),
        place_row=lambda target: None,
        setting=lambda key, default: default,
        fps=lambda: 30,
    )
    worker = navmod._NavWorker(
        SimpleNamespace(),
        SimpleNamespace(check=lambda cam, fast=False: cam),
        threading.Lock(),
        links=links,
    )
    monkeypatch.setattr(worker, "_first_tick", lambda session, ctx: False)
    ground = navmod.NavPayload({"n": "X"}, {"key": "x"}, False)
    tick = worker.tick(
        Session(1, threading.Event(), ground), navmod._NavCtx(1, ground), 0.0
    )
    assert abs(tick.wait - 0.5 / 30) < 1e-9
    space = navmod.NavPayload({"n": "X"}, {"key": "x"}, True)
    tick = worker.tick(
        Session(2, threading.Event(), space), navmod._NavCtx(2, space), 0.0
    )
    assert tick.wait == 0.3


def test_overlay_reads_nav_fps_with_its_settings(monkeypatch):
    """悬浮窗两秒读一次设置时把导航帧数也读上（控制台补）"""
    monkeypatch.setattr(overlay, "ENABLED", False)
    h = overlay.Hud()
    monkeypatch.setattr(settings, "load", lambda: {**settings.DEFAULTS, "nav_fps": 30})
    h._cfg_at = 0.0
    h._settings()
    assert h._fps == 30


def test_ground_tick_waits_by_fps_when_commit_refused(monkeypatch):
    """提交被拒（会话已停）那一圈也按帧数等（控制台补）"""
    import threading

    from astral_toolkit.app.engines import nav as navmod
    from astral_toolkit.navigation import navigate as n
    from astral_toolkit.runtime.session import Session

    for name, value in (
        ("label", lambda t: "目标"),
        ("load", lambda: {}),
        ("read_clipboard", lambda: ""),
        ("parse_clip", lambda clip: None),
    ):
        monkeypatch.setattr(n, name, value)
    links = navmod.NavLinks(
        log=lambda msg: None,
        fix_key_hint=lambda: ("", ""),
        place_row=lambda target: None,
        setting=lambda key, default: default,
        fps=lambda: 30,
    )
    snap = SimpleNamespace(
        current=(0.0, None, None),
        latest=(0.0, None, None),
        read_at=0.0,
        reader_active=False,
        reader_ok_at=0.0,
    )
    pos = SimpleNamespace(snapshot=lambda: snap, set_demand=lambda *a, **k: None)
    worker = navmod._NavWorker(
        pos,
        SimpleNamespace(check=lambda cam, fast=False: cam),
        threading.Lock(),
        links=links,
    )
    worker.loop = SimpleNamespace(commit=lambda session, *ops: False)
    payload = navmod.NavPayload({"n": "X", "b": "B"}, {"key": "x"}, False)
    ctx = navmod._NavCtx(1, payload)
    ctx.first = False
    ctx.data = {}
    tick = worker._ground_tick(Session(1, threading.Event(), payload), ctx, 100.0)
    assert abs(tick.wait - 0.5 / 30) < 1e-9
