"""最近接受的功能结果（架构稿 §7.1、§7.3）：全程序只有这里保存，别的模块读快照，不改字典

旧会话、旧 epoch、序号不增的结果一律拒收。自带一把小锁，锁内只做字典操作。
"""

import copy
import threading
from dataclasses import dataclass, replace
from typing import Any

MINING_SCAN = "mining.scan"
MINING_SIGNALS = "mining.signals"


@dataclass(frozen=True)
class Entry:
    """一条已接受的结果。value 是 ResultStore 自己的副本，get 每次另给一份，读方怎么改都碰不到存着的那份"""

    value: Any
    session_id: int
    epoch: int
    sequence: int
    captured_mono: float  # 单调钟：算间隔用
    captured_wall: float  # 墙钟：显示和诊断用
    quality: str = "complete"  # complete / partial（面板被挡，只读到一部分）


class ResultStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}
        self._cleared: dict[str, int] = {}  # 每个槽清到哪个会话：这个会话及更早的不再收
        self._cleared_all = -1

    def _floor(self, slot):
        return max(self._cleared_all, self._cleared.get(slot, -1))

    def accept(
        self,
        slot,
        value,
        session,
        epoch,
        seq,
        captured_mono,
        captured_wall,
        quality="complete",
    ) -> bool:
        entry = Entry(
            copy.deepcopy(value),
            session,
            epoch,
            seq,
            captured_mono,
            captured_wall,
            quality,
        )
        with self._lock:
            if session <= self._floor(slot):
                return False
            old = self._entries.get(slot)
            if old is not None and (
                session < old.session_id
                or (
                    session == old.session_id
                    and (epoch < old.epoch or seq <= old.sequence)
                )
            ):
                return False
            self._entries[slot] = entry
            return True

    def get(self, slot) -> Entry | None:
        with self._lock:
            entry = self._entries.get(slot)
        if entry is None:
            return None
        return replace(entry, value=copy.deepcopy(entry.value))

    def clear(self, slot, session):
        """清掉 session 及更早会话的结果，之后它们也不能再写进来；slot=None 清全部。更新的会话不受影响"""
        with self._lock:
            if slot is None:
                self._cleared_all = max(self._cleared_all, session)
                slots = list(self._entries)
            else:
                self._cleared[slot] = max(self._cleared.get(slot, -1), session)
                slots = [slot]
            for s in slots:
                entry = self._entries.get(s)
                if entry is not None and entry.session_id <= session:
                    del self._entries[s]
