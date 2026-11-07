"""程序内部的消息广播和运行日志：后台功能（读屏、导航、F8 识别、更新数据）把结果发到这里，窗口实时收到。publish(kind, data) 发一条；subscribe() / unsubscribe(q) 窗口每个连接一个队列（新连接补发每类最后一条和运行日志）；runtime_log 记一行运行日志。截图预览在 app/preview.py，后台任务和 print 转窗口日志在 app/task_runner.py（F 段 B4 拆出去的）。"""

import collections
import queue
import threading
import time

from ..core import day_logs

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

# ---------------------------------------------------------------- 运行时日志
_runtime_logs = collections.deque(maxlen=300)


def runtime_log(line, tag="SYS", level="INFO"):
    """向前端 UI 广播运行时日志（等宽终端显示），同时记进 logs/runlog_日期.log：窗口那份只留最近 300 行、
    「清空」只清窗口，文件里的关了 AT 也查得到、导出日志带上（2026-11-08 老大定日志和窗口分开）"""
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "line": str(line),
        "tag": str(tag),
        "level": str(level),
    }
    with _lock:
        _runtime_logs.append(entry)
    publish("runtime_log", entry)
    day_logs.write("runlog", f"[{entry['level']}] [{entry['tag']}] {entry['line']}")


def clear_runtime_logs():
    """清空运行时日志"""
    with _lock:
        _runtime_logs.clear()
    publish("runtime_log_clear", {})


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
