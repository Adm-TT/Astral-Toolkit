"""业务任务层（Tasks Layer，借鉴 MAA 架构）

每个游戏功能为一个独立任务，与底层 core、system、trade、mining 平级，
上层 app/services.py 作为门面网关进行统一聚合与 Web API 分发。
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
