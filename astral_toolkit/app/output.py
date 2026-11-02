"""会话输出的生产实现（设计稿 §2.1）：总线 + 悬浮窗

放在 app/ 里，是因为 runtime/ 不许 import 界面层：会话循环通过构造参数拿 `Output`，
自己不认识 bus / hud_state。行为照 live.py 原来的 `_apply` / `_hud_clear`：
悬浮窗没建起来（`_hud()` 为 None）就什么都不做，别让停止 / 出错收尾半路抛错。
锁内调用，这里只入队 / 写状态。
"""

from . import bus, hud_state


class BusOutput:
    def publish(self, kind, data):
        bus.publish(kind, data)

    def hud_set(self, section, text, rich=None):
        hud = hud_state._hud()
        if hud is not None:
            hud.set(section, text, rich)

    def hud_clear(self, *sections):
        hud = hud_state._hud()
        if hud is not None:
            for section in sections:
                hud.clear(section)

    def note_hud(self, section, text, secs=None):
        if secs is None:
            hud_state._note_hud(section, text)
        else:
            hud_state._note_hud(section, text, secs)

    def log(self, line, tag, level="INFO"):
        bus.runtime_log(line, tag=tag, level=level)
