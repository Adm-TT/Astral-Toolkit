"""RT-B7 测试夹具：保存 / 恢复全局绑定，测试里显式装配 app。"""

from __future__ import annotations

from contextlib import contextmanager

from astral_toolkit import bootstrap
from astral_toolkit.app import lifecycle_gate, ui_stream
from astral_toolkit.navigation import navigate
from astral_toolkit.tasks import count, navigation
from astral_toolkit.tasks.system import common as system_common

_BINDINGS = (
    (navigation, ("_nav", "_pos", "_game_events", "_results")),
    (count, ("_count",)),
    (system_common, ("_status", "_start")),
    (lifecycle_gate, ("_CLOSING",)),
    (ui_stream, ("_SOURCES",)),
    (navigate, ("HINTS",)),
)


def snapshot_bindings() -> dict:
    """记下这些模块全局的当前值；None 表示原来没绑定。"""
    saved = {}
    for module, names in _BINDINGS:
        for name in names:
            saved[(module.__name__, name)] = (module, name, getattr(module, name))
    return saved


def restore_bindings(saved: dict) -> None:
    """原样写回；不经 bind，也不检查当前值。"""
    for module, name, value in saved.values():
        setattr(module, name, value)


@contextmanager
def bind_for_test(module, *args, **kwargs):
    """临时换一个模块的绑定，退出时恢复所有全局绑定。"""
    saved = snapshot_bindings()
    try:
        module.bind(*args, replace=True, **kwargs)
        yield module
    finally:
        restore_bindings(saved)


@contextmanager
def app_for_test(**overrides):
    """建一个 test app、绑上全局，退出时 shutdown 并恢复进来前的绑定。"""
    saved = snapshot_bindings()
    app = None
    try:
        app = bootstrap.build("test", overrides=overrides or None)
        bootstrap.bind_all(app, replace=True)
        yield app
    finally:
        if app is not None:
            try:
                bootstrap.shutdown(app, budget=2.0)
            except Exception:
                pass
        restore_bindings(saved)
