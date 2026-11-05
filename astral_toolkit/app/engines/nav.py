"""导航引擎：实时方位 / 路标 / 站内导航（_Nav）、读数平滑（_Steady）、摄像头过滤（_CamFilter）、游戏事件（_GameEvents）

2026-10-28 从 app/services.py 原样剪出来（逻辑没改）。2026-10-30 重构阶段 4 删了 services.py，
NV-B3 / NV-B4（2026-11-05）：HUD 记号（_NavMarker）、三个视图和导航日志都搬进本模块；以前经 _T 动态去 tasks/mining、
tasks/navigation 取的东西，现在由 bootstrap 造对象时传进来（_NavMarker 的依赖、NavLinks），本模块不再动态导入 tasks。

RT-B5b：导航线程 / 停止 / 提交边界 / 重试全部交给 runtime/session.py 的 SessionLoop；
_Nav 只保留对外兼容外壳，_NavWorker 只写一轮业务，会话可变状态放在 _NavCtx。
锁序（有 tests/test_nav_session.py 守着）：
- 不持有 fix_lock / marker_lock 时才调用 loop.*；
- loop 锁内只调 Worker 的纯函数钩子 start_ops / stop_ops；
- fix_lock 内不调 PositionService、不读设置、不碰剪贴板 / OCR、不画记号、不 bus.publish；
- marker_lock 只串行画记号与 stop 清记号，不和 loop 锁嵌套。
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import bus
from ..output import BusOutput
from ..presenters import nav as _present_nav
from ..presenters.nav import activity as _nav_activity
from ...navigation import marker as _marker
from ...navigation import views as _views
from ...runtime.results import ResultStore
from ...runtime.session import (
    RunState,
    Session,
    SessionLoop,
    StopAttempt,
    StopInfo,
    Tick,
)

WIN = sys.platform == "win32"

LIVE_STALE = 3.0  # 右上角多少秒没读到才算读不到（这时才用玩家自己输的 /showlocation）
DI_HELP = "未检测到右上角位置信息：在游戏中按 ~ 打开控制台，输入 r_DisplayInfo 2 后回车"
_BASE_FPS = 5  # 导航帧数取不到时按 5（设置默认值）
CLIP_EVERY = 0.3  # 地面导航没有新读数时多久看一次剪贴板（以前每 3 圈一次、一圈 0.1 秒；帧数调高后一圈变短，改按时间，NV-B5）
NAV_LOG_EVERY = 0.2  # 导航日志最多每 0.2 秒一行（帧数调高后 300 KB 不至于十几秒就写满；5 帧时和以前一样）


def _base_fps() -> int:
    return _BASE_FPS


@dataclass(frozen=True)
class NavLinks:
    """导航引擎要用的导航任务那边的东西（NV-B4：以前经 _T("navigation") 动态去 tasks 取，现在由 bootstrap 传进来）"""

    log: Callable[
        [str], Any
    ]  # 路标日志一行（tasks.navigation._wp_log，写 nav_log.txt）
    fix_key_hint: Callable[[], tuple[str, str]]  # 一键定位提示：(热键, 提示文字)
    place_row: Callable[
        [Any], Any
    ]  # 目标行（tasks.navigation._place_row，同时把目标登记进地点表）
    setting: Callable[
        [str, Any], Any
    ]  # 读一项设置（tasks.navigation.settings_key：空值也按没设）
    # 导航帧数（设置页「导航帧数」；bootstrap 传进来时已限在 5–30）
    fps: Callable[[], int] = _base_fps


def _quiet_log(msg: str) -> None:
    return None


# 只有测试直接造引擎、没传 links 时用：不写日志、不读设置、不登记地点
QUIET_LINKS = NavLinks(
    log=_quiet_log,
    fix_key_hint=lambda: ("", "在聊天框输入 /showlocation 定位"),
    place_row=lambda target: None,
    setting=lambda key, default: default,
)


def _links_fps(links: NavLinks) -> int:
    """导航帧数；取不到、不像数字按 5"""
    try:
        return max(1, int(links.fps()))
    except Exception:
        return _BASE_FPS


def nav_tip(on, last_ok, now, has_shown, di_help):
    """导航时右上角读位置的说法 → (窗口状态, 悬浮窗末尾那行)。窗口和悬浮窗说法一致（审查 2026-10-30）：
    读得到：实时；8–30 秒前读到过而且有上次结果：标「暂停更新」，不冒充实时；刚开始还没结果：等待；
    更久没读到 / 从没读到：教开调试信息"""
    if on:
        return "右上角调试信息：实时识别位置", ""
    if last_ok and now - last_ok < 30:
        if has_shown:
            return (
                "右上角位置暂时认不出，显示的是上次结果",
                "\n位置暂停更新，以上是上次结果",
            )
        return "等待右上角位置信息…", ""
    return (
        di_help + "（或在聊天框输入 /showlocation）",
        "\n读不到位置：控制台输入 r_DisplayInfo 2，或聊天框输入 /showlocation",
    )


def _space_view(g, target, data):
    """导航去太空路标：没有南北，给直线距离、先量子跳到哪、对准哪个标记偏几度"""
    return _present_nav.space_view(_views.space_facts(g, target, data), g, target, data)


def _station_view(g, target, data, when=None, prev=None, info=None):
    """拉格朗日点 / 跳跃点空间站里走路：距离按米、按站自己的朝向分上下；转向靠机头那一行和屏幕记号"""
    return _present_nav.station_view(
        _views.station_facts(g, target, data, when, prev, info),
        g,
        target,
        data,
        when,
    )


def _nav_view(here, target, data, steady=None, prev=None):
    return _present_nav.ground_view(
        _views.ground_facts(here, target, data, prev), here, target, data, steady
    )


def nav_log(here, info, view):
    """导航时每次算出新位置记一行（logs/nav_log.txt），方向不对时用来查是哪一步的问题"""
    try:
        from ...core import paths

        p = paths.log("nav_log.txt")
        if p.exists() and p.stat().st_size > 300_000:
            p.write_text(
                "\n".join(p.read_text(encoding="utf-8").splitlines()[-1000:]) + "\n",
                encoding="utf-8",
            )
        loc = info.get("local")
        line = (
            f"{time.strftime('%H:%M:%S')} 来源={here.get('src', '?')} 核对={info.get('local_ok')} "
            f"游戏局部={tuple(round(v, 4) for v in loc) if loc else None} "
            f"用的=({here['x']:.4f}, {here['y']:.4f}, {here['z']:.4f}) "
            f"方位={view.get('raw_bearing', 0):.1f}° 显示={view.get('bearing', 0):.0f}° 距离={view.get('surface', 0):.2f}km"
        )
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class _Steady:
    """显示的方位角防抖：真实方位角变了 2° 以上才换显示，免得数字在 359/000/001 之间来回跳"""

    DEADBAND = 2.0

    def __init__(self) -> None:
        self.shown: Any = None

    def __call__(self, brg):
        if (
            self.shown is None
            or abs((brg - self.shown + 180) % 360 - 180) >= self.DEADBAND
        ):
            self.shown = brg
        return self.shown


class _CamFilter:
    """CamDir 防误读：OCR 偶尔把负号漏掉（-142 认成 142），指的方向就完全反了。
    跟上一次比：某个角度绝对值差不多、正负号却反了（而且不小），多半是漏了负号，这次不用"""

    AGREE = 3  # 被拒的读数连着这么多帧都差不多：是真转过去了（俯仰 +30 → -30 停住不动），收下

    def __init__(self, log: Callable[[str], Any] | None = None) -> None:
        self.last: Any = None
        self.held: Any = None
        self.count: int = 0
        self._log = log if log is not None else _quiet_log

    def check(self, cam, fast=False):
        """fast = 这帧是字模认的：字模把丢了的负号写成 #，那一行已经作废，镜像读数可以信。
        识别引擎认的帧不放行：镜头不动时它每帧都可能错得一样，连着几帧一致也不说明是真的（复审 2026-10-31）"""
        if not cam:
            return None
        prev, self.last = self.last, cam
        # 绕过 ±180°（比如偏航 178 → -178）是真的转过去了，不算
        if prev and any(
            10 < abs(a) < 170 and a * b < 0 and abs(abs(a) - abs(b)) <= 4
            for a, b in zip(cam, prev)
        ):
            same = self.held and all(abs(a - b) <= 4 for a, b in zip(cam, self.held))
            self.held, self.count = (
                cam,
                (self.count + 1 if same and fast else 1 if fast else 0),
            )
            if self.count < self.AGREE:
                self.last = prev  # 不信这次，下次还跟上一次比
                return None
        if (
            self.count >= self.AGREE
        ):  # 以前拒了一次就永远跟旧值比，姿态真变成镜像会一直卡住（审查 2026-10-31）
            self._log(
                f"镜头朝向：连着 {self.AGREE} 帧字模读数一致，收下 {cam}（之前是 {prev}）"
            )
        self.held, self.count = None, 0
        return cam


MARKER_STALE = 4.0  # 右上角多少秒没读到就收起导航记号（城里偶尔几次读不到，1.5 秒就收会一直闪，2026-10-27 实测）
CAM_HOLD = 1.0  # 这一帧坐标有、镜头方向没读出：这么久以内读到的镜头方向接着用（按它自己的读取时间算，不当成新的）


def marker_diag(why):
    """导航记号收起 / 重新出来时记一行进 logs/di_log.txt（和读右上角的诊断放一起对时间，老大 11-03 实测「记号还会消失」）"""
    try:
        from ...core import paths

        with paths.log("di_log.txt").open("a", encoding="utf-8") as f:
            f.write(
                f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} "
                f"记号 {'收起：' + why if why else '显示'}\n"
            )
    except Exception:
        pass


class _NavMarker:
    """导航 HUD 记号（NV-B3 从 tasks/mining 搬来，逻辑没改）：按位置、镜头和设置决定画不画，画时把投影交给悬浮窗。"""

    def __init__(
        self,
        positions: Any,
        *,
        mining_running: Callable[[], bool],
        foreground: Callable[[], bool],
        game_area: Callable[[], dict[str, Any]],
        last_fov: Callable[[], Any],
        settings: Callable[[], dict[str, Any]],
        hud: Callable[[], Any],
        diag: Callable[[Any], None],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._pos = positions
        self._mining_running = mining_running
        self._foreground = foreground
        self._game_area = game_area
        self._last_fov = last_fov
        self._settings = settings
        self._hud = hud
        self._diag = diag
        self._clock = clock if clock is not None else time.time
        self.cfg: dict[str, Any] = {"on": True, "at": 0.0}
        self.cam_last: dict[str, Any] = {"t": 0.0, "cam": None}
        self.why: Any = None

    def enabled(self):
        """设置里的 nav_marker（两秒读一次，导航每 0.1 秒问一次）"""
        if self._clock() - self.cfg["at"] > 2:
            self.cfg["at"] = self._clock()
            try:
                self.cfg["on"] = self._settings().get("nav_marker", True) is not False
            except Exception:
                self.cfg["on"] = True
        return self.cfg["on"]

    def tick(self, target, data, state, shown, ref=None):
        """导航记号（2026-10-27）：每圈先判断该不该显示（还没算出位置、到了、跨星系、1.5 秒没读到、切出游戏、玩家关了、
        采矿助手开着——记号窗口读屏时会被涂黑，会挡住扫描面板和雷达信号），不该显示就收起；
        该显示且右上角有新截图（停着只转镜头也算）就按镜头朝向和视角重算位置。返回这次画的截图时间，收起了返回 None"""
        from ...navigation import navigate as n

        t, g, info = self._pos.snapshot().current
        h = state.get("here")
        # 镜头方向来自读屏，没有类型；走到投影那一步时一定有值
        cam: Any = _marker.camera_hold(
            (info or {}).get("camdir"), t, self.cam_last, CAM_HOLD
        )
        try:
            fg = self._foreground()
        except Exception:
            fg = True
        why = _marker.hidden_reason(
            h,
            g,
            cam,
            t,
            now=self._clock,
            stale=MARKER_STALE,
            foreground=fg,
            mining_running=self._mining_running,
            enabled=self.enabled,
        )
        if why != self.why:
            self.why = why
            self._diag(why)
        if why:
            if shown is not None:
                self._draw(None)
            return None
        if t == shown:
            return shown
        try:
            a = self._game_area()
            fov = _marker.pick_fov(info.get("fov"), self._last_fov)
            tg = n.target_global(target, data, info.get("t"), ref)
            pr = n.project(
                g,
                cam,
                fov,
                tg,
                a["width"],
                a["height"],
                vertical=self._setting("fov_axis", "v") != "h",
            )
            label = _present_nav.marker_label(pr["dist"])
            model = _present_nav.marker_model(a, pr, label)
            self._draw(model)
            return t
        except Exception:
            self._draw(None)
            return None

    def _setting(self, key, default=None):
        try:
            return self._settings().get(key, default)
        except Exception:
            return default

    def _draw(self, data):
        try:
            self._hud().marker(data)
        except Exception:  # 测试里的假悬浮窗没有这个接口
            pass

    def clear(self):
        self._draw(None)


class _NoMarker:
    """没传记号（只有测试直接造 _Nav / _NavWorker）：不画、不碰悬浮窗"""

    def tick(self, target, data, state, shown, ref=None):
        return None

    def clear(self):
        return None


@dataclass(frozen=True)
class NavPayload:
    """开导航那一刻定死的东西：目标、目标行、实时/手动模式。整个会话不变"""

    target: Any
    target_row: Any
    space_mode: bool


@dataclass(frozen=True)
class NavStart:
    """_Nav.start 的兼容返回值"""

    session_id: int | None
    status: str  # started / busy_stopping / closing / rejected
    message: str = ""


@dataclass
class _FixRequest:
    session_id: int
    g: tuple[Any, ...]
    clip: Any
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    claimed: bool = False  # 已被 tick 拿去处理（_fixq_lock 下改）
    cancelled: bool = False  # 调用方等超时放弃了，tick 不再应用（_fixq_lock 下改）


class _NavCtx:
    """一个导航会话的一次尝试的全部可变状态：旧线程停在自己的 Ctx 里，碰不到新会话"""

    session_id: int
    payload: NavPayload
    data: dict[str, Any] | None
    here: Any
    ref: Any
    fixes: list[tuple[float, tuple[Any, ...]]]
    clip_seen: str | None
    last_view: dict[str, Any] | None
    steady: _Steady
    seen: float
    seen_cur: float
    prev_goal: Any
    plan: dict[str, Any]
    mk_seen: Any
    state: dict[str, Any]
    shown: str
    first: bool
    arrived_once: bool
    clip_at: float
    log_at: float
    fps: int | None

    def __init__(self, session_id: int, payload: NavPayload) -> None:
        self.session_id = session_id
        self.payload = payload
        self.data = None
        self.here = None
        self.ref = None
        self.fixes = []
        self.clip_seen = None
        self.last_view = None
        self.steady = _Steady()
        self.seen = 0.0
        self.seen_cur = (
            0.0  # 坐标没变的读数（原地转机头）处理到哪一帧：转向提示要跟着镜头重算
        )
        self.last_ok = 0.0
        self.prev_goal = None
        self.plan = {}
        self.mk_seen = None
        self.state = {}
        self.shown = ""
        self.first = True
        self.arrived_once = False
        self.clip_at = float("-inf")  # 上次看剪贴板（tick 的 now）
        self.log_at = float("-inf")  # 上次写导航日志（tick 的 now）
        self.fps = None  # 已经告诉位置服务的帧数


class _NavWorker:
    """导航 Worker：只做一轮位置判断 / 定位 / 视图 / nav_tip，输出统一走 loop.commit"""

    name: str = "nav"
    log_tag: str = "NAV"
    display_name: str = "导航"
    activity_kind: str = "nav"
    retries: int = 3
    idle_close: float | None = None
    stale_after: dict[str, float] = {}
    needs_foreground: bool = False
    restart_while_stopping: bool = False
    loop: Any = None

    def __init__(
        self,
        positions: Any,
        cam_filter: Any,
        marker_lock: Any,
        results: ResultStore | None = None,
        marker: Any = None,
        links: NavLinks | None = None,
    ) -> None:
        self._pos = positions
        self._cam_filter = cam_filter
        self._marker_lock = marker_lock
        self._results = results if results is not None else ResultStore()
        self._marker = marker if marker is not None else _NoMarker()
        self._links = links if links is not None else QUIET_LINKS
        self._fixq: list[_FixRequest] = []
        self._fixq_lock = threading.Lock()
        self._ctx_lock = threading.Lock()
        self._ctx: _NavCtx | None = None

    def _require_loop(self) -> Any:
        loop = self.loop
        if loop is None:
            raise RuntimeError("导航循环尚未绑定")
        return loop

    def _ground_wait(self) -> float:
        """地面导航每圈等多久：读数间隔的一半，最长 0.1 秒（5 帧时和以前一样 0.1）"""
        return min(0.1, 0.5 / _links_fps(self._links))

    @property
    def pause_wait(self) -> float:
        return 0.1

    def hotkey(self) -> str:
        return ""

    def start_ops(self, session: Session) -> list[tuple[Any, ...]]:
        payload = session.payload
        if not isinstance(payload, NavPayload):
            return []
        view = {
            "state": "starting",
            "quality": "partial",
            "here": None,
            "status": None,
            "stale_since": None,
        }
        return [("ui", "ui.activity", _nav_activity(session.id, payload, view))]

    def stop_ops(
        self, session: Session | None, info: StopInfo
    ) -> list[tuple[Any, ...]]:
        """纯函数：只读 info / 不可变 payload，不取 fix_lock、不读设置"""
        if session is None or info.reason == "user":
            return [("hud.clear", "导航"), ("bus", "nav", {"active": False})]
        if info.reason == "error":
            payload = getattr(session, "payload", None)
            row = payload.target_row if isinstance(payload, NavPayload) else None
            error = info.error or ""
            return [
                (
                    "bus",
                    "nav",
                    {
                        "active": True,
                        "target": row,
                        "here": None,
                        "msgs": [],
                        "status": f"导航出错：{error}（重新开始导航试试）",
                        "help": "",
                    },
                ),
                ("hud.set", "导航", f"导航出错：{error}"),
            ]
        return []

    def setup(self, session: Session) -> _NavCtx:
        payload = session.payload
        if not isinstance(payload, NavPayload):
            raise RuntimeError("导航会话缺少 payload")
        ctx = _NavCtx(session.id, payload)
        if not payload.space_mode:
            from ...navigation import navigate as n

            ctx.data = n.load()
        with self._ctx_lock:
            self._ctx = ctx
        return ctx

    def teardown(self, session: Session, ctx: Any) -> None:
        with self._ctx_lock:
            if self._ctx is ctx:
                self._ctx = None

    def fixes_snapshot(self) -> list[Any]:
        with self._ctx_lock:
            ctx = self._ctx
            if ctx is None:
                return []
            return list(ctx.fixes)

    def enqueue_fix(
        self, session_id: int, g: tuple[Any, ...], clip: Any
    ) -> _FixRequest:
        req = _FixRequest(int(session_id), tuple(g), clip)
        with self._fixq_lock:
            self._fixq.append(req)
        return req

    def cancel_fix(self, req: _FixRequest) -> bool:
        """调用方等超时：还没被 tick 拿走就撤回（返回 True）；已在处理中返回 False，调用方接着等结果"""
        with self._fixq_lock:
            if req.claimed:
                return False
            req.cancelled = True
            if req in self._fixq:
                self._fixq.remove(req)
            return True

    def _claim(self, req: _FixRequest) -> bool:
        with self._fixq_lock:
            if req.cancelled:
                return False
            req.claimed = True
            return True

    def _take_fix_requests(self) -> list[_FixRequest]:
        with self._fixq_lock:
            reqs, self._fixq = self._fixq, []
        return reqs

    def _fail_pending(self) -> None:
        reqs = self._take_fix_requests()
        for req in reqs:
            if not req.done.is_set():
                req.result = None
                req.done.set()

    def tick(self, session: Session, ctx: Any, now: float) -> Tick:
        if ctx.first:
            ok = self._first_tick(session, ctx)
            if not ok:
                return Tick(self._ground_wait() if not ctx.payload.space_mode else 0.3)
            ctx.first = False
        self._process_fix_requests(session, ctx)
        if ctx.payload.space_mode:
            return self._space_tick(session, ctx, now)
        return self._ground_tick(session, ctx, now)

    def _first_tick(self, session: Session, ctx: _NavCtx) -> bool:
        from ...navigation import navigate as n

        target = ctx.payload.target
        if ctx.payload.space_mode:
            key, hint = self._links.fix_key_hint()
            state = {
                "active": True,
                "target": ctx.payload.target_row,
                "here": None,
                "msgs": [],
                "status": hint,
                "help": "",
            }
            ctx.state = state
            activity = _nav_activity(
                session.id,
                ctx.payload,
                {
                    "state": "starting",
                    "quality": "partial",
                    "here": None,
                    "status": hint,
                    "stale_since": None,
                },
            )
            hud = f"→ {n.label(target)}\n" + (
                f"按 {key} 后输入 /showlocation 定位"
                if hint.startswith("一键定位")
                else hint
            )
            ok = self._require_loop().commit(
                session,
                ("bus", "nav", state),
                ("hud.set", "导航", hud),
                ("ui", "ui.activity", activity),
            )
            if ok:
                ctx.clip_seen = n.read_clipboard()
            return bool(ok)
        head = f"→ {n.label(target)}"
        state = {
            "active": True,
            "target": ctx.payload.target_row,
            "status": "等待右上角位置信息…",
            "help": DI_HELP,
            "msgs": [],
            "here": None,
        }
        ctx.state = state
        activity = _nav_activity(
            session.id,
            ctx.payload,
            {
                "state": "starting",
                "quality": "partial",
                "here": None,
                "status": state["status"],
                "stale_since": None,
            },
        )
        ok = self._require_loop().commit(
            session,
            ("bus", "nav", state),
            ("hud.set", "导航", f"{head}\n等待位置信息…"),
            ("ui", "ui.activity", activity),
        )
        if not ok:
            return False
        snap = self._pos.snapshot()
        ctx.seen = float(snap.latest[0] or 0.0)
        ctx.seen_cur = float(snap.current[0] or 0.0)
        ctx.steady = _Steady()
        self._pos.request_read_now()
        ctx.clip_seen = n.read_clipboard()
        # 第一圈地面导航照旧马上看一次剪贴板（以前是 tick_count 清零）
        ctx.clip_at = float("-inf")
        ctx.mk_seen = None
        return True

    def _process_fix_requests(self, session: Session, ctx: _NavCtx) -> None:
        for req in self._take_fix_requests():
            if req.session_id != session.id or not session.alive():
                req.result = None
                req.done.set()
                continue
            if not ctx.payload.space_mode:
                req.result = None
                req.done.set()
                continue
            if not self._claim(
                req
            ):  # 调用方已放弃：不应用，免得返回「无效」后导航又更新
                req.done.set()
                continue
            try:
                req.result = self._apply_fix(session, ctx, req.g, req.clip)
            except Exception as e:  # noqa: BLE001 —— 一次定位出错只算这次无效，不能拖垮整个导航（旧 add_fix 也只回给调用方）
                print(f"导航一键定位出错：{e!r}")
                req.result = None
            finally:
                req.done.set()

    def _space_tick(self, session: Session, ctx: _NavCtx, now: float) -> Tick:
        from ...navigation import navigate as n

        clip = n.read_clipboard()
        g = n.parse_clip(clip)
        if g and clip != ctx.clip_seen:
            self._apply_fix(session, ctx, g, clip)
        return Tick(0.3)

    def _apply_fix(
        self, session: Session, ctx: _NavCtx, g: Any, clip: Any = None
    ) -> Any:
        """F9 / 剪贴板拿到一次 /showlocation：只在这里算，随后同一批 loop.commit 发旧通道"""
        from ...navigation import navigate as n

        if not ctx.payload.space_mode:
            return None
        target = ctx.payload.target
        if not target:
            return None
        g = tuple(g)
        dup = (clip is not None and clip == ctx.clip_seen) or (
            bool(ctx.fixes) and ctx.fixes[-1][1] == g
        )
        if clip is not None:
            ctx.clip_seen = clip
        if dup:
            return ctx.last_view
        ctx.fixes = (ctx.fixes + [(time.time(), g)])[-10:]
        fixes = list(ctx.fixes)
        key, hint = self._links.fix_key_hint()
        f = n.fix_guide(
            fixes,
            target,
            prev_arrived=bool(ctx.last_view and ctx.last_view.get("arrived")),
        )
        text = n.fix_text(f, key)
        view: dict[str, Any] = {
            "space": True,
            "fix": True,
            "text": text,
            "direct": f.get("direct"),
            "arrived": f.get("arrived"),
            "city": f.get("city"),
            "close": f.get("close"),
            "deviation": f.get("deviation"),
            "delta": f.get("delta"),
            "eta": f.get("eta"),
            "qt": f.get("qt"),
            "aim": f.get("aim"),
            "fixes": len(fixes),
        }
        if not f["same_system"]:
            view["far"] = text
        ctx.last_view = view
        state = {
            "active": True,
            "target": ctx.payload.target_row,
            "here": view,
            "msgs": [],
            "status": f"一键定位：按 {key}（或输入 /showlocation）更新"
            if hint.startswith("一键定位")
            else hint,
            "help": "",
            "at": time.strftime("%H:%M:%S"),
        }
        activity = _nav_activity(
            session.id,
            ctx.payload,
            {
                "state": "running",
                "quality": "partial",
                "here": view,
                "status": state["status"],
                "stale_since": None,
            },
        )
        ok = self._require_loop().commit(
            session,
            ("bus", "nav", state),
            ("hud.set", "导航", f"→ {n.label(target)}\n{text}"),
            ("ui", "ui.activity", activity),
        )
        if not ok:
            return None
        try:
            self._links.log(
                "太空导航定位："
                + f"{tuple(round(v / 1000, 3) for v in g)} km"
                + " → "
                + text.splitlines()[0]
            )
        except Exception:
            pass
        return view

    def _ground_tick(self, session: Session, ctx: _NavCtx, now: float) -> Tick:
        from ...navigation import navigate as n

        fps = _links_fps(self._links)
        if fps != ctx.fps:  # 帧数变了（设置页改了）：告诉位置服务按新的读
            ctx.fps = fps
            try:
                self._pos.set_demand("nav", float("inf"), fps=fps)
            except Exception:
                pass
        data: Any = ctx.data
        target = ctx.payload.target
        if data is None:
            data = ctx.data = n.load()
        snap = self._pos.snapshot()
        fresh = False
        by_clip = False
        got: tuple[Any, dict[str, Any], bool] | None = None
        still = False
        cur = snap.current
        if (
            ctx.state.get("here") is None
            and cur[1]
            and time.time() - cur[0] < LIVE_STALE
        ):
            got = (cur[1], cur[2] or {}, False)
        elif snap.latest[0] != ctx.seen and snap.latest[1]:
            ctx.seen, g_di, info = snap.latest
            got = (g_di, info or {}, False)
        elif snap.current[1] and (snap.current[0] or 0.0) > max(ctx.seen, ctx.seen_cur):
            # 坐标没变（停着转机头）但读到了新一帧：镜头方向变了，转向提示要重算，不能冻在上一帧（负责人 2026-11-03 截图）
            ctx.seen_cur, g_di, info = snap.current
            got = (g_di, info or {}, False)
            still = True
        elif now - ctx.clip_at >= CLIP_EVERY:
            ctx.clip_at = now
            clip = n.read_clipboard()
            g_clip = n.parse_clip(clip)
            live_ok = time.time() - snap.read_at < LIVE_STALE
            if g_clip and clip != ctx.clip_seen and not live_ok:
                got = (tuple(g_clip), {"t": time.time()}, True)
            if g_clip:
                ctx.clip_seen = clip
        here = ctx.here
        ref = ctx.ref
        if got is not None:
            g_di, info, by_clip = got
            when = info.get("t")
            if by_clip:
                here = n.locate(g_di, when=when, data=data, use_offset=False)
            else:
                here = n.locate(
                    g_di,
                    when=when,
                    data=data,
                    local=info.get("local"),
                    zone=info.get("zone"),
                    local_ok=info.get("local_ok"),
                )
            ref = (g_di, here, when)
            inner_zone = str(info.get("inner_zone") or "")
            if n.is_city(target) and n.is_space(target):
                goal, steps = n.station_leg(
                    tuple(v / 1000 for v in g_di),
                    target,
                    ctx.plan,
                    inner_zone,
                )
                ctx.prev_goal = goal
                ctx.state["here"] = _station_view(
                    g_di,
                    goal,
                    data,
                    when,
                    prev=ctx.state.get("here"),
                    info=info,
                )
                if goal is not target:
                    ctx.state["here"]["arrived"] = False
                if steps and not ctx.state["here"].get("far"):
                    ctx.state["here"]["steps"] = steps
                else:
                    ctx.state["here"].pop("steps", None)
                ctx.shown = str(
                    ctx.state["here"].get("far")
                    or n.station_text(
                        g_di,
                        goal,
                        data,
                        when,
                        ctx.state["here"].get("arrived"),
                    )
                )
                if ctx.state["here"].get("steps"):
                    ctx.shown += "\n" + "\n".join(str(s) for s in steps)
            elif n.is_space(target):
                ctx.state["here"] = _space_view(g_di, target, data)
                ctx.shown = str(n.space_text(g_di, target, data))
            else:
                if n.is_city(target):
                    goal, steps = n.city_leg(here, target, ctx.plan, inner_zone)
                else:
                    goal, steps = target, []
                if goal is not target and ctx.prev_goal is not goal:
                    ctx.steady = _Steady()
                ctx.prev_goal = goal
                ctx.state["here"] = _nav_view(
                    here, goal, data, ctx.steady, prev=ctx.state.get("here")
                )
                if goal is not target:
                    ctx.state["here"]["arrived"] = False
                if steps:
                    ctx.state["here"]["steps"] = steps
                else:
                    ctx.state["here"].pop("steps", None)
                near = n.near_text(here, data)
                ctx.shown = str(
                    n._short(
                        here,
                        goal,
                        ctx.state["here"].get("bearing"),
                        ctx.state["here"].get("arrived"),
                    )
                ) + (f"\n{near}" if near else "")
                if steps:
                    ctx.shown += "\n" + "\n".join(str(s) for s in steps)
                # 停着不动每帧都来，日志只记坐标变了的；最多每 0.2 秒一行
                if not still and now - ctx.log_at >= NAV_LOG_EVERY:
                    ctx.log_at = now
                    nav_log(here, info, ctx.state["here"])
            cam = self._cam_filter.check(
                info.get("camdir"), fast=bool(info.get("fast"))
            )
            close = bool(
                ctx.state["here"].get("city")
                and (ctx.state["here"].get("direct_m") or 0) < n.CITY_NEAR_M
            )
            if (
                cam
                and not ctx.state["here"].get("arrived")
                and not ctx.state["here"].get("far")
                and not close
            ):
                try:
                    st = n.steer(
                        g_di,
                        cam,
                        n.target_global(
                            ctx.prev_goal or target, data, info.get("t"), ref
                        ),
                    )
                    stx = n.steer_text(st, walk=n.is_city(target))
                    ctx.state["here"]["steer"] = {**dict(st), "text": stx}
                    ctx.shown = str(stx) + "\n" + ctx.shown
                except Exception:
                    pass
            fresh = True
            ctx.last_ok = time.time()
        head = f"→ {n.label(target)}"
        stat_text, tip = nav_tip(
            snap.reader_active,
            snap.reader_ok_at,
            time.time(),
            bool(ctx.shown),
            DI_HELP,
        )
        pub: dict[str, Any] | None = None
        if fresh or ctx.state.get("status") != stat_text:
            ctx.state["status"] = stat_text
            if fresh:
                ctx.state["at"] = time.strftime("%H:%M:%S")
            pub = dict(ctx.state)
        ops: list[tuple[Any, ...]] = []
        if pub is not None:
            ops.append(("bus", "nav", pub))
            act_state = "running" if fresh else "stale"
            stale_since = None
            if act_state == "stale":
                stale_since = snap.reader_ok_at or ctx.last_ok or None
            act_view = {
                "state": act_state,
                "quality": "partial" if (not fresh or by_clip) else "complete",
                "here": pub.get("here"),
                "status": pub.get("status"),
                "stale_since": stale_since,
            }
            ops.append(
                ("ui", "ui.activity", _nav_activity(session.id, ctx.payload, act_view))
            )
        ops.append(("hud.set", "导航", f"{head}\n{ctx.shown or '等待位置信息…'}" + tip))
        ok = self._require_loop().commit(session, *ops)
        if not ok:
            return Tick(self._ground_wait())
        if fresh:
            ctx.here = here
            ctx.ref = ref
        ctx.mk_seen = self._marker_after_commit(
            session,
            ctx,
            ctx.prev_goal or target,
            data,
            ctx.state,
            ref if fresh else ctx.ref,
        )
        return Tick(self._ground_wait())

    def _marker_after_commit(
        self, session: Session, ctx: Any, target: Any, data: Any, state: Any, ref: Any
    ) -> Any:
        """记号只在 loop.commit 成功之后画；marker_lock 内不再碰 loop，只再用 cancel 核一次会话"""
        if not session.alive():
            return ctx.mk_seen
        with self._marker_lock:
            if not session.alive():
                return ctx.mk_seen
            try:
                return self._marker.tick(target, data, state, ctx.mk_seen, ref)
            except Exception:
                return ctx.mk_seen

    def on_pause(self, session: Session, ctx: Any) -> list[tuple[Any, ...]]:
        return []

    def on_resume(
        self, session: Session, ctx: Any, gap: float
    ) -> list[tuple[Any, ...]]:
        return []

    def on_stale(
        self, session: Session, ctx: Any, channel: str
    ) -> list[tuple[Any, ...]]:
        return []

    def on_error(self, session: Session, ctx: Any, exc: BaseException) -> None:
        import traceback

        msg = f"导航出错：{exc!r}"
        try:
            self._links.log(msg + "\n" + traceback.format_exc())
        except Exception:
            pass
        print(msg)

    def before_retry(
        self, session: Session, ctx: Any, error: str
    ) -> list[tuple[Any, ...]]:
        return []

    def finish(
        self, session: Session, ctx: Any, info: StopInfo
    ) -> list[tuple[Any, ...]]:
        self._fail_pending()
        try:
            self._pos.set_demand("nav", 0)
        except Exception:
            pass
        return []


class _StopProxy:
    """`stop_ev` 代理（RT-B7 删）：set() = 按 shutdown 停当前会话；is_set() = 当前没有运行中的会话"""

    def __init__(self, loop: Any) -> None:
        self._loop = loop

    def set(self) -> None:
        self._loop.request_shutdown()

    def is_set(self) -> bool:
        return not self._loop.running()

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def clear(self) -> None:
        pass


class _Nav:
    """导航跟踪：对外兼容外壳。真正的线程 / 停止 / 重试 / 提交边界在 SessionLoop + _NavWorker"""

    def __init__(
        self,
        positions: Any,
        cam_filter: Any,
        steady: _Steady | None,
        results: ResultStore | None = None,
        output: Any = None,
        *,
        clock: Callable[[], float] | None = None,
        closing: Callable[[], bool] | None = None,
        join_timeout: float = 2.0,
        marker: Any = None,
        links: NavLinks | None = None,
        _loop_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.fix_lock = threading.Lock()
        self.marker_lock = threading.Lock()
        self.target: Any = None
        self.space_mode: bool = False
        self._positions = positions
        self._marker = marker if marker is not None else _NoMarker()
        self._links = links if links is not None else QUIET_LINKS
        self._stop_ev_override: Any = None
        self._closing = closing if closing is not None else (lambda: False)
        results = results if results is not None else ResultStore()
        self._worker = _NavWorker(
            positions,
            cam_filter,
            self.marker_lock,
            results,
            self._marker,
            links=self._links,
        )
        factory = _loop_factory if _loop_factory is not None else SessionLoop
        self.loop: Any = factory(
            self._worker,
            results=results,
            output=output if output is not None else BusOutput(),
            foreground=lambda: True,
            clock=clock,
            join_timeout=join_timeout,
            closing=self._closing,
        )
        self._worker.loop = self.loop

    # ---------------------------------------------------------------- 兼容只读口
    @property
    def session(self) -> Any:
        return self.loop.state().session_id

    @property
    def stop_ev(self) -> Any:
        override = self._stop_ev_override
        if override is not None:
            return override
        return _StopProxy(self.loop)

    @stop_ev.setter
    def stop_ev(self, value: Any) -> None:
        self._stop_ev_override = value

    @property
    def fixes(self) -> list[Any]:
        return self._worker.fixes_snapshot()

    def running(self) -> bool:
        return bool(self.loop.running())

    def target_label(self) -> str:
        if not self.target:
            return ""
        from ...navigation.navigate import label

        return label(self.target)

    def use_space(self, target: Any) -> bool:
        """「手动定位」（只用 /showlocation 的坐标）还是「实时定位」（读右上角）：玩家在导航页自己切，默认实时。
        太空路标在实时定位下按星系坐标给距离和机头转向（_space_view + steer）"""
        mode = self._links.setting("nav_mode", "auto")
        return mode == "space"

    # ---------------------------------------------------------------- 起停
    def start(
        self,
        target: Any,
        target_row: Any = None,
        space_mode: bool | None = None,
    ) -> NavStart:
        """开始导航；返回 NavStart。先保留旧 start 无条件 stop 的输出，但停止超时后拒绝新开始"""
        if self._closing():
            return NavStart(None, "closing")
        st = self.loop.state()
        if st.state is RunState.STOPPING and st.prev_stop_pending:
            return NavStart(st.session_id, "busy_stopping")
        att = self._stop_current(StopInfo("user"))
        if att.timed_out:
            return NavStart(att.session_id, "busy_stopping")
        st = self.loop.state()
        if st.prev_stop_pending:
            return NavStart(st.session_id, "busy_stopping")
        space = bool(space_mode) if space_mode is not None else self.use_space(target)
        if target_row is None:
            try:
                target_row = self._links.place_row(target)
            except Exception:
                target_row = None
        sid = self.loop.start(NavPayload(target, target_row, space))
        if sid is None:
            if self._closing():
                return NavStart(None, "closing")
            return NavStart(None, "busy_stopping")
        with self.fix_lock:
            self.target = target
            self.space_mode = space
        try:
            self._positions.set_demand(
                "nav", float("inf"), fps=None if space else _links_fps(self._links)
            )  # 实时定位按导航帧数读；手动定位（只用 /showlocation）不用读得快
            self._positions.request_read_now()
        except Exception:
            pass
        return NavStart(sid, "started")

    def stop(self) -> StopAttempt:
        return self._stop_current(StopInfo("user"))

    def _stop_current(self, info: StopInfo) -> StopAttempt:
        sid = self.loop.request_stop_current(info)
        if sid is None:
            self._clear_shell()
            self._clear_marker()
            return StopAttempt(None, False, False)
        self._clear_shell()
        joined = self.loop.join(session_id=sid)
        self._clear_marker()
        return StopAttempt(sid, joined, not joined)

    def _clear_shell(self) -> None:
        with self.fix_lock:
            self.target = None
            self.space_mode = False

    def _clear_marker(self) -> None:
        with self.marker_lock:
            try:
                self._marker.clear()
            except Exception:
                pass

    def refresh(self) -> None:
        """「立即刷新位置」：马上读一次右上角"""
        try:
            self._positions.request_read_now()
        except Exception:
            pass

    def add_fix(self, g: Any, clip: Any = None, session: int | None = None) -> Any:
        """太空路标：请求投进 Worker 队列，由 tick 在本 Ctx 上处理并走同一个 loop.commit。
        旧 session_id 的请求直接丢弃；等待一小会儿把处理结果交回旧调用方（没有结果返回 None）。"""
        with self.fix_lock:
            target = self.target
            space = self.space_mode
        if not target or not space:
            return None
        try:
            g = tuple(g)
        except TypeError:
            return None
        st = self.loop.state()
        sid = int(st.session_id)
        if session is not None and session != sid:
            return None
        if st.state not in (RunState.STARTING, RunState.RUNNING, RunState.PAUSED):
            return None
        req = self._worker.enqueue_fix(sid, g, clip)
        if not req.done.wait(1.0) and not self._worker.cancel_fix(req):
            req.done.wait(5.0)  # 已在处理中：等它做完，返回值如实
        return req.result


class _GameEvents:
    """读游戏日志里的量子、管辖区、禁火区、重生事件（2026-10-27）：推给窗口（gamelog），量子一到就调注入回调"""

    def __init__(self, on_qt_arrived: Callable[[], None] | None = None) -> None:
        self.thread: threading.Thread | None = None
        self.last: dict[str, tuple[float, Any]] = {}
        self.arrived_at: float = 0.0
        self.stop_ev = threading.Event()
        self.on_qt_arrived = on_qt_arrived

    def start(self) -> None:
        if WIN and (self.thread is None or not self.thread.is_alive()):
            self.stop_ev.clear()
            self.thread = threading.Thread(
                target=self._run, daemon=True, name="game-events"
            )
            self.thread.start()

    def request_stop(self) -> None:
        self.stop_ev.set()

    def join(self, timeout: float | None = None) -> bool:
        thread = self.thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        from ...system.gamelog import EventTail

        tail = EventTail()
        while not self.stop_ev.is_set():
            try:
                for t, k, v in tail.poll():
                    self.last[k] = (t, v)
                    if k == "qt_arrived":
                        self.arrived_at = time.time()
                        if self.on_qt_arrived is not None:
                            try:
                                self.on_qt_arrived()
                            except Exception:
                                pass
                    bus.publish("gamelog", {"kind": k, "value": v, "t": t})
            except Exception:
                pass
            if self.stop_ev.wait(0.5):
                break
