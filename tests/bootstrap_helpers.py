"""RT-B7 测试夹具：保存 / 恢复全局绑定，测试里显式装配 app。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from astral_toolkit import bootstrap
from astral_toolkit.app import hud_state, lifecycle_gate, ui_stream
from astral_toolkit.core import run_records
from astral_toolkit.infrastructure.platform import capture
from astral_toolkit.navigation import navigate
from astral_toolkit.tasks import count
from astral_toolkit.tasks.navigation import NavDeps

_BINDINGS = (
    (count, ("_count",)),
    (lifecycle_gate, ("_CLOSING",)),
    (ui_stream, ("_SOURCES",)),
    (navigate, ("HINTS",)),
    (capture, ("_overlay_state",)),  # CL-C5：bind_all 接的截图涂黑悬浮窗
    (run_records, ("_ui_sink",)),  # CL-C5：bind_all 接的运行记录推面板
    (
        hud_state,
        ("_cursor_reader", "_key_reader"),
    ),  # 目录迁移收尾：bind_all 接的读光标、读键
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


def nav_deps(
    nav: Any = None,
    pos: Any = None,
    game_events: Any = None,
    results: Any = None,
    halo: Any = None,
    here: Any = None,
) -> NavDeps:
    """测试用的导航后台对象（F 段 B5）：只给用得到的那几样，其余是 None；假对象、None 都能塞，类型检查不拦。
    halo / here 没给就造真的小后台会话（和 bootstrap 一样接 tasks/navigation，2026-11-09）"""
    from astral_toolkit.app.output import BusOutput
    from astral_toolkit.runtime.results import ResultStore

    box: dict[str, NavDeps] = {}
    real_halo, real_here = bootstrap.nav_watches(
        ResultStore(), BusOutput(), lambda: False, lambda: box["deps"]
    )
    box["deps"] = NavDeps(
        nav=nav,
        pos=pos,
        game_events=game_events,
        results=results,
        halo=halo if halo is not None else real_halo,
        here=here if here is not None else real_here,
    )
    return box["deps"]
