"""装配出来的 app（DesktopApp）和 build 认的 overrides 键"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..runtime.lifecycle import (
    Lifecycle,
)
from ..runtime.results import ResultStore


@dataclass(frozen=True)
class DesktopApp:
    """一次装配出来的全部后台对象；state 只放本 app 自己的少量可变状态。"""

    results: ResultStore
    output: Any
    lifecycle: Lifecycle
    live: Any
    nav: Any
    count: Any
    pos: Any
    hotkeys: Any
    hotkey_commands: Any
    game_events: Any
    logwatch: Any
    cam_filter: Any
    steady: Any
    hover_links: Any
    nav_deps: Any
    state: dict = field(default_factory=dict, compare=False)


_ALLOWED_OVERRIDES = frozenset(
    {
        "results",
        "output",
        "lifecycle",
        "clock",
        "foreground",
        "grab",
        "cursor_pos",
        "count_worker",
    }
)
