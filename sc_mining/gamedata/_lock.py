"""数据目录写锁：建库、发布、改源文件都要先拿它；跨进程靠文件锁（写法同 app/instance.py），进程内靠 RLock

文件锁由操作系统在进程退出时释放，所以“锁文件存在”不代表有人占着——判断占用只看能不能锁上。"""

import os
import threading
import time
from contextlib import contextmanager
from typing import IO, Iterator

from ._paths import lock_path
from ._types import GamedataError

_rlock = threading.RLock()
_depth = 0
_file: IO[bytes] | None = None


def _try_lock_file(f: IO[bytes]) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_file(f: IO[bytes]) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def write_lock(timeout: float = 30.0) -> Iterator[None]:
    """拿数据目录写锁；同线程可重入。timeout 秒内拿不到抛 GamedataError"""
    global _depth, _file
    with _rlock:
        if _depth == 0:
            p = lock_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            f = open(p, "a+b")
            f.seek(0)
            deadline = time.monotonic() + timeout
            while not _try_lock_file(f):
                if time.monotonic() >= deadline:
                    f.close()
                    raise GamedataError("游戏数据目录正被另一个 AT 使用，稍后再试")
                time.sleep(0.05)
            _file = f
        _depth += 1
        try:
            yield
        finally:
            _depth -= 1
            if _depth == 0 and _file is not None:
                _unlock_file(_file)
                _file.close()
                _file = None


def other_instance_running() -> bool:
    """有没有别的 AT 开着：试锁 userdata/instance.lock（和 app/instance.py 同一个文件）。能锁上就立刻放开，返回 False"""
    import sys

    from ..core import paths

    inst = sys.modules.get("sc_mining.app.instance")
    if inst is not None and getattr(
        getattr(inst, "_single_instance", None), "lock", None
    ):
        return False  # 这个进程就是那个唯一的 AT：锁在自己手里，不会有别的 AT
    p = paths.USER / "instance.lock"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        f = open(p, "a+b")
    except OSError:
        return True  # 连文件都打不开，当成有人在用，宁可不清理
    try:
        f.seek(0)
        if _try_lock_file(f):
            _unlock_file(f)
            return False
        return True
    finally:
        f.close()
