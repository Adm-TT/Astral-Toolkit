"""导航业务共用的底子：依赖（NavDeps）、共享状态和常量、悬浮窗写字、读位置、导航日志、热键名（2026-11-19 从 tasks/navigation.py 按段落拆出来，只搬位置、代码没改）"""

import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from typing import Protocol

from ...app.hud_state import _hud
from ..system.settings import hotkey_conflicts


class _NavLike(Protocol):
    target: Any
    space_mode: bool

    @property
    def session(self) -> Any: ...

    def start(
        self,
        target: Any,
        target_row: Any = None,
        space_mode: bool | None = None,
    ) -> Any: ...

    def stop(self) -> Any: ...

    def refresh(self) -> None: ...

    def add_fix(self, g: Any, clip: Any = None, session: int | None = None) -> Any: ...


class _PosLike(Protocol):
    def snapshot(self) -> Any: ...

    def read_now(self, force: bool = True) -> Any: ...

    def hints(self, max_age: float = 5.0) -> dict[str, str]: ...

    def set_demand(self, key: str, until: float, fps: float | None = None) -> None: ...


class _GameEventsLike(Protocol):
    arrived_at: float


class _ResultsLike(Protocol):
    def get(self, slot: str) -> Any: ...


class _WatchLike(Protocol):
    """导航的小后台会话（runtime/workers/nav_watch.NavWatch）：halo 核对、here 等坐标"""

    def start(self, payload: Any = None) -> Any: ...

    def running(self) -> bool: ...


# ---------------------------------------------------------------- 基础状态与常量
_places = {}


try:
    from ...update.data_pack import CACHE_HOOKS as _CACHE_HOOKS

    _CACHE_HOOKS.append(_places.clear)
except Exception:
    pass


POS_FRESH = 120  # 「用当前位置」：位置最多是多少秒前读到的


_WHERE = {"t": 0.0, "v": None, "tried": 0.0}


_AREA = {"key": None, "v": None}


AREA_MAX_AGE = (
    10  # 位置超过 10 秒没更新就不判断产矿区（不过滤），刚跳跃、读不到时宁可不过滤
)


HERE_WAIT = 90  # 点「用当前位置新建」后等 /showlocation 坐标多少秒


# 等着的路标名和期限；盯剪贴板等坐标的是 deps.here 会话（2026-11-09 起不再自己起线程）
_HERE = {"name": None, "until": 0.0}


_MARKING = {
    "on": False
}  # 热键记路标正在等 /showlocation（只有它会用「新建」填的名字；一键定位、原矿记录不会）


_HALO = {
    "plan": None,
    "sess": 0,
    "seen": None,
    "last": None,
    "ends": None,  # 方案起点、目标的坐标（Gm）：挂上时查好，每秒核对不再碰星图库
    "near": 0.1,  # 离起点多近（Gm）算还在起点：挂上时按路线算
    "jumped": False,  # 挂上以后测到过起跳
    "first": False,  # 这一跳是从起点跳的、断开后还没核对过：下一次带「多飞 / 少飞」的核对在导航日志里标出来
    "logged": None,  # 导航日志上一次记的核对：一样的不再记
    "lock": threading.Lock(),
}


HALO_WAIT = 0.3  # 秒：挂着方案时 halo 会话每轮之间等多久


QT_SPEED = 50_000  # 米/秒：比这快就是在量子跳跃（普通飞行最快一千多米每秒）


LEFT_START = (
    0.1  # Gm：离方案起点这么近算还在起点（普通飞行一千多米每秒，飞 0.1 Gm 要一天多）
)


NEAR_MIN = 0.01  # Gm：离起点多近算在起点，最少这么多（起点本身就在要去的带里时，按路线算出来是 0）


STOP_S = 3.0  # 秒：一跳里读数慢下来连续这么久才算断开停下；游戏卡一下、掉进带里加载石头卡一两秒都不算（审查 2026-11-08）


ROUTE_NEAR = 0.2  # Gm：离方案「起点→目标」那条直线超过这么远，就是跳去了别处，不说多飞 / 少飞（审查 2026-11-08）


AT_TARGET = 0.05  # Gm：离目标这么近就是到了目标（比如挖完去卖矿），不说；安全窗口一直延到目标跟前的路线


# （去 CRU-L2 的第 8、9 带）按窗口出口离目标多远算，窗口里照样说（审查 2026-11-08）
# ---------------------------------------------------------------- 依赖与辅助
# 2026-10-30 重构阶段 2：悬浮窗从 app.hud_state 拿，引擎和最近结果（ResultStore）由 bootstrap 造好的 NavDeps 当参数传进来（F 段 B5），
# 不再经 services 转发、出错也不再回头找 services 兜底。接口由 app/api/navigation.py 的 ROUTES 注册，不再用 api 装饰器。


def _hud_set(section, text):
    """悬浮窗写一段字；悬浮窗建不起来（_hud() 是 None）就不写，小行星带、一键定位照常跑（以前直接
    _hud().set 会抛 AttributeError，待做原第 342 行）"""
    h = _hud()
    if h is not None:
        h.set(section, text)


def _hud_clear(section):
    """悬浮窗收起一段字；悬浮窗建不起来就不管"""
    h = _hud()
    if h is not None:
        h.clear(section)


@dataclass(frozen=True)
class NavDeps:
    """导航任务要的后台对象（F 段 B5）：导航引擎、位置服务、游戏事件、最近结果，
    还有两个小后台会话（2026-11-09）：halo（挂着小行星带方案时核对）、here（「用当前位置新建」等坐标）。
    bootstrap 造一份，交给接口层（routes）和热键 / 采矿读屏，不经模块级绑定"""

    nav: _NavLike
    pos: _PosLike
    game_events: _GameEventsLike
    results: _ResultsLike
    halo: _WatchLike
    here: _WatchLike


def _pos_current(deps: NavDeps) -> Any:
    pos = deps.pos
    snap = getattr(pos, "snapshot", None)
    if callable(snap):
        return getattr(snap(), "current", (0.0, None, None))
    return getattr(pos, "current", (0.0, None, None))


def _pos_latest(deps: NavDeps) -> Any:
    pos = deps.pos
    snap = getattr(pos, "snapshot", None)
    if callable(snap):
        return getattr(snap(), "latest", (0.0, None, None))
    return getattr(pos, "latest", (0.0, None, None))


# ---------------------------------------------------------------- 热键提示
def fix_key_hint():
    """导航面板上的定位提示：热键能用就说按哪个键，被占用了就说自己输 /showlocation"""
    key = settings_key("fix_key", "")
    bad = [w for w in hotkey_conflicts() if "一键定位" in w]
    if bad:
        return key, bad[0]
    return key, (
        f"一键定位：按 {key} 后在聊天框输入 /showlocation"
        if key
        else "在聊天框输入 /showlocation 定位"
    )


def settings_key(k, default):
    try:
        from ...core import settings

        return settings.load().get(k) or default
    except Exception:
        return default


# ---------------------------------------------------------------- 路标保存与快捷记录
# nav_log.txt 会打进问题反馈包上传：用户目录（C:\Users\<用户名>）换成 ~（审查 2026-10-31）
_HOME_RE = re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+[^\\/:*?\"'<>|\r\n]+", re.I)


def _no_home(msg):
    return _HOME_RE.sub("~", str(msg))


_WP_LOCK = threading.Lock()  # 导航日志：看量子的线程和接口线程会同时追加，不锁会互相盖掉（审查 2026-11-08 第三轮）


def _wp_log(msg):
    try:
        from ...core import paths

        with _WP_LOCK, open(paths.log("nav_log.txt"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%F %T')} 路标 {_no_home(msg)}\n")
    except OSError:
        pass


def nav_log(here, info, view):
    """导航时每次算出新位置记一行（logs/nav_log.txt），方向不对时用来查是哪一步的问题
    （目录迁移 R2 从 app/engines/nav 搬来，和 _wp_log 写同一个文件；bootstrap 接进导航线程的 NavLinks.trace）"""
    try:
        from ...core import paths

        p = paths.log("nav_log.txt")
        loc = info.get("local")
        line = (
            f"{time.strftime('%H:%M:%S')} 来源={here.get('src', '?')} 核对={info.get('local_ok')} "
            f"游戏局部={tuple(round(v, 4) for v in loc) if loc else None} "
            f"用的=({here['x']:.4f}, {here['y']:.4f}, {here['z']:.4f}) "
            f"方位={view.get('raw_bearing', 0):.1f}° 显示={view.get('bearing', 0):.0f}° 距离={view.get('surface', 0):.2f}km"
        )
        # 和 _wp_log 写同一个文件：截短、追加都拿同一把锁（审查 2026-11-08）
        with _WP_LOCK:
            if p.exists() and p.stat().st_size > 300_000:
                p.write_text(
                    "\n".join(p.read_text(encoding="utf-8").splitlines()[-1000:])
                    + "\n",
                    encoding="utf-8",
                )
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
