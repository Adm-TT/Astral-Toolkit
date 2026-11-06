"""视觉识别 Controller（2026-10-30 重构阶段 3，NGU 设计 4.4 节）

F8 物品悬停识别、F6 盘点。
每个接口只是薄转发：收关键字参数、调 tasks 里同名函数、原样返回；校验照旧留在 tasks。
hover_trigger 要 F8 接线：bound(links) 给，bootstrap.routes 接（F 段 B5）。
"""

from .. import task_runner
from ...tasks import count as _count
from ...tasks import hover as _hover


def bound(links):
    """要 F8 物品查询接线（HoverLinks）的接口（F 段 B5）：bootstrap.routes 把这个 app 的 links 交进来"""

    def hover_trigger():
        """手动触发一次 F8 物品悬停识别；F8 热键那次还没识别完就不再起（同一个任务名，见 engines/hover.py）"""
        th = task_runner.run_task_once(
            "hover", _hover.hover_once, links, title="F8物品识别"
        )
        return th if th is not None else {"error": "F8 正在识别中，请稍候"}

    return {"hover_trigger": hover_trigger}


def count_toggle(**kw):
    return _count.count_toggle(**kw)


def count_state(**kw):
    return _count.count_state(**kw)


def count_apply(**kw):
    return _count.count_apply(**kw)


def count_cancel(**kw):
    return _count.count_cancel(**kw)


ROUTES = {
    "count_toggle": count_toggle,
    "count_state": count_state,
    "count_apply": count_apply,
    "count_cancel": count_cancel,
}
