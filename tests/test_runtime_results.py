"""ResultStore：只收新的，读到的是快照（架构稿 §7.1、§7.3）"""

import threading

from astral_toolkit.runtime.results import MINING_SCAN, MINING_SIGNALS, ResultStore


def _put(store, value, session=1, epoch=1, seq=1, slot=MINING_SCAN, **kw):
    return store.accept(slot, value, session, epoch, seq, 10.0, 1000.0, **kw)


def test_accept_keeps_metadata():
    s = ResultStore()
    assert s.get(MINING_SCAN) is None
    assert _put(s, {"rock": "铜"}, session=2, epoch=3, seq=4, quality="partial")
    e = s.get(MINING_SCAN)
    assert e is not None and e.value == {"rock": "铜"}
    assert (e.session_id, e.epoch, e.sequence, e.quality) == (2, 3, 4, "partial")
    assert (e.captured_mono, e.captured_wall) == (10.0, 1000.0)


def test_rejects_old_session_old_epoch_and_seq_not_increasing():
    s = ResultStore()
    assert _put(s, "b", session=2, epoch=5, seq=5)
    assert not _put(s, "旧会话", session=1, epoch=9, seq=99)
    assert not _put(s, "旧 epoch", session=2, epoch=4, seq=99)
    assert not _put(s, "序号回退", session=2, epoch=5, seq=4)
    assert not _put(s, "序号相同", session=2, epoch=5, seq=5)
    e = s.get(MINING_SCAN)
    assert e is not None and e.value == "b"
    assert _put(s, "新 epoch", session=2, epoch=6, seq=6)
    assert _put(s, "新会话序号可以从头来", session=3, epoch=6, seq=1)


def test_slots_are_independent():
    s = ResultStore()
    assert _put(s, "扫描", seq=5)
    assert not _put(s, "序号回退", seq=4)
    assert _put(s, "信号", seq=4, slot=MINING_SIGNALS)
    e = s.get(MINING_SIGNALS)
    assert e is not None and e.value == "信号"


def test_end_keeps_results_but_blocks_that_session():
    s = ResultStore()
    assert _put(s, "a", session=1)
    assert _put(s, "b", session=1, slot=MINING_SIGNALS)
    s.end(1)
    for slot, want in ((MINING_SCAN, "a"), (MINING_SIGNALS, "b")):
        e = s.get(slot)
        assert e is not None and e.value == want
    assert not _put(s, "迟到", session=1, seq=9)
    assert not _put(s, "更早的会话", session=0, seq=9)
    e = s.get(MINING_SCAN)
    assert e is not None and e.value == "a"


def test_new_session_first_result_ignores_old_seq():
    s = ResultStore()
    assert _put(s, "旧", session=1, epoch=5, seq=50)
    s.end(1)
    assert _put(s, "新", session=2, epoch=1, seq=1)
    e = s.get(MINING_SCAN)
    assert e is not None and e.value == "新"


def test_late_end_of_old_session_keeps_newer_session_writing():
    s = ResultStore()
    assert _put(s, "新", session=2)
    s.end(1)
    assert _put(s, "新 2", session=2, seq=2)


def test_end_is_per_owner():
    """采矿 / 导航 / 盘点的会话号各数各的：一个循环结束的会话，不能把别的循环的会话也拦掉（2026-11-04）"""
    s = ResultStore()
    s.end(3, owner="nav")
    assert _put(s, "采矿第 1 个会话", session=1, owner="live")
    s.end(1, owner="live")
    assert not _put(s, "采矿迟到", session=1, seq=2, owner="live")
    assert _put(s, "采矿第 2 个会话", session=2, seq=1, owner="live")


def test_loops_sharing_one_store_do_not_block_each_other():
    """真会话循环：导航那个循环开停 3 次后，共用同一个 ResultStore 的采矿循环第 1 个会话照样能提交（2026-11-04 复现）"""
    import time

    from astral_toolkit.runtime.session import StopInfo
    from tests.runtime_fakes import FakeWorker, make_loop

    shared = ResultStore()
    nav_loop, nav_w, _ = make_loop(FakeWorker(name="nav"), results=shared)
    for _ in range(3):
        sid = nav_loop.start("目标")
        assert sid is not None and nav_w.started.wait(2)
        nav_w.started.clear()
        nav_loop.request_stop_current(StopInfo("user"))
        assert nav_loop.join(2.0, session_id=sid)
    live_loop, live_w, _ = make_loop(FakeWorker(name="live"), results=shared)
    try:
        sid = live_loop.start(None)
        assert sid == 1 and live_w.ticked.wait(2)
        session = live_w.session
        stamp = live_loop.stamp(session, time.time())
        assert stamp is not None
        assert live_loop.commit(
            session, ("bus", "scan", {}), slot=MINING_SCAN, value={"v": 1}, stamp=stamp
        )
        e = shared.get(MINING_SCAN)
        assert e is not None and e.value == {"v": 1} and e.session_id == 1
    finally:
        live_loop.request_shutdown()
        live_loop.join_all(2.0)


def test_values_are_snapshots():
    s = ResultStore()
    src = {"lots": [{"q": 1}]}
    assert _put(s, src)
    src["lots"][0]["q"] = 2  # 写方后来改了自己那份
    e = s.get(MINING_SCAN)
    assert e is not None and e.value["lots"][0]["q"] == 1
    e.value["lots"][0]["q"] = 3  # 读方改了拿到的那份
    e2 = s.get(MINING_SCAN)
    assert e2 is not None and e2.value["lots"][0]["q"] == 1


def test_concurrent_accept_keeps_highest_seq():
    s = ResultStore()
    n, workers = 200, 8
    gate = threading.Barrier(workers)
    wins = []

    def work(k):
        gate.wait(5)
        for i in range(n):
            if _put(s, k, seq=i * workers + k):
                wins.append(i * workers + k)

    threads = [threading.Thread(target=work, args=(k,)) for k in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    e = s.get(MINING_SCAN)
    assert e is not None and e.sequence == n * workers - 1 == max(wins)
