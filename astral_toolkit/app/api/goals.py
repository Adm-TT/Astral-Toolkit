"""目标 Controller（2026-10-30 重构阶段 2）

目标规划的接口：收关键字参数，原样转给 tasks/goals.py 里同名函数。
只做转发，不加校验（校验留在 tasks 里，改行为要 NGU 定）。router 自动收集文件末尾的 ROUTES。
"""

from ...tasks import goals as _t


def goal_finish_preview(**kw):
    return _t.goal_finish_preview(**kw)


def goal_finish(**kw):
    return _t.goal_finish(**kw)


def goals(**kw):
    return _t.goals(**kw)


def goal_add(**kw):
    return _t.goal_add(**kw)


def goal_update(**kw):
    return _t.goal_update(**kw)


def goal_stock_add(**kw):
    return _t.goal_stock_add(**kw)


def goal_prices(**kw):
    return _t.goal_prices(**kw)


ROUTES = {
    "goal_finish_preview": goal_finish_preview,
    "goal_finish": goal_finish,
    "goals": goals,
    "goal_add": goal_add,
    "goal_update": goal_update,
    "goal_stock_add": goal_stock_add,
    "goal_prices": goal_prices,
}
