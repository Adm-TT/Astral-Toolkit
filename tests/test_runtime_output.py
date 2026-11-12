"""会话输出端口（设计稿 v3 §2.1）：生产实现把 op 分发到总线 / 悬浮窗 / 运行日志 / 运行记录

证明的是「锁内类只入队」「悬浮窗没建起来时什么都不做」「记录器按 order 记锁状态」，
不碰真悬浮窗、不连总线订阅。
"""

from tests.runtime_fakes import RecordingOutput


class _Hud:
    def __init__(self):
        self.calls = []

    def set(self, section, text, rich=None, *, activity=True):
        self.calls.append(("set", section, text, rich, activity))

    def clear(self, section):
        self.calls.append(("clear", section))


def test_bus_output_dispatches_lock_in_ops(monkeypatch):
    from astral_toolkit.app import bus, hud_state
    from astral_toolkit.app.output import BusOutput

    pub, notes = [], []
    hud = _Hud()
    monkeypatch.setattr(bus, "publish", lambda kind, data: pub.append((kind, data)))
    monkeypatch.setattr(hud_state, "_hud", lambda: hud)
    monkeypatch.setattr(
        hud_state,
        "_note_hud",
        lambda section, text, secs=6: notes.append((section, text, secs)),
    )
    out = BusOutput()
    out.apply(("bus", "live", {"running": True}))
    out.apply(("hud.set", "扫描", "读数"))
    out.apply(("hud.set", "信号", "4,285", {"title": "x"}))
    out.apply(("hud.set", "盘点", "盘点｜站\n矿 ×1", False))
    out.apply(("hud.clear", "信号", "扫描"))
    out.apply(("note", "采矿助手", "已关闭"))
    assert pub == [("live", {"running": True})]
    assert hud.calls == [
        ("set", "扫描", "读数", None, True),
        ("set", "信号", "4,285", {"title": "x"}, True),
        ("set", "盘点", "盘点｜站\n矿 ×1", None, False),
        ("clear", "信号"),
        ("clear", "扫描"),
    ]
    assert notes == [("采矿助手", "已关闭", 6)]


def test_bus_output_dispatches_post_lock_ops(monkeypatch):
    from astral_toolkit.app import bus
    from astral_toolkit.app.output import BusOutput

    logs, records = [], []
    monkeypatch.setattr(
        bus,
        "runtime_log",
        lambda line, tag="SYS", level="INFO": logs.append((line, tag, level)),
    )
    from astral_toolkit.core import run_records

    monkeypatch.setattr(
        run_records,
        "record",
        lambda cat, text, details=None, **kw: records.append((cat, text, details, kw)),
    )
    out = BusOutput()
    out.apply(("log", "一行日志", "LIVE", "WARN"))
    out.apply(("record", "MINING", "采矿助手已暂停", "LIVE", "游戏不在最前面", "WARN"))
    out.apply(("record", "MINING", "采矿助手引擎已停止", "LIVE"))
    assert logs == [("一行日志", "LIVE", "WARN")]
    assert records == [
        (
            "MINING",
            "采矿助手已暂停",
            "游戏不在最前面",
            {"level": "WARN", "ui_tag": "LIVE"},
        ),
        ("MINING", "采矿助手引擎已停止", "", {"level": "INFO", "ui_tag": "LIVE"}),
    ]


def test_bus_output_is_silent_without_hud(monkeypatch):
    """悬浮窗没建起来（_hud() 为 None）：和以前一样什么都不做，也不抛错"""
    from astral_toolkit.app import hud_state
    from astral_toolkit.app.output import BusOutput

    monkeypatch.setattr(hud_state, "_hud", lambda: None)
    out = BusOutput()
    out.apply(("hud.set", "扫描", "读数"))
    out.apply(("hud.clear", "信号", "扫描"))
    out.apply(("note", "采矿助手", "已关闭"))


def test_bus_output_rejects_unknown_op():
    from astral_toolkit.app.output import BusOutput

    out = BusOutput()
    try:
        out.apply(("什么", 1))
    except ValueError as e:
        assert "未知输出类型" in str(e)
    else:
        raise AssertionError("未知 op 应该被拒绝")


def test_setting_run_flag_writes_settings(monkeypatch):
    from astral_toolkit.app.output import setting_run_flag
    from astral_toolkit.core import settings

    saved = []
    monkeypatch.setattr(settings, "update", lambda **kw: saved.append(kw))
    flag = setting_run_flag("live_on")
    flag.write(flag.key, True)
    flag.write(flag.key, False)
    assert saved == [{"live_on": True}, {"live_on": False}]


def test_recording_output_marks_whether_loop_lock_is_held():
    """记录器用 loop.lock_held_by_me() 记锁状态，不用 Lock.locked()"""
    from tests.runtime_fakes import make_loop

    class _Out(RecordingOutput):
        pass

    out = _Out()
    loop, _, _ = make_loop(output=out)
    out.apply(("bus", "x", {}))
    with loop._lock:
        out.apply(("hud.clear", "信号"))
    assert [r.op[0] for r in out.ops] == ["bus", "hud.clear"]
    assert [r.locked for r in out.ops] == [False, True]
    assert out.published("x") == [("x", {})]
