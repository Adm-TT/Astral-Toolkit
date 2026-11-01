"""测试 core/audit.py 证据日志与 core/migration.py 解耦"""

import os
from pathlib import Path
import threading
import time


def test_audit_record_and_read(tmp_path, monkeypatch):
    from sc_mining.core import audit, paths

    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")

    audit.record("ITEM_SEARCH", "F8识图查询", "螺旋 Helix II", tag="READ_SCREEN")
    audit.record(
        "MINING", "发现矿石", {"mass": 5000, "scu": 32}, tag="READ_SCREEN"
    )

    records = audit.read_records()
    assert len(records) == 2
    assert "[READ_SCREEN]" in records[0]
    assert "[ITEM_SEARCH]" in records[0]
    assert "螺旋 Helix II" in records[0]
    assert "[prev:0000000000000000]" in records[0]
    assert "[hash:" in records[0]
    assert "[MINING]" in records[1]
    assert '"mass": 5000' in records[1]


def test_audit_hash_chain_tamper_detection(tmp_path, monkeypatch):
    """测试哈希链校验与防篡改能力：修改字、删行均能精准捕获"""
    from sc_mining.core import audit, paths

    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(paths, "LOGS", logs_dir)
    today = time.strftime("%Y-%m-%d")

    audit.record("SYSTEM", "系统启动", tag="LOCAL_SERVER")
    audit.record("ITEM_SEARCH", "F8识别", "原始物品A", tag="READ_SCREEN")
    audit.record("NAV", "规划路线", "地点B", tag="OFFLINE_CALC")

    # 1. 正常未篡改校验通过
    ok, count, msg = audit.verify_chain(today)
    assert ok is True
    assert count == 3
    assert "通过" in msg

    # 2. 篡改第 2 行内容（把 A 改成 Z）
    log_file = audit.audit_path(today)
    lines = log_file.read_text(encoding="utf-8").splitlines()
    tampered_lines = list(lines)
    tampered_lines[1] = tampered_lines[1].replace("原始物品A", "篡改物品Z")
    log_file.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

    ok, bad_idx, msg = audit.verify_chain(today)
    assert ok is False
    assert bad_idx == 2
    assert "校验不符" in msg or "篡改" in msg

    # 3. 删掉第 2 行（导致第 3 行的 prev 指向断裂）
    tampered_lines_del = [lines[0], lines[2]]
    log_file.write_text("\n".join(tampered_lines_del) + "\n", encoding="utf-8")

    ok, bad_idx, msg = audit.verify_chain(today)
    assert ok is False
    assert bad_idx == 2
    assert "断裂" in msg


def test_audit_cleanup_retention(tmp_path, monkeypatch):
    from sc_mining.core import audit, paths

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths, "LOGS", logs_dir)

    now = time.time()
    # 40 天前的文件
    old_file = logs_dir / "audit_2026-09-20.log"
    old_file.write_text("old audit line\n", encoding="utf-8")
    old_time = now - (40 * 86400)
    os.utime(old_file, (old_time, old_time))

    # 10 天前的文件
    recent_file = logs_dir / "audit_2026-10-22.log"
    recent_file.write_text("recent audit line\n", encoding="utf-8")
    recent_time = now - (10 * 86400)
    os.utime(recent_file, (recent_time, recent_time))

    # 今天的正常记录
    audit.record("SYSTEM", "自检启动", tag="LOCAL_SERVER")

    assert old_file.exists()
    assert recent_file.exists()

    removed = audit.cleanup_retention(days=30)
    assert removed == 1
    assert not old_file.exists()
    assert recent_file.exists()


def test_audit_concurrent_writes(tmp_path, monkeypatch):
    from sc_mining.core import audit, paths

    logs_dir = tmp_path / "logs"
    monkeypatch.setattr(paths, "LOGS", logs_dir)

    def worker(idx):
        for j in range(20):
            audit.record("THREAD", f"并发写入_{idx}_{j}", tag="BENCH")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    records = audit.read_records(limit=200)
    assert len(records) == 100

    # 验证并发写入后的整条哈希链依旧严丝合缝
    today = time.strftime("%Y-%m-%d")
    ok, count, msg = audit.verify_chain(today)
    assert ok is True
    assert count == 100


def test_migration_reexports():
    from sc_mining.core import paths

    assert hasattr(paths, "migrate")
    assert hasattr(paths, "import_inno")
    assert hasattr(paths, "_MOVES")
    assert hasattr(paths, "_DELETE")
    assert callable(paths.migrate)
    assert callable(paths.import_inno)


def test_perfmon_on_demand_start(monkeypatch):
    from sc_mining.core import perfmon

    monkeypatch.setenv("DUBHE_PERFMON", "0")
    m = perfmon.Monitor()
    m.start()
    assert m.thread is None  # 默认不启动常驻线程

    monkeypatch.setenv("DUBHE_PERFMON", "1")
    m2 = perfmon.Monitor()
    # 避免在测试环境真的常驻循环，打桩 _run
    monkeypatch.setattr(m2, "_run", lambda: None)
    m2.start()
    assert m2.thread is not None
    m2.thread.join(timeout=1.0)
