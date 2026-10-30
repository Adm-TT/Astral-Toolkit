"""导航引擎：实时方位 / 路标 / 站内导航（_Nav）、读数平滑（_Steady）、摄像头过滤（_CamFilter）、游戏事件（_GameEvents）

2026-10-28 从 app/services.py 原样剪出来（逻辑没改）。2026-10-30 重构阶段 4 删了 services.py，
用到的函数 / 变量直接到它们所在的模块取，运行时才取，避免互相 import：
_T("mining").xxx = tasks/mining.py，_H().xxx = app/hud_state.py，_E().live / .nav / .pos / .cam_filter = 引擎实例。
用到：DI_HELP, LIVE_STALE, WIN, _cam_filter, _hud, _mark_hud, _marker_tick, _nav, _nav_log, _nav_view, _off, _place_row, _pos, _space_view, _station_view, _wp_log, fix_key_hint, settings_key, status
"""
import importlib
import sys
import threading
import time

from .. import bus

WIN = sys.platform == "win32"


def _T(name):
    """sc_mining.tasks 里的模块（运行时才取，避免互相 import）"""
    return importlib.import_module(f"sc_mining.tasks.{name}")


def _H():
    from .. import hud_state
    return hud_state


def _E():
    """后台引擎（EngineManager 单例：.live、.nav、.pos、.cam_filter …）"""
    from .manager import EngineManager
    return EngineManager.get_instance()


class _Steady:
    """显示的方位角防抖：真实方位角变了 2° 以上才换显示，免得数字在 359/000/001 之间来回跳"""
    DEADBAND = 2.0

    def __init__(self):
        self.shown = None

    def __call__(self, brg):
        if self.shown is None or abs((brg - self.shown + 180) % 360 - 180) >= self.DEADBAND:
            self.shown = brg
        return self.shown


class _CamFilter:
    """CamDir 防误读：OCR 偶尔把负号漏掉（-142 认成 142），指的方向就完全反了。
    跟上一次比：某个角度绝对值差不多、正负号却反了（而且不小），多半是漏了负号，这次不用"""

    def __init__(self):
        self.last = None

    def check(self, cam):
        if not cam:
            return None
        prev, self.last = self.last, cam
        # 绕过 ±180°（比如偏航 178 → -178）是真的转过去了，不算
        if prev and any(10 < abs(a) < 170 and a * b < 0 and abs(abs(a) - abs(b)) <= 4 for a, b in zip(cam, prev)):
            self.last = prev                 # 不信这次，下次还跟上一次比
            return None
        return cam


class _Nav:
    """导航跟踪：读游戏右上角的调试信息拿位置，算方位，推给窗口和悬浮窗"""

    def __init__(self):
        self.target = None
        self.stop_ev = threading.Event()
        self.thread = None
        self.last_here = None
        self.fixes = []                     # 太空导航：一键定位（/showlocation）拿到的 [(时间, 星系坐标米)]
        self.space_mode = False
        self.fix_lock = threading.Lock()
        self.clip_seen = None
        self.session = 0                    # 每次开始 / 结束导航 +1：旧线程、旧的一键定位结果对不上就丢掉
        self.last_view = None
        self.ref = None                     # 最近一次算位置用的 (星系坐标, locate 结果, 时间)：记号、转向和罗盘同一个基准

    def target_label(self):
        if not self.target:
            return ""
        from ...navigation.navigate import label
        return label(self.target)

    def use_space(self, target):
        """「手动定位」（只用 /showlocation 的坐标）还是「实时定位」（读右上角）：玩家在导航页自己切，默认实时。
        太空路标在实时定位下按星系坐标给距离和机头转向（_space_view + steer）"""
        mode = _T("navigation").settings_key("nav_mode", "auto")
        return mode == "space"      # 2026-10-27：太空路标默认也读右上角（实时），玩家选「手动定位」才只用 /showlocation

    def start(self, target):
        self.stop()
        space = self.use_space(target)
        ev = threading.Event()                   # 每次导航自己的停止开关，旧线程拿不到新的
        with self.fix_lock:
            self.session += 1
            sess = self.session
            self.space_mode = space
            self.target = target
            self.fixes = []
            self.last_view = None
            self.ref = None
            self.stop_ev = ev
        self.thread = threading.Thread(target=self._guard, args=(ev, sess), daemon=True, name="nav")
        self.thread.start()

    def _guard(self, ev, sess):
        """导航线程的兜底（细查 2026-10-28：以前出错就静默停摆、绿灯还亮着）：记日志、重来最多 3 次，再不行发「导航出错」"""
        for attempt in range(3):
            try:
                self._run(ev, sess)
                return
            except Exception as e:
                import traceback
                msg = f"导航出错（第 {attempt + 1} 次）：{e!r}"
                _T("navigation")._wp_log(msg + "\n" + traceback.format_exc())
                print(msg)
                if ev.is_set() or sess != self.session:
                    return
                if attempt == 2:
                    self._commit(sess, state={"active": True, "target": _T("navigation")._place_row(self.target) if self.target else None,
                                              "here": None, "msgs": [], "status": f"导航出错：{e}（重新开始导航试试）", "help": ""},
                                 hud=f"导航出错：{e}")
                    return
                ev.wait(1)

    def _commit(self, sess, here=None, ref=None, state=None, hud=None, marker=None):
        """导航线程每轮的「落账」（老大审查 2026-10-28 第 6 条）：在锁里核对 session，仍是这次导航才一起
        记位置（last_here / ref）、发窗口（state）、改悬浮窗（hud）、画记号（marker=(目标, data, state, mk_seen)）。
        stop() / 换目标也在这把锁里改 session，所以停了以后旧线程算完的结果不会再冒出来。
        返回 (是否仍有效, 记号这轮画的截图时间)"""
        with self.fix_lock:
            if sess != self.session:
                return False, None
            if here is not None:
                self.last_here = here
            if ref is not None:
                self.ref = ref
            mk = None
            if marker is not None:
                target, data, st, mk_seen = marker
                mk = _T("mining")._marker_tick(target, data, st, mk_seen, ref if ref is not None else self.ref)
            if state is not None:
                bus.publish("nav", dict(state))
            if hud is not None:
                _H()._hud().set("导航", hud)
            return True, mk

    def stop(self):
        with self.fix_lock:                      # 跟 add_fix、_commit 互斥：停了以后旧的定位结果不会再发出来
            self.session += 1
            self.target = None
            self.ref = None                      # 停了基准也清掉：下次开始前记号 / 转向不会拿旧位置算
            self.stop_ev.set()
        if self.thread:
            self.thread.join(2)
        self.thread = None
        _H()._hud().clear("导航")
        _T("mining")._mark_hud(None)
        bus.publish("nav", {"active": False})

    def refresh(self):
        """「立即刷新位置」：马上读一次右上角"""
        _E().pos.reader.next_at = 0.0
        _E().pos.reader.misses = 0

    def add_fix(self, g, clip=None, session=None):
        """太空路标：拿到一次 /showlocation 坐标 → 距离、近了多少、偏离角、多久到，推给窗口和悬浮窗。
        剪贴板监听和 F9 可能拿到同一份坐标：查重、记录、发布都在同一把锁里做，同一份只算一次"""
        from ...navigation import navigate as n
        g = tuple(g)
        with self.fix_lock:
            if session is not None and session != self.session:
                return None                          # 导航已经结束或换了目标
            target = self.target
            if not target or not self.space_mode:
                return None
            dup = (clip is not None and clip == self.clip_seen) or (self.fixes and self.fixes[-1][1] == g)
            if clip is not None:
                self.clip_seen = clip
            if dup:
                return self.last_view
            self.fixes = (self.fixes + [(time.time(), g)])[-10:]
            fixes = list(self.fixes)
            key, hint = _T("navigation").fix_key_hint()
            f = n.fix_guide(fixes, target, prev_arrived=bool(self.last_view and self.last_view.get("arrived")))
            text = n.fix_text(f, key)
            view = {"space": True, "fix": True, "text": text, "direct": f.get("direct"), "arrived": f.get("arrived"),
                    "city": f.get("city"), "close": f.get("close"),
                    "deviation": f.get("deviation"), "delta": f.get("delta"), "eta": f.get("eta"), "qt": f.get("qt"),
                    "aim": f.get("aim"), "fixes": len(fixes)}
            if not f["same_system"]:
                view["far"] = text
            self.last_view = view
            bus.publish("nav", {"active": True, "target": _T("navigation")._place_row(target), "here": view, "msgs": [],
                                "status": f"一键定位：按 {key}（或输入 /showlocation）更新" if hint.startswith("一键定位") else hint,
                                "help": "", "at": time.strftime("%H:%M:%S")})
            _H()._hud().set("导航", f"→ {n.label(target)}\n{text}")
        _T("navigation")._wp_log(f"太空导航定位：{tuple(round(v / 1000, 3) for v in g)} km → {text.splitlines()[0]}")
        return view

    def _run_space(self, target, ev, sess):
        """去太空路标：只用 /showlocation 的坐标（玩家社区的通用做法），不读右上角、不靠机头朝向。
        按一键定位热键 AT 替你输；自己在聊天框输 /showlocation 也行（盯着剪贴板）"""
        from ...navigation import navigate as n
        key, hint = _T("navigation").fix_key_hint()
        with self.fix_lock:
            if sess != self.session:
                return
            bus.publish("nav", {"active": True, "target": _T("navigation")._place_row(target), "here": None, "msgs": [],
                                "status": hint, "help": ""})
            _H()._hud().set("导航", f"→ {n.label(target)}\n" + (f"按 {key} 定位（自动输入 /showlocation）" if hint.startswith("一键定位") else hint))
            self.clip_seen = n.read_clipboard()       # 开始前剪贴板里的旧坐标不算
        while not ev.is_set():
            clip = n.read_clipboard()
            g = n.parse_clip(clip)
            if g and clip != self.clip_seen:
                self.add_fix(g, clip, session=sess)
            ev.wait(0.3)

    def _run(self, ev=None, sess=None):
        from ...navigation import navigate as n
        ev = ev or self.stop_ev
        sess = self.session if sess is None else sess
        target = self.target
        if not target or sess != self.session:
            return
        if self.space_mode:
            return self._run_space(target, ev, sess)
        data = n.load()
        head = f"→ {n.label(target)}"
        state = {"active": True, "target": _T("navigation")._place_row(target), "status": "等待右上角位置信息…", "help": _T("navigation").DI_HELP,
                 "msgs": [], "here": None}
        if not self._commit(sess, state=state, hud=f"{head}\n等待位置信息…")[0]:
            return
        shown = ""
        seen = _E().pos.latest[0]
        steady = _Steady()
        self.refresh()
        clip_seen, tick = n.read_clipboard(), 0       # 读不到右上角时，玩家自己输的 /showlocation 也接住（只在必要时用）
        prev_goal = None                              # 城里分段路线：当前这一段指向的点（站台 / 目的地）
        plan = {}                                     # 城里分段路线：定下来的路线和走到第几段
        mk_seen = None
        here = ref = None
        while not ev.is_set():
            fresh = False
            got = None
            cur = _E().pos.current
            if state["here"] is None and cur[1] and time.time() - cur[0] < _T("navigation").LIVE_STALE:
                # 还没算出位置（停着开始导航、或在 AT 里选完目标才切回游戏）：latest 只在坐标变了才换，
                # 用最近一次读到的完整一份马上算（Codex 2026-10-27）
                got = (cur[1], cur[2] or {}, False)
            elif _E().pos.latest[0] != seen and _E().pos.latest[1]:
                seen, g_di, info = _E().pos.latest
                got = (g_di, info or {}, False)
            elif tick % 3 == 0:
                clip = n.read_clipboard()
                g_clip = n.parse_clip(clip)
                live_ok = time.time() - _E().pos.read_at < _T("navigation").LIVE_STALE        # 右上角读得到：剪贴板的坐标只记下不用（Codex 2026-10-27）
                if g_clip and clip != clip_seen and not live_ok:
                    got = (tuple(g_clip), {"t": time.time()}, True)
                clip_seen = clip if g_clip else clip_seen
            tick += 1
            if got:
                g_di, info, by_clip = got
                if by_clip:                               # /showlocation 的坐标：不掺右上角学来的偏差
                    here = n.locate(g_di, when=info.get("t"), data=data, use_offset=False)
                else:
                    here = n.locate(g_di, when=info.get("t"), data=data, local=info.get("local"),
                                    zone=info.get("zone"), local_ok=info.get("local_ok"))
                ref = (g_di, here, info.get("t"))         # 这轮的基准：落账（_commit）时才写进 self.ref
                if n.is_city(target) and n.is_space(target):      # 拉格朗日点 / 跳跃点空间站里（2026-10-27）
                    # 不在同一个区域：按区域坐电梯分段，指向这一段的电梯门（2026-10-28）
                    goal, steps = n.station_leg(tuple(v / 1000 for v in g_di), target, plan, info.get("inner_zone") or "")
                    prev_goal = goal
                    state["here"] = _T("mining")._station_view(g_di, goal, data, info.get("t"), prev=state.get("here"), info=info)
                    if goal is not target:                # 分段路线：到电梯门不算到达
                        state["here"]["arrived"] = False
                    if steps and not state["here"].get("far"):
                        state["here"]["steps"] = steps
                    else:
                        state["here"].pop("steps", None)
                    shown = state["here"].get("far") or n.station_text(g_di, goal, data, info.get("t"), state["here"].get("arrived"))
                    if state["here"].get("steps"):
                        shown += "\n" + "\n".join(steps)
                elif n.is_space(target):
                    state["here"] = _T("mining")._space_view(g_di, target, data)
                    shown = n.space_text(g_di, target, data)
                else:
                    goal, steps = (n.city_leg(here, target, plan, info.get("inner_zone") or "") if n.is_city(target) else (target, []))
                    if goal is not target and prev_goal is not goal:
                        steady = _Steady()                # 换了一段：方位重新防抖
                    prev_goal = goal
                    state["here"] = _T("mining")._nav_view(here, goal, data, steady, prev=state.get("here"))
                    if goal is not target:                # 分段路线：到站台不算到达，到没到看最终目的地
                        state["here"]["arrived"] = False
                    if steps:                             # 最后一段（出站步行）也留着步骤，标在最后一步
                        state["here"]["steps"] = steps
                    else:
                        state["here"].pop("steps", None)
                    near = n.near_text(here, data)
                    shown = n._short(here, goal, state["here"].get("bearing"), state["here"].get("arrived")) + (f"\n{near}" if near else "")
                    if steps:
                        shown += "\n" + "\n".join(steps)
                    _T("mining")._nav_log(here, info, state["here"])
                cam = _E().cam_filter.check(info.get("camdir"))
                close = state["here"].get("city") and (state["here"].get("direct_m") or 0) < n.CITY_NEAR_M
                if cam and not state["here"].get("arrived") and not state["here"].get("far") and not close:
                    try:                                  # 机头要怎么转（太空里没有南北，靠这个）
                        st = n.steer(g_di, cam, n.target_global(prev_goal or target, data, info.get("t"), ref))
                        stx = n.steer_text(st, walk=n.is_city(target))
                        state["here"]["steer"] = {**st, "text": stx}
                        shown = stx + "\n" + shown
                    except Exception:
                        pass
                fresh = True
            if ev.is_set():
                return
            rd = _E().pos.reader
            on = rd.active
            # 「读不到位置」提示：读到过的话，30 秒内偶尔认岔不提示（玩家反馈 2026-10-30：调试信息开着还一直挂着这句）
            last_ok = getattr(rd, "ok_at", 0.0)
            recent = bool(last_ok and time.time() - last_ok < 30)
            # 没读到新位置时不能让旧方向冒充实时的：先标「暂停更新」，超过 30 秒再教怎么开调试信息（Codex 审查 2026-10-30）
            tip = "" if on else ("\n位置暂停更新，以上是上次结果" if recent else
                                 "\n读不到位置：控制台输入 r_DisplayInfo 2，或聊天框输入 /showlocation")
            stat_text = "右上角调试信息：实时识别位置" if on else _T("navigation").DI_HELP + "（或在聊天框输入 /showlocation）"
            pub = None
            if fresh or state["status"] != stat_text:
                state["status"] = stat_text
                state["at"] = time.strftime("%H:%M:%S")
                pub = state
            # 算的时候被停掉 / 换了目标：_commit 在锁里核对 session，不对就什么都不发、记号不画（老大审查 2026-10-28）
            ok, mk_seen = self._commit(sess, here=here if fresh else None, ref=ref if fresh else None, state=pub,
                                       hud=f"{head}\n{shown or '等待位置信息…'}" + tip,
                                       marker=(prev_goal or target, data, state, mk_seen))
            if not ok:
                return
            time.sleep(0.1)


class _GameEvents:
    """读游戏日志里的量子、管辖区、禁火区、重生事件（2026-10-27）：推给窗口（gamelog），量子一到就马上读一次右上角的位置"""

    def __init__(self):
        self.thread = None
        self.last = {}               # 种类 → (时间, 内容)
        self.arrived_at = 0.0        # 最后一次量子到达（本机时间）

    def start(self):
        if WIN and not self.thread:
            self.thread = threading.Thread(target=self._run, daemon=True, name="game-events")
            self.thread.start()

    def _run(self):
        from ...system.gamelog import EventTail
        tail = EventTail()
        while True:
            if _H()._off("game_events"):
                time.sleep(5)
                continue
            try:
                for t, k, v in tail.poll():
                    self.last[k] = (t, v)
                    if k == "qt_arrived":
                        self.arrived_at = time.time()
                        _E().nav.refresh()                     # 马上读一次位置
                    bus.publish("gamelog", {"kind": k, "value": v, "t": t})
            except Exception:
                pass
            time.sleep(0.5)
