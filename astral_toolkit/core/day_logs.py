"""按天写的日志文件（2026-11-08 老大定：日常日志保留、调试模式多输出，日志和窗口分开）：

- runlog_日期.log：窗口右边「运行日志」里的每一行。窗口那份只留最近 300 行、「清空」只清窗口，这份关了 AT 也查得到
- debug_日期.log：调试模式开着时 F8 / 盘点每一步的裁切、耗时、停因。只进这里，不进窗口运行日志（老大定细节只进文件）

都在 userdata/logs 下，导出日志会带上；问题反馈自动上传的不带。每天一个文件，当天写到上限就停（最后记一行说明）；
过了保留天数的删掉。写不进去一律吞掉，不拖垮主功能。
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

# 种类 → (保留最近几天, 每天最多写多少字节)
KINDS = {"runlog": (30, 5 << 20), "debug": (3, 20 << 20)}

_LOCK = threading.Lock()
_cleaned: set[tuple[str, str, str]] = set()  # (日志目录, 种类, 哪天) 清过过期文件
_full: set[str] = set()  # 当天写满了的文件


def path_for(kind: str, date_str: str | None = None) -> Path:
    """某种日志某天（默认今天）的文件"""
    from . import paths

    return paths.LOGS / f"{kind}_{date_str or time.strftime('%Y-%m-%d')}.log"


def write(kind: str, line: str) -> None:
    """记一行，前面加上时分秒。种类不认识、写不进去都不抛"""
    try:
        days, cap = KINDS[kind]
        today = time.strftime("%Y-%m-%d")
        path = path_for(kind, today)
        key = (str(path.parent), kind, today)
        if key not in _cleaned:
            _cleaned.add(key)
            cleanup(kind, days)
        if str(path) in _full:
            return
        stamp = time.strftime("%H:%M:%S")
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            size = path.stat().st_size if path.exists() else 0
            with open(path, "a", encoding="utf-8") as f:
                if size >= cap:
                    f.write(f"{stamp} 今天这份超过 {cap >> 20} MB 了，后面的不记了\n")
                    _full.add(str(path))
                else:
                    f.write(f"{stamp} {line}\n")
    except Exception:
        pass


def cleanup(kind: str, days: int) -> int:
    """删掉这一种里文件名日期早于 days 天前的，返回删了几个；别的种类不动"""
    from . import paths

    pat = re.compile(rf"^{re.escape(kind)}_(\d{{4}}-\d{{2}}-\d{{2}})\.log$")
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    removed = 0
    try:
        files = list(paths.LOGS.glob(f"{kind}_*.log"))
    except OSError:
        return 0
    for p in files:
        m = pat.match(p.name)
        if m and m.group(1) < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed
