"""会话输出的生产实现（设计稿 v3 §2.1）：总线 + 悬浮窗 + 运行日志 + 运行记录

放在 app/ 里，是因为 runtime/ 不许 import 界面层和设置：会话循环通过构造参数拿 `Output` /
`RunFlag`，自己不认识 bus / hud_state / settings。悬浮窗没建起来（`_hud()` 为 None）就什么都不做。

锁内类（bus / hud.set / hud.clear / note）只入队 / 写状态；锁后类（log / record）才写盘——
循环保证它们在锁外调用。
"""

from ..runtime.session import RunFlag
from . import bus, hud_state


def _hud_set(section, text, rich=None):
    hud = hud_state._hud()
    if hud is not None:
        hud.set(section, text, rich)


def _note(section, text, secs=None):
    if secs is None:
        hud_state._note_hud(section, text)
    else:
        hud_state._note_hud(section, text, secs)


class BusOutput:
    def apply(self, op):
        kind, *args = op
        if kind == "bus":
            bus.publish(*args)
        elif kind == "hud.set":
            _hud_set(*args)
        elif kind == "hud.clear":
            hud = hud_state._hud()
            if hud is not None:
                for section in args:
                    hud.clear(section)
        elif kind == "note":
            _note(*args)
        elif kind == "log":
            line, tag = args[0], args[1]
            level = args[2] if len(args) > 2 else "INFO"
            bus.runtime_log(line, tag=tag, level=level)
        elif kind == "record":
            from ..core import run_records

            cat, text = args[0], args[1]
            ui_tag = args[2] if len(args) > 2 else ""
            details = args[3] if len(args) > 3 else ""
            level = args[4] if len(args) > 4 else "INFO"
            run_records.record(cat, text, details, level=level, ui_tag=ui_tag or None)
        else:
            raise ValueError(f"未知输出类型：{op!r}")


def setting_run_flag(key: str) -> RunFlag:
    """「循环独占」的设置开关（live_on）：循环给最新期望值，这里只负责写盘"""

    def write(k: str, value: bool) -> None:
        from ..core import settings

        settings.update(**{k: value})

    return RunFlag(key, write)
