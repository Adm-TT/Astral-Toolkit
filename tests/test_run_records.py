"""运行记录：落盘、清理、读尾、写入失败不抛"""

import time
from datetime import datetime, timedelta, timezone

from astral_toolkit.core import paths, run_records


def test_record_writes_daily_file(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    run_records._LAST_CLEANUP_DAY = None
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
    assert mirrored and mirrored[0][1] == "HOVER"


def test_cleanup_removes_old_files(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    old_day = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%d")
    keep_day = time.strftime("%Y-%m-%d")
    old = logs / f"runrec_{old_day}.log"
    keep = logs / f"runrec_{keep_day}.log"
    old.write_text("old\n", encoding="utf-8")
    keep.write_text("keep\n", encoding="utf-8")
    # 把 mtime 也拨到够旧，避免仅靠文件名时区边界误判
    old_ts = time.time() - 31 * 86400
    import os

    os.utime(old, (old_ts, old_ts))
    others = [  # 名字不完全是 runrec_日期.log 的，再旧也不能删
        logs / "app_log.txt",
        logs / "perf_log.txt",
        logs / "runrec_foo.log",
        logs / f"runrec_{old_day}.log.bak",
    ]
    for f in others:
        f.write_text("x\n", encoding="utf-8")
        os.utime(f, (old_ts, old_ts))
    n = run_records.cleanup_retention(days=30)
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
    def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(run_records, "path_for", boom)
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
    """面板那条经界面登记的函数推（core 不 import 界面，CL-C5）；没登记就只写文件、不抛"""
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


def test_bootstrap_wires_runtime_log_as_sink(monkeypatch):
    """装配（bootstrap.bind_all）把面板那条接到 bus.runtime_log；经名字再调，换掉 bus.runtime_log 也照样走到"""
    import astral_toolkit.app.bus as bus
    from astral_toolkit import bootstrap
    from astral_toolkit.core import capture

    monkeypatch.setattr(run_records, "_ui_sink", None)  # 测完还原
    monkeypatch.setattr(capture, "_overlay_state", None)
    bootstrap._bind_core_to_ui()
    seen = []
    monkeypatch.setattr(
        bus, "runtime_log", lambda line, tag="SYS", level="INFO": seen.append(line)
    )
    run_records._ui_sink("一行", tag="SYS", level="INFO")
    assert seen == ["一行"]


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
