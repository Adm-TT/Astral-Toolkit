"""后台任务和 print 转窗口日志：线程里跑任务、同一任务只起一个、输出按任务进窗口，从 app/bus.py 拆来。"""

import io
import sys
import threading
import time

from . import bus, ui_stream

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
                            bus.runtime_log(line, tag="APP", level="INFO")
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
            bus.publish("log", {"task": tid, "line": line})
            bus.runtime_log(line, tag=tid.upper(), level="INFO")
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
_run_seq = 0
_run_seq_lock = threading.Lock()


def _next_run_id():
    """给一次真正启动的后台任务分配进程内单调的 run_id"""
    global _run_seq
    with _run_seq_lock:
        _run_seq += 1
        return _run_seq


def task_running(task_id):
    """这个后台任务是不是还在跑"""
    th = _running.get(task_id)
    return bool(th and th.is_alive())


def run_task_once(task_id, fn, *args, title="", **kw):
    """同一个任务已经在跑就不再起（查和起在同一把锁里，两个请求同时到也只起一个，审查 2026-10-28）；起了返回线程，没起返回 None"""
    with _run_lock:
        if task_running(task_id):
            return None
        return run_task(task_id, fn, *args, title=title, **kw)


def run_task(task_id, fn, *args, title="", **kw):
    """在后台线程里跑 fn，期间的 print 都进窗口日志；开始/结束发 task 消息"""

    def body():
        _task.id = task_id
        bus.publish("task", {"id": task_id, "title": title, "state": "running"})
        bus.runtime_log(
            f"任务开始: {title or task_id}", tag=task_id.upper(), level="INFO"
        )
        run_id = _next_run_id()
        ui_active = task_id in ("update", "upgrade")
        activity_id = f"{task_id}:{run_id}"
        if ui_active:
            try:
                ui_stream.publish_ui(
                    "ui.activity",
                    {
                        "activity": {
                            "activity_id": activity_id,
                            "kind": task_id,
                            "state": "running",
                            "title": title or task_id,
                            "primary": {"value": 0, "unit": ""},
                            "secondary": [],
                            "progress": None,
                            "quality": "partial",
                            "action": None,
                            "link": None,
                            "stale_since": None,
                            "error": None,
                            "updated_wall": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    },
                )
            except Exception:
                pass
        ui_ended = False

        def end_ui(reason, error=None):
            nonlocal ui_ended
            if not ui_active or ui_ended:
                return
            ui_ended = True
            try:
                data = {
                    "activity_id": activity_id,
                    "end_reason": reason,
                }
                if error is not None:
                    data["error"] = str(error)
                ui_stream.publish_ui("ui.activity_end", data)
            except Exception:
                pass

        try:
            result = fn(*args, **kw)
            bus.publish(
                "task",
                {"id": task_id, "title": title, "state": "done", "result": result},
            )
            bus.runtime_log(
                f"任务结束: {title or task_id}", tag=task_id.upper(), level="INFO"
            )
            end_ui("done")
        except Exception as e:
            import traceback

            traceback.print_exc(file=sys.stdout)
            bus.publish(
                "task",
                {"id": task_id, "title": title, "state": "error", "error": str(e)},
            )
            bus.runtime_log(
                f"任务出错: {title or task_id} - {e}",
                tag=task_id.upper(),
                level="ERROR",
            )
            end_ui("error", e)
        except BaseException as e:
            name = type(e).__name__.lower()
            if "cancel" in name:
                end_ui("user", e)
            elif isinstance(e, (KeyboardInterrupt, SystemExit)):
                end_ui("shutdown", e)
            else:
                end_ui("error", e)
            raise
        finally:
            r = sys.stdout
            if isinstance(r, _Router):
                for key in [k for k in list(r.buf) if k[0] == task_id]:
                    rest = r.buf.pop(key)
                    if rest:
                        bus.publish("log", {"task": task_id, "line": rest})
                        bus.runtime_log(rest, tag=task_id.upper(), level="INFO")
            _task.id = None

    th = threading.Thread(target=body, daemon=True, name=f"task-{task_id}")
    _running[task_id] = th
    th.start()
    return th
