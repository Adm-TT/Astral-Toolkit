"""小行星带（Aaron Halo）航线、断开距离核对、一键定位（2026-11-19 从 tasks/navigation.py 按段落拆出来，只搬位置、代码没改）"""

import math
import threading
import time
from dataclasses import dataclass

from ...app import bus
from .base import (
    AT_TARGET,
    LEFT_START,
    NEAR_MIN,
    NavDeps,
    QT_SPEED,
    ROUTE_NEAR,
    STOP_S,
    _HALO,
    _hud_clear,
    _hud_set,
    _pos_current,
    _wp_log,
    settings_key,
)
from .search import _rt_b6_closing_error
from .marks import _wait_showloc


# ---------------------------------------------------------------- 小行星带（Aaron Halo）导航与一键定位
def halo_options():
    """小行星带页要的选项：10 条带、出发点、量子引擎、上次选的引擎、悬浮窗上正挂着的方案"""
    from ...navigation import halo

    return {
        "bands": [halo.band_row(r) for r in halo.BANDS],
        "points": [{"key": k, "label": halo.point_zh(k)} for k in halo.points()],
        "qds": [{"name": f"{a} ({b})", "speed": v} for a, b, v in halo.QDS],
        "qd": settings_key("halo_qd", "Atlas (S1)"),
        "plan": _HALO["plan"],
    }


def halo_routes(frm="ARC-L1", band=5, qd=""):
    """从 frm 出发、能在第 band 带断开的所有目标"""
    from ...navigation import halo
    from ...core import settings

    try:
        row = halo.band(band)
    except (TypeError, ValueError):
        return {"error": "带号需为 1–10"}
    pts = halo.points()
    if frm not in pts:
        return {"error": f"未找到出发点 {frm}"}
    if qd:
        settings.update(halo_qd=qd)
    speed = halo.qd_speed(qd or settings_key("halo_qd", "Atlas (S1)"))
    return {
        "from": frm,
        "band": halo.band_row(row),
        "speed": speed,
        "rows": halo.routes(frm, band, speed, pts),
    }


def halo_pin(deps: NavDeps, /, frm="", to="", band=5, qd=""):
    """把这条路线挂到悬浮窗：游戏里看着 HUD 剩余距离断开；断开后按一键定位键（或自己输 /showlocation）核对在不在带里"""
    refused = _rt_b6_closing_error()
    if refused:
        return refused
    from ...navigation import halo
    from ...navigation import navigate as n

    pts: dict = {}
    try:
        pts = halo.points()
        r = halo.route(
            frm,
            to,
            band,
            halo.qd_speed(qd or settings_key("halo_qd", "Atlas (S1)")),
            pts=pts,
        )
    except (TypeError, ValueError):
        r = None
    if not r:
        return {"error": "此航线不穿过该带"}
    r["text"] = halo.plan_text(r) + "\n退出量子后自动核对是否在带内"
    with _HALO["lock"]:
        # 代次加一：核对会话下一轮看到换了方案就从头记；旧方案还没出完的核对结果按代次作废
        _HALO["sess"] += 1
        _HALO.update(
            plan=r,
            last=None,
            ends=(pts[frm], pts[to]),
            near=_start_near(r),
            jumped=False,
            first=False,
            logged=None,
        )
        try:
            _HALO["seen"] = n.read_clipboard()  # 挂上之前剪贴板里的旧坐标不算
        except Exception:
            _HALO["seen"] = None
        _hud_set("小行星带", r["text"])
    # 先记方案那行再开核对会话：会话一起来就会核对、记日志（审查 2026-11-08 第三轮）
    _wp_log(f"小行星带方案：{frm} → {to} 第{band}带，剩 {r['dropout']} Gm 断开")
    # 核对会话（2026-11-09 起由 SessionLoop 跑，deps.halo）：已经在跑就是它，跟上新方案；退出时会停、会等它退
    deps.halo.start()
    return r


def halo_unpin():
    """取下方案：核对会话下一轮（HALO_WAIT 秒内）看到没有方案了就自己结束"""
    with _HALO["lock"]:
        _HALO["sess"] += 1
        _HALO.update(
            plan=None, last=None, ends=None, jumped=False, first=False, logged=None
        )
        _hud_clear("小行星带")
    return {"ok": True}


@dataclass
class _HaloSeen:
    """halo 会话里要记着的几样：跟着哪一份方案（代次），换了方案就从头记（以前是换一条新线程）"""

    sess: int | None  # 跟着的方案代次；None = 还没开始跟
    arr: float  # 游戏日志上次说量子到了的时刻
    seen_live: float | None = None  # 上一份处理过的实时读数的读数时间
    live_at: float = 0.0  # 上次按实时坐标核对的时刻
    prev: tuple | None = None  # 上一份实时读数 (读数时间, 坐标)
    in_qt: bool = False  # 在一跳里：测到起跳、还没确认停下
    slow_since: float | None = None  # 一跳里读数慢下来的那一刻（读数时间）

    def follow(self, sess: int, arr: float) -> None:
        """换成跟新的一份方案：其余从头记"""
        self.sess, self.arr = sess, arr
        self.seen_live, self.live_at, self.prev = None, 0.0, None
        self.in_qt, self.slow_since = False, None


def _halo_state(deps: NavDeps) -> _HaloSeen:
    """halo 会话开始时：还没跟哪份方案，第一轮跟上当前的"""
    return _HaloSeen(sess=None, arr=deps.game_events.arrived_at)


def _halo_step(deps: NavDeps, st: _HaloSeen) -> bool:
    """挂着方案时的一轮（halo 会话每 HALO_WAIT 秒一次）：读右上角的实时坐标自动核对（每秒一次）；读不到时
    玩家自己在聊天框输 /showlocation 也能核对（/showlocation 只在必要时用，2026-10-27 用户定；太空导航进行中时
    剪贴板归导航管）。2026-11-09 由 _halo_watch 的循环体改来：一个会话跟着当前方案，换了方案（代次变了）从头记、
    不重开会话；方案取下了返回 True，会话自己结束"""
    from ...navigation import navigate as n

    with _HALO["lock"]:
        cur, pinned = _HALO["sess"], _HALO["plan"] is not None
    if not pinned:
        return True
    if st.sess != cur:
        st.follow(cur, deps.game_events.arrived_at)
    sess = cur
    nav = deps.nav
    events = deps.game_events
    try:
        if events.arrived_at != st.arr:
            # 游戏日志说量子到了：下一次核对提前，不用等每秒那一下；跳没跳完照旧按读数算——手动断开时船还在滑，
            # 这会儿就当停下，量出来的滑行距离会少一截（审查 2026-11-08 第三轮）
            st.arr, st.live_at = events.arrived_at, 0.0
        t, g_live, _ = _pos_current(
            deps
        )  # 每次读到都更新（停着不动也有新的一份），latest 只在坐标变了才换（审查 2026-10-27）
        if g_live and t != st.seen_live and time.time() - t < 3:
            st.seen_live = t
            prev = st.prev
            fast = bool(
                prev
                and t > prev[0]
                and math.dist(g_live, prev[1]) / (t - prev[0]) > QT_SPEED
            )
            if fast:
                # 从慢变快就是起跳了，每次起跳都算：起跳前最后一次读数在方案起点附近，就是从起点跳的那一趟
                if not st.in_qt:
                    _halo_jump(sess, prev is not None and _near_start(prev[1]))
                st.in_qt, st.slow_since = True, None
            elif st.in_qt:
                # 一跳里慢下来：连续 STOP_S 秒都慢才算断开停下，中间又快起来还是这一跳（游戏卡一下、
                # 按断开那一刻卡住，都会连着读到一样的坐标）；停下了马上核对
                if st.slow_since is None:
                    st.slow_since = t
                if t - st.slow_since >= STOP_S:
                    st.in_qt, st.slow_since, st.live_at = False, None, 0.0
            st.prev = (t, g_live)
            if (
                not st.in_qt and time.time() - st.live_at >= 1.0
            ):  # 量子途中（每秒几万公里）不核对，等确认停下
                st.live_at = time.time()
                halo_check(g_live, None, sess)
        clip = n.read_clipboard()
        g = n.parse_clip(clip)
        if g and clip != _HALO["seen"] and not (nav.target and nav.space_mode):
            halo_check(g, clip, sess)
    except Exception:
        pass
    return False


def _halo_jump(sess, from_start):
    """挂着方案时测到一次起跳（每次起跳都算）：悬浮窗刷回只剩方案那几行，起跳前、上一跳的核对别冻在上面；
    记下挂上以后跳过了（每秒自动核对这才说「多飞 / 少飞」）；从方案起点跳的这一趟，
    断开后第一次说那句的核对在导航日志里标出来（审查 2026-11-08）"""
    with _HALO["lock"]:
        p = _HALO["plan"]
        if not p or sess != _HALO["sess"]:
            return
        _HALO.update(jumped=True, first=bool(from_start))
        _hud_set("小行星带", p["text"])


def _start_near(r):
    """离方案起点多近算还在起点（Gm）：一般 LEFT_START；断开点离起点很近的路线（CRU-L2 本身就在带里）缩到起点到
    安全窗口那段的一半，最少 NEAR_MIN（审查 2026-11-08）"""
    return max(NEAR_MIN, min(LEFT_START, (r["total"] - r["early"]) / 2))


def _near_start(g):
    """坐标（米）离方案起点不超过 near（挂方案时按路线算好）"""
    ends = _HALO["ends"]
    return (
        bool(ends) and math.dist(ends[0], [float(v) / 1e9 for v in g]) <= _HALO["near"]
    )


def halo_check(g, clip=None, sess=None):
    """拿到 /showlocation 坐标：离恒星多远、在不在要去的那条带里。
    F9 和剪贴板监听可能拿到同一份坐标：查重、发布在同一把锁里；方案已取下或换了就丢掉"""
    from ...navigation import halo

    with _HALO["lock"]:
        p = _HALO["plan"]
        if not p or (sess is not None and sess != _HALO["sess"]):
            return None
        if clip is not None and clip == _HALO["seen"] and _HALO["last"]:
            return _HALO["last"]
        if clip is not None:
            _HALO["seen"] = clip
        w = halo.where(g)
        w["text"] = halo.where_text(w, p["band"])
        # 比方案的断开点多飞 / 少飞多少：老大实飞量断开后船滑多远（2026-11-08）。在方案起点附近、差得太远都不说；
        # 每秒自动核对还要挂上以后测到过起跳才说（还没跳就说「少飞了」像是玩家错了）；
        # 手动定位（剪贴板、F9）没有实时坐标测起跳，只看离起点多远（审查 2026-11-08）
        # 离航线远（跳去了别处）、到了目标跟前也不说（审查 2026-11-08）
        ends = _HALO["ends"]
        over, first = None, False
        if (
            ends
            and not _near_start(g)
            and (clip is not None or _HALO["jumped"])
            and halo.route_gap(ends[0], ends[1], g) <= ROUTE_NEAR
        ):
            over = halo.overshoot(p, g, {p.get("to"): ends[1]})
            if over and over["left"] < min(AT_TARGET, p.get("late", AT_TARGET)):
                over = None
        if over:
            w["left"], w["over"] = over["left"], over["over"]
            w["text"] += "\n" + over["text"]
            first, _HALO["first"] = _HALO["first"], False
        _HALO["last"] = w
        _hud_set(
            "小行星带", p["text"] + "\n" + w["text"]
        )  # 退出距离、安全区间一直留着（审查 2026-10-27：自动核对不能把它盖掉）
        bus.publish("halo", w)
        # 每秒自动核对：跟上次一样就不再记（审查 2026-11-08）
        log_it = w["text"] != _HALO["logged"]
        _HALO["logged"] = w["text"]
    if log_it:
        mark = "（量子后第一次）" if first else ""
        _wp_log(f"小行星带核对{mark}：{w['text']}".replace("\n", "｜"))
    return w


def fix_here(deps: NavDeps, /):
    """游戏里按一键定位热键：导航去太空路标时，等你输 /showlocation 更新距离和偏离角（AT 不替你输入）；
    挂着小行星带方案时，核对现在在不在那条带里"""
    from ...navigation import navigate as n

    nav = deps.nav
    if (not nav.target or not nav.space_mode) and _HALO["plan"]:
        sess = _HALO["sess"]  # 等坐标期间方案取下或换了，这次结果就作废
        g, clip = _wait_showloc()
        with _HALO["lock"]:
            plan = _HALO["plan"] if _HALO["sess"] == sess else None
            if not g and plan:
                _hud_set("小行星带", plan["text"] + f"\n本次定位失败：{clip}")
        if not g:
            return {"error": clip}
        return halo_check(g, clip, sess) or {
            "error": "小行星带方案已移除或更换，本次定位无效"
        }
    if not nav.target or not nav.space_mode:
        _hud_set("导航", "一键定位仅用于手动定位（可在导航页切换）")
        threading.Timer(
            5, lambda: _hud_clear("导航") if not nav.target else None
        ).start()
        return {"error": "当前未导航到太空路标"}
    sess = nav.session  # 等坐标期间导航结束或换了目标，这次结果就作废
    g, clip = _wait_showloc()
    if not g:
        if nav.session == sess and nav.target:
            _hud_set("导航", f"→ {n.label(nav.target)}\n这次没定位成功：{clip}")
        return {"error": clip}
    return nav.add_fix(g, clip, session=sess) or {
        "error": "导航已结束或目标已更换，本次定位无效"
    }
