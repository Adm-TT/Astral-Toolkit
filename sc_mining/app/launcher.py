"""打开 AT 窗口（从 server.py 拆出来，2026-10-31 控制台指令第 1 批）：有外壳 ATShell 用外壳，没有或打不开用 Edge 应用窗口；退出时一起关掉
"""
import os
import subprocess
import threading
from pathlib import Path

QUIT = threading.Event()
STATE = {"url": "", "tray": None, "told_tray": False}


def _browser():
    cands = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                      Path(base) / "Google/Chrome/Application/chrome.exe"]
    return next((str(c) for c in cands if c.exists()), None)


# Edge 省资源：只开一个渲染进程，关掉扩展、同步、翻译、后台下载等用不到的东西
EDGE_FLAGS = ["--no-first-run", "--no-default-browser-check", "--renderer-process-limit=1",
              "--disable-extensions", "--disable-sync", "--disable-background-networking",
              "--disable-component-update", "--disable-default-apps", "--disable-breakpad", "--no-pings",
              "--disable-features=Translate,msEdgeShopping,msEdgeCollections,EdgeRewards,"
              "msImplicitSignin,MediaRouter,OptimizationHints,AutofillServerCommunication,CalculateNativeWinOcclusion",
              "--js-flags=--max-old-space-size=128",
              # 窗口在另一个屏幕、被游戏挡住或在后台时也照常刷新（Edge 默认会暂停后台窗口，切回来才一口气补上）
              "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
              "--disable-background-timer-throttling"]


SHELL_FALLBACK = 3          # ATShell.exe 打不开 WebView2 时的退出码：改用 Edge 窗口


def shell_exe():
    """AT 自己的窗口外壳（2026-10-27，WinUI 3 + WebView2，tools 外的 AT_build 下的 shell 编好放进 shell 文件夹）；没有返回 None"""
    from ..core import paths
    p = paths.ROOT / "shell" / "ATShell.exe"
    return p if p.exists() else None


def open_window(url):
    """打开 AT 窗口：有外壳用外壳（标题栏融进界面、系统分屏菜单），没有或打不开就用 Edge 应用窗口（以前的做法）"""
    from ..core import paths
    shell = shell_exe()
    if shell:
        try:
            proc = subprocess.Popen([str(shell), "--url", url, "--data", str(paths.USER / "shell"), "--parent", str(os.getpid())],
                                    cwd=str(shell.parent))
        except OSError:
            proc = None
        if proc:
            try:                                    # 任务栏上是 AT，固定到任务栏后点它运行 AT.exe
                from .winid import brand_window
                brand_window(paths.ROOT)
            except Exception:
                pass

            STATE["edge"] = proc                    # 先记下：外壳秒退时监视线程也认得出是这个（复审 2026-10-27）

            def fallback():
                try:
                    code = proc.wait(timeout=20)
                except Exception:
                    return                          # 20 秒还开着：外壳正常
                if code:
                    print(f"窗口外壳退出码 {code}" + ("（没有 WebView2 运行库，改用 Edge 窗口）" if code == SHELL_FALLBACK else ""))
                if code not in (0,) and STATE.get("edge") is proc and not QUIT.is_set():
                    STATE["edge"] = _open_edge(url)     # 外壳打不开（没装 WebView2 运行库、崩了）：换 Edge
            threading.Thread(target=fallback, daemon=True, name="shell-watch").start()
            return proc
    STATE["edge"] = _open_edge(url)          # 记在这里，外面不再赋值：外壳秒退换 Edge 的后台线程不会被覆盖回外壳进程，退出时漏关 Edge
    return STATE["edge"]


def _open_edge(url):
    from ..core import paths
    exe = _browser()
    if not exe:
        import webbrowser
        webbrowser.open(url)
        return None
    profile = paths.USER / "window"
    proc = subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1320,860", *EDGE_FLAGS])
    try:                                    # 任务栏上显示成「天枢」，固定到任务栏后点它运行 Dubhe.exe
        from .winid import brand_window
        brand_window(paths.ROOT)
    except Exception:
        pass
    return proc


def show_window():
    """打开 AT 窗口：已经开着就拉到最前面，没开才新开一个（以前每次都新开，会叠出好几个窗口）"""
    try:
        from .winid import focus_window
        if focus_window():
            return
    except Exception:
        pass
    if STATE["url"]:
        open_window(STATE["url"])


def _close_edge():
    """AT 退出（升级、重启、托盘退出）时把它开的 Edge 窗口一起关掉，不留一个没用的窗口要手动关（2026-10-27 用户要求）。
    先发「关闭」让 Edge 自己关（等最多 2 秒），关不掉再结束进程——直接结束的话下次打开 Edge 会提示「恢复页面」"""
    proc = STATE.get("edge")
    if proc is None:
        return
    try:
        from ..core import paths
        from .winid import close_windows, profile_pids
        pids = {proc.pid}
        is_shell = str((getattr(proc, "args", None) or [""])[0]).lower().endswith("atshell.exe")
        if not is_shell:                              # Edge 窗口：进程号要靠命令行里的资料夹找；外壳模式不用起 PowerShell 找（2026-10-28 审查）
            pids |= profile_pids(paths.USER / "window")
        close_windows(pids)                           # 外壳窗口也是按进程号关
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
