"""RT-B6 提交 2：命令层 closing 门。

只给「开始 / 写入」类命令用；停止类命令不要调用这里。
没绑定时一律当作没在退出；绑定由 bootstrap 在装配时完成。
"""

from __future__ import annotations

from collections.abc import Callable

_CLOSING: Callable[[], bool] | None = None


def bind_closing(fn: Callable[[], bool], *, replace: bool = False) -> None:
    """由 bootstrap 绑上本 app 的 lifecycle.is_closing。"""
    global _CLOSING
    if _CLOSING is not None and not replace:
        raise RuntimeError(
            "app.lifecycle_gate 已绑定：生产只绑一次；测试用 replace=True 并在用完后恢复"
        )
    _CLOSING = fn


def is_closing() -> bool:
    fn = _CLOSING
    if fn is None:
        return False
    try:
        return bool(fn())
    except Exception:
        return False


def closing_error() -> dict[str, str] | None:
    if is_closing():
        return {"error": "正在退出"}
    return None


__all__ = ["bind_closing", "closing_error", "is_closing"]
