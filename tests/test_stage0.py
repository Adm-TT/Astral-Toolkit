"""重构阶段 0（2026-10-30）：接口路由、网桥、引擎管理器、悬浮窗状态、PyWebview 窗口"""
import threading
from decimal import Decimal


def test_router_ok_envelope():
    from sc_mining.app.api import router
    r = router.call("about_info")
    assert r["ok"] is True and isinstance(r["data"], dict)


def test_router_unknown():
    from sc_mining.app.api import router
    assert router.call("没有这个") == {"ok": False, "error": "没有 没有这个"}


def test_router_error_envelope():
    from sc_mining.app.api import router

    def bad():
        raise ValueError("坏了")
    try:
        router.routes()["x_bad"] = bad
        assert router.call("x_bad") == {"ok": False, "error": "坏了"}
    finally:
        router.reset()
    assert "x_bad" not in router.routes()


def test_router_collects_controller_routes(monkeypatch, tmp_path):
    """阶段 1–3 的 Controller：api/ 下的模块带 ROUTES，不改 router 就收进来（假模块放临时目录，不碰源码目录）"""
    import sys
    from sc_mining.app import api
    from sc_mining.app.api import router
    (tmp_path / "x_stage0_ctl.py").write_text('ROUTES = {"x_test": lambda: 1}\n', encoding="utf-8")
    monkeypatch.setattr(api, "__path__", list(api.__path__) + [str(tmp_path)])
    try:
        router.reset()
        assert router.routes()["x_test"]() == 1
        assert router.call("x_test") == {"ok": True, "data": 1}
        assert "about_info" in router.routes()                  # 原有的 Controller 照样在（阶段 4 起没有 services.API 兜底）
    finally:
        sys.modules.pop("sc_mining.app.api.x_stage0_ctl", None)
        monkeypatch.restore()
        router.reset()
    assert "x_test" not in router.routes()


def test_router_json_safe():
    from sc_mining.app.api import router
    try:
        router.routes()["x_dec"] = lambda: Decimal("1.5")
        assert router.call("x_dec") == {"ok": True, "data": "1.5"}
    finally:
        router.reset()


def test_bridge_same_as_http():
    import json
    import urllib.request
    from http.server import ThreadingHTTPServer
    from sc_mining.app.server import Handler, TOKEN
    from sc_mining.app.api.bridge import BackendBridge
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/about_info", data=b"{}",
                                     headers={"Content-Type": "application/json", "X-Token": TOKEN})
        http = json.loads(urllib.request.urlopen(req).read())
    finally:
        srv.shutdown()
    b = BackendBridge().call("about_info")
    assert http["ok"] and b["ok"] and http["data"] == b["data"]


ENGINES = ("game_events", "nav", "live", "pos", "count", "hover", "cam_filter", "steady", "logwatch")


def test_engine_manager_singleton():
    from sc_mining.app.engines.manager import EngineManager
    m = EngineManager.get_instance()
    assert m is EngineManager.get_instance()
    for n in ENGINES:                                    # 阶段 4：services.py 删了，不再对 services._xxx 是同一个
        assert getattr(m, n) is not None, n


def test_start_all_needs_agreed(monkeypatch):
    from sc_mining.core import settings
    from sc_mining.app.engines.manager import EngineManager
    m = EngineManager.get_instance()
    monkeypatch.setattr(settings, "load", lambda: {"agreed": False, "live_on": True})
    called = []
    for n in ENGINES:
        if hasattr(getattr(m, n), "start"):
            monkeypatch.setattr(getattr(m, n), "start", lambda n=n: called.append(n))
    m.start_all()
    assert called == []


def test_stop_all_sets_events(monkeypatch):
    from sc_mining.app.engines.manager import EngineManager
    from sc_mining.system import gpu_ocr
    m = EngineManager.get_instance()
    monkeypatch.setattr(m.live, "stop_ev", threading.Event())        # 用新的，测完换回原来的（别把真引擎停了）
    monkeypatch.setattr(m.nav, "stop_ev", threading.Event())
    monkeypatch.setattr(gpu_ocr, "shutdown", lambda: None)
    m.stop_all()
    assert m.live.stop_ev.is_set() and m.nav.stop_ev.is_set()


def test_window_fallback(monkeypatch, tmp_path):
    """没有 pywebview：server.main 照旧用 open_window（ATShell → Edge），不碰 window.run"""
    from sc_mining.app import server, window, bus, overlay, tray
    from sc_mining.tasks import system as t_sys
    from sc_mining.app.engines.manager import EngineManager
    from sc_mining.core import paths, perf
    calls = []

    class FakeServer:
        server_address = ("127.0.0.1", 12345)

        def __init__(self, *a):
            pass

        def serve_forever(self):
            pass

        def shutdown(self):
            calls.append("shutdown")

    class FakeTray:
        ok = True

        def __init__(self, *a, **k):
            pass

        def start(self):
            return True

        def notify(self, *a):
            pass

        def remove(self):
            pass

    def fake_open(url):
        calls.append(("open_window", url))
        server.QUIT.set()                                   # 打开后马上退出，main 走完收尾
        return None
    monkeypatch.setattr(window, "available", lambda: False)
    monkeypatch.setattr(window, "run", lambda *a, **k: calls.append("run"))
    monkeypatch.setattr(server, "_single_instance", lambda restart=False: True)
    monkeypatch.setattr(server, "Server", FakeServer)
    monkeypatch.setattr(server, "open_window", fake_open)
    monkeypatch.setattr(bus, "install_router", lambda: None)
    monkeypatch.setattr(perf, "lower_priority", lambda: None)
    monkeypatch.setattr(overlay, "hud", lambda: None)
    monkeypatch.setattr(t_sys, "start_background", lambda: None)            # server.main 调的是 tasks.system 的（阶段 4）
    monkeypatch.setattr(tray, "Tray", FakeTray)
    monkeypatch.setattr(paths, "USER", tmp_path)
    monkeypatch.setattr(server, "STATE", {"url": "", "tray": None, "told_tray": False})    # 别留下假托盘给后面的测试
    monkeypatch.setattr(EngineManager.get_instance(), "stop_all", lambda: calls.append("stop_all"))
    try:
        server.main()
    finally:
        server.QUIT.clear()
    assert "run" not in calls
    assert ("open_window", "http://127.0.0.1:12345/#t=" + server.TOKEN) in calls
    assert "stop_all" in calls and "shutdown" in calls


def test_closing_hides():
    from sc_mining.app import window

    class Win:
        hidden = 0

        def hide(self):
            self.hidden += 1
    w, told, quit_ev = Win(), [], threading.Event()
    closing = window.make_closing(w, lambda: told.append(1), quit_ev)
    assert closing() is False and w.hidden == 1 and told == [1] and not quit_ev.is_set()
    assert closing() is False and w.hidden == 2 and told == [1]          # 第二次关不再提示
    quit_ev.set()
    assert closing() is True and w.hidden == 2                            # 托盘退出时让它真关
    nobody = window.make_closing(Win(), lambda: None, threading.Event(), keep_running=lambda: False)
    assert nobody() is True                                               # 没有托盘：点关闭就真关


def test_appjs_pywebview_path():
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "sc_mining" / "app" / "web" / "app.js").read_text(encoding="utf-8")
    assert "pywebview.api.call(" in js
    body = js[js.index("function shellSync()"):]
    body = body[:body.index("\n}\n")]
    assert "!window.pywebview" in body
