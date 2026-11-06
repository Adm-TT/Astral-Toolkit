"""位置的不可变值（目录迁移章程 R1）：后台定位线程（runtime/workers/position.py）交给导航、采矿、状态页的东西。

只有定位线程造，别处只读字段；「当前位置」只有定位线程那一份，tasks 里不另存。
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PositionSnapshot:
    """一次锁内复制出来的位置快照；兼容字段供 status / mining / 旧测试过渡用"""

    current: Any
    latest: Any
    read_at: float
    label: Any
    system: Any
    fast: bool
    reader_active: bool
    reader_ok_at: float
    here: Any = None


@dataclass(frozen=True)
class PositionRead:
    """read_now() 的同步读结果：给 _where_now 这类非要马上读一次的地方用"""

    ok_at: float
    info: dict
    global_: tuple | None
