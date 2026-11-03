"""AT 的本机网页服务（从 server.py 拆出来，2026-10-31 整改第 1 批）：令牌校验、静态文件、接口转发、安装包上传、事件流、截图

- 只监听 127.0.0.1（server.main 里建服务时传入），别的电脑访问不到
- 每次启动随机生成口令 TOKEN：只有 AT 自己打开的窗口知道
"""

import json
import mimetypes
import queue
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import bus
from . import ui_stream

# 2026-10-30 阶段 4：services.py 删了。import tasks 这一层会把全部任务模块加载好（tasks/__init__.py），
# tasks.goals / tasks.navigation 在 import 时登记数据包清缓存函数，和原来 import services 时顺带做的一样早

WEB = Path(__file__).resolve().parent / "web"
mimetypes.add_type(
    "font/woff2", ".woff2"
)  # 1.6.59：D-DIN 字体（Windows 自带的类型表里可能没有）
mimetypes.add_type("image/webp", ".webp")  # 阿塔的图片
mimetypes.add_type("image/svg+xml", ".svg")
# 每次启动随机生成的口令：只有助手自己打开的窗口知道（在网址里带过去），别的网页、别的程序猜不到
TOKEN = secrets.token_urlsafe(24)
MAX_BODY = 16 << 20  # 接口的请求体上限（都是小 JSON）
_last_client = {"t": time.time(), "ever": False}
# 新展示流心跳间隔（秒）；测试可调小，不需要长 sleep
UI_HEARTBEAT_INTERVAL = 5.0
UI_STATE_REFRESH_INTERVAL = 1.0  # 无业务事件时也确认旧线程是否已收尾，不另起后台线程


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
        given = (
            self.headers.get("X-Token") or (qs.get("token") or qs.get("t") or [""])[0]
        )
        return secrets.compare_digest(given, TOKEN)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/events":
            if not self._allowed():
                return self._send(403, "{}")
            return self._events()
        if path == "/api/ui/events":
            if not self._allowed():
                return self._send(403, "{}")
            return self._ui_events()
        if path == "/api/ui/snapshot":
            if not self._allowed():
                return self._send(403, "{}")
            return self._ui_snapshot()
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
        # 拒绝时不读请求体，答完就关连接（请求体留在连接里，这条连接不能再复用）。
        # 审查 2026-10-31：以前先按 Content-Length 把请求体整个读进内存再验令牌，本机任何程序不带令牌就能让 AT 吃掉上 GB 内存
        if not self.path.startswith("/api/"):
            self.close_connection = True
            return self._send(404, "{}")
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0:
            self.close_connection = True
            return self._send(
                400,
                json.dumps({"ok": False, "error": "请求格式不对"}, ensure_ascii=False),
            )
        name = self.path[5:].split("?")[0]
        if not self._allowed():  # 只看请求头和网址，不用先读请求体
            self.close_connection = True
            return self._send(403, json.dumps({"ok": False, "error": "拒绝访问"}))
        if n > MAX_BODY:
            self.close_connection = True
            return self._send(
                413, json.dumps({"ok": False, "error": "请求太大"}, ensure_ascii=False)
            )
        raw = self.rfile.read(n) if n else b""
        if name == "ui/dismiss":
            return self._ui_dismiss(raw)
        from .api import router  # 2026-10-30 阶段 0：接口统一走 router

        if name not in router.routes():
            return self._send(
                404,
                json.dumps({"ok": False, "error": f"没有 {name}"}, ensure_ascii=False),
            )
        try:
            args = json.loads(raw or b"{}")
        except Exception as e:
            return self._send(
                200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
            )
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

    def _ui_events(self):
        # SSE 没有 Content-Length：必须明确关闭连接，否则 HTTP/1.1 keep-alive
        # 会让客户端永远等不到 EOF（满队列/bye 后服务端线程也会卡住）。
        self.close_connection = True
        hello, q = ui_stream.subscribe()
        if q is None:
            error = (
                hello.get("error", "已关闭") if isinstance(hello, dict) else "已关闭"
            )
            return self._send(
                503,
                json.dumps({"ok": False, "error": error}, ensure_ascii=False),
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        conn = hello["conn"]
        interval = max(0.01, float(UI_HEARTBEAT_INTERVAL))
        refresh = max(0.01, float(UI_STATE_REFRESH_INTERVAL))
        poll = min(1.0, interval, refresh)
        try:
            self.wfile.write(ui_stream.encode(hello).encode("utf-8"))
            self.wfile.flush()
            last_hb = time.time()
            next_refresh = time.monotonic() + refresh
            while True:
                if not ui_stream.is_connected(q):
                    break
                if time.monotonic() >= next_refresh:
                    ui_stream.refresh_switches()
                    next_refresh = time.monotonic() + refresh
                try:
                    msg = q.get(timeout=poll)
                except queue.Empty:
                    if not ui_stream.is_connected(q):
                        break
                    now = time.time()
                    if now - last_hb >= interval:
                        hb = ui_stream.heartbeat(conn)
                        self.wfile.write(ui_stream.encode(hb).encode("utf-8"))
                        self.wfile.flush()
                        last_hb = now
                    continue
                if not ui_stream.is_connected(q):
                    break
                try:
                    self.wfile.write(ui_stream.encode(msg).encode("utf-8"))
                    self.wfile.flush()
                finally:
                    ui_stream.mark_dequeued(q)
                last_hb = time.time()
                if msg.get("kind") == "ui.bye":
                    break
        except Exception:
            pass
        finally:
            ui_stream.unsubscribe(q)

    def _ui_snapshot(self):
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(self.path).query)
        conn = (qs.get("conn") or [""])[0]
        try:
            conn = int(conn)
        except (TypeError, ValueError):
            pass
        # 全家福只读；开关刷新必须先走 set_switches，有变化会在展示流锁内分配 ui_seq 并广播 ui.tile
        read_mono = time.monotonic()
        try:
            ui_stream.set_switches(ui_stream.read_switches(), read_mono=read_mono)
        except Exception:
            pass
        snap = ui_stream.snapshot(conn)
        self._send(
            200,
            json.dumps(snap, ensure_ascii=False, default=str),
        )

    def _ui_dismiss(self, raw):
        try:
            args = json.loads(raw or b"{}")
        except Exception as e:
            return self._send(
                200,
                json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False),
            )
        notice_id = args.get("notice_id") if isinstance(args, dict) else None
        if not notice_id:
            return self._send(
                200,
                json.dumps(
                    {"ok": False, "error": "缺少 notice_id"},
                    ensure_ascii=False,
                ),
            )
        notice_id = str(notice_id)
        ok = ui_stream.dismiss_notice(notice_id)
        body = {
            "ok": bool(ok),
            "data": {"notice_id": notice_id, "dismissed": bool(ok)},
        }
        if not ok:
            body["error"] = "没有这条通知"
        return self._send(200, json.dumps(body, ensure_ascii=False))


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """窗口关掉/刷新时连接被断开是正常的，不往日志里写一大段错误"""
        exc = sys.exc_info()[1]
        if isinstance(
            exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)
        ):
            return
        super().handle_error(request, client_address)
