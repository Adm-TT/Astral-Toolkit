"""首次查询前确保库是最新的：后台 warm_up 在跑就等它；然后按源文件核对一次内容版本，过时（升级后安装包换了源文件、
表结构升了版本）就重建

各 topic 查询前调 ensure()。进程里对同一个库目录核对过一次之后直接返回（以后换代由 snapshot() 读清单跟上），
不在每次查询都读源文件算哈希；库目录换了（测试换 paths.DATA）就重新核对。真的建不出库才抛 BuildError。
不另加锁：rebuild_if_needed 自己在数据目录写锁里核对和建库，多个线程同时进来只会建一次；
更新边界 updating() 里（已拿着写锁）再调到这里是同线程重入，不会卡住（审查 2026-11-02 第 1 条）。
代价：每个进程第一次查询一定要拿一次数据目录写锁、读一遍源算哈希（真实数据 50–70 ms）；这时别的线程正在
updating() 里装数据，就要等它装完。mining/data.py 在 import 时就调 apply_live → 这里，升级后库过时会在 import 的线程上
同步重建一次（约 0.5 秒）。"""

import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from ._db import Snapshot

_state: dict = {"done": None}  # 核对过的库目录


def ensure(timeout: float = 30.0) -> None:
    """后台 warm_up 在跑就先等它（最多 timeout 秒）；再 rebuild_if_needed()：源没变、表结构一致、库打得开就直接返回，
    否则同步重建（阻塞，真实数据约 0.5 秒）"""
    from ._paths import gamedata_dir

    where = str(gamedata_dir())
    if _state["done"] == where:
        return
    from . import _state as pkg_state

    t = pkg_state.get("warm_thread")
    if t is not None and t is not threading.current_thread() and t.is_alive():
        t.join(timeout)
    from ._build import rebuild_if_needed

    rebuild_if_needed()
    _state["done"] = where


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
