"""采矿线程（目录迁移 R3 从 app/engines/live.py 搬来）：扫描面板识别、雷达信号、破碎方案、袋子（_Live）

目录迁移 R3（2026-11-07）：本模块只留扫描节奏、会话、取消和结果提交。一轮识别要用的分析（analysis：
tasks/mining_analysis，原样转给 mining/screen、mining/signals、tasks/mining 等）、活动磁贴（views：
app/presenters/mining）、外面的东西（MiningLinks：抓图、游戏在不在前台、热键名、日志和截图目录、没出结果的画面
交给后台存、让读位置让出识别引擎、设置里的 live_on）都由 bootstrap 接进来；以前经 _T 动态去 tasks 取，或在
构造器里直接造。

RT-B4：线程 / 停止 / 提交边界 / 暂停 / 过期 / 自动关闭 / 重试都在 runtime/session.py 的 SessionLoop；
这里只写一轮识别（Worker）。一个会话的每次尝试的状态放在 _Ctx 里（按会话分开：停止超时后旧线程
还卡在识别里时，不会写坏新会话的投票队列）。收尾提示里的热键名不在这里存：循环在收尾那一刻锁外现读，放进 StopInfo.hotkey。
"""

import collections
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..results import MINING_SCAN, MINING_SIGNALS, ResultStore
from ..session import (
    RunFlag,
    RunState,
    SessionLoop,
    StopAttempt,
    StopInfo,
    Tick,
)


class MiningAnalysis(Protocol):
    """一轮识别要用的分析（目录迁移 R3）：tasks/mining_analysis 这个模块实现，bootstrap 接进来，线程不 import 它"""

    def interval(self) -> float: ...
    def vote_frames(self) -> int: ...
    def search(self) -> Any: ...
    def analyse(self, *args: Any, **kwargs: Any) -> Any: ...
    def last_raw(self) -> Any: ...
    def last_panel(self) -> Any: ...
    def panel_seen(self, *args: Any, **kwargs: Any) -> Any: ...
    def enqueue_rock(self, *args: Any, **kwargs: Any) -> Any: ...
    def miss_reason(self, *args: Any, **kwargs: Any) -> Any: ...
    def vote(self, *args: Any, **kwargs: Any) -> Any: ...
    def vote_partial(self, *args: Any, **kwargs: Any) -> Any: ...
    def find_signatures(self, *args: Any, **kwargs: Any) -> Any: ...
    def match_signature(self, *args: Any, **kwargs: Any) -> Any: ...
    def describe_all(self, *args: Any, **kwargs: Any) -> Any: ...
    def guesses(self, *args: Any, **kwargs: Any) -> Any: ...
    def mark_goal_lines(self, *args: Any, **kwargs: Any) -> Any: ...
    def rocks_stamp(self) -> Any: ...
    def mine_file_stamp(self) -> Any: ...
    def scan_view(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class MiningViews:
    """采矿线程要的排版（目录迁移 R3）：app/presenters/mining 实现，bootstrap 接进来"""

    activity: Callable[..., Any]  # 活动磁贴：activity(session_id, ui, quality=None)


@dataclass(frozen=True)
class MiningLinks:
    """采矿线程要的外面的东西（目录迁移 R3：以前在构造器里直接造、或经 _T 动态去 tasks 取，现在由 bootstrap 传进来）"""

    # 抓一帧游戏画面（mining/screen.grab）
    grab: Callable[[], Any]
    # 游戏在不在最前面：True / False；判断不了（不是 Windows、读不到前台窗口）返回 None——照常识别。
    # 切到聊天、浏览器、AT 窗口时别的窗口里的字会被当成扫描面板 / 雷达信号（2026-10-23 用户同意暂停）
    foreground: Callable[[], bool | None]
    # 采矿助手开关的热键名（提示文案里用；循环在锁外现读）
    hotkey: Callable[[], str]
    # 日志文件在哪（core/paths.log）
    log_file: Callable[[str], Any]
    # 截图目录（core/paths.shots：live 认出的石头、miss 没出结果的画面）
    shots: Callable[[str], Any]
    # 没出结果的画面交给它在后台存（app/miss_shots.MissShotsService，lifecycle 登记的就是它）
    miss_shots: Any
    # 看着面板、认出信号时让读位置先别占识别引擎（navigation/displayinfo.yield_ocr）
    yield_ocr: Callable[[], Any]
    # 设置里的 live_on 跟着开关写（app/output.setting_run_flag）；一定要给
    run_flag: RunFlag


def _pub(kind, data):
    return ("bus", kind, data)


def _say(line, tag):
    return ("log", line, tag)


def _set(*args):
    return ("hud.set", *args)


def _del(*sections):
    return ("hud.clear", *sections)


def _note(section, text, secs=None):
    return ("note", section, text, secs)


def _record(cat, text, ui_tag="", details="", level="INFO"):
    return ("record", cat, text, ui_tag, details, level)


def _ui(kind, data):
    return ("ui", kind, data)


class _Ctx:
    """一个会话的一次尝试的全部可变状态：旧线程停在自己的 Ctx 里，碰不到新会话"""

    def __init__(self, log, shots, now, frames):
        self.log = log
        self.shots = shots
        # 投票看最近几帧（mining/screen.VOTE_FRAMES）
        self.recent = collections.deque(maxlen=frames)
        self.part = collections.deque(maxlen=frames)
        self.hint: dict[str, Any] = {"why": None}
        self.last_key: Any = None
        self.sig_prev: Any = None
        self.sig_shown: Any = None
        self.prev_small: Any = None
        self.prev_panel: Any = None
        self.same = 0
        self.settled = False
        self.done_here = 0
        self.last_shown: Any = None
        self.last_full = 0.0
        self.miss_n = 0
        self.unstable_n = 0
        self.miss_t = 0.0
        # 显示用的墙钟时间戳（「已过期」里的从几点起、暂停补偿）
        self.last_panel_t = now
        self.last_sig_t = now
        self.ui = {
            "state": "starting",
            "scan": None,
            "signals": None,
            "stale_since": None,
        }
        self.scan_live = False
        self.sig_live = False
        self.missing = 0
        self._closed = False

    def close(self):
        """幂等：finish 关过以后再 teardown 不再关"""
        if self._closed:
            return
        self._closed = True
        try:
            self.log.close()
        except (OSError, ValueError):
            pass


class _StopProxy:
    """`stop_ev` 代理（RT-B7 删）：set() = 按当前会话停止；is_set() = 当前会话已取消或没有会话"""

    def __init__(self, loop):
        self._loop = loop

    def set(self):
        self._loop.request_shutdown()

    def is_set(self):
        return not self._loop.running()

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def clear(self):
        pass


class _Live:
    """实时读屏：投票逻辑在 mining/screen（vote / enqueue_rock），结果推给窗口和悬浮窗"""

    # ---- 会话循环要的类属性（设计稿 v3 §2.2）
    name = "live"
    log_tag = "MINING"
    display_name = "采矿助手"
    activity_kind = "mining"
    retries = 3
    idle_close: float | None = 120.0  # 所有通道最近一次「看到」都超过这么久：自动关闭
    stale_after: dict[str, float] = {"panel": 20.0, "signals": 20.0}
    needs_foreground = True
    restart_while_stopping = True

    RECHECK_SECONDS = (
        5  # 画面静止省电时，也每隔这么久复核一次（防止面板里的数变了但整屏几乎没变）
    )
    MISS_FRAMES = (
        4  # 看得到扫描面板、却连续这么多帧读不全 / 读不稳：自动留一张图（排查用）
    )
    MISS_GAP = 30  # 两次留图至少隔这么多秒
    MISS_KEEP = 10  # 最多留这么多张（userdata\shots\miss，每张 5MB 左右）

    HINTS = {  # 读不全的原因 → (采矿助手页的提示, 悬浮窗的短提示)
        "cut": (
            "扫描面板右侧被屏幕边缘遮挡，无法识别品质和总 SCU。在游戏设置中调大「FOV视野」，使整个面板（包括最右侧的品质数字）完整显示。",
            "采矿助手识别不完整：面板被屏幕右侧遮挡，需调大游戏「FOV视野」",
        ),
        "ca": (
            "扫描面板文字有红蓝重影（游戏开启了「色差」），小字无法准确识别。在游戏设置 → 图形中关闭「色差」；调高或关闭「超采样」可使文字更清晰。",
            "采矿助手识别不完整：面板文字有重影，需在游戏图形设置中关闭「色差」",
        ),
    }

    def __init__(
        self,
        results: ResultStore | None = None,
        *,
        output: Any,
        analysis: MiningAnalysis,
        views: MiningViews,
        links: MiningLinks,
        clock: Callable[[], float] | None = None,
        closing: Callable[[], bool] | None = None,
        where_now: Callable[[], Any] | None = None,
        area_now: Callable[[], Any] | None = None,
    ):
        self.results = results if results is not None else ResultStore()
        self._an = analysis
        self._views = views
        self._links = links
        # 没出结果的画面交给它在后台存；lifecycle 登记的就是它（bootstrap._register）
        self.miss_shots = links.miss_shots
        # 现在在哪、在哪个产矿区，bootstrap 接 tasks/navigation 的 _where_now / _area_now（F 段 B5）；不给就当不知道
        self._where_now = where_now
        self._area_now = area_now
        self.loop: Any = SessionLoop(
            self,
            results=self.results,
            output=output,
            foreground=links.foreground,
            clock=clock,
            run_flag=links.run_flag,
            closing=closing if closing is not None else (lambda: False),
        )

    @property
    def pause_wait(self):
        return min(self._an.interval(), 0.25)

    @property
    def prev_stop_pending(self):
        """停止请求已发出、上一会话还没收完；tasks 层只读这个，不碰 loop。"""
        return bool(self.loop.state().prev_stop_pending)

    # ---------------------------------------------------------------- 兼容外壳（RT-B7 删）
    def start(self):  # RT-B7 删
        """开会话；返回会话号，被拒返回 None"""
        return self.loop.start(None)

    def stop(self):  # RT-B7 删
        """按当前会话停止；返回 StopAttempt（本来就没在跑 → session_id=None，不 join）"""
        info = StopInfo("user", hotkey=self.hotkey())
        sid = self.loop.request_stop_current(info)
        if sid is None:
            return StopAttempt(None, False, False)
        joined = self.loop.join(session_id=sid)
        return StopAttempt(sid, joined, not joined)

    def hotkey(self):  # RT-B7 删
        """收尾提示里的热键名：循环在工作线程里、锁外现读（Worker 实例上不留）"""
        return self._links.hotkey()

    def running(self):  # RT-B7 删
        return self.loop.running()

    @property
    def paused(self):  # RT-B7 删
        return self.loop.state().state is RunState.PAUSED

    @property
    def session_id(self):  # RT-B7 删
        return self.loop.state().session_id

    @property
    def epoch(self):  # RT-B7 删
        return self.loop.state().epoch

    @property
    def stop_ev(self):  # RT-B7 删
        return _StopProxy(self.loop)

    def config_changed(self):  # RT-B7 删
        """配装变了：正在算的结果作废，正在显示的石头按新配装重算（采矿助手最多 5 秒后重新发布）"""
        self.loop.config_changed()

    # ---------------------------------------------------------------- Worker
    def start_ops(self, session):
        ui = {"state": "starting", "scan": None, "signals": None, "stale_since": None}
        return [
            _record("MINING", "采矿助手引擎已启动", "LIVE"),
            _pub("live", {"running": True}),
            _ui("ui.activity", self._views.activity(session.id, ui)),
        ]

    def stop_ops(self, session, info):
        """「已停止」确认的 ops（循环在锁内套用；纯函数，只读 info）。逐字照 dev 三处收尾

        user：清三块 → 记「引擎已停止」→ scan_hint → live running=False（不发 note）
        idle：清三块 → scan_hint → live auto_off → note（不写「引擎已停止」）
        error：清三块 → scan_hint → live error → note（不写「引擎已停止」）
        shutdown：什么都不发；replaced 不经这里
        """
        if info.reason not in ("user", "idle", "error"):
            return []
        hotkey = info.hotkey or "F5"
        ops: list[tuple] = [_del("信号", "扫描", "矿袋")]
        if info.reason == "user":
            # 列表顺序照设计表：清三块 → record → scan_hint → live（执行顺序里 record 是锁后类）
            ops.append(_record("MINING", "采矿助手引擎已停止", "LIVE"))
        ops.append(_pub("scan_hint", {"why": "", "text": ""}))
        if info.reason == "user":
            ops.append(_pub("live", {"running": False}))
        elif info.reason == "idle":
            ops.append(_pub("live", {"running": False, "auto_off": True}))
            ops.append(_note("采矿助手", f"采矿助手已关闭｜按 {hotkey} 开启"))
        else:
            ops.append(_pub("live", {"running": False, "error": info.error}))
            ops.append(
                _note(
                    "采矿助手",
                    f"采矿助手出错已关闭｜按 {hotkey} 重开（详情见日志）",
                )
            )
        return ops

    def setup(self, session):
        log = open(self._links.log_file("live_log.txt"), "a", encoding="utf-8")
        return _Ctx(log, self._links.shots("live"), time.time(), self._an.vote_frames())

    def teardown(self, session, ctx):
        if ctx is not None:
            ctx.close()

    def finish(self, session, ctx, info):
        """工作线程退出循环后（锁外）：自动关闭写 AUTO_OFF 日志，关本 Ctx 的日志"""
        if ctx is not None:
            if info.reason == "idle":
                try:
                    ctx.log.write(
                        f"{time.strftime('%F %T')} AUTO_OFF {int(self.idle_close or 0)} 秒没看到扫描面板和信号，采矿助手自动关闭\n"
                    )
                    ctx.log.flush()
                except (OSError, ValueError):
                    pass
            ctx.close()
        return []

    def on_error(self, session, ctx, exc):
        """把 traceback 写进本 Ctx 的日志（错误文本由循环记进本会话的待停记录）"""
        import traceback

        msg = f"采矿助手出错：{exc!r}"
        print(msg)
        if ctx is None:
            return
        try:
            ctx.log.write(
                f"{time.strftime('%F %T')} ERROR {msg}\n{traceback.format_exc()}"
            )
            ctx.log.flush()
        except (OSError, ValueError):
            pass

    def before_retry(self, session, ctx, error):
        """重来前把上一轮的旧结果清掉（新一轮的过期清理不认旧的）"""
        return [_del("信号", "扫描", "矿袋")]

    def on_pause(self, session, ctx):
        if ctx is None:
            return []
        ctx.miss_n = ctx.unstable_n = 0
        ctx.ui["state"] = "paused"
        try:
            ctx.log.write(f"{time.strftime('%F %T')} PAUSE 游戏不在最前面，暂停识别\n")
            ctx.log.flush()
        except (OSError, ValueError):
            pass
        return [
            _pub("live", {"running": True, "paused": True}),
            _record("MINING", "采矿助手已暂停", "LIVE", "游戏不在最前面", "WARN"),
            _ui("ui.activity", self._views.activity(session.id, ctx.ui)),
        ]

    def on_resume(self, session, ctx, gap):
        if ctx is None:
            return []
        # 暂停的这段不算「面板 / 信号消失了」：显示用的时间戳跟着推
        ctx.last_panel_t += gap
        ctx.last_sig_t += gap
        ctx.prev_small = ctx.prev_panel = (
            None  # 回来的第一帧一定重新认，不按「画面没变」跳过
        )
        try:
            ctx.log.write(
                f"{time.strftime('%F %T')} RESUME 回到游戏，继续识别（暂停了 {gap:.0f} 秒）\n"
            )
            ctx.log.flush()
        except (OSError, ValueError):
            pass
        ctx.ui["state"] = (
            "running"
            if ctx.ui.get("scan") is not None or ctx.ui.get("signals") is not None
            else "starting"
        )
        return [
            _pub("live", {"running": True, "paused": False}),
            _record("MINING", "采矿助手已继续", "LIVE", f"暂停了 {gap:.0f} 秒", "INFO"),
            _ui("ui.activity", self._views.activity(session.id, ctx.ui)),
        ]

    def on_stale(self, session, ctx, channel):
        """某个通道超过 stale_after 没看到：面板 / 信号标过期（每次「看到→没看到」只来一次）"""
        if ctx is None:
            return []
        ops = []
        if channel == "signals" and ctx.sig_live:
            ctx.sig_live, ctx.sig_shown = (
                False,
                None,
            )  # 信号没了：悬浮窗清掉，窗口里标过期
            since = time.strftime("%H:%M:%S", time.localtime(ctx.last_sig_t))
            shown_sig = self.results.get(MINING_SIGNALS)
            ops.append(_del("信号"))
            ops.append(
                _pub(
                    "signals",
                    {
                        **(shown_sig.value["view"] if shown_sig else {"lines": []}),
                        "stale": since,
                    },
                )
            )
        elif channel == "panel":
            if ctx.hint["why"]:
                ops.extend(
                    self._hint_ops(ctx, None, clear_hud=True)
                )  # 面板不在了：读不全提示也收起
            if ctx.scan_live:
                ctx.scan_live, ctx.last_shown, ctx.last_key = False, None, None
                ctx.recent.clear()
                ctx.part.clear()
                since = time.strftime("%H:%M:%S", time.localtime(ctx.last_panel_t))
                ctx.ui["state"] = "stale"
                ctx.ui["stale_since"] = since
                shown_scan = self.results.get(MINING_SCAN)
                ops.append(_del("扫描", "矿袋"))
                ops.append(
                    _pub(
                        "scan",
                        {**(shown_scan.value if shown_scan else {}), "stale": since},
                    )
                )
                ops.append(_ui("ui.activity", self._views.activity(session.id, ctx.ui)))
        return ops

    # ---------------------------------------------------------------- 一轮识别
    def tick(self, session, ctx, now):
        import numpy as np

        n = self._an
        log = ctx.log
        wall = time.time()
        img = self._links.grab()
        l, t, r, b = n.search()  # noqa: E741
        W, H = img.size
        # 省电：画面几乎没变、这个画面已经出过结果（或根本没有面板）就不重复识别。
        # 整屏缩小比一次，扫描面板那块再单独细一点比一次（面板里数字变了、整屏几乎没变的情况）
        small = np.asarray(
            img.reduce(max(1, img.width // 160)).convert("L"), dtype=np.int16
        )
        panel = np.asarray(
            img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
            .reduce(max(1, img.width // 640))
            .convert("L"),
            dtype=np.int16,
        )
        still = (
            ctx.prev_small is not None
            and ctx.prev_panel is not None
            and ctx.prev_panel.shape == panel.shape
            and np.abs(small - ctx.prev_small).mean() < 1.5
            and np.abs(panel - ctx.prev_panel).mean() < 1.0
        )
        if still:
            ctx.same += 1
        else:
            ctx.same, ctx.settled, ctx.done_here = 0, False, 0
        ctx.prev_small, ctx.prev_panel = small, panel
        if ctx.same >= 2 and ctx.settled and now - ctx.last_full < self.RECHECK_SECONDS:
            return Tick(n.interval(), {})
        ctx.last_full = now
        stamp = self.loop.stamp(session, wall)
        if stamp is None:
            return Tick(n.interval(), {})
        observed: dict[str, float] = {}
        # ---- 扫描面板（先看有没有面板：有面板时屏幕上的质量等数字会被当成信号，信号识别就暂停）
        scan, bag = n.analyse(img)
        raw = n.last_raw().get("scan") if n.last_raw().get("t", 0) >= wall else None
        # 真有面板才算（读全了，或认出面板上的字 / 带矿名的成分）。只读到几个零散数字不算：勘探者驾驶舱右边的
        # 高度表、气压会被拼成「质量 0.7、抗性 76」，以前因此一直当面板开着，信号识别整段暂停（2026-10-23 Calliope）
        panel_now = n.panel_seen(scan, raw)
        if panel_now:  # 看着面板：读位置别占识别引擎（2026-10-27 悬浮窗晚 10–18 秒）
            self._links.yield_ocr()
        # 面板顶着屏幕右边、被挡住一截（16:10 屏幕上鼹鼠炮塔的面板，2026-10-23 用户反馈）：品质和总 SCU 在屏幕外面，
        # 质量、抗性、不稳定性读到了就照样算破碎方案（part 队列，两帧一致才出）
        cut = panel_now and bool(n.last_panel().get("cut"))
        part_ok = (
            not scan.valid
            and cut
            and scan.complete
            and (scan.mass or 0) >= 500
            and scan.resistance is not None
            and 0 <= scan.resistance <= 100
        )
        if part_ok:
            n.enqueue_rock(ctx.part, scan)  # 同一块石头才进投票队列
        elif scan.valid or not panel_now:
            ctx.part.clear()
        # 面板在却读不全：连续几帧这样就留一张图，并告诉玩家可能的原因（被屏幕挡住 / 字有色差重影）
        ctx.miss_n = 0 if (scan.valid or not panel_now or part_ok) else ctx.miss_n + 1
        if ctx.miss_n >= self.MISS_FRAMES and now - ctx.miss_t > self.MISS_GAP:
            ctx.miss_t, ctx.miss_n = now, 0
            self._save_miss(ctx, img, "读不全", raw)
            why = n.miss_reason(img)
            if why and why != ctx.hint["why"]:
                self.loop.commit(session, *self._hint_ops(ctx, why))
        if panel_now and ctx.sig_live:
            ctx.sig_live, ctx.sig_shown, ctx.sig_prev = (
                False,
                None,
                None,
            )  # 对着石头看面板：悬浮窗收起信号
            self.loop.commit(session, _del("信号"))
        # ---- 雷达信号（扫描面板开着时不认，2026-10-23 用户反馈把石头质量 13,586 当成了信号）
        try:
            found = [] if panel_now else n.find_signatures(img)
            sigs = frozenset(v for v, *_ in found)
            if sigs:
                ctx.last_sig_t = wall
                observed["signals"] = now
                self._links.yield_ocr()
            area = (
                self._area_now()
                if self._area_now is not None and sigs and sigs == ctx.sig_prev
                else None
            )
            # 产矿区变了（飞进矿带、跳跃）也要重新发：以前只看信号数值，同样的 7,200 会一直停在旧地点的说法
            shown_key = (
                sigs,
                frozenset((v, f) for v, f, *_ in found),
                (area or {}).get("name"),
                (area or {}).get("zh"),
                n.rocks_stamp(),
                n.mine_file_stamp(),
            )  # 换了石头表、读数改没改过、自己起了名都重发
            if (
                sigs
                and sigs == ctx.sig_prev
                and shown_key != ctx.sig_shown
                and session.alive()
            ):
                where = (
                    self._where_now()
                    if self._where_now is not None
                    and any(not n.match_signature(v) for v in sigs)
                    else None
                )
                lines = n.mark_goal_lines(n.describe_all(found, where, area))
                unknown = [
                    v
                    for v in sorted(sigs)
                    if v and not any(e for *_, e in n.guesses(v, where, area))
                ]
                msg = {
                    "lines": lines,
                    "at": time.strftime("%H:%M:%S"),
                    "area": (area or {}).get("zh", ""),
                    "unknown": unknown,
                }  # 没认准的：窗口里可以起名记下（2026-10-27）
                prev_ui = dict(ctx.ui)
                ctx.ui.update(state="running", signals=msg, stale_since=None)
                if self.loop.commit(
                    session,
                    _pub("signals", msg),
                    _set(
                        "信号",
                        "\n".join(
                            x.split("｜精炼后")[0].replace("信号 ", "")
                            for x in lines[:4]
                        ),
                    ),
                    _say(
                        f"雷达信号: {sorted(sigs)} 产区: {(area or {}).get('zh') or '未知'}",
                        "SIGNAL",
                    ),
                    _ui("ui.activity", self._views.activity(session.id, ctx.ui)),
                    slot=MINING_SIGNALS,
                    value={"view": msg, "values": sorted(sigs)},
                    stamp=stamp,
                ):
                    ctx.sig_shown, ctx.sig_live = shown_key, True
                    log.write(
                        f"{time.strftime('%F %T')} SIG {sorted(sigs)} 产矿区={(area or {}).get('zh') or '未知'}\n"
                    )
                    log.flush()
                else:
                    ctx.ui = prev_ui
            ctx.sig_prev = sigs
        except Exception as e:  # noqa: BLE001 —— 信号识别出错只丢这一轮的结果，不能拖垮面板识别
            self.loop.commit(
                session, _pub("log", {"task": "live", "line": f"信号识别失败：{e}"})
            )
        ctx.done_here += 1
        if panel_now:
            ctx.last_panel_t, ctx.missing = wall, 0
            observed["panel"] = now
        else:
            ctx.missing += 1
            if ctx.missing >= 3:
                ctx.recent.clear()  # 目标丢了（连续 3 帧没面板）：投票队列重来，别把下一块石头混进来
            if not scan.valid:
                ctx.settled = ctx.same >= 2  # 画面里没有扫描面板，静止时不用一直认
        if scan.valid:
            self._tick_scan(session, ctx, scan, bag, img, now, stamp)
        elif part_ok and len(ctx.part) >= 2:
            self._tick_part(session, ctx, bag, now, stamp)
        return Tick(n.interval(), observed)

    def _tick_scan(self, session, ctx, scan, bag, img, now, stamp):
        n = self._an
        log = ctx.log
        if n.enqueue_rock(ctx.recent, scan, bag):
            ctx.unstable_n = 0  # 换了石头：投票队列重计
        # 这一帧和队列里的石头对不上、被当成可疑帧先记下（没进队列）：这次不投票、不发结果。
        # 以前照样拿队列里上一块石头的帧投票，换石头后的第一帧会把上一块的结果又发一遍（2026-10-24 玩家反馈：
        # 画面是 5561 / 18.35 SCU 的新石头，发出去的是上一块 10187 / 33.71 SCU）
        accepted = bool(ctx.recent) and ctx.recent[-1][0] is scan
        if accepted and len(ctx.recent) >= 2:
            best, stable = n.vote([x[0] for x in ctx.recent])
            # 每帧都读全了、但几帧之间对不上（投不出结果）：也算没出结果，留一张图
            ctx.unstable_n = 0 if stable else ctx.unstable_n + 1
            if (
                ctx.unstable_n >= self.MISS_FRAMES + 1
                and now - ctx.miss_t > self.MISS_GAP
            ):
                ctx.miss_t, ctx.unstable_n = now, 0
                self._save_miss(
                    ctx, img, "读不稳", [str(x[0]) for x in list(ctx.recent)[-3:]]
                )
            key = (round(best.mass or 0), best.resistance, best.instability)
            # 任何影响计算的字段变了（总 SCU、成分、评级、矿袋）都重新发布，修正后的数也要推出去
            shown = (
                key,
                best.total_scu,
                best.rock,
                best.difficulty,
                tuple(best.composition),
                ctx.recent[-1][1][1],
                self.loop.config_rev,
            )
            if stable and best.valid and shown != ctx.last_shown and session.alive():
                view = n.scan_view(best, ctx.recent[-1][1])  # 慢：算完再看一次有没有停
                prev_ui = dict(ctx.ui)
                ctx.ui.update(
                    state="running", scan=view, stale_since=None, quality="complete"
                )
                ops = [
                    _pub("scan", view),
                    _say(
                        f"扫描岩石: {best.rock or '岩石'} (质量 {round(best.mass or 0)} | 矿量 {best.total_scu:.1f} SCU)",
                        "SCAN",
                    ),
                    _set("扫描", view["hud"], view.get("hud_rich")),
                ]
                if view["bag_text"]:
                    ops.append(_set("矿袋", view["bag_text"]))
                ops.append(_ui("ui.activity", self._views.activity(session.id, ctx.ui)))
                if not self.loop.commit(
                    session, *ops, slot=MINING_SCAN, value=view, stamp=stamp
                ):
                    # 算的时候停了 / 配装变了：这份作废，下一帧按新配装重算
                    ctx.ui = prev_ui
                    ctx.settled = False
                    return
                if ctx.hint["why"]:
                    self.loop.commit(session, *self._hint_ops(ctx, None))
                ctx.last_key, ctx.last_shown, ctx.scan_live = key, shown, True
                log.write(f"{time.strftime('%F %T')} {best} {ctx.recent[-1][1]}\n")
                log.flush()
                try:
                    img.save(ctx.shots / f"{time.strftime('%H%M%S')}.png")
                    for f in sorted(ctx.shots.glob("*.png"))[:-20]:
                        f.unlink()
                except OSError:
                    pass
        # 同一个画面认够一轮投票（5 帧）、结果也出了，就不再重复认（每 RECHECK_SECONDS 秒仍复核一次）
        ctx.settled = ctx.last_shown is not None and ctx.done_here >= n.vote_frames()

    def _tick_part(self, session, ctx, bag, now, stamp):
        n = self._an
        best, stable = n.vote_partial([x[0] for x in ctx.part])
        # 读一半的帧（面板顶出屏幕）连续两帧一致、又和完整读数队列里的石头不是同一块：说明已经换了石头，
        # 旧石头的完整读数作废（不然转回来读全时，第一帧新石头会被当成可疑帧挡掉，旧结果又冒出来）
        # 只看质量（差 1% 以上才算换了）：同一块石头开着激光时抗性会变（45% ↔ 65%），不能因此清掉
        prev_rock = ctx.recent[-1][0] if ctx.recent else None
        if (
            stable
            and prev_rock is not None
            and best.mass
            and prev_rock.mass
            and abs(best.mass - prev_rock.mass) / prev_rock.mass >= 0.01
        ):
            ctx.recent.clear()
        shown = (
            "cut",
            round(best.mass or 0),
            best.resistance,
            best.instability,
            best.rock,
            best.difficulty,
            tuple(best.composition),
            self.loop.config_rev,
        )
        if stable and shown != ctx.last_shown and session.alive():
            view = n.scan_view(best, bag, cut=True)
            prev_ui = dict(ctx.ui)
            ctx.ui.update(
                state="running", scan=view, stale_since=None, quality="partial"
            )
            if not self.loop.commit(
                session,
                _pub("scan", view),
                _set("扫描", view["hud"], view.get("hud_rich")),
                _ui("ui.activity", self._views.activity(session.id, ctx.ui)),
                slot=MINING_SCAN,
                value=view,
                stamp=stamp,
                quality="partial",
            ):
                ctx.ui = prev_ui
                ctx.settled = False
                return
            if ctx.hint["why"]:
                self.loop.commit(session, *self._hint_ops(ctx, None))
            ctx.last_key, ctx.last_shown, ctx.scan_live = None, shown, True
            ctx.log.write(
                f"{time.strftime('%F %T')} PART 面板被屏幕挡住，只算破碎 {best}\n"
            )
            ctx.log.flush()
        ctx.settled = ctx.last_shown is not None and ctx.done_here >= n.vote_frames()

    # ---------------------------------------------------------------- 小动作
    def _save_miss(self, ctx, img, why, raw):
        """采矿助手没出结果的画面自动存下来：之后从这些图找原因（2026-10-23 用户反馈「部分矿物扫描失败」，当时没有图）"""
        stamp = time.strftime("%H%M%S")
        try:
            ctx.log.write(f"{time.strftime('%F %T')} MISS {why} {raw}\n")
            ctx.log.flush()
        except (OSError, ValueError):
            pass

        try:
            d = self._links.shots("miss")
        except OSError:
            return
        self.miss_shots.submit(d, stamp, img, self.MISS_KEEP)

    def _hint_ops(self, ctx, why, clear_hud=False):
        """读不全的提示 ops；why=None 收起（clear_hud：悬浮窗上的提示也擦掉）"""
        ctx.hint["why"] = why
        text, short = self.HINTS.get(why, ("", ""))
        if why:
            try:
                ctx.log.write(f"{time.strftime('%F %T')} HINT {why}\n")
                ctx.log.flush()
            except (OSError, ValueError):
                pass
        ops: list[tuple] = [
            _pub(
                "scan_hint",
                {"why": why or "", "text": text, "at": time.strftime("%H:%M:%S")},
            )
        ]
        if why:
            ops.append(_set("扫描", short))
        elif clear_hud:
            ops.append(_del("扫描"))
        return ops
