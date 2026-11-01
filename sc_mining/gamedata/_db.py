"""读端：每线程一条只读连接，一次业务操作钉在一个快照上

snapshot() 进入时读清单、打开对应的库；嵌套调用复用最外层的快照，中途发布新版本不影响正在进行的操作。
连接按 (线程, 代号) 缓存，换代时下次进入快照再开新连接、关旧连接。连接对象不出包。"""

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from ._manifest import Manifest, read_manifest
from ._paths import db_path
from ._types import GamedataUnavailable

_tls = threading.local()


class Snapshot:
    """一次业务操作看到的库：版本固定，连接只读"""

    def __init__(self, manifest: Manifest, conn: sqlite3.Connection):
        self.manifest = manifest
        self._conn = conn

    @property
    def data_version(self) -> str:
        return self.manifest.data_version

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        """包内各 topic 用；不对功能模块开放"""
        return self._conn.execute(sql, params).fetchall()


def _open_readonly(m: Manifest) -> sqlite3.Connection:
    p = db_path(m.generation_id)
    if p.name != m.file:
        raise GamedataUnavailable(f"游戏数据清单里的文件名对不上：{m.file}")
    if not p.exists():
        raise GamedataUnavailable(f"游戏数据库文件不见了：{p.name}")
    try:
        conn = sqlite3.connect(
            f"{p.as_uri()}?mode=ro", uri=True, check_same_thread=True
        )
        got = conn.execute(
            "select value from meta where key='generation_id'"
        ).fetchone()
    except sqlite3.Error as e:
        raise GamedataUnavailable(f"打不开游戏数据库 {p.name}：{e}") from e
    if not got or got[0] != m.generation_id:
        conn.close()
        raise GamedataUnavailable(
            f"游戏数据库 {p.name} 里的代号（{got[0] if got else '无'}）和清单（{m.generation_id}）对不上"
        )
    return conn


def _thread_conn(m: Manifest) -> tuple[sqlite3.Connection, Manifest]:
    """本线程对这一代的连接；代号变了就关旧开新。返回 (连接, 实际打开的那份清单)"""
    cur = getattr(_tls, "conn", None)
    gen = getattr(_tls, "gen", None)
    if cur is not None and gen == m.generation_id:
        return cur, m
    if cur is not None:
        try:
            cur.close()
        except sqlite3.Error:
            pass
        _tls.conn = _tls.gen = None
    try:
        conn = _open_readonly(m)
    except GamedataUnavailable:
        # 文件可能刚被换代清理掉：按最新清单再试一次
        m2 = read_manifest()
        if m2 is None or m2 == m:
            raise
        conn = _open_readonly(m2)
        m = m2
    _tls.conn, _tls.gen = conn, m.generation_id
    return conn, m


@contextmanager
def snapshot() -> Iterator[Snapshot]:
    """进入时钉住当前版本；嵌套复用最外层。没有库 / 库坏了抛 GamedataUnavailable，不吞成空结果"""
    outer = getattr(_tls, "snap", None)
    if outer is not None:
        yield outer
        return
    m = read_manifest()
    if m is None:
        raise GamedataUnavailable("游戏数据库还没建好，稍等或先「更新数据」")
    conn, m = _thread_conn(m)
    snap = Snapshot(m, conn)
    _tls.snap = snap
    try:
        yield snap
    finally:
        _tls.snap = None


def current_version() -> str | None:
    """快照内：快照的内容版本；快照外：当前清单的内容版本；还没有库：None"""
    snap = getattr(_tls, "snap", None)
    if snap is not None:
        return snap.data_version
    m = read_manifest()
    return None if m is None else m.data_version


def close_thread_connections() -> None:
    """关掉本线程缓存的连接（换代后、线程收尾时用）；快照进行中不关"""
    if getattr(_tls, "snap", None) is not None:
        return
    cur = getattr(_tls, "conn", None)
    if cur is not None:
        try:
            cur.close()
        except sqlite3.Error:
            pass
    _tls.conn = _tls.gen = None
