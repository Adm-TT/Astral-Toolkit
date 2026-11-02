"""ResultStore：只收新的，读到的是快照（架构稿 §7.1、§7.3）"""

import threading

from sc_mining.runtime.results import MINING_SCAN, MINING_SIGNALS, ResultStore


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
    assert _put(s, "信号", seq=5, slot=MINING_SIGNALS)
    s.clear(MINING_SCAN, 1)
    assert s.get(MINING_SCAN) is None
    e = s.get(MINING_SIGNALS)
    assert e is not None and e.value == "信号"


def test_clear_blocks_that_session_but_not_newer():
    s = ResultStore()
    assert _put(s, "a", session=1)
    assert _put(s, "b", session=1, slot=MINING_SIGNALS)
    s.clear(None, 1)
    assert s.get(MINING_SCAN) is None and s.get(MINING_SIGNALS) is None
    assert not _put(s, "迟到", session=1, seq=9)
    assert _put(s, "新会话", session=2)


def test_late_clear_of_old_session_keeps_newer_result():
    s = ResultStore()
    assert _put(s, "新", session=2)
    s.clear(None, 1)
    e = s.get(MINING_SCAN)
    assert e is not None and e.value == "新"


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
