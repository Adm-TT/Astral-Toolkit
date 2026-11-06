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
from astral_toolkit.app.engines import nav as navmod
from astral_toolkit.crafting import stockplaces
from astral_toolkit.mining import screen as mining_screen
from astral_toolkit.mining import signals as mining_signals
from astral_toolkit.mining.parse import Scan
from astral_toolkit.runtime.session import RunFlag, RunState
from astral_toolkit.tasks import catalog as catalog_tasks
from astral_toolkit.tasks import count as count_tasks
from astral_toolkit.tasks import crafting as crafting_tasks
from astral_toolkit.tasks import hover as hover_tasks
from astral_toolkit.tasks import mining as mining_tasks
from astral_toolkit.tasks import navigation as nav_tasks
from astral_toolkit.tasks import system as system_tasks
from astral_toolkit.tasks import trade as trade_tasks
from astral_toolkit.tasks import wikelo as wikelo_tasks
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
            assert not hasattr(mining_tasks, "_live")
            assert not hasattr(nav_tasks, "_nav")
            assert app.nav_deps == nav_tasks.NavDeps(
                app.nav, app.pos, app.game_events, app.results
            )
            assert app.hover._nav is app.nav_deps
            assert count_tasks._count is app.count
            assert not hasattr(hover_tasks, "_links")
            assert app.hover_links.loot is catalog_tasks.get_item_loot
            assert app.hover._links is app.hover_links
            assert not hasattr(system_common, "_status") and not hasattr(
                system_common, "_start"
            )
            assert (
                app.hover._feedback is not None
                and app.pos._status is not None
                and app.logwatch._status is not None
            )
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


def test_nav_marker_is_wired_by_bootstrap():
    from astral_toolkit.app import hud_state
    from astral_toolkit.core import settings
    from astral_toolkit.infrastructure.platform import window
    from astral_toolkit.navigation import displayinfo

    app = bootstrap.build("test")
    try:
        marker = app.nav._marker
        assert isinstance(marker, navmod._NavMarker)
        assert app.nav._worker._marker is marker
        assert marker._pos is app.pos
        assert marker._mining_running == app.live.running
        assert marker._hud() is None
        assert marker._hud is not hud_state._hud
    finally:
        try:
            bootstrap.shutdown(app, budget=0.2)
        except Exception:
            pass

    pos = SimpleNamespace()
    live = SimpleNamespace(running=lambda: False)
    view = settings.View()
    marker = bootstrap._nav_marker(pos, live, "desktop", view)
    assert marker._pos is pos
    assert marker._mining_running is live.running
    assert marker._hud is hud_state._hud
    assert marker._foreground is window.foreground
    assert marker._game_area is window.game_area
    assert marker._last_fov is displayinfo.last_fov
    assert marker._settings == view.all


def test_debug_mode_gates_nav_diagnostics(monkeypatch, tmp_path):
    from astral_toolkit.core import paths, settings

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    monkeypatch.setattr(paths, "log", lambda name: tmp_path / name)
    app = bootstrap.build("test")
    try:
        app.nav._marker._diag("读数过期")
        assert not (tmp_path / "di_log.txt").exists()
        assert app.pos.reader._diag_on() is False

        settings.update(debug_mode=True)
        app.nav._marker._diag("读数过期")
        text = (tmp_path / "di_log.txt").read_text(encoding="utf-8")
        assert text.count("\n") == 1
        assert "记号 收起：读数过期" in text
        assert app.pos.reader._diag_on() is True

        settings.update(debug_mode=False)
        app.nav._marker._diag("读数过期")
        text = (tmp_path / "di_log.txt").read_text(encoding="utf-8")
        assert text.count("\n") == 1
        assert app.pos.reader._diag_on() is False
    finally:
        bootstrap.shutdown(app, budget=0.2)


def test_nav_links_are_wired_by_bootstrap():
    app = bootstrap.build("test")
    try:
        links = app.nav._links
        assert links is app.nav._worker._links
        assert links.log is nav_tasks._wp_log
        assert links.fix_key_hint is nav_tasks.fix_key_hint
        assert links.place_row is nav_tasks._place_row
        assert links.setting is nav_tasks.settings_key
        assert app.cam_filter._log is links.log
    finally:
        bootstrap.shutdown(app, budget=0.2)


def test_hover_links_are_wired_by_bootstrap(monkeypatch):
    """IQ-B6：bootstrap 把 F8 的物品卡片、掉落、玩家市场接到 tasks/catalog。"""
    from astral_toolkit.catalog.results import ItemInfo
    from astral_toolkit.core import i18n

    links = bootstrap._hover_links()
    assert links.loot is catalog_tasks.get_item_loot
    assert links.market is catalog_tasks.open_market
    assert links.market_rows is catalog_tasks.market_rows
    assert links.hud_market is catalog_tasks.market_hud_text
    assert links.wikelo_rewards is wikelo_tasks.rewards_for
    assert links.has_blueprint is crafting_tasks.has_blueprint

    calls = []

    def fake_item_info(name="", zh="", item_id=None, loot=True, exact=False):
        calls.append((name, zh, item_id, loot, exact))
        return ItemInfo(
            facts={"name": "N", "zh": "", "category": "Helmets"},
            zh="中",
            goal="",
        )

    monkeypatch.setattr(catalog_tasks, "get_item_info", fake_item_info)
    monkeypatch.setattr(i18n, "SHOP_CAT_ZH", {"Helmets": "头盔"})
    expected = {"name": "N", "zh": "中", "category": "头盔", "goal": ""}
    # loot、exact 给不一样的值，接反了测得出
    out = links.item_card("N", "中", loot=False, exact=True)
    assert out == expected
    assert list(out) == list(expected)
    assert calls == [("N", "中", None, False, True)]


def test_nav_fps_follows_settings_page(monkeypatch, tmp_path):
    from astral_toolkit.core import settings
    from astral_toolkit.infrastructure.platform import timer

    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    app = bootstrap.build("test")
    try:
        assert app.nav._links.fps() == 5
        settings.update(nav_fps=30)
        assert app.nav._links.fps() == 30
        settings.update(nav_fps=999)
        assert app.nav._links.fps() == 30
        assert app.pos._fine_timer is None
        assert bootstrap._fine_timer("desktop") is timer.fine
        desktop_pos = bootstrap._pos_service("desktop", settings.View())
        assert desktop_pos._fine_timer is timer.fine  # 只造对象，不起线程
        assert bootstrap._pos_service("test", settings.View())._fine_timer is None
    finally:
        bootstrap.shutdown(app, budget=0.2)


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
        _assert_error(RuntimeError, "已绑定", lambda: count_tasks.bind(app.count))
    assert snapshot_bindings() == before


def test_unbound_modules_raise_and_gate_stays_open():
    saved = snapshot_bindings()
    try:
        count_tasks._count = None
        _assert_error(RuntimeError, "未绑定", count_tasks.count_state)

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


def _quiet_mining(monkeypatch):
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
    return real_grab_calls, flag_writes


def test_mining_session_starts_and_stops_with_fake_screen(monkeypatch):
    real_grab_calls, flag_writes = _quiet_mining(monkeypatch)
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
        count_tasks._count = None
        before = snapshot_bindings()
        with app_for_test() as app:
            assert count_tasks._count is app.count
        assert snapshot_bindings() == before
        assert count_tasks._count is None

        # 只看绑定是不是原样恢复，用不着真引擎
        a_count: Any = SimpleNamespace(name="A-count")
        count_tasks.bind(a_count, replace=True)
        with_a = snapshot_bindings()
        with app_for_test() as app:
            assert count_tasks._count is app.count
        assert snapshot_bindings() == with_a
        assert count_tasks._count is a_count
    finally:
        restore_bindings(saved)


def test_routes_table_static_plus_bound(monkeypatch):
    """F 段 B5a：bootstrap.routes(app) = 各 Controller 的 ROUTES + 要后台对象的 bound(...)；采矿那 4 个拿的是这个 app 的 live，F8 的拿这个 app 的 HoverLinks，系统的拿这个 app 的状态源和启动回调，导航和物品查询的商店导航拿这个 app 的 NavDeps"""
    from astral_toolkit.app.api import mining as mining_api
    from astral_toolkit.app.api import navigation as navigation_api
    from astral_toolkit.app.api import router
    from astral_toolkit.app.api import system as system_api
    from astral_toolkit.app.api import trade as trade_api
    from astral_toolkit.app.api import vision as vision_api

    real_mining = mining_api.bound
    seen = []
    monkeypatch.setattr(
        mining_api, "bound", lambda live: seen.append(live) or real_mining(live)
    )
    real_vision = vision_api.bound
    seen_vision = []
    monkeypatch.setattr(
        vision_api,
        "bound",
        lambda links: seen_vision.append(links) or real_vision(links),
    )
    real_system = system_api.bound
    seen_system = []

    def fake_system(sources, start):
        seen_system.append((sources, start))
        return real_system(sources, start)

    monkeypatch.setattr(system_api, "bound", fake_system)
    real_navigation = navigation_api.bound
    seen_navigation = []
    monkeypatch.setattr(
        navigation_api,
        "bound",
        lambda deps: seen_navigation.append(deps) or real_navigation(deps),
    )
    real_trade = trade_api.bound
    seen_trade = []
    monkeypatch.setattr(
        trade_api,
        "bound",
        lambda deps: seen_trade.append(deps) or real_trade(deps),
    )
    app = bootstrap.build("test")
    try:
        api = bootstrap.routes(app)
        assert seen == [app.live]
        assert seen_vision == [app.hover_links]
        assert seen_navigation == [app.nav_deps]
        assert seen_trade == [app.nav_deps]
        assert len(seen_system) == 1
        system_sources, system_start = seen_system[0]
        assert system_sources.results is app.results
        assert callable(system_start)
        static = router.routes()
        bound = (
            set(real_mining(app.live))
            | set(real_vision(app.hover_links))
            | set(real_system(system_sources, system_start))
            | set(real_navigation(app.nav_deps))
            | set(real_trade(app.nav_deps))
        )
        assert bound == {
            "live_start",
            "live_stop",
            "set_mining_gear",
            "set_mining_gadgets",
            "hover_trigger",
            "status",
            "feedback_report",
            "set_settings",
            "agree",
            "nav_near",
            "nav_site",
            "nav_start",
            "nav_mode",
            "nav_stop",
            "nav_refresh",
            "waypoint_add",
            "waypoint_preview",
            "waypoint_from_text",
            "ore_record",
            "ore_go",
            "halo_pin",
            "nav_shop",
        }
        assert not bound & set(static)
        assert set(api.table) == set(static) | bound
        for name in static:
            assert api.table[name] is static[name], name
    finally:
        bootstrap.shutdown(app, budget=0.2)


def test_nav_deps_reach_hotkeys_live_and_routes(monkeypatch):
    """F 段 B5d：热键记路标 / 原矿 / 一键定位、采矿读屏问位置、导航接口、物品查询的商店导航，拿的都是这个 app 的 NavDeps"""
    got = []
    for name in ("mark_here", "fix_here", "_where_now", "_area_now", "nav_stop"):
        monkeypatch.setattr(
            nav_tasks, name, lambda deps, *a, _n=name, **k: got.append((_n, deps)) or {}
        )
    monkeypatch.setattr(
        nav_tasks,
        "ore_record",
        lambda deps, **k: got.append(("ore_record", deps, k)) or {},
    )
    monkeypatch.setattr(
        trade_tasks,
        "nav_shop",
        lambda deps, **k: got.append(("nav_shop", deps)) or {},
    )
    monkeypatch.setattr(lifecycle_gate, "_CLOSING", None)
    app = bootstrap.build("test")
    try:
        d = app.nav_deps
        app.hover._mark()
        app.hover._ore()
        app.hover._fix()
        app.live._where_now()
        app.live._area_now()
        assert bootstrap.routes(app).call("nav_stop") == {"ok": True, "data": {}}
        assert bootstrap.routes(app).call("nav_shop") == {"ok": True, "data": {}}
        assert got == [
            ("mark_here", d),
            ("ore_record", d, {"here": True}),
            ("fix_here", d),
            ("_where_now", d),
            ("_area_now", d),
            ("nav_stop", d),
            ("nav_shop", d),
        ]
    finally:
        bootstrap.shutdown(app, budget=0.2)


def test_status_callbacks_read_this_app(monkeypatch):
    """F 段 B5c：位置服务、读日志推的状态，反馈键的反馈，「status」接口，读的都是这个 app 的状态源"""
    got = []
    monkeypatch.setattr(
        system_tasks,
        "status",
        lambda sources: got.append(("status", sources.results)) or {},
    )
    monkeypatch.setattr(
        system_tasks,
        "feedback_report",
        lambda sources, **kw: got.append(("feedback", sources.results, kw)) or {},
    )
    app = bootstrap.build("test")
    try:
        app.pos._publish(force=True)
        app.logwatch._status()
        app.hover._report()
        assert bootstrap.routes(app).call("status") == {"ok": True, "data": {}}
        assert got == [
            ("status", app.results),
            ("status", app.results),
            ("feedback", app.results, {"kind": "auto"}),
            ("status", app.results),
        ]
    finally:
        bootstrap.shutdown(app, budget=0.2)


def test_hover_links_shared_by_hotkey_and_route(monkeypatch):
    """F 段 B5b：F8 热键（app.hover）和窗口「识别」接口（routes 的 hover_trigger）用同一份 HoverLinks"""
    from astral_toolkit.app import task_runner

    app = bootstrap.build("test")
    try:
        assert app.hover._links is app.hover_links
        got = []
        monkeypatch.setattr(
            task_runner,
            "run_task_once",
            lambda task_id, fn, *args, **kw: got.append((task_id, fn, args)),
        )
        out = bootstrap.routes(app).call("hover_trigger")
        assert got == [("hover", hover_tasks.hover_once, (app.hover_links,))]
        assert out == {"ok": True, "data": {"error": "F8 正在识别中，请稍候"}}
        seen = []
        monkeypatch.setattr(
            hover_tasks,
            "hover_once",
            lambda links, img=None: seen.append(links) or {"ok": True},
        )
        app.hover._recognize()
        assert seen == [app.hover_links]
    finally:
        bootstrap.shutdown(app, budget=0.2)


def test_routes_hold_this_apps_live(monkeypatch):
    """F 段 B5a（架构稿 §12.3 验收）：两个 build("test") 各一张接口表，采矿开 / 关只动自己那个 app 的实时读屏"""
    real_grab_calls, _ = _quiet_mining(monkeypatch)
    monkeypatch.setattr(
        lifecycle_gate, "_CLOSING", None
    )  # 不经 bind_all：没有「正在退出」
    apps = []
    try:
        for _ in range(2):
            apps.append(
                bootstrap.build(
                    "test",
                    overrides={
                        "foreground": lambda: True,
                        "grab": _Grabber(),
                        "clock": FakeClock(),
                        "output": RecordingOutput(),
                    },
                )
            )
        a, b = apps
        api_a, api_b = bootstrap.routes(a), bootstrap.routes(b)
        got = api_a.call("live_start")
        assert got["ok"] and not got["data"].get("error"), got
        assert _wait_until(a.live.running)
        assert not b.live.running()
        got = api_b.call("live_start")
        assert got["ok"] and not got["data"].get("error"), got
        assert _wait_until(b.live.running) and a.live.running()
        assert api_a.call("live_stop")["ok"]
        assert not a.live.running() and b.live.running()
        assert api_b.call("live_stop")["ok"]
        assert not b.live.running()
    finally:
        for app in apps:
            bootstrap.shutdown(app, budget=0.5)
    assert not real_grab_calls


def test_search_warmup_thread_builds_index_in_background(monkeypatch):
    """搜索预热（Q1 起线程由 bootstrap 起，搜索模块 import 时不起）：后台 daemon 线程、名字 search-warmup，
    跑 _warm_search_index → tasks/catalog_queries/search.build_index；建索引出错不往外抛"""
    from astral_toolkit.tasks.catalog_queries import search as item_search

    made = {}
    real = bootstrap.OneShot

    def record(name, phase, thread=None, *, factory=None):
        made[name] = factory
        return real(name, phase, thread, factory=factory)

    monkeypatch.setattr(bootstrap, "OneShot", record)
    app = bootstrap.build("test")
    try:
        calls = []
        monkeypatch.setattr(
            item_search, "build_index", lambda: calls.append(threading.current_thread())
        )
        t = made["search-warmup"]()
        t.join(5)
        assert calls == [t] and t.daemon and t.name == "search-warmup"

        def boom():
            raise RuntimeError("坏了")

        hooked = []
        monkeypatch.setattr(item_search, "build_index", boom)
        monkeypatch.setattr(threading, "excepthook", hooked.append)
        t = made["search-warmup"]()
        t.join(5)
        assert hooked == [] and not t.is_alive()
    finally:
        bootstrap.shutdown(app, budget=0.2)
