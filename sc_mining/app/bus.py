"""程序内部的消息广播：后台功能（读屏、导航、F8 识别、更新数据）把结果发到这里，窗口实时收到

- publish(kind, data)：发一条
- subscribe() / unsubscribe(q)：窗口每个连接一个队列
- 后台任务里的 print() 也会转成 log 消息，显示在窗口里（按线程区分属于哪个任务）
"""

import collections
import io
import json
import queue
import sys
import threading
import time

_subs = []
_lock = threading.Lock()
_last = {}  # 每类消息最后一条（窗口刷新/新打开时补发）
STICKY = {
    "hud",
    "status",
    "scan",
    "scan_hint",
    "signals",
    "nav",
    "hover",
    "live",
    "task",
    "runtime_preview",
}

# ---------------------------------------------------------------- 运行时日志与实时截图缓存
_runtime_logs = collections.deque(maxlen=300)
_preview_thumb_bytes = None
_preview_full_bytes = None
_preview_meta = {}
_last_preview_t = 0.0
_preview_lock = threading.Lock()


def runtime_log(line, tag="SYS", level="INFO"):
    """向前端 UI 广播运行时日志（等宽终端显示）"""
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "line": str(line),
        "tag": str(tag),
        "level": str(level),
    }
    with _lock:
        _runtime_logs.append(entry)
    publish("runtime_log", entry)


def clear_runtime_logs():
    """清空运行时日志"""
    with _lock:
        _runtime_logs.clear()
    publish("runtime_log_clear", {})


def update_preview(img, source="live", force=False):
    """更新最新画面截图缓存，并向前端推送通知（节流保护，最高 2 次/秒）"""
    global _last_preview_t, _preview_thumb_bytes, _preview_full_bytes, _preview_meta
    now = time.time()
    if not force and now - _last_preview_t < 0.5:
        return
    with _preview_lock:
        if not force and now - _last_preview_t < 0.5:
            return
        _last_preview_t = now
        try:
            w, h = img.size
            # 缩略图（针对右下角预览区域，宽度限制在 360px）
            tw = min(360, w)
            th = max(1, int(h * (tw / w)))
            thumb = img.resize((tw, th))
            if thumb.mode != "RGB":
                thumb = thumb.convert("RGB")
            bio = io.BytesIO()
            thumb.save(bio, format="JPEG", quality=75)
            _preview_thumb_bytes = bio.getvalue()

            # 大图缓存（用于点击弹出放大，最大宽 1280px）
            fw = min(1280, w)
            fh = max(1, int(h * (fw / w)))
            fimg = img if fw >= w else img.resize((fw, fh))
            if fimg.mode != "RGB":
                fimg = fimg.convert("RGB")
            bio_full = io.BytesIO()
            fimg.save(bio_full, format="JPEG", quality=80)
            _preview_full_bytes = bio_full.getvalue()

            _preview_meta = {
                "t": now,
                "time_str": time.strftime("%H:%M:%S"),
                "w": w,
                "h": h,
                "source": source,
                "bytes": len(_preview_thumb_bytes),
            }
        except Exception as e:
            runtime_log(f"截图预览处理异常: {e}", tag="SYS", level="WARN")
            return
    publish("runtime_preview", _preview_meta)


def get_preview_bytes(full=False):
    """获取最新截图的二进制数据与元数据"""
    with _preview_lock:
        return (_preview_full_bytes if full else _preview_thumb_bytes), dict(
            _preview_meta
        )


def publish(kind, data):
    msg = {"kind": kind, "data": data, "t": time.time()}
    with _lock:
        if kind in STICKY:
            key = kind + (
                ":" + str(data.get("section", ""))
                if kind == "hud" and isinstance(data, dict)
                else ""
            )
            key += (
                ":" + str(data.get("id", ""))
                if kind == "task" and isinstance(data, dict)
                else ""
            )
            _last[key] = msg
        subs = list(_subs)
    for q in subs:
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


def subscribe():
    q = queue.Queue(maxsize=2000)
    with _lock:
        _subs.append(q)
        for msg in _last.values():
            q.put_nowait(
                {**msg, "replay": True}
            )  # 补发的旧消息：前端只恢复状态，不跳页、不弹提示（2026-10-28 审查）
        for entry in _runtime_logs:
            q.put_nowait({"kind": "runtime_log", "data": entry, "replay": True})
    return q


def unsubscribe(q):
    with _lock:
        if q in _subs:
            _subs.remove(q)


def clients():
    with _lock:
        return len(_subs)


def encode(msg):
    return "data: " + json.dumps(msg, ensure_ascii=False, default=str) + "\n\n"


# ---------------------------------------------------------------- print() → 窗口日志

_task = threading.local()
_router_guard = threading.local()


class _Router(io.TextIOBase):
    """替换 sys.stdout：属于某个后台任务的线程，输出发到窗口；其他照常写到控制台并镜像到运行日志"""

    def __init__(self, real):
        self.real = real
        self.buf = {}

    def write(self, s):
        tid = getattr(_task, "id", None)
        if tid is None:
            res = len(s)
            try:
                res = self.real.write(s)
            except Exception:
                pass
            if not getattr(_router_guard, "active", False):
                _router_guard.active = True
                try:
                    for line in s.splitlines():
                        line = line.strip()
                        if line:
                            runtime_log(line, tag="APP", level="INFO")
                except Exception:
                    pass
                finally:
                    _router_guard.active = False
            return res
        key = (
            tid,
            threading.get_ident(),
        )  # 同一个任务可能有几个线程一起输出：各攒各的半行，别拼错
        text = self.buf.get(key, "") + s
        *lines, rest = text.split("\n")
        self.buf[key] = rest
        for line in lines:
            publish("log", {"task": tid, "line": line})
            runtime_log(line, tag=tid.upper(), level="INFO")
            try:
                self.real.write(
                    f"[{tid}] {line}\n"
                )  # 也进 app_log.txt（2026-10-28 整体审查：以前只发窗口，导出的日志里没有）
            except Exception:
                pass
        return len(s)

    def flush(self):
        try:
            self.real.flush()
        except Exception:
            pass


def install_router():
    if not isinstance(sys.stdout, _Router):
        sys.stdout = _Router(sys.stdout)


def current_task():
    """当前线程属于哪个后台任务（没有返回 None）"""
    return getattr(_task, "id", None)


def adopt_task(task_id):
    """任务里另开的线程调用：让这个线程的 print 也进同一个任务的窗口日志"""
    _task.id = task_id


_running = {}
_run_lock = threading.Lock()


def task_running(task_id):
    """这个后台任务是不是还在跑"""
    th = _running.get(task_id)
    return bool(th and th.is_alive())


def run_task_once(task_id, fn, *args, title="", **kw):
    """同一个任务已经在跑就不再起（查和起在同一把锁里，两个请求同时到也只起一个，老大审查 2026-10-28）；起了返回线程，没起返回 None"""
    with _run_lock:
        if task_running(task_id):
            return None
        return run_task(task_id, fn, *args, title=title, **kw)


def run_task(task_id, fn, *args, title="", **kw):
    """在后台线程里跑 fn，期间的 print 都进窗口日志；开始/结束发 task 消息"""

    def body():
        _task.id = task_id
        publish("task", {"id": task_id, "title": title, "state": "running"})
        runtime_log(f"任务开始: {title or task_id}", tag=task_id.upper(), level="INFO")
        try:
            result = fn(*args, **kw)
            publish(
                "task",
                {"id": task_id, "title": title, "state": "done", "result": result},
            )
            runtime_log(
                f"任务结束: {title or task_id}", tag=task_id.upper(), level="INFO"
            )
        except Exception as e:
            import traceback

            traceback.print_exc(file=sys.stdout)
            publish(
                "task",
                {"id": task_id, "title": title, "state": "error", "error": str(e)},
            )
            runtime_log(
                f"任务出错: {title or task_id} - {e}",
                tag=task_id.upper(),
                level="ERROR",
            )
        finally:
            r = sys.stdout
            if isinstance(r, _Router):
                for key in [k for k in list(r.buf) if k[0] == task_id]:
                    rest = r.buf.pop(key)
                    if rest:
                        publish("log", {"task": task_id, "line": rest})
                        runtime_log(rest, tag=task_id.upper(), level="INFO")
            _task.id = None

    th = threading.Thread(target=body, daemon=True, name=f"task-{task_id}")
    _running[task_id] = th
    th.start()
    return th
