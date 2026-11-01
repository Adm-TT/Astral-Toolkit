"""功能运行证据日志（安全合规、操作留痕与防篡改哈希链）

- 按天切分日志文件（userdata/logs/audit_YYYY-MM-DD.log），记录关键功能触发事实
- 引入哈希链（Hash Chaining）：每行记录计算并挂载上一行的 SHA-256 摘要，防止本地篡改、插行与删行
- 启动及每日首次写入时自动清理超过 30 天的历史日志
- 标明操作性质为 [READ_SCREEN]（仅截屏文字识别）或 [USER_CLIPBOARD]（用户主动操作剪贴板）
- 提供 verify_chain 校验接口，随时自证日志完整性
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, List, Optional, Tuple

_LOCK = threading.Lock()
_LAST_CLEANUP_DAY: Optional[str] = None
_DATE_PATTERN = re.compile(r"^audit_(\d{4}-\d{2}-\d{2})\.log$")
GENESIS_HASH = "0" * 16
_HASH_PATTERN = re.compile(r"\[prev:([0-9a-f]{16})\]\s+\[hash:([0-9a-f]{16})\]$")

# 缓存当天最后写入的哈希
_LAST_HASH_CACHE: dict[str, str] = {}


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
                    _LAST_HASH_CACHE.pop(m.group(1), None)
                    removed += 1
                except OSError:
                    pass

    return removed


def _get_last_hash(date_str: str, path: Path) -> str:
    """获取或从文件恢复该日期的末尾哈希"""
    if not path.exists() or path.stat().st_size == 0:
        _LAST_HASH_CACHE[date_str] = GENESIS_HASH
        return GENESIS_HASH

    cached = _LAST_HASH_CACHE.get(date_str)
    if cached:
        return cached

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            m = _HASH_PATTERN.search(line)
            if m:
                h = m.group(2)
                _LAST_HASH_CACHE[date_str] = h
                return h
    except Exception:
        pass

    _LAST_HASH_CACHE[date_str] = GENESIS_HASH
    return GENESIS_HASH


def record(
    category: str,
    action: str,
    details: Any = None,
    tag: str = "READ_SCREEN",
    level: str = "INFO",
) -> None:
    """写入一条功能运行证据日志（带哈希链防篡改）

    Args:
        category: 功能模块（如 SYSTEM, MINING, ITEM_SEARCH, NAV, WAYPOINT）
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

    path = audit_path(today)
    with _LOCK:
        prev_hash = _get_last_hash(today, path)
        content_prefix = f"{timestamp_str} [{level}] [{tag}] [{category}] {action}{detail_str} [prev:{prev_hash}]"
        curr_hash = hashlib.sha256(content_prefix.encode("utf-8")).hexdigest()[:16]
        full_line = f"{content_prefix} [hash:{curr_hash}]\n"

        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(full_line)
            _LAST_HASH_CACHE[today] = curr_hash
        except Exception:
            pass


def verify_chain(date_str: Optional[str] = None) -> Tuple[bool, int, str]:
    """校验指定日期（默认当天）的证据日志哈希链完整性

    Returns:
        (是否有效, 总记录条数, 状态描述信息)
    """
    path = audit_path(date_str)
    if not path.exists():
        return True, 0, "日志文件不存在或为空"

    with _LOCK:
        try:
            lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        except Exception as e:
            return False, 0, f"读取日志出错: {e}"

    if not lines:
        return True, 0, "空日志文件"

    expected_prev = GENESIS_HASH
    for idx, line in enumerate(lines, start=1):
        m = _HASH_PATTERN.search(line)
        if not m:
            return False, idx, f"第 {idx} 行格式异常，未包含有效的防伪哈希标头"

        line_prev, line_hash = m.group(1), m.group(2)
        if line_prev != expected_prev:
            return False, idx, f"第 {idx} 行哈希链断裂: prev={line_prev} 与上行期望={expected_prev} 不匹配（存在删行或篡改）"

        prefix = line[:line.rfind(" [hash:")].strip()
        recalc_hash = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]
        if recalc_hash != line_hash:
            return False, idx, f"第 {idx} 行内容与哈希校验不符（内容曾被修改）"

        expected_prev = line_hash

    return True, len(lines), f"哈希链验证通过，共 {len(lines)} 条记录无篡改"


def read_records(date_str: Optional[str] = None, limit: int = 100) -> List[str]:
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
