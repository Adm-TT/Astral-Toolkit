"""采矿助手主循环：扫描面板识别、雷达信号、破碎方案、袋子（_Live）

2026-10-28 从 app/services.py 原样剪出来（逻辑没改）。2026-10-30 重构阶段 4 删了 services.py，
用到的函数 / 变量直接到它们所在的模块取，运行时才取，避免互相 import：
_T("mining").xxx = tasks/mining.py，_H().xxx = app/hud_state.py，_E().live / .nav / .pos / .cam_filter = 引擎实例。
用到：_FB_LAST, _ORE_LAST, _area_now, _game_front, _hud, _mark_goal_lines, _note_hud, _off, _where_now, scan_view, settings_key
"""

import importlib
import threading
import time

from .. import bus


def _T(name):
    """sc_mining.tasks 里的模块（运行时才取，避免互相 import）"""
    return importlib.import_module(f"sc_mining.tasks.{name}")


def _H():
    from .. import hud_state

    return hud_state


class _Live:
    """实时读屏：和命令行版同样的投票逻辑，结果推给窗口和悬浮窗"""

    def __init__(self):
        self.stop_ev = threading.Event()
        self.thread = None
        self.lock = (
            threading.Lock()
        )  # 发布结果和「停止」互斥：停止清理之后，旧会话再也写不进来
        self.paused = False  # 游戏不在最前面，暂停识别中
        self.gear_rev = (
            0  # 配置改了几次：变了就把正在显示的石头按新配置重算一遍（2026-10-26）
        )

    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def _emit(self, ev, fn):
        """只有本会话还没停时才把结果推给窗口/悬浮窗（识别和计算很慢，算完时可能已经停了）"""
        with self.lock:
            if ev.is_set():
                return False
            fn()
            return True

    STALE_SECONDS = (
        20  # 扫描面板 / 信号消失这么久：算目标丢失，悬浮窗清掉，窗口里标「已过期」
    )
    RECHECK_SECONDS = (
        5  # 画面静止省电时，也每隔这么久复核一次（防止面板里的数变了但整屏几乎没变）
    )
    MISS_FRAMES = (
        4  # 看得到扫描面板、却连续这么多帧读不全 / 读不稳：自动留一张图（排查用）
    )
    MISS_GAP = 30  # 两次留图至少隔这么多秒
    MISS_KEEP = 10  # 最多留这么多张（userdata\shots\miss，每张 5MB 左右）
    IDLE_CLOSE = 120  # 这么多秒没看到扫描面板、也没认到信号：自动关掉采矿助手（用户 2026-10-25；切出游戏暂停的那段不算）

    def _save_miss(self, img, why, raw, log):
        """采矿助手没出结果的画面自动存下来：之后从这些图找原因（2026-10-23 用户反馈「部分矿物扫描失败」，当时没有图）"""
        from ...core import paths

        stamp = time.strftime("%H%M%S")
        try:
            log.write(f"{time.strftime('%F %T')} MISS {why} {raw}\n")
            log.flush()
        except (OSError, ValueError):
            pass

        def save():
            try:
                d = paths.shots("miss")
                img.save(d / f"{stamp}.png")
                for f in sorted(d.glob("*.png"), key=lambda f: f.stat().st_mtime)[
                    : -self.MISS_KEEP
                ]:
                    f.unlink()
            except OSError:
                pass

        threading.Thread(target=save, daemon=True).start()

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

    def _hint(self, ev, hint, why, log, clear_hud=False):
        """采矿助手读不全时告诉玩家原因（采矿助手页 + 悬浮窗）；why=None 收起（clear_hud：悬浮窗上的提示也擦掉；
        刚发了新结果时不擦，悬浮窗上已经是新结果了）"""
        hint["why"] = why
        text, short = self.HINTS.get(why, ("", ""))
        if why:
            try:
                log.write(f"{time.strftime('%F %T')} HINT {why}\n")
                log.flush()
            except (OSError, ValueError):
                pass

        def tell():
            bus.publish(
                "scan_hint",
                {"why": why or "", "text": text, "at": time.strftime("%H:%M:%S")},
            )
            if why:
                _H()._hud().set("扫描", short)
            elif clear_hud:
                _H()._hud().clear("扫描")

        self._emit(ev, tell)

    def _set_paused(self, ev, on, log, gap=0.0):
        """暂停 / 继续：记一行日志，告诉窗口（采矿助手页和左边的小灯）"""
        msg = (
            "游戏不在最前面，暂停识别"
            if on
            else f"回到游戏，继续识别（暂停了 {gap:.0f} 秒）"
        )
        bus.runtime_log(msg, tag="LIVE", level="WARN" if on else "INFO")
        try:
            log.write(
                f"{time.strftime('%F %T')} "
                + (
                    "PAUSE 游戏不在最前面，暂停识别"
                    if on
                    else f"RESUME 回到游戏，继续识别（暂停了 {gap:.0f} 秒）"
                )
                + "\n"
            )
            log.flush()
        except (OSError, ValueError):
            pass

        def tell():
            self.paused = on
            bus.publish("live", {"running": True, "paused": on})

        self._emit(ev, tell)

    def start(self):
        if self.running():
            return
        self.paused = False
        bus.runtime_log("采矿助手实时识别引擎已启动", tag="LIVE", level="INFO")
        # 每次开始都是一个新的会话（自己的停止开关）：快速停了又开，旧线程哪怕还没退出也只认自己的开关，
        # 不会和新线程一起往悬浮窗写东西
        self.stop_ev = ev = threading.Event()
        self.thread = threading.Thread(
            target=self._run_gpu, args=(ev,), daemon=True, name="live"
        )
        self.thread.start()
        bus.publish("live", {"running": True})

    def _run_gpu(self, ev):
        """跑采矿助手（出错最多重试 3 次）。识别引擎在主进程里，按设置用显卡（DirectML）或 CPU，采矿助手关掉后引擎照样留着；
        gpu_ocr 现在只是兼容层：acquire 只是顺带把引擎建好（还没建的话），release 什么都不做（以前的显卡识别小进程 NGU 重构时去掉了，2026-10-31 控制台定认现状）"""
        from ...system import gpu_ocr

        try:
            gpu_ocr.acquire()
        except Exception:
            pass
        try:
            for attempt in range(3):
                try:
                    self._run(ev)
                    break
                except Exception as e:
                    import traceback
                    from ...core import paths

                    msg = f"采矿助手出错（第 {attempt + 1} 次）：{e!r}"
                    try:
                        with open(
                            paths.log("live_log.txt"), "a", encoding="utf-8"
                        ) as f:
                            f.write(
                                f"{time.strftime('%F %T')} ERROR {msg}\n{traceback.format_exc()}"
                            )
                    except OSError:
                        pass
                    print(msg)
                    if ev.is_set():
                        break
                    if attempt == 2:
                        self._fail_off(ev, str(e))
                        break
                    with (
                        self.lock
                    ):  # 重来前把上一轮的旧结果清掉（新一轮的过期清理不认旧的）
                        for k in ("信号", "扫描", "矿袋"):
                            _H()._hud().clear(k)
                    ev.wait(1)
        finally:
            try:
                gpu_ocr.release()
            except Exception:
                pass

    def _fail_off(self, ev, why):
        """连着出错：自己关掉并告诉玩家（和 _auto_off 一样收尾）"""
        from ...core import settings

        with self.lock:
            if ev.is_set():
                return
            ev.set()
            self.paused = False
            for k in ("信号", "扫描", "矿袋"):
                _H()._hud().clear(k)
        try:
            settings.update(live_on=False)
        except Exception:
            pass
        bus.publish("scan_hint", {"why": "", "text": ""})
        bus.publish("live", {"running": False, "error": why})
        _H()._note_hud(
            "采矿助手",
            f"采矿助手出错已关闭｜按 {_T('navigation').settings_key('live_key', 'F5')} 重开（详情见日志）",
        )

    def _auto_off(self, ev, log):
        """太久没看到扫描面板和信号：自己关掉（在识别线程里调用，不能 join 自己）"""
        from ...core import settings

        try:
            log.write(
                f"{time.strftime('%F %T')} AUTO_OFF {self.IDLE_CLOSE} 秒没看到扫描面板和信号，采矿助手自动关闭\n"
            )
            log.flush()
        except (OSError, ValueError):
            pass
        with self.lock:
            if ev.is_set():
                return
            ev.set()
            self.paused = False
            for k in ("信号", "扫描", "矿袋"):
                _H()._hud().clear(k)
        settings.update(live_on=False)
        bus.publish("scan_hint", {"why": "", "text": ""})
        bus.publish("live", {"running": False, "auto_off": True})
        _H()._note_hud(
            "采矿助手",
            f"采矿助手已关闭｜按 {_T('navigation').settings_key('live_key', 'F5')} 开启",
        )

    def stop(self):
        with self.lock:
            self.stop_ev.set()
        if self.thread:
            self.thread.join(3)
        self.thread = None
        with self.lock:
            self.paused = False
            for k in ("信号", "扫描", "矿袋"):
                _H()._hud().clear(k)
        bus.runtime_log("采矿助手实时识别引擎已停止", tag="LIVE", level="INFO")
        bus.publish("scan_hint", {"why": "", "text": ""})
        bus.publish("live", {"running": False})

    def _run(self, ev=None):
        import collections
        import numpy as np
        from ...core import paths
        from ...mining import screen
        from ...mining.signals import find_signatures, describe_all, match_signature

        ev = ev or self.stop_ev
        alive = lambda: not ev.is_set()  # 只看本会话的开关  # noqa: E731
        shots = paths.shots("live")
        log = open(paths.log("live_log.txt"), "a", encoding="utf-8")
        recent = collections.deque(maxlen=screen.VOTE_FRAMES)
        part = collections.deque(
            maxlen=screen.VOTE_FRAMES
        )  # 面板被屏幕右边挡住时（只读到质量/抗性/不稳定性）的投票队列
        hint = {"why": None}  # 现在显示着的「读不全」原因提示
        last_key, sig_prev, sig_shown = None, None, None
        l, t, r, b = screen.SEARCH  # noqa: E741
        try:
            prev_small, prev_panel, same, settled, done_here = None, None, 0, False, 0
            last_shown, last_full, last_view, last_sig_msg = None, 0.0, {}, None
            miss_n, unstable_n, miss_t = 0, 0, 0.0
            now = time.time()
            last_panel_t, last_sig_t, scan_live, sig_live, missing = (
                now,
                now,
                False,
                False,
                0,
            )
            paused_at = None
            while alive():
                # 游戏不在最前面（切到聊天、浏览器、天枢窗口）就不认扫描面板和信号：别的窗口里的「质量: 12431」会被当成面板，
                # 聊天里的 0.495 会被当成信号（2026-10-23 用户同意）。已经出的结果原样留着、过期计时也停住，
                # 回到游戏马上接着认；判断不了（不是 Windows、读不到前台窗口）照常认
                if _T("mining")._game_front() is False:
                    if paused_at is None:
                        paused_at = time.time()
                        miss_n = unstable_n = 0
                        self._set_paused(ev, True, log)
                    ev.wait(min(screen.INTERVAL, 0.25))
                    continue
                if paused_at is not None:
                    gap = time.time() - paused_at
                    last_panel_t += gap  # 暂停的这段不算「面板 / 信号消失了」
                    last_sig_t += gap
                    prev_small = prev_panel = (
                        None  # 回来的第一帧一定重新认，不按「画面没变」跳过
                    )
                    paused_at = None
                    self._set_paused(ev, False, log, gap)
                if time.time() - max(last_panel_t, last_sig_t) > self.IDLE_CLOSE:
                    self._auto_off(ev, log)
                    break
                img = screen.grab()
                now = time.time()
                # 省电：画面几乎没变、这个画面已经出过结果（或根本没有面板）就不重复识别。
                # 整屏缩小比一次，扫描面板那块再单独细一点比一次（面板里数字变了、整屏几乎没变的情况）
                small = np.asarray(
                    img.reduce(max(1, img.width // 160)).convert("L"), dtype=np.int16
                )
                W, H = img.size
                panel = np.asarray(
                    img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
                    .reduce(max(1, img.width // 640))
                    .convert("L"),
                    dtype=np.int16,
                )
                still = (
                    prev_small is not None
                    and prev_panel is not None
                    and prev_panel.shape == panel.shape
                    and np.abs(small - prev_small).mean() < 1.5
                    and np.abs(panel - prev_panel).mean() < 1.0
                )
                if still:
                    same += 1
                else:
                    same, settled, done_here = 0, False, 0
                prev_small, prev_panel = small, panel
                # 结果失效按时间算，省电跳过识别时也要检查（画面静止时面板早没了，也得清掉）
                # 过期的结果带上 stale 标记重新发一次（总线会保存最后一条 scan / signals，窗口刷新、重连后也看得到「已过期」）
                if sig_live and now - last_sig_t > self.STALE_SECONDS:
                    sig_live, sig_shown = (
                        False,
                        None,
                    )  # 信号没了：悬浮窗清掉，窗口里标过期
                    since = time.strftime("%H:%M:%S", time.localtime(last_sig_t))
                    self._emit(
                        ev,
                        lambda: (
                            _H()._hud().clear("信号"),
                            bus.publish(
                                "signals",
                                {**(last_sig_msg or {"lines": []}), "stale": since},
                            ),
                        ),
                    )
                if hint["why"] and now - last_panel_t > self.STALE_SECONDS:
                    self._hint(
                        ev, hint, None, log, clear_hud=True
                    )  # 面板不在了：「读不全」提示也收起
                if scan_live and now - last_panel_t > self.STALE_SECONDS:
                    scan_live, last_shown, last_key = (
                        False,
                        None,
                        None,
                    )  # 面板消失太久：结果作废
                    recent.clear()
                    part.clear()
                    since = time.strftime("%H:%M:%S", time.localtime(last_panel_t))
                    self._emit(
                        ev,
                        lambda: (
                            _H()._hud().clear("扫描"),
                            _H()._hud().clear("矿袋"),
                            bus.publish("scan", {**last_view, "stale": since}),
                        ),
                    )
                if same >= 2 and settled and now - last_full < self.RECHECK_SECONDS:
                    ev.wait(screen.INTERVAL)
                    continue
                last_full = now
                # ---- 扫描面板（先看有没有面板：有面板时屏幕上的质量等数字会被当成信号，信号识别就暂停）
                scan, bag = screen.analyse(img)
                raw = (
                    screen.LAST_RAW.get("scan")
                    if screen.LAST_RAW.get("t", 0) >= now
                    else None
                )
                # 真有面板才算（读全了，或认出面板上的字 / 带矿名的成分）。只读到几个零散数字不算：勘探者驾驶舱右边的
                # 高度表、气压会被拼成「质量 0.7、抗性 76」，以前因此一直当面板开着，信号识别整段暂停（2026-10-23 Calliope）
                panel_now = screen.panel_seen(scan, raw)
                if (
                    panel_now
                ):  # 看着面板：读位置别占识别引擎（2026-10-27 悬浮窗晚 10–18 秒）
                    from ...navigation.displayinfo import yield_ocr

                    yield_ocr()
                scan_off = bool(_H()._off("scan"))
                if scan_off:  # 远程关了：面板在不在照样判断（雷达靠它避开面板上的数字），结果不用；
                    from ...mining.parse import (
                        parse_scan,
                        parse_bag,
                    )  # 投票队列清掉、悬浮窗旧结果收起、不算「读不全」（Codex 2026-10-27）

                    scan, bag = parse_scan([]), parse_bag([])
                    recent.clear()
                    part.clear()
                    if not getattr(self, "_scan_off_cleared", False):
                        self._scan_off_cleared = True
                        self._emit(
                            ev,
                            lambda: (
                                _H()._hud().clear("扫描"),
                                _H()._hud().clear("矿袋"),
                            ),
                        )
                else:
                    self._scan_off_cleared = False
                # 面板顶着屏幕右边、被挡住一截（16:10 屏幕上鼹鼠炮塔的面板，2026-10-23 用户反馈）：品质和总 SCU 在屏幕外面，
                # 质量、抗性、不稳定性读到了就照样算破碎方案（part 队列，两帧一致才出）
                cut = panel_now and bool(screen.LAST_PANEL.get("cut"))
                part_ok = (
                    not scan.valid
                    and cut
                    and scan.complete
                    and (scan.mass or 0) >= 500
                    and 0 <= scan.resistance <= 100
                )
                if part_ok:
                    screen.enqueue_rock(part, scan)  # 同一块石头才进投票队列
                elif scan.valid or not panel_now:
                    part.clear()
                # 面板在却读不全：连续几帧这样就留一张图，并告诉玩家可能的原因（被屏幕挡住 / 字有色差重影）
                miss_n = (
                    0
                    if (scan_off or scan.valid or not panel_now or part_ok)
                    else miss_n + 1
                )
                if miss_n >= self.MISS_FRAMES and now - miss_t > self.MISS_GAP:
                    miss_t, miss_n = now, 0
                    self._save_miss(img, "读不全", raw, log)
                    why = screen.miss_reason(img)
                    if why and why != hint["why"]:
                        self._hint(ev, hint, why, log)
                if panel_now and sig_live:
                    sig_live, sig_shown, sig_prev = (
                        False,
                        None,
                        None,
                    )  # 对着石头看面板：悬浮窗收起信号
                    self._emit(ev, lambda: _H()._hud().clear("信号"))
                # ---- 雷达信号（扫描面板开着时不认，2026-10-23 用户反馈把石头质量 13,586 当成了信号）
                try:
                    found = (
                        [] if panel_now or _H()._off("radar") else find_signatures(img)
                    )
                    sigs = frozenset(v for v, *_ in found)
                    if sigs:
                        last_sig_t = now
                        from ...navigation.displayinfo import yield_ocr

                        yield_ocr()
                    area = (
                        _T("navigation")._area_now()
                        if sigs and sigs == sig_prev
                        else None
                    )
                    # 产矿区变了（飞进矿带、跳跃）也要重新发：以前只看信号数值，同样的 7,200 会一直停在旧地点的说法
                    from ...mining.mining_area import rocks_stamp
                    from ...mining.signals import _mine_file
                    from ...core.paths import file_stamp

                    shown_key = (
                        sigs,
                        frozenset((v, f) for v, f, *_ in found),
                        (area or {}).get("name"),
                        (area or {}).get("zh"),
                        rocks_stamp(),
                        file_stamp(_mine_file()),
                    )  # 换了石头表、读数改没改过、自己起了名都重发
                    if sigs and sigs == sig_prev and shown_key != sig_shown and alive():
                        where = (
                            _T("navigation")._where_now()
                            if any(not match_signature(v) for v in sigs)
                            else None
                        )
                        lines = _T("goals")._mark_goal_lines(
                            describe_all(found, where, area)
                        )
                        from ...mining.signals import guesses as _g

                        unknown = [
                            v
                            for v in sorted(sigs)
                            if v and not any(e for *_, e in _g(v, where, area))
                        ]
                        msg = {
                            "lines": lines,
                            "at": time.strftime("%H:%M:%S"),
                            "area": (area or {}).get("zh", ""),
                            "unknown": unknown,
                        }  # 没认准的：窗口里可以起名记下（2026-10-27）
                        if self._emit(
                            ev,
                            lambda: (
                                bus.publish("signals", msg),
                                _H()
                                ._hud()
                                .set(
                                    "信号",
                                    "\n".join(
                                        x.split("｜精炼后")[0].replace("信号 ", "")
                                        for x in lines[:4]
                                    ),
                                ),
                            ),
                        ):
                            sig_shown, sig_live, last_sig_msg = shown_key, True, msg
                            _T("system")._FB_LAST["sig"] = {
                                **msg,
                                "values": sorted(sigs),
                            }
                            bus.runtime_log(
                                f"雷达信号: {sorted(sigs)} 产区: {(area or {}).get('zh') or '未知'}",
                                tag="SIGNAL",
                                level="INFO",
                            )
                            log.write(
                                f"{time.strftime('%F %T')} SIG {sorted(sigs)} 产矿区={(area or {}).get('zh') or '未知'}\n"
                            )
                            log.flush()
                    sig_prev = sigs
                except Exception as e:
                    bus.publish("log", {"task": "live", "line": f"信号识别失败：{e}"})
                done_here += 1
                if panel_now and not scan_off:
                    last_panel_t, missing = now, 0
                else:
                    missing += 1
                    if missing >= 3:
                        recent.clear()  # 目标丢了（连续 3 帧没面板）：投票队列重来，别把下一块石头混进来
                    if not scan.valid:
                        settled = same >= 2  # 画面里没有扫描面板，静止时不用一直认
                if scan.valid:
                    if screen.enqueue_rock(recent, scan, bag):
                        unstable_n = 0  # 换了石头：投票队列重计
                    # 这一帧和队列里的石头对不上、被当成可疑帧先记下（没进队列）：这次不投票、不发结果。
                    # 以前照样拿队列里上一块石头的帧投票，换石头后的第一帧会把上一块的结果又发一遍（2026-10-24 玩家反馈：
                    # 画面是 5561 / 18.35 SCU 的新石头，发出去的是上一块 10187 / 33.71 SCU）
                    accepted = bool(recent) and recent[-1][0] is scan
                    if accepted and len(recent) >= 2:
                        best, stable = screen.vote([x[0] for x in recent])
                        # 每帧都读全了、但几帧之间对不上（投不出结果）：也算没出结果，留一张图
                        unstable_n = 0 if stable else unstable_n + 1
                        if (
                            unstable_n >= self.MISS_FRAMES + 1
                            and now - miss_t > self.MISS_GAP
                        ):
                            miss_t, unstable_n = now, 0
                            self._save_miss(
                                img,
                                "读不稳",
                                [str(x[0]) for x in list(recent)[-3:]],
                                log,
                            )
                        key = (round(best.mass), best.resistance, best.instability)
                        # 任何影响计算的字段变了（总 SCU、成分、评级、矿袋）都重新发布，修正后的数也要推出去
                        shown = (
                            key,
                            best.total_scu,
                            best.rock,
                            best.difficulty,
                            tuple(best.composition),
                            recent[-1][1][1],
                            self.gear_rev,
                        )
                        if stable and best.valid and shown != last_shown and alive():
                            view = _T("mining").scan_view(
                                best, recent[-1][1]
                            )  # 慢：算完再看一次有没有停

                            def publish():
                                bus.publish("scan", view)
                                bus.runtime_log(
                                    f"扫描岩石: {best.rock or '岩石'} (质量 {round(best.mass)} | 矿量 {best.total_scu:.1f} SCU)",
                                    tag="SCAN",
                                    level="INFO",
                                )
                                _H()._hud().set(
                                    "扫描", view["hud"], view.get("hud_rich")
                                )
                                if view["bag_text"]:
                                    _H()._hud().set("矿袋", view["bag_text"])

                            if not self._emit(ev, publish):
                                break
                            if hint["why"]:
                                self._hint(ev, hint, None, log)
                            last_key, last_shown, scan_live, last_view = (
                                key,
                                shown,
                                True,
                                view,
                            )
                            _T("system")._ORE_LAST["view"] = view
                            _T("system")._FB_LAST["scan"] = {
                                "rock": view.get("rock"),
                                "mass": view.get("mass"),
                                "resistance": view.get("resistance"),
                                "instability": view.get("instability"),
                                "minerals": view.get("minerals"),
                                "at": view.get("at"),
                            }
                            log.write(
                                f"{time.strftime('%F %T')} {best} {recent[-1][1]}\n"
                            )
                            log.flush()
                            try:
                                img.save(shots / f"{time.strftime('%H%M%S')}.png")
                                for f in sorted(shots.glob("*.png"))[:-20]:
                                    f.unlink()
                            except OSError:
                                pass
                    # 同一个画面认够一轮投票（5 帧）、结果也出了，就不再重复认（每 RECHECK_SECONDS 秒仍复核一次）
                    settled = last_shown is not None and done_here >= screen.VOTE_FRAMES
                elif part_ok and len(part) >= 2:
                    best, stable = screen.vote_partial([x[0] for x in part])
                    # 读一半的帧（面板顶出屏幕）连续两帧一致、又和完整读数队列里的石头不是同一块：说明已经换了石头，
                    # 旧石头的完整读数作废（不然转回来读全时，第一帧新石头会被当成可疑帧挡掉，旧结果又冒出来）
                    # 只看质量（差 1% 以上才算换了）：同一块石头开着激光时抗性会变（45% ↔ 65%），不能因此清掉
                    prev_rock = recent[-1][0] if recent else None
                    if (
                        stable
                        and prev_rock is not None
                        and best.mass
                        and prev_rock.mass
                        and abs(best.mass - prev_rock.mass) / prev_rock.mass >= 0.01
                    ):
                        recent.clear()
                    shown = (
                        "cut",
                        round(best.mass),
                        best.resistance,
                        best.instability,
                        best.rock,
                        best.difficulty,
                        tuple(best.composition),
                        self.gear_rev,
                    )
                    if stable and shown != last_shown and alive():
                        view = _T("mining").scan_view(best, bag, cut=True)
                        if not self._emit(
                            ev,
                            lambda: (
                                bus.publish("scan", view),
                                _H()
                                ._hud()
                                .set("扫描", view["hud"], view.get("hud_rich")),
                            ),
                        ):
                            break
                        if hint["why"]:
                            self._hint(ev, hint, None, log)
                        last_key, last_shown, scan_live, last_view = (
                            None,
                            shown,
                            True,
                            view,
                        )  # noqa: F841
                        _T("system")._ORE_LAST["view"] = view
                        _T("system")._FB_LAST["scan"] = {
                            "rock": view.get("rock"),
                            "mass": view.get("mass"),
                            "resistance": view.get("resistance"),
                            "instability": view.get("instability"),
                            "cut": True,
                            "at": view.get("at"),
                        }
                        log.write(
                            f"{time.strftime('%F %T')} PART 面板被屏幕挡住，只算破碎 {best}\n"
                        )
                        log.flush()
                    settled = last_shown is not None and done_here >= screen.VOTE_FRAMES
                ev.wait(screen.INTERVAL)
        finally:
            log.close()
