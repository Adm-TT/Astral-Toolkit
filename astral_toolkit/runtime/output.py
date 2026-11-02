"""会话输出端口（设计稿 §2.1、§4.4）：会话循环只认这个接口，不 import 界面层（架构稿 §4.3）

把 live.py 原来 `_apply` 的四种输出收成五个方法：总线、悬浮窗分区、悬浮窗短提示、运行日志。
锁内调用，实现里只做入队 / 写状态，不做文件、网络、截图（同 RT-B3 的锁内规矩）。
生产实现是 `astral_toolkit/app/output.py` 的 `BusOutput`（runtime/ 不许 import app/）；
测试用记录器在 `tests/runtime_fakes.py`。
"""

from typing import Any, Protocol


class Output(Protocol):
    """一次会话能看到的全部对外输出"""

    def publish(self, kind: str, data: Any) -> None:
        """发一条总线消息（SSE 事件名和 payload 一字不改）"""

    def hud_set(self, section: str, text: str, rich: Any = None) -> None:
        """写悬浮窗一个分区；rich 是采矿助手那种有层次的内容"""

    def hud_clear(self, *sections: str) -> None:
        """擦掉悬浮窗的几块；悬浮窗没建起来就什么都不做"""

    def note_hud(self, section: str, text: str, secs: float | None = None) -> None:
        """悬浮窗上一条短提示（secs 秒后自己收起，不给就用默认）"""

    def log(self, line: str, tag: str, level: str = "INFO") -> None:
        """运行日志（窗口日志面板）"""
