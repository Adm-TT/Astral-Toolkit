"""按天写的日志文件（2026-11-08 老大定：日常日志保留、调试模式多输出，日志和窗口分开）：

- runrec_日期.log：运行记录（core/run_records：各功能开关、触发），留 30 天，问题反馈带最近一百多行
- runlog_日期.log：后台推到窗口右边「运行日志」的每一行。窗口那份只留最近 300 行、「清空」只清窗口，这份关了 AT 也查得到
- debug_日期.log：调试模式开着时 F8 / 盘点每一步的裁切、耗时、停因。只进这里，不进窗口运行日志（老大定细节只进文件）

都在 userdata/logs 下，导出日志会带上（导出时抹掉 Windows 用户名这类个人信息）。每天一个文件，有上限的当天写到上限
就停（最后记一行说明）。每天第一次写日志时把各种的过期文件都清一遍：关掉调试模式以后，旧的调试日志也照样清。
写不进去一律吞掉，不拖垮主功能。
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

# 种类 → (留最近几天、含今天, 每天最多写多少字节；None = 不设上限)
KINDS: dict[str, tuple[int, int | None]] = {
    "runrec": (30, None),
    "runlog": (30, 5 << 20),
    "debug": (3, 20 << 20),
}

LOCK = threading.Lock()  # 追加、清理、读尾巴（run_records.read_tail）都在这把锁里
_cleaned: set[tuple[str, str]] = set()  # (日志目录, 哪天) 清过过期文件
_full: set[str] = set()  # 当天写满了的文件


def path_for(kind: str, date_str: str | None = None) -> Path:
    """某种日志某天（默认今天）的文件"""
    from . import paths

    return paths.LOGS / f"{kind}_{date_str or time.strftime('%Y-%m-%d')}.log"


def write(kind: str, line: str, *, stamp: bool = True) -> None:
    """记一行。stamp：前面加上时分秒（运行记录自己带完整时间，不加）。种类不认识、写不进去都不抛"""
    try:
        cap = KINDS[kind][1]
        today = time.strftime("%Y-%m-%d")
        path = path_for(kind, today)
        key = (str(path.parent), today)
        if key not in _cleaned:
            _cleaned.add(key)
            cleanup_all()
        head = time.strftime("%H:%M:%S ") if stamp else ""
        with LOCK:
            if str(path) in _full:  # 在锁里看：几个线程同时写到上限，说明也只记一次
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            full = cap is not None and path.exists() and path.stat().st_size >= cap
            with open(path, "a", encoding="utf-8") as f:
                if full:
                    note = f"今天这份超过 {(cap or 0) >> 20} MB 了，后面的不记了"
                    f.write(f"{time.strftime('%H:%M:%S')} {note}\n")
                    _full.add(str(path))
                else:
                    f.write(f"{head}{line}\n")
    except Exception:
        pass


def cleanup(kind: str, days: int) -> int:
    """删掉这一种里文件名日期早于「最近 days 天（含今天）」的，返回删了几个；名字不完全是「种类_日期.log」的不动"""
    from . import paths

    pat = re.compile(rf"^{re.escape(kind)}_(\d{{4}}-\d{{2}}-\d{{2}})\.log$")
    first = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    removed = 0
    try:
        files = list(paths.LOGS.glob(f"{kind}_*.log"))
    except OSError:
        return 0
    with LOCK:
        for p in files:
            m = pat.match(p.name)
            if m and m.group(1) < first:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def cleanup_all() -> int:
    """各种日志都按自己的保留天数清一遍，返回一共删了几个"""
    return sum(cleanup(kind, days) for kind, (days, _cap) in KINDS.items())
