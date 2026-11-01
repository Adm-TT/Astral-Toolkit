"""首次查询前确保库已建好：库没好就等后台 warm_up；没在跑就自己同步建一次

各 topic 查询前调 ensure()。进程里确认过一次库能用之后直接返回（以后换代由 snapshot() 读清单跟上），
不在每次查询都开一次库校验。真的建不出库才抛 BuildError，不把「还没建好」抛给调用方。"""

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from ._types import GamedataUnavailable

if TYPE_CHECKING:
    from ._db import Snapshot

_state: dict = {"done": False}
_lock = threading.Lock()


def _usable() -> bool:
    from ._build import _db_usable
    from ._manifest import read_manifest

    try:
        m = read_manifest()
    except GamedataUnavailable:
        return False  # 清单坏了：当成没有，下面重建
    return m is not None and _db_usable(m)


def ensure(timeout: float = 30.0) -> None:
    """库能用就返回；后台 warm_up 在跑就等它（最多 timeout 秒）；还不行就同步 rebuild()（阻塞）"""
    if _state["done"]:
        return
    if not _usable():
        from . import _state as pkg_state

        t = pkg_state.get("warm_thread")
        if t is not None and t is not threading.current_thread() and t.is_alive():
            t.join(timeout)
        if not _usable():
            with _lock:  # 多个线程同时走到这里：只建一次
                if not _usable():
                    from ._build import rebuild_if_needed

                    rebuild_if_needed()
    _state["done"] = True


@contextmanager
def use(snap: "Snapshot | None" = None) -> Iterator["Snapshot"]:
    """各 topic 用：传了快照就用它（调用方一次操作钉在一个版本上）；没传就先 ensure() 再开一个"""
    if snap is not None:
        yield snap
        return
    from ._db import snapshot

    ensure()
    with snapshot() as s:
        yield s
