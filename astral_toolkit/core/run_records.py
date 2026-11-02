"""运行记录：按天记下功能模块的调用过程，方便对照调了哪些工具

- 文件：userdata/logs/runrec_YYYY-MM-DD.log，默认保留 30 天
- 只记启停/触发等过程，不记识别结果内容
- 可选镜像到运行日志面板（bus.runtime_log）
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import threading
import time
from typing import Any, Optional

_LOCK = threading.Lock()
_LAST_CLEANUP_DAY: Optional[str] = None
_DATE_PATTERN = re.compile(r"^runrec_(\d{4}-\d{2}-\d{2})\.log$")

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


def _logs_dir() -> Path:
    from . import paths

    paths.LOGS.mkdir(parents=True, exist_ok=True)
    return paths.LOGS


def path_for(date_str: Optional[str] = None) -> Path:
    """指定日期（YYYY-MM-DD，默认当天）的运行记录文件路径"""
    if not date_str:
        date_str = time.strftime("%Y-%m-%d")
    return _logs_dir() / f"runrec_{date_str}.log"


def cleanup_retention(days: int = 30) -> int:
    """删除超过 days 天的 runrec_*.log，返回删除个数"""
    d = _logs_dir()
    if not d.exists():
        return 0
    cutoff_ts = time.time() - (days * 86400)
    removed = 0
    with _LOCK:
        for p in list(d.glob("runrec_*.log")):
            m = _DATE_PATTERN.match(p.name)
            if not m:
                continue
            expired = False
            try:
                if p.stat().st_mtime < cutoff_ts:
                    expired = True
                else:
                    dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                    if dt.timestamp() < cutoff_ts:
                        expired = True
            except Exception:
                continue
            if expired:
                try:
                    p.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    pass
    return removed


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
    global _LAST_CLEANUP_DAY
    try:
        today = time.strftime("%Y-%m-%d")
        if _LAST_CLEANUP_DAY != today:
            _LAST_CLEANUP_DAY = today
            try:
                cleanup_retention(days=30)
            except Exception:
                pass

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        mod = str(module or "SYSTEM").upper()
        act = str(action or "").strip() or "（未命名动作）"
        if details is None or details == "":
            detail_str = ""
        else:
            detail_str = f" | {details}"
        line = f"{timestamp_str} [{level}] [{mod}] {act}{detail_str}\n"
        try:
            path = path_for(today)
            with _LOCK:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            pass  # 写不进文件（连 logs 目录都建不了）也别丢面板那条

        if mirror_ui:
            try:
                from ..app import bus

                tag = ui_tag or UI_TAGS.get(mod, mod)
                ui_line = f"{act}{detail_str}"
                bus.runtime_log(ui_line, tag=tag, level=level)
            except Exception:
                pass
    except Exception:
        pass


def read_tail(date_str: Optional[str] = None, limit: int = 100) -> list[str]:
    """读某天最后 N 条（默认当天）"""
    path = path_for(date_str)
    if not path.exists():
        return []
    with _LOCK:
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
