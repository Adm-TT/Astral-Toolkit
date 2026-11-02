"""按库内容版本缓存一份值：版本变了重算，只留当前版本

各 topic 模块（items.candidates、shops.catalog）和功能模块（stockplaces.places、itemsearch 的索引）以前各写一份
「字典 + 比版本 + 清字典」，批 1 复审第 9 条：抽成一个。两种用法：
- get(snap, build)：开着快照时用，键是 snap.data_version，build(snap) 算值；
- get_for(key, build, key_after=None)：不开快照、自己拿到的版本当键（stockplaces 按 version() 返回值）。键可以是 None
  （还没有库）：照样缓存在 None 下，和以前一样；给了 key_after 就在算完后再取一次键（这次刚建好的库有版本了）。
- identity=True：键按 `is` 比（stockplaces 的二级索引跟着 places() 那份对象走）；缓存持有键的引用，对象活着地址就不会被复用。
线程安全：查和存在锁里，build 在锁外——两个线程同时算同一版本会各算一遍、后写的赢，值一样；和以前的字典写法一样不串行化 build。"""

import threading
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class VersionCache(Generic[T]):
    def __init__(self, identity: bool = False) -> None:
        self._identity = identity
        self._key: object = None
        self._val: T | None = None
        self._has = False
        self._lock = threading.Lock()

    def _same(self, key) -> bool:
        return (self._key is key) if self._identity else (self._key == key)

    def get(self, snap, build: Callable[..., T]) -> T:
        """快照版本当键；命中直接返回，否则 build(snap) 并换成当前版本"""
        return self.get_for(snap.data_version, lambda: build(snap))

    def get_for(
        self, key, build: Callable[[], T], key_after: Callable[[], object] | None = None
    ) -> T:
        """key 当键；命中直接返回，否则 build() 并记成当前版本（只留一份）"""
        with self._lock:
            if self._has and self._same(key):
                return self._val  # type: ignore[return-value]
        val = build()
        if key is None and key_after is not None:
            key = key_after()
        with self._lock:
            self._key, self._val, self._has = key, val, True
        return val

    def peek(self) -> T | None:
        """缓存里现在的值（没有就 None），不触发计算；只给测试看"""
        with self._lock:
            return self._val if self._has else None

    def clear(self) -> None:
        with self._lock:
            self._key, self._val, self._has = None, None, False
