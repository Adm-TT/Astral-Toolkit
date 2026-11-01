"""功能运行证据日志（安全合规与操作留痕）

- 按天切分日志文件（userdata/logs/audit_YYYY-MM-DD.log），记录关键功能触发事实
- 启动及每日首次写入时自动清理超过 30 天的历史日志
- 标明操作性质为 [READ_SCREEN]（仅截屏文字识别）或 [USER_CLIPBOARD]（用户主动操作剪贴板）
- 所有记录均为客观执行证据，证明不注入、不改内存、不模拟按键
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, List, Optional

_LOCK = threading.Lock()
_LAST_CLEANUP_DAY: Optional[str] = None
_DATE_PATTERN = re.compile(r"^audit_(\d{4}-\d{2}-\d{2})\.log$")


def _logs_dir() -> Path:
    from . import paths

    paths.LOGS.mkdir(parents=True, exist_ok=True)
    return paths.LOGS


def audit_path(date_str: Optional[str] = None) -> Path:
    """获取指定日期（格式 YYYY-MM-DD，默认当天）的证据日志路径"""
    if not date_str:
        date_str = time.strftime("%Y-%m-%d")
    return _logs_dir() / f"audit_{date_str}.log"


def cleanup_retention(days: int = 30) -> int:
    """扫描并清理超过指定天数（默认 30 天）的历史证据日志，返回删除的文件个数"""
    d = _logs_dir()
    if not d.exists():
        return 0

    now_ts = time.time()
    cutoff_ts = now_ts - (days * 86400)
    removed = 0

    with _LOCK:
        for p in list(d.glob("audit_*.log")):
            m = _DATE_PATTERN.match(p.name)
            if not m:
                continue
            is_expired = False
            try:
                file_ts = p.stat().st_mtime
                if file_ts < cutoff_ts:
                    is_expired = True
                else:
                    # 双重校验：依据文件名中的日期解析
                    dt = datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )
                    if dt.timestamp() < cutoff_ts:
                        is_expired = True
            except Exception:
                pass

            if is_expired:
                try:
                    p.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    pass

    return removed


def record(
    category: str,
    action: str,
    details: Any = None,
    tag: str = "READ_SCREEN",
    level: str = "INFO",
) -> None:
    """写入一条功能运行证据日志

    Args:
        category: 功能模块（如 SYSTEM, MINING, ITEM_SEARCH, NAV, WAYPOINT, STOCK）
        action: 操作行为（如 启动, F8识图, 开启采矿助手, 路线规划）
        details: 详细数据（字符串、字典或列表）
        tag: 安全合规标签（默认 READ_SCREEN 仅截屏读文字；或 USER_CLIPBOARD, OFFLINE_CALC 等）
        level: 日志级别（INFO, WARN, ERROR）
    """
    global _LAST_CLEANUP_DAY
    today = time.strftime("%Y-%m-%d")

    # 每日首次记录时执行 30 天过期清理
    if _LAST_CLEANUP_DAY != today:
        _LAST_CLEANUP_DAY = today
        try:
            cleanup_retention(days=30)
        except Exception:
            pass

    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    if details is None:
        detail_str = ""
    elif isinstance(details, (dict, list)):
        detail_str = " | " + json.dumps(details, ensure_ascii=False)
    else:
        detail_str = f" | {details}"

    line = f"{timestamp_str} [{level}] [{tag}] [{category}] {action}{detail_str}\n"

    path = audit_path(today)
    with _LOCK:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass


def read_records(
    date_str: Optional[str] = None, limit: int = 100
) -> List[str]:
    """读取某天最后 N 条审计日志（默认当天）"""
    path = audit_path(date_str)
    if not path.exists():
        return []
    with _LOCK:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            return lines[-limit:]
        except Exception:
            return []
