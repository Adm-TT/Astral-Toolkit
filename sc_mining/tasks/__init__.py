"""业务任务层（Tasks Layer，借鉴 MAA 架构）

每个游戏功能为一个独立任务，与底层 core、system、trade、mining 平级，
上层 app/api/<领域>.py 的 Controller 把接口转给这里（2026-10-30 重构，原来的 app/services.py 门面已删）。
"""

from . import count, goals, hover, mining, navigation, stock, system, trade

__all__ = [
    "count",
    "goals",
    "hover",
    "mining",
    "navigation",
    "stock",
    "system",
    "trade",
]
