"""运行记录：落盘、清理、读尾、写入失败不抛"""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sc_mining.core import paths, run_records


def test_record_writes_daily_file(monkeypatch, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(paths, "LOGS", logs)
    run_records._LAST_CLEANUP_DAY = None
    mirrored = []

    def fake_runtime_log(line, tag="SYS", level="INFO"):
        mirrored.append((line, tag, level))

    import sc_mining.app.bus as bus

    monkeypatch.setattr(bus, "runtime_log", fake_runtime_log)

    run_records.record("HOVER", "触发 F8 物品识别", ui_tag="HOVER")
    today = time.strftime("%Y-%m-%d")
    p = logs / f"runrec_{today}.log"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "[HOVER] 触发 F8 物品识别" in text
    assert "量子" not in text  # 不写结果样例
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
    n = run_records.cleanup_retention(days=30)
    assert n >= 1
    assert not old.exists()
    assert keep.exists()


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


def test_perfmon_start_off_by_default(monkeypatch):
    from sc_mining.core import perfmon

    monkeypatch.setenv("DUBHE_PERFMON", "0")  # 非 1 即不启动
    m = perfmon.Monitor()
    m.start()
    assert m.thread is None
    monkeypatch.setenv("DUBHE_PERFMON", "1")
    started = []

    class FakeThread:
        def __init__(self, *a, **k):
            started.append(1)

        def start(self):
            pass

    monkeypatch.setattr(perfmon.threading, "Thread", FakeThread)
    m2 = perfmon.Monitor()
    m2.start()
    assert started == [1]
