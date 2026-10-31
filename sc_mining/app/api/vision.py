"""视觉识别 Controller（2026-10-30 重构阶段 3，NGU 设计 4.4 节）

F8 物品悬停识别、F6 盘点。
每个接口只是薄转发：收关键字参数、调 tasks 里同名函数、原样返回；校验照旧留在 tasks。
hover_trigger 原来定义在 services.py，搬到这里（services 里那份阶段 4 删）。
"""
from .. import bus
from ...tasks import count as _count
from ...tasks import hover as _hover


def hover_trigger():
    """手动触发一次 F8 物品悬停识别；F8 热键那次还没识别完就不再起（同一个任务名，见 engines/hover.py）"""
    th = bus.run_task_once("hover", _hover.hover_once, title="F8物品识别")
    return th if th is not None else {"error": "F8 正在识别中，请稍候"}


def count_toggle(**kw):
    return _count.count_toggle(**kw)


def count_state(**kw):
    return _count.count_state(**kw)


def count_apply(**kw):
    return _count.count_apply(**kw)


def count_cancel(**kw):
    return _count.count_cancel(**kw)


ROUTES = {
    "hover_trigger": hover_trigger,
    "count_toggle": count_toggle,
    "count_state": count_state,
    "count_apply": count_apply,
    "count_cancel": count_cancel,
}
