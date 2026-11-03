"""会话输出端口（设计稿 v3 §2.1）：op 的种类，以及哪些能在锁里套用

- **锁内类**（只入队 / 写内存）：`bus / hud.set / hud.clear / note`，以及 `shared`（写循环自己的共享结果表，循环自己处理、不经过 Output）
- **锁后类**（写盘）：`log / record`——锁释放后按序执行，且只在锁内检查通过时执行

`Output.apply(op)` 是唯一出口；循环在拿到 op 列表时（锁外）先 `validate_ops`，
未知种类在那里就拒绝，不会到锁里才抛。
"""

from typing import Any, Iterable, Protocol

LOCK_IN_KINDS = frozenset({"bus", "hud.set", "hud.clear", "note", "ui", "shared"})
POST_LOCK_KINDS = frozenset({"log", "record"})
OP_KINDS = LOCK_IN_KINDS | POST_LOCK_KINDS


def validate_ops(ops: Iterable[Any]) -> None:
    """锁外调用：op 种类不认识就立刻拒绝"""
    for op in ops:
        if not isinstance(op, tuple) or not op or op[0] not in OP_KINDS:
            raise ValueError(f"未知输出类型：{op!r}")


class Output(Protocol):
    """一次会话能看到的全部对外输出。锁内类只入队 / 写状态，锁后类才写盘"""

    def apply(self, op: tuple) -> None: ...
