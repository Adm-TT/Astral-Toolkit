"""运行记录：落盘、清理、读尾、写入失败不抛"""

import time
from datetime import datetime, timedelta, timezone

from astral_toolkit.core import day_logs, paths, run_records


def test_record_writes_daily_file(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    mirrored = []

    def fake_runtime_log(line, tag="SYS", level="INFO"):
        mirrored.append((line, tag, level))

    monkeypatch.setattr(
        run_records, "_ui_sink", fake_runtime_log
    )  # 面板那条经装配接进来的函数推（CL-C5）

    run_records.record("HOVER", "触发 F8 物品识别", ui_tag="HOVER")
    today = time.strftime("%Y-%m-%d")
    p = logs / f"runrec_{today}.log"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "[HOVER] 触发 F8 物品识别" in text
    assert text.startswith(today + " ")  # 运行记录自己带完整时间，前面不再加时分秒
    assert mirrored and mirrored[0][1] == "HOVER"


def test_cleanup_removes_old_files(monkeypatch, tmp_path):
    """运行记录留 30 天：按文件名里的日期清（day_logs 每天第一次写日志时清）"""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    old_day = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%d")
    keep_day = time.strftime("%Y-%m-%d")
    old = logs / f"runrec_{old_day}.log"
    keep = logs / f"runrec_{keep_day}.log"
    old.write_text("old\n", encoding="utf-8")
    keep.write_text("keep\n", encoding="utf-8")
    others = [  # 名字不完全是 runrec_日期.log 的不删
        logs / "app_log.txt",
        logs / "perf_log.txt",
        logs / "runrec_foo.log",
        logs / f"runrec_{old_day}.log.bak",
    ]
    for f in others:
        f.write_text("x\n", encoding="utf-8")
    n = day_logs.cleanup("runrec", 30)
    assert n == 1
    assert not old.exists()
    assert keep.exists()
    assert all(f.exists() for f in others)


def test_read_tail_limit(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    today = time.strftime("%Y-%m-%d")
    p = logs / f"runrec_{today}.log"
    p.write_text("\n".join(f"line{i}" for i in range(10)) + "\n", encoding="utf-8")
    assert run_records.read_tail(limit=3) == ["line7", "line8", "line9"]


def test_record_swallows_errors(monkeypatch, tmp_path):
    from astral_toolkit.core import day_logs

    def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(day_logs, "path_for", boom)  # 运行记录也经 day_logs 写文件
    run_records.record("SYSTEM", "应被吞掉")  # 不得抛出


def test_path_for_default_today(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    p = run_records.path_for()
    assert p.name.startswith("runrec_")
    assert p.parent == logs


def test_perfmon_on_by_default(monkeypatch):
    """性能记录默认开着（导出日志里的 perf_log.txt 是排查卡顿的唯一数据，2026-11-01 审查）"""
    from astral_toolkit.core import perfmon

    started = []

    class FakeThread:
        def __init__(self, *a, **k):
            started.append(1)

        def start(self):
            pass

    monkeypatch.setattr(perfmon.threading, "Thread", FakeThread)
    perfmon.Monitor().start()
    assert started == [1]


def test_read_recent_fills_from_yesterday(monkeypatch, tmp_path):
    """今天不够 N 条就从昨天的末尾补，按时间先后排（刚过零点按 F10 也带得上前一晚的）"""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    today = time.strftime("%Y-%m-%d")
    yday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    (logs / f"runrec_{yday}.log").write_text(
        "\n".join(f"y{i}" for i in range(10)) + "\n", encoding="utf-8"
    )
    (logs / f"runrec_{today}.log").write_text("t0\nt1\n", encoding="utf-8")
    assert run_records.read_recent(limit=5) == ["y7", "y8", "y9", "t0", "t1"]
    assert run_records.read_recent(limit=2) == ["t0", "t1"]


def test_record_mirrors_through_registered_sink(monkeypatch, tmp_path):
    """面板那条经装配接进来的函数推（core 不 import 界面，CL-C5）；没接就只写文件、不抛"""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    seen = []
    monkeypatch.setattr(
        run_records,
        "_ui_sink",
        lambda line, tag="SYS", level="INFO": seen.append((line, tag, level)),
    )
    run_records.record("NAV", "停止导航")
    run_records.record("NAV", "不推面板", mirror_ui=False)
    assert seen == [("停止导航", "NAV", "INFO")]
    monkeypatch.setattr(run_records, "_ui_sink", None)
    run_records.record("NAV", "再停一次")
    text = (logs / f"runrec_{time.strftime('%Y-%m-%d')}.log").read_text(
        encoding="utf-8"
    )
    assert len(seen) == 1 and "再停一次" in text


def test_bootstrap_wires_runtime_log_as_sink(monkeypatch, tmp_path):
    """装配（bootstrap.bind_all）把面板那条接到 bus.runtime_log；经名字再调，换掉 bus.runtime_log 也照样走到"""
    import astral_toolkit.app.bus as bus
    from astral_toolkit import bootstrap
    from astral_toolkit.core import capture

    monkeypatch.setattr(run_records, "_ui_sink", None)  # 测完还原
    monkeypatch.setattr(capture, "_overlay_state", None)
    bootstrap._bind_core_to_ui()
    seen = []
    monkeypatch.setattr(
        bus,
        "runtime_log",
        lambda line, tag="SYS", level="INFO": seen.append((line, tag, level)),
    )
    monkeypatch.setattr(paths, "LOGS", tmp_path)  # 运行记录写到临时目录，不碰真的日志
    run_records.record(
        "MINING", "x", ui_tag="LIVE", level="WARN"
    )  # 走完整路径：标签、级别也要传到面板
    assert seen == [("x", "LIVE", "WARN")]


def test_record_still_mirrors_when_logs_unwritable(monkeypatch, tmp_path):
    """logs 位置被同名文件占了、建不了目录：不抛错，面板那条照样显示"""
    blocker = tmp_path / "logs"
    blocker.write_text("not a dir", encoding="utf-8")
    monkeypatch.setattr(paths, "LOGS", blocker)
    seen = []
    monkeypatch.setattr(
        run_records,
        "_ui_sink",
        lambda line, tag="SYS", level="INFO": seen.append(line),
    )
    run_records.record("MINING", "采矿助手已暂停", "游戏不在最前面")
    assert seen == ["采矿助手已暂停 | 游戏不在最前面"]


def test_day_logs_write_cap_and_cleanup(monkeypatch, tmp_path):
    """按天的日志文件（core/day_logs：运行记录 runrec、窗口运行日志 runlog、调试细节 debug）：记一行带时分秒；
    不认识的种类、写不进去都不抛；当天写到上限就停，几个线程一起写也只记一次说明；每天第一次写哪一种都把
    各种的过期文件清一遍——只写运行日志，旧调试日志也清掉（关了调试模式以后就是这样）；「留 N 天」含今天"""
    import threading

    from astral_toolkit.core import day_logs

    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)

    def ago(n):
        return time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))

    today = ago(0)
    for name in (
        f"debug_{ago(3)}",
        f"debug_{ago(2)}",
        f"runlog_{ago(10)}",
        f"runrec_{ago(30)}",
        f"runrec_{ago(29)}",
    ):
        (logs / f"{name}.log").write_text("旧\n", encoding="utf-8")
    (logs / f"debug_{ago(9)}.log.bak").write_text(
        "旧\n", encoding="utf-8"
    )  # 名字不完全对的不动
    day_logs.write("runlog", "[INFO] [HOVER] F8 价格与数据同步完成")
    text = (logs / f"runlog_{today}.log").read_text(encoding="utf-8")
    assert (
        "[INFO] [HOVER] F8 价格与数据同步完成" in text and text[2] == ":"
    )  # 前面是时分秒
    left = sorted(p.name for p in logs.iterdir())
    assert (
        f"debug_{ago(3)}.log" not in left and f"debug_{ago(2)}.log" in left
    )  # 调试日志留 3 天（含今天）
    assert (
        f"runrec_{ago(30)}.log" not in left and f"runrec_{ago(29)}.log" in left
    )  # 运行记录留 30 天
    assert f"runlog_{ago(10)}.log" in left and f"debug_{ago(9)}.log.bak" in left
    day_logs.write("没有这种", "x")  # 不认识的种类：不抛、不写
    assert not list(logs.glob("没有这种_*"))
    monkeypatch.setattr(day_logs, "KINDS", {**day_logs.KINDS, "debug": (3, 200)})
    for i in range(3):
        day_logs.write("debug", f"第 {i} 行 " + "字" * 20)
    threads = [
        threading.Thread(
            target=lambda: [day_logs.write("debug", "字" * 30) for _ in range(20)]
        )
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    text = (logs / f"debug_{today}.log").read_text(encoding="utf-8")
    assert text.rstrip().endswith("后面的不记了") and text.count("后面的不记了") == 1
    blocked = tmp_path / "不是目录.txt"
    blocked.write_text("", encoding="utf-8")
    monkeypatch.setattr(paths, "LOGS", blocked)
    day_logs.write("runlog", "写不进去也不抛")


def test_runtime_log_lines_also_kept_in_runlog_file(monkeypatch, tmp_path):
    """窗口运行日志的每一行也记进 logs/runlog_日期.log：窗口那份只留最近 300 行、「清空」只清窗口，
    文件里的关了 AT 也查得到（2026-11-08 老大定日志和窗口分开）"""
    from astral_toolkit.app import bus

    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    bus.runtime_log("F8 价格与数据同步完成: 塔兰导电石", tag="HOVER")
    p = logs / f"runlog_{time.strftime('%Y-%m-%d')}.log"
    assert "[INFO] [HOVER] F8 价格与数据同步完成: 塔兰导电石" in p.read_text(
        encoding="utf-8"
    )
