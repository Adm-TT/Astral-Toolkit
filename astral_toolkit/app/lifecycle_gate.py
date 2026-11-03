"""RT-B6 提交 2：命令层 closing 门。

只给「开始 / 写入」类命令用；停止类命令不要调用这里。
取不到 EngineManager / lifecycle 时一律当作没在退出。
"""

from __future__ import annotations


def is_closing() -> bool:
    try:
        from .engines.manager import EngineManager

        return bool(EngineManager.get_instance().lifecycle.is_closing())
    except Exception:
        return False


def closing_error() -> dict[str, str] | None:
    if is_closing():
        return {"error": "正在退出"}
    return None


__all__ = ["closing_error", "is_closing"]
