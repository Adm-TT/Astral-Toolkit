"""助手窗口：本机小网页服务 + 用 Edge 的「应用模式」开一个没有地址栏的窗口

- 不用另装任何东西（Windows 10/11 都自带 Edge；找不到就用默认浏览器打开）
- 只监听 127.0.0.1，别的电脑访问不到
- 关掉窗口，助手就退出（后台辅助、悬浮窗一起停）
"""
import json
import mimetypes
import queue
import secrets
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import bus
# 2026-10-30 阶段 4：services.py 删了。import tasks 这一层会把全部任务模块加载好（tasks/__init__.py），
# tasks.goals / tasks.navigation 在 import 时登记数据包清缓存函数，和原来 import services 时顺带做的一样早
from ..tasks import system as _sys_task

WEB = Path(__file__).resolve().parent / "web"
mimetypes.add_type("font/woff2", ".woff2")            # 1.6.59：D-DIN 字体（Windows 自带的类型表里可能没有）
mimetypes.add_type("image/webp", ".webp")              # 阿塔的图片
mimetypes.add_type("image/svg+xml", ".svg")
# 每次启动随机生成的口令：只有助手自己打开的窗口知道（在网址里带过去），别的网页、别的程序猜不到
TOKEN = secrets.token_urlsafe(24)
_last_client = {"t": time.time(), "ever": False}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self):
        """只认本机、带对口令、不是从别的网站发来的请求"""
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return False
        origin = self.headers.get("Origin")
        if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
            return False
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        given = self.headers.get("X-Token") or (qs.get("token") or qs.get("t") or [""])[0]
        return secrets.compare_digest(given, TOKEN)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/events":
            if not self._allowed():
                return self._send(403, "{}")
            return self._events()
        if path == "/api/screenshot":
            if not self._allowed():
                return self._send(403, "{}")
            return self._screenshot()
        if path == "/":
            path = "/index.html"
        f = (WEB / path.lstrip("/")).resolve()
        if WEB not in f.parents or not f.is_file():
            return self._send(404, "{}")
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)

    def _upload_raw(self, n):
        """安装包整个文件流式写盘；真正存到哪、怎么校验、怎么交给升级任务都在 tasks.system.upgrade_receive（新旧接口共用）"""
        from urllib.parse import unquote
        allowed = self._allowed()
        fname = unquote(self.headers.get("X-File-Name") or "")
        if n > 400 << 20:                               # 安装包不会这么大：拒绝，连接不复用
            self.close_connection = True
            return self._send(200, json.dumps({"ok": False, "error": "文件太大，不是 AT 安装包"}, ensure_ascii=False))
        if not allowed:
            self._drain(n)
            return self._send(403, json.dumps({"ok": False, "error": "拒绝访问"}))

        got = [0]                                       # 已经从连接读了多少（出错时把剩下的读掉，连接才能复用）

        def write(f):
            while got[0] < n:
                chunk = self.rfile.read(min(1 << 20, n - got[0]))
                if not chunk:
                    self.close_connection = True        # 请求体没读完：这条连接不能再复用
                    raise OSError("上传中断，再试一次")
                got[0] += len(chunk)
                f.write(chunk)

        try:
            result = _sys_task.upgrade_receive(fname, write)
        except Exception as e:
            self.close_connection = True
            return self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        if isinstance(result, dict) and result.get("error"):
            if not self.close_connection:               # 文件名不对 / 正在升级 / 写盘失败：请求体没读完的读掉再答复
                self._drain(n - got[0])
            return self._send(200, json.dumps({"ok": False, "error": result["error"]}, ensure_ascii=False))
        self._send(200, json.dumps({"ok": True, "data": result}, ensure_ascii=False, default=str))

    def _drain(self, n):
        """把没用的请求体读掉，读不完就关连接"""
        left = n
        try:
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                left -= len(chunk)
        except OSError:
            left = 1
        if left > 0:
            self.close_connection = True

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self._send(404, "{}")
        n = int(self.headers.get("Content-Length") or 0)
        name = self.path[5:].split("?")[0]
        if name == "upgrade_upload_raw":                # 安装包整个文件流式写盘（2026-10-28 审查：以前 base64 进内存，30 MB 的包就撑爆网页进程）
            return self._upload_raw(n)
        raw = self.rfile.read(n) if n else b""          # 先把请求体读完，拒绝时也不能留在连接里
        if not self._allowed():
            return self._send(403, json.dumps({"ok": False, "error": "拒绝访问"}))
        from .api import router                         # 2026-10-30 阶段 0：HTTP 和 PyWebview 走同一个 router
        if name not in router.routes():
            return self._send(404, json.dumps({"ok": False, "error": f"没有 {name}"}, ensure_ascii=False))
        try:
            args = json.loads(raw or b"{}")
        except Exception as e:
            return self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        self._send(200, json.dumps(router.call(name, args), ensure_ascii=False))

    def _screenshot(self):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        full = qs.get("full", ["0"])[0] == "1"
        data, meta = bus.get_preview_bytes(full=full)
        if data:
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            if meta:
                self.send_header("X-Screenshot-Time", str(meta.get("t", 0)))
                self.send_header("X-Screenshot-Width", str(meta.get("w", 0)))
                self.send_header("X-Screenshot-Height", str(meta.get("h", 0)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._send(404, "{}")

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = bus.subscribe()
        _last_client["ever"] = True
        try:
            while True:
                try:
                    msg = q.get(timeout=5)
                    self.wfile.write(bus.encode(msg).encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                _last_client["t"] = time.time()
        except Exception:
            pass
        finally:
            bus.unsubscribe(q)
            _last_client["t"] = time.time()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """窗口关掉/刷新时连接被断开是正常的，不往日志里写一大段错误"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


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
    return _open_edge(url)


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


QUIT = threading.Event()
RESTART = threading.Event()
STATE = {"url": "", "tray": None, "told_tray": False}


def _call_old(url, action):
    """给已经开着的 AT 发命令：show = 打开窗口，quit = 退出"""
    import urllib.request
    from urllib.parse import urlparse
    u = urlparse(url)
    token = u.fragment.split("t=", 1)[-1] if "t=" in u.fragment else ""
    req = urllib.request.Request(f"{u.scheme}://{u.netloc}/api/{action}", data=b"{}",
                                 headers={"Content-Type": "application/json", "X-Token": token})
    urllib.request.urlopen(req, timeout=3).read()


def _try_lock():
    """只开一个 AT 的锁：锁住 userdata/instance.lock 这个文件。锁上了返回打开的文件，已经被别的 AT 锁着返回 None。
    AT 退出（哪怕是被强制结束）时 Windows 会自动解锁；管理员身份、普通身份开的都认这同一把锁"""
    from ..core import paths
    f = open(paths.USER / "instance.lock", "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def release_instance():
    """放开锁（换管理员身份重开前用，让新开的那个能拿到）"""
    f = getattr(_single_instance, "lock", None)
    if f:
        try:
            f.close()
        except Exception:
            pass
    _single_instance.lock = None
    _single_instance.mine = False


def _single_instance(restart=False):
    """只允许一个 AT 在运行。已经开着一个：平时只是把它的窗口打开；restart=True 时请它退出、等它退完再启动。
    返回 True 表示这次要启动"""
    if getattr(_single_instance, "mine", False):
        return True
    from ..core import paths
    f = _try_lock()
    if f:
        _single_instance.lock, _single_instance.mine = f, True
        return True
    try:
        url = (paths.USER / "window_url.txt").read_text(encoding="utf-8").strip()
    except Exception:
        url = ""
    if not restart:
        try:
            from .winid import allow_focus
            allow_focus()
        except Exception:
            pass
        try:
            _call_old(url, "show")                              # 已经开着的天枢把窗口打开
            return False
        except Exception:
            time.sleep(3)                                       # 可能刚好也在启动：等它起来再叫一次
            try:
                _call_old((paths.USER / "window_url.txt").read_text(encoding="utf-8").strip(), "show")
                return False
            except Exception:
                pass                                            # 旧天枢卡住了：请它退出，重新开
    try:
        _call_old(url, "quit")
    except Exception:
        pass
    for _ in range(240):                                        # 最多等 60 秒（旧进程要关窗口、停助手；慢机器 / 杀毒扫描时 15 秒不够，2026-10-28）
        time.sleep(0.25)
        f = _try_lock()
        if f:
            _single_instance.lock, _single_instance.mine = f, True
            return True
    try:                                                        # 一分钟还没放锁：别悄悄退出，告诉玩家怎么办（终审 2026-10-28）
        from ..run import _error_box
        _error_box("上一个 AT 还没退出。在屏幕右下角托盘右键 AT 图标选「退出」，再打开。")
    except Exception:
        pass
    return False                                                # 拿不到锁就不开第二个


def show_window():
    """打开 AT 窗口：已经开着就拉到最前面，没开才新开一个（以前每次都新开，会叠出好几个窗口）"""
    from . import window
    if window.active():                             # 2026-10-30 阶段 0：PyWebview 窗口藏在托盘时 focus_window 找不到（只找看得见的窗口）
        window.show()
        return
    try:
        from .winid import focus_window
        if focus_window():
            return
    except Exception:
        pass
    if STATE["url"]:
        STATE["edge"] = open_window(STATE["url"])


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


def _relaunch():
    """托盘「重新启动」：开一个新的 AT（它会等这个退出），这个退出"""
    from ..core import paths
    subprocess.Popen(paths.self_cmd("restart"), cwd=str(paths.ROOT),
                     creationflags=0x08000000 if sys.platform == "win32" else 0)
    QUIT.set()


def _told_tray(tray):
    """第一次关窗口：托盘气泡告诉你 AT 还在右下角（只说一次）"""
    if STATE["told_tray"] or tray is None:
        return
    STATE["told_tray"] = True
    tray.notify("AT 还在后台运行", "F8 识别、自动跑、悬浮窗照常可用。双击右下角图标重新打开，右键可以退出。")


def main(open_ui=True, port=0, restart=False):
    if open_ui and not _single_instance(restart):
        return
    bus.install_router()
    from ..core.perf import lower_priority
    lower_priority()
    server = Server(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/#t={TOKEN}"
    STATE["url"] = url
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()
    from .overlay import hud
    hud()
    _sys_task.start_background()                    # = EngineManager.get_instance().start_all()
    print(f"AT 已启动（端口 {server.server_address[1]}）")
    try:
        from ..core import paths
        (paths.USER / "window_url.txt").write_text(url, encoding="utf-8")
    except Exception:
        pass
    tray = None
    from . import window
    use_wv = open_ui and window.available()         # 2026-10-30 阶段 0：有 pywebview 就用自己的窗口，没有走原来的 ATShell → Edge
    if open_ui:
        from .tray import Tray
        # on_open 还是 show_window：PyWebview 窗口在的时候它直接调 window.show()；PyWebview 打不开退回 Edge 时照旧
        tray = Tray(Path(__file__).resolve().parent / "icon.ico", on_open=show_window, on_restart=_relaunch,
                    on_quit=QUIT.set)
        tray.start()
        STATE["tray"] = tray
        if not use_wv:
            STATE["edge"] = open_window(url)
    started = time.time()
    try:
        if use_wv:
            # 主线程跑窗口，一直到窗口销毁（托盘退出 → QUIT → window 里的线程 destroy；没托盘时点关闭就真关）。
            # 原来下面那个等 QUIT 的循环在 PyWebview 模式下不用跑：窗口藏起来时网页的实时推送连接不断，
            # 「没连接就提示托盘 / 退出」那两条本来就不会触发；托盘提示改由窗口的 closing 发
            try:
                from .api.bridge import BackendBridge
                window.run(url, BackendBridge(), on_hide_first=lambda: _told_tray(tray), quit_ev=QUIT,
                           keep_running=lambda: bool(tray and tray.ok))
            except Exception:
                import traceback
                traceback.print_exc()
                if not QUIT.is_set():
                    STATE["edge"] = open_window(url)            # PyWebview 打不开：照旧用 ATShell / Edge
                    use_wv = False
            if use_wv:
                QUIT.set()                                      # 窗口真关了（没托盘时）或被 destroy：退出
        while not QUIT.is_set():
            time.sleep(0.5)
            if bus.clients():
                continue
            if tray is None or not tray.ok:
                # 没有托盘图标（极少数情况）：还按老办法，窗口关了就退出
                if _last_client["ever"] and time.time() - _last_client["t"] > 8:
                    break
                if not _last_client["ever"] and time.time() - started > 90:
                    break
            elif _last_client["ever"] and not STATE["told_tray"] and time.time() - _last_client["t"] > 3:
                _told_tray(tray)                        # 第一次关窗口：告诉你天枢还在右下角
    except KeyboardInterrupt:
        pass
    finally:
        bus.publish("quit", {})
        time.sleep(0.3)
        _close_edge()
        if tray:
            tray.remove()
        from .engines.manager import EngineManager
        EngineManager.get_instance().stop_all()
        server.shutdown()
