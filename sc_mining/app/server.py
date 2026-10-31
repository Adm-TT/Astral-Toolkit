"""AT 的启动和退出：起本机网页服务（http_server）、开窗口（launcher）、托盘，退出时收尾

- 只监听 127.0.0.1，别的电脑访问不到；只开一个 AT（instance）
- 关掉窗口后 AT 在托盘里继续跑（F8、悬浮窗照常）；没有托盘图标时窗口关了就退出
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

from . import bus
from . import http_server, instance, launcher
from ..tasks import system as _sys_task  # main 里启动后台引擎

# 2026-10-31 按职责拆开（控制台指令第 1 批）：网页服务在 http_server，开窗口在 launcher，只开一个 AT 在 instance；
# 这里只留启动 / 退出流程。下面这些名字原样导回，外面的 import 不用改
from .http_server import WEB, TOKEN, MAX_BODY, Handler, Server, _last_client  # noqa: F401
from .launcher import (
    QUIT,
    STATE,  # noqa: F401
    EDGE_FLAGS,  # noqa: F401
    SHELL_FALLBACK,  # noqa: F401
    _browser,  # noqa: F401
    shell_exe,  # noqa: F401
    open_window,  # noqa: F401
    _open_edge,  # noqa: F401
    show_window,  # noqa: F401
    _close_edge,  # noqa: F401
)  # noqa: F401
from .instance import _call_old, _try_lock, release_instance, _single_instance  # noqa: F401

RESTART = threading.Event()


def _relaunch():
    """托盘「重新启动」：开一个新的 AT（它会等这个退出），这个退出"""
    from ..core import paths

    subprocess.Popen(
        paths.self_cmd("restart"),
        cwd=str(paths.ROOT),
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    QUIT.set()


def _told_tray(tray):
    """第一次关窗口：托盘气泡告诉你 AT 还在右下角（只说一次）"""
    if launcher.STATE["told_tray"] or tray is None:
        return
    launcher.STATE["told_tray"] = True
    tray.notify(
        "AT 还在后台运行",
        "F8 识别、悬浮窗照常可用。双击右下角图标重新打开，右键可以退出。",
    )


def main(open_ui=True, port=0, restart=False):
    if open_ui and not instance._single_instance(restart):
        return
    bus.install_router()
    from ..core.perf import lower_priority

    lower_priority()
    server = http_server.Server(("127.0.0.1", port), http_server.Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/#t={http_server.TOKEN}"
    launcher.STATE["url"] = url
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    from .overlay import hud

    hud()
    _sys_task.start_background()  # = EngineManager.get_instance().start_all()
    print(f"AT 已启动（端口 {server.server_address[1]}）")
    try:
        from ..core import paths

        (paths.USER / "window_url.txt").write_text(url, encoding="utf-8")
    except Exception:
        pass
    tray = None
    if open_ui:
        from .tray import Tray

        # 窗口只用 ATShell，打不开退回 Edge 应用窗口（2026-10-31 去掉 PyWebview：关窗后 ATShell 整个退出，私有内存约 113 MB；
        # PyWebview 关窗藏托盘仍占约 420 MB）
        tray = Tray(
            Path(__file__).resolve().parent / "icon.ico",
            on_open=launcher.show_window,
            on_restart=_relaunch,
            on_quit=QUIT.set,
        )
        tray.start()
        launcher.STATE["tray"] = tray
        launcher.open_window(url)
    started = time.time()
    try:
        while not QUIT.is_set():
            time.sleep(0.5)
            if bus.clients():
                continue
            if tray is None or not tray.ok:
                # 没有托盘图标（极少数情况）：还按老办法，窗口关了就退出
                if (
                    http_server._last_client["ever"]
                    and time.time() - http_server._last_client["t"] > 8
                ):
                    break
                if not http_server._last_client["ever"] and time.time() - started > 90:
                    break
            elif (
                http_server._last_client["ever"]
                and not launcher.STATE["told_tray"]
                and time.time() - http_server._last_client["t"] > 3
            ):
                _told_tray(tray)  # 第一次关窗口：告诉你天枢还在右下角
    except KeyboardInterrupt:
        pass
    finally:
        bus.publish("quit", {})
        time.sleep(0.3)
        launcher._close_edge()
        if tray:
            tray.remove()
        from .engines.manager import EngineManager

        EngineManager.get_instance().stop_all()
        server.shutdown()
