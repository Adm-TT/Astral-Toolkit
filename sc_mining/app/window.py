"""AT 窗口：PyWebview（WebView2）开在本进程里（2026-10-30 重构阶段 0，NGU 设计第 2 节）

- 网页还是 server.py 那个本机网址打开的（实时推送 /api/events、截图、上传安装包照旧走 HTTP），
  普通接口走 js_api（window.pywebview.api.call），不经过 TCP。
- 点关闭只是藏到托盘（和原来 ATShell / Edge 窗口关掉后 AT 留在托盘一样），托盘「退出」才真关。
- 窗口最小化、藏起来时把本进程用不着的内存还给系统（core.perf.trim_process_memory，NGU 设计 4.3 节）。
- 没装 pywebview、没有 WebView2 运行库、打不开：run() 抛异常，server.main 照旧用 ATShell → Edge。
"""
import threading

WIDTH, HEIGHT = 1320, 860           # 和原来 Edge 窗口一样（server._open_edge 的 --window-size）
BACKGROUND = "#152851"              # style.css 深色主题 --ink，打开时不闪白
_STATE = {"win": None}


def available():
    """装了 pywebview 就是 True"""
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def active():
    """PyWebview 窗口现在开着（可能藏在托盘里）"""
    return _STATE["win"] is not None


def _trim():
    try:
        from ..core import perf
        perf.trim_process_memory()
    except Exception:
        pass


def _later(fn):
    threading.Thread(target=fn, daemon=True, name="window-trim").start()


def make_closing(win, on_hide_first, quit_ev, keep_running=lambda: True):
    """closing 事件的处理函数：要退出了（quit_ev 置位）或没有托盘可回来（keep_running() 是 False）就让它真关；
    否则藏起来、返回 False（不关），第一次藏起来时调 on_hide_first()（托盘提示）"""
    told = [False]

    def closing():
        if quit_ev.is_set() or not keep_running():
            return True
        win.hide()
        if not told[0]:
            told[0] = True
            try:
                on_hide_first()
            except Exception:
                pass
        _later(_trim)
        return False
    return closing


def run(url, bridge, on_hide_first, quit_ev, keep_running=lambda: True):
    """在主线程里开窗口，一直阻塞到窗口销毁。打不开（没装、没有 WebView2 运行库）就抛异常"""
    import webview
    import sys
    if sys.platform == "win32":
        from webview.platforms import winforms             # 没有 WebView2 时 pywebview 会悄悄退回 IE 内核（MSHTML），网页用不了
        if getattr(winforms, "renderer", "") != "edgechromium":
            raise RuntimeError("没有 WebView2 运行库")
    from ..core import paths
    from .winid import TITLE
    base, _, frag = url.partition("#")
    url = base + ("&" if "?" in base else "?") + "pywebview=1" + ("#" + frag if frag else "")   # 网页一打开就知道在 PyWebview 里（app.js shellSync）
    win = webview.create_window(TITLE, url, js_api=bridge, width=WIDTH, height=HEIGHT,
                                background_color=BACKGROUND, text_select=True)
    win.events.closing += make_closing(win, on_hide_first, quit_ev, keep_running)
    win.events.minimized += _trim
    _STATE["win"] = win

    def wait_quit():
        quit_ev.wait()
        try:
            win.destroy()
        except Exception:
            pass
    threading.Thread(target=wait_quit, daemon=True, name="window-quit").start()
    try:
        storage = paths.USER / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        webview.start(private_mode=False, storage_path=str(storage))
    finally:
        _STATE["win"] = None


def show():
    """托盘「打开」、再开一次 AT 时：藏着就显示出来，最小化了就还原，拉到最前面"""
    win = _STATE["win"]
    if win is None:
        return
    try:
        win.show()
    except Exception:
        pass
    try:
        from .winid import focus_window
        focus_window()
    except Exception:
        pass
