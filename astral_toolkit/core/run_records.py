"""运行记录：按天记下功能模块的调用过程，方便对照调了哪些工具

- 文件：userdata/logs/runrec_YYYY-MM-DD.log，留 30 天（按天的文件统一在 core/day_logs：放哪、怎么追加、过期清理）
- 只记启停/触发等过程，不记识别结果内容
- 可选镜像到运行日志面板：装配（bootstrap.bind_all）用 set_ui_sink 接 bus.runtime_log，core 不再反过来 import 界面
  （CL-C5）；没接（不是桌面程序）就只写文件
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import day_logs

# 落盘 MODULE → 面板 tag（缺省 ui_tag 时用）
UI_TAGS = {
    "SYSTEM": "SYS",
    "MINING": "LIVE",
    "HOVER": "HOVER",
    "NAV": "NAV",
    "COUNT": "COUNT",
    "STOCK": "STOCK",
    "CRAFT": "CRAFT",
    "GOALS": "GOALS",
    "UPDATE": "UPDATE",
    "FEEDBACK": "SYS",
}

_ui_sink = None  # 装配接进来的 runtime_log(line, tag=, level=)，见 set_ui_sink


def set_ui_sink(fn):
    """装配时接「推一条到运行日志面板」的函数（bootstrap.bind_all）；record 写完文件顺手推一条"""
    global _ui_sink
    _ui_sink = fn


def path_for(date_str: Optional[str] = None) -> Path:
    """指定日期（YYYY-MM-DD，默认当天）的运行记录文件路径"""
    return day_logs.path_for("runrec", date_str)


def cleanup_retention(days: int = 30) -> int:
    """删掉早于最近 days 天（含今天）的 runrec_日期.log，返回删了几个（day_logs 每天第一次写日志时自己也会清）"""
    return day_logs.cleanup("runrec", days)


def record(
    module: str,
    action: str,
    details: Any = None,
    *,
    level: str = "INFO",
    ui_tag: Optional[str] = None,
    mirror_ui: bool = True,
) -> None:
    """写一条运行过程记录；失败一律吞掉，不拖垮主功能"""
    try:
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        mod = str(module or "SYSTEM").upper()
        act = str(action or "").strip() or "（未命名动作）"
        if details is None or details == "":
            detail_str = ""
        else:
            detail_str = f" | {details}"
        # 写不进文件（连 logs 目录都建不了）day_logs 自己吞掉，也别丢面板那条
        line = f"{timestamp_str} [{level}] [{mod}] {act}{detail_str}"
        day_logs.write("runrec", line, stamp=False)

        sink = _ui_sink
        if mirror_ui and sink is not None:
            try:
                tag = ui_tag or UI_TAGS.get(mod, mod)
                ui_line = f"{act}{detail_str}"
                sink(ui_line, tag=tag, level=level)
            except Exception:
                pass
    except Exception:
        pass


def read_tail(date_str: Optional[str] = None, limit: int = 100) -> list[str]:
    """读某天最后 N 条（默认当天）"""
    path = path_for(date_str)
    if not path.exists():
        return []
    with day_logs.LOCK:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            return lines[-limit:] if limit > 0 else lines
        except Exception:
            return []


def read_recent(limit: int = 150) -> list[str]:
    """最近 N 条：今天不够就从昨天的文件末尾补（刚过零点按 F10 也能带上前一晚的）"""
    today = read_tail(limit=limit)
    if len(today) >= limit:
        return today
    yday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    return read_tail(yday, limit=limit - len(today)) + today
