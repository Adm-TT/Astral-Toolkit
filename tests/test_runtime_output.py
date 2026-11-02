"""会话输出端口（设计稿 §2.1）：生产实现包总线 + 悬浮窗，测试用记录器

证明的是「悬浮窗没建起来时什么都不做」和「四种输出各自到对的地方」，不碰真悬浮窗、不连总线订阅。
"""

import threading

from tests.runtime_fakes import RecordingOutput


class _Hud:
    def __init__(self):
        self.calls = []

    def set(self, section, text, rich=None):
        self.calls.append(("set", section, text, rich))

    def clear(self, section):
        self.calls.append(("clear", section))


def _patch_bus(monkeypatch, pub, logs):
    from astral_toolkit.app import bus

    monkeypatch.setattr(bus, "publish", lambda kind, data: pub.append((kind, data)))
    monkeypatch.setattr(
        bus,
        "runtime_log",
        lambda line, tag="SYS", level="INFO": logs.append((line, tag, level)),
    )


def test_bus_output_publishes_and_logs_to_bus(monkeypatch):
    from astral_toolkit.app.output import BusOutput

    pub, logs = [], []
    _patch_bus(monkeypatch, pub, logs)
    out = BusOutput()
    out.publish("live", {"running": True})
    out.log("采矿助手已暂停", "LIVE", "WARN")
    assert pub == [("live", {"running": True})]
    assert logs == [("采矿助手已暂停", "LIVE", "WARN")]


def test_bus_output_writes_hud_sections_and_notes(monkeypatch):
    from astral_toolkit.app import hud_state
    from astral_toolkit.app.output import BusOutput

    hud, notes = _Hud(), []
    monkeypatch.setattr(hud_state, "_hud", lambda: hud)
    monkeypatch.setattr(
        hud_state,
        "_note_hud",
        lambda section, text, secs=6: notes.append((section, text, secs)),
    )
    out = BusOutput()
    out.hud_set("扫描", "读数")
    out.hud_set("信号", "4,285", {"title": "x"})
    out.hud_clear("信号", "扫描")
    out.note_hud("采矿助手", "已关闭")
    out.note_hud("采矿助手", "已关闭", 3)
    assert hud.calls == [
        ("set", "扫描", "读数", None),
        ("set", "信号", "4,285", {"title": "x"}),
        ("clear", "信号"),
        ("clear", "扫描"),
    ]
    assert notes == [
        ("采矿助手", "已关闭", 6),
        ("采矿助手", "已关闭", 3),
    ]


def test_bus_output_is_silent_without_hud(monkeypatch):
    """悬浮窗没建起来（_hud() 为 None）：和以前一样什么都不做，也不抛错"""
    from astral_toolkit.app import hud_state
    from astral_toolkit.app.output import BusOutput

    monkeypatch.setattr(hud_state, "_hud", lambda: None)
    out = BusOutput()
    out.hud_set("扫描", "读数")
    out.hud_clear("信号", "扫描", "矿袋")
    out.note_hud("采矿助手", "已关闭")


def test_recording_output_marks_whether_loop_lock_is_held():
    out = RecordingOutput()
    lock = threading.Lock()
    out.bind(lock)
    out.publish("live", {"running": True})
    with lock:
        out.hud_set("扫描", "x")
    assert [c.op for c in out.calls] == ["publish", "hud_set"]
    assert [c.locked for c in out.calls] == [False, True]
    assert out.live_events() == [{"running": True}]
