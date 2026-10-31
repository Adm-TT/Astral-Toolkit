"""重构阶段 0（2026-10-30）：接口路由、引擎管理器、悬浮窗状态；窗口只走 ATShell → Edge（2026-10-31 去掉 PyWebview）"""

import sys
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

    (tmp_path / "x_stage0_ctl.py").write_text(
        'ROUTES = {"x_test": lambda: 1}\n', encoding="utf-8"
    )
    monkeypatch.setattr(api, "__path__", list(api.__path__) + [str(tmp_path)])
    try:
        router.reset()
        assert router.routes()["x_test"]() == 1
        assert router.call("x_test") == {"ok": True, "data": 1}
        assert (
            "about_info" in router.routes()
        )  # 原有的 Controller 照样在（阶段 4 起没有 services.API 兜底）
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


def test_router_same_as_http():
    import json
    import urllib.request
    from http.server import ThreadingHTTPServer
    from sc_mining.app.server import Handler, TOKEN
    from sc_mining.app.api import router

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.server_address[1]}/api/about_info",
            data=b"{}",
            headers={"Content-Type": "application/json", "X-Token": TOKEN},
        )
        http = json.loads(urllib.request.urlopen(req).read())
    finally:
        srv.shutdown()
    b = router.call("about_info")
    assert http["ok"] and b["ok"] and http["data"] == b["data"]


def _raw_post(port, headers, body=b""):
    """手写一个 POST，返回状态行；5 秒没答复抛 socket.timeout（以前不带令牌也会先等着读完请求体）"""
    import socket

    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        h = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        s.sendall(
            f"POST /api/about_info HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{h}\r\n".encode()
            + body
        )
        return s.recv(4096).split(b"\r\n", 1)[0]
    finally:
        s.close()


def test_post_rejects_before_reading_body():
    """不带令牌、请求体太大、Content-Length 不对：不读请求体直接拒绝（S5 审查 2026-10-31：以前先按 Content-Length
    把请求体整个读进内存再验令牌，本机任何程序不带令牌就能让 AT 吃掉上 GB 内存）"""
    from sc_mining.app.server import Server, Handler, TOKEN

    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        assert b" 403 " in _raw_post(port, {"Content-Length": str(10**9)})
        assert b" 403 " in _raw_post(
            port, {"Content-Length": str(10**9), "X-Token": "guess"}
        )
        assert b" 413 " in _raw_post(
            port, {"Content-Length": str(10**9), "X-Token": TOKEN}
        )
        assert b" 400 " in _raw_post(port, {"Content-Length": "-1", "X-Token": TOKEN})
        assert b" 400 " in _raw_post(port, {"Content-Length": "abc", "X-Token": TOKEN})
        assert b" 200 " in _raw_post(
            port,
            {
                "Content-Length": "2",
                "X-Token": TOKEN,
                "Content-Type": "application/json",
            },
            b"{}",
        )
    finally:
        srv.shutdown()


def test_no_synthetic_input():
    """1.1.2：AT 不再模拟任何键盘 / 鼠标输入（防挂机、双击 W 自动跑、自动输入 /showlocation、抢前台按 Alt 都删了）。
    发给自己窗口的 PostMessage / SendMessage 不算"""
    import re
    from sc_mining.core import paths

    bad = re.compile(
        r"SendInput|keybd_event|mouse_event|KEYEVENTF|_KEYBDINPUT|pyautogui|pynput|pydirectinput|SetCursorPos|WM_KEYDOWN|WM_CHAR"
    )
    hits = {}
    for p in paths.CODE.rglob("*.py"):
        rel = p.relative_to(paths.CODE).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line):
                hits.setdefault(rel, []).append(i)
    assert not hits, hits
    assert not (paths.CODE / "system" / "helpers.py").exists()


ENGINES = (
    "game_events",
    "nav",
    "live",
    "pos",
    "count",
    "hover",
    "cam_filter",
    "steady",
    "logwatch",
)


def test_engine_manager_singleton():
    from sc_mining.app.engines.manager import EngineManager

    m = EngineManager.get_instance()
    assert m is EngineManager.get_instance()
    for n in ENGINES:  # 阶段 4：services.py 删了，不再对 services._xxx 是同一个
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

    m = EngineManager.get_instance()
    monkeypatch.setattr(
        m.live, "stop_ev", threading.Event()
    )  # 用新的，测完换回原来的（别把真引擎停了）
    monkeypatch.setattr(m.nav, "stop_ev", threading.Event())
    m.stop_all()
    assert m.live.stop_ev.is_set() and m.nav.stop_ev.is_set()


def _run_main(monkeypatch, tmp_path, shell):
    """server.main(open_ui=True) 跑一遍：网页服务、托盘、引擎、子进程都换成假的。
    shell：假的 ATShell.exe 路径（None = 没有外壳）。返回 (子进程命令行列表, 其它调用)"""
    from sc_mining.app import (
        server,
        bus,
        overlay,
        tray,
        winid,
        launcher,
        instance,
        http_server,
    )
    from sc_mining.tasks import system as t_sys
    from sc_mining.app.engines.manager import EngineManager
    from sc_mining.core import paths, perf

    calls, popen = [], []

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

    class FakeProc:
        pid = 424242

        def __init__(self, args, **k):
            self.args = args
            popen.append([str(a) for a in args])
            server.QUIT.set()  # 窗口一开就退出，main 走完收尾

        def wait(self, timeout=None):
            return 0  # 外壳正常退出：不触发换 Edge

        def terminate(self):
            pass

    monkeypatch.setattr(server.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(
        launcher, "shell_exe", lambda: shell
    )  # server.py 按职责拆开后，开窗口在 launcher（2026-10-31）
    monkeypatch.setattr(launcher, "_browser", lambda: "msedge.exe")
    monkeypatch.setattr(winid, "brand_window", lambda *a, **k: None)
    monkeypatch.setattr(winid, "close_windows", lambda *a, **k: None)
    monkeypatch.setattr(winid, "profile_pids", lambda *a, **k: set())
    monkeypatch.setattr(instance, "_single_instance", lambda restart=False: True)
    monkeypatch.setattr(http_server, "Server", FakeServer)
    monkeypatch.setattr(bus, "install_router", lambda: None)
    monkeypatch.setattr(perf, "lower_priority", lambda: None)
    monkeypatch.setattr(overlay, "hud", lambda: None)
    monkeypatch.setattr(
        t_sys, "start_background", lambda: None
    )  # server.main 调的是 tasks.system 的（阶段 4）
    monkeypatch.setattr(tray, "Tray", FakeTray)
    monkeypatch.setattr(paths, "USER", tmp_path)
    monkeypatch.setattr(
        launcher, "STATE", {"url": "", "tray": None, "told_tray": False}
    )  # 别留下假托盘给后面的测试
    monkeypatch.setattr(
        EngineManager.get_instance(), "stop_all", lambda: calls.append("stop_all")
    )
    try:
        server.main()
    finally:
        server.QUIT.clear()
    return popen, calls


def test_main_opens_shell_or_edge(monkeypatch, tmp_path):
    """open_ui 时窗口只走 ATShell，没有外壳才开 Edge 应用窗口；PyWebview 窗口已删（2026-10-31）"""
    import importlib.util
    from sc_mining.app import server

    url = "http://127.0.0.1:12345/#t=" + server.TOKEN
    assert importlib.util.find_spec("sc_mining.app.window") is None
    assert importlib.util.find_spec("sc_mining.app.api.bridge") is None

    shell = tmp_path / "shell" / "ATShell.exe"
    popen, calls = _run_main(monkeypatch, tmp_path, shell)
    assert len(popen) == 1, popen
    assert popen[0][0] == str(shell) and popen[0][1:3] == ["--url", url]
    assert "stop_all" in calls and "shutdown" in calls
    monkeypatch.restore()

    popen, calls = _run_main(monkeypatch, tmp_path, None)
    assert len(popen) == 1, popen
    assert popen[0][0] == "msedge.exe" and f"--app={url}" in popen[0]
    assert "stop_all" in calls and "shutdown" in calls
    assert "webview" not in sys.modules


def test_appjs_no_pywebview():
    """app.js 不再有 PyWebview 分支：api() 只走 fetch，shellSync 只看 ATShell 的 chrome.webview"""
    from pathlib import Path

    js = (
        Path(__file__).resolve().parent.parent / "sc_mining" / "app" / "web" / "app.js"
    ).read_text(encoding="utf-8")
    assert "pywebview" not in js.lower()
    body = js[js.index("function shellSync()") :]
    body = body[: body.index("\n}\n")]
    assert "if (!wv) return;" in body


def test_server_split_keeps_old_names():
    """server.py 按职责拆成 http_server / launcher / instance（控制台指令第 1 批，2026-10-31）：
    外面用的旧名字从 server 照样拿得到，是同一个对象；令牌、监听地址的检查只在 http_server 一处"""
    from sc_mining.app import server, http_server, launcher, instance

    for name, mod in (
        ("Server", http_server),
        ("Handler", http_server),
        ("TOKEN", http_server),
        ("MAX_BODY", http_server),
        ("QUIT", launcher),
        ("STATE", launcher),
        ("_browser", launcher),
        ("show_window", launcher),
        ("open_window", launcher),
        ("_try_lock", instance),
        ("_single_instance", instance),
        ("release_instance", instance),
    ):
        assert getattr(server, name) is getattr(mod, name), name
    assert callable(server.main) and callable(server._relaunch)


def test_stock_kind_mineral_not_swallowed():
    """库存类别：矿物要认成「矿物」（抽 OCR 模块时删了 tasks.hover 的转出，stock 的导入失败被吞掉，矿物全成了「材料」）"""
    from sc_mining.tasks import stock

    assert stock._stock_kind("塔兰导电石", "Taranite", "scu") == "矿物"
    assert stock._stock_kind("", "Taranite", "scu") == "矿物"
    assert stock._stock_kind("", "Recycled Material Composite", "scu") == "材料"
    assert stock._stock_kind("", "Taranite", "unit") == "物品"


def test_frozen_main_old_helper_args_exit(monkeypatch):
    """打包版收到老版本的 helpers / ocrworker 参数：直接退出，不把整个 AT 跑起来"""
    from sc_mining import frozen_main
    from sc_mining.core import paths

    from sc_mining import run

    seeded = []
    monkeypatch.setattr(frozen_main, "_velopack", lambda: None)
    fake = lambda *a, **k: seeded.append("menu")  # noqa: E731  万一没退出，也别真把 AT 跑起来
    monkeypatch.setattr(run, "ENTRIES", {**run.ENTRIES, "menu": fake})
    monkeypatch.setattr(paths, "seed_data", lambda: seeded.append(1))
    for argv in (["AT.exe", "helpers", "123"], ["AT.exe", "ocrworker"]):
        monkeypatch.setattr(sys, "argv", argv)
        try:
            frozen_main.main()
            raise AssertionError("没有退出")
        except SystemExit as e:
            assert e.code in (0, None), argv
    assert seeded == []


def test_startup_drops_stale_helper_files():
    """老版本留下的重启请求文件：启动时（paths.migrate）删掉，没有代码再读它"""
    from sc_mining.core import paths

    names = [
        p.name for p in paths._DELETE
    ]  # 测试时 paths.USER 被换成临时目录，_DELETE 是导入时算好的，只比名字
    assert "restart_request" in names


def test_live_fail_off_without_hud(monkeypatch):
    """悬浮窗没建起来时采矿助手出错：照样关掉、存 live_on=False、告诉窗口（以前收尾时擦悬浮窗抛错，线程死掉，界面一直显示在运行）"""
    import threading
    from sc_mining.app import bus, hud_state
    from sc_mining.app.engines import live as live_mod
    from sc_mining.core import settings

    saved, pub = [], []
    monkeypatch.setattr(hud_state, "_hud", lambda: None)
    monkeypatch.setattr(hud_state, "_note_hud", lambda *a, **k: None)
    monkeypatch.setattr(settings, "update", lambda **kw: saved.append(kw))
    monkeypatch.setattr(bus, "publish", lambda kind, data: pub.append((kind, data)))
    live = live_mod._Live()
    ev = threading.Event()
    live._fail_off(ev, "坏了")
    assert ev.is_set() and {"live_on": False} in saved
    assert ("live", {"running": False, "error": "坏了"}) in pub
    live.stop()  # 停止收尾也不抛错


def test_settings_ignore_removed_keys(monkeypatch, tmp_path):
    """老设置文件里删掉的功能（autorun、防挂机、双击间隔）读不进来，也不在默认值里"""
    import json
    from sc_mining.core import settings

    old = (
        "autorun",
        "autorun_sprint",
        "anti_afk",
        "afk_seconds",
        "afk_v3",
        "afk_v4",
        "double_tap_ms",
    )
    monkeypatch.setattr(settings, "FILE", tmp_path / "settings.json")
    settings.FILE.write_text(
        json.dumps({"agreed": True, "keys_v5": True, **{k: True for k in old}}),
        encoding="utf-8",
    )
    c = settings.load()
    assert c["agreed"] is True and not any(
        k in c or k in settings.DEFAULTS for k in old
    )
