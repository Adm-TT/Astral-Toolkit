"""路标、折跃光环与导航业务任务模块（Task: Navigation & Halo）

专职处理：
1. 地点搜索、最近地点推荐、站点识别与导航路线规划；
2. 实时/手动定位模式切换、雷达信号重命名；
3. 路标增删改查、剪贴板坐标导入与 /showlocation 实时抓取；
4. 小行星带（Aaron Halo）航线计算、断开距离监控与 HUD 联动核对；
5. 原矿扫描记录及导航追溯。

2026-11-19：按段落拆成 base / where / search / marks / ore_records / belt 几个文件，这里是总入口，外面照旧从 tasks.navigation 取名字。
测试往这个总入口上换名字（monkeypatch）时，会同步到各个文件里（见文件末尾 _NavModule，和 tasks/system 一个办法）。
"""

import sys
import time

from ...app import bus
from ...app.hud_state import _hud
from ...app.hud_state import _note_hud
from ..system.settings import hotkey_conflicts
from . import (
    base as _m_base,
    belt as _m_belt,
    marks as _m_marks,
    ore_records as _m_ore,
    place_patches as _m_patches,
    search as _m_search,
    where as _m_where,
)
from .base import (
    AREA_MAX_AGE,
    AT_TARGET,
    HALO_WAIT,
    HERE_WAIT,
    LEFT_START,
    NEAR_MIN,
    NavDeps,
    POS_FRESH,
    QT_SPEED,
    ROUTE_NEAR,
    _AREA,
    _HALO,
    _HERE,
    _MARKING,
    _WHERE,
    _hud_set,
    _no_home,
    _places,
    _pos_current,
    _wp_log,
    fix_key_hint,
    nav_log,
    settings_key,
)
from .where import _area_now, _where_now
from .search import (
    QT_DIRECT_MSG,
    _place_row,
    _start_nav,
    nav_mode,
    nav_plan,
    nav_refresh,
    nav_search,
    nav_site,
    nav_start,
    nav_stop,
    sig_name,
    sig_names,
)
from .marks import (
    _here_state,
    _here_step,
    _hints_near,
    _on_body,
    _save_here,
    _saved,
    _start_here_watch,
    _surface_limit,
    _wait_showloc,
    mark_here,
    waypoint_add,
    waypoint_delete,
    waypoint_from_text,
    waypoint_preview,
    waypoints,
)
from .ore_records import (
    _coord_desc,
    ore_delete,
    ore_go,
    ore_list,
    ore_record,
    ore_restore,
)
from .belt import (
    _halo_jump,
    _halo_state,
    _halo_step,
    _start_near,
    fix_here,
    halo_check,
    halo_options,
    halo_pin,
    halo_routes,
    halo_unpin,
)
from .place_patches import (
    patch_delete,
    patch_export,
    patch_import,
    patch_list,
    patch_toggle,
)

__all__ = [
    "patch_export",
    "patch_import",
    "patch_list",
    "patch_toggle",
    "patch_delete",
    "_start_nav",
    "_places",
    "POS_FRESH",
    "_WHERE",
    "_AREA",
    "AREA_MAX_AGE",
    "HERE_WAIT",
    "_HERE",
    "_HALO",
    "QT_SPEED",
    "NavDeps",
    "_place_row",
    "nav_search",
    "nav_site",
    "nav_plan",
    "nav_start",
    "nav_mode",
    "sig_name",
    "sig_names",
    "nav_stop",
    "nav_refresh",
    "waypoints",
    "waypoint_add",
    "waypoint_preview",
    "waypoint_from_text",
    "_where_now",
    "_area_now",
    "fix_key_hint",
    "settings_key",
    "_wp_log",
    "_save_here",
    "_saved",
    "_start_here_watch",
    "_here_state",
    "_here_step",
    "mark_here",
    "_coord_desc",
    "ore_record",
    "ore_list",
    "ore_delete",
    "ore_restore",
    "ore_go",
    "halo_options",
    "halo_routes",
    "halo_pin",
    "halo_unpin",
    "_halo_state",
    "_halo_step",
    "HALO_WAIT",
    "halo_check",
    "fix_here",
    "_surface_limit",
    "waypoint_delete",
    "_MARKING",
    "_hud",
    "_hud_set",
    "_note_hud",
    "_pos_current",
    "nav_log",
    "time",
    "AT_TARGET",
    "LEFT_START",
    "NEAR_MIN",
    "QT_DIRECT_MSG",
    "ROUTE_NEAR",
    "_halo_jump",
    "_hints_near",
    "_no_home",
    "_on_body",
    "_start_near",
    "_wait_showloc",
    "bus",
    "hotkey_conflicts",
]


# ---------------------------------------------------------------- 总入口上换名字时同步到各文件（测试的 monkeypatch 靠它）
class _NavModule(sys.modules[__name__].__class__):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for sub in (
            _m_base,
            _m_where,
            _m_search,
            _m_marks,
            _m_ore,
            _m_belt,
            _m_patches,
        ):
            if hasattr(sub, name):
                setattr(sub, name, value)


sys.modules[__name__].__class__ = _NavModule
