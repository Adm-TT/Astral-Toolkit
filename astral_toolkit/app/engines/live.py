"""采矿助手主循环：扫描面板识别、雷达信号、破碎方案、袋子（_Live）

2026-10-28 从 app/services.py 原样剪出来（逻辑没改）。2026-10-30 重构阶段 4 删了 services.py，
用到的函数 / 变量直接到它们所在的模块取，运行时才取，避免互相 import：
_T("mining").xxx = tasks/mining.py，_H().xxx = app/hud_state.py，_E().live / .nav / .pos / .cam_filter = 引擎实例。
用到：_area_now, _game_front, _hud, _mark_goal_lines, _note_hud, _off, _where_now, scan_view, settings_key

RT-B4：线程、停止、提交边界、暂停 / 过期 / 自动关闭 / 重试都搬进 runtime/session.py 的 SessionLoop，
这里只剩「一轮识别」这一层：setup / tick / on_pause / on_resume / on_stale / finish_ops / teardown。
一个会话的识别状态放在 _Ctx 里（按会话号分开）：停止超时后旧线程还卡在识别里时，不会写坏新会话的投票队列。
"""

import collections
import importlib
import threading
import time
from typing import Any

from ...runtime.results import MINING_SCAN, MINING_SIGNALS, ResultStore
from ...runtime.session import RunState, SessionLoop, Tick
from ..output import BusOutput


def _T(name):
    """astral_toolkit.tasks 里的模块（运行时才取，避免互相 import）"""
    return importlib.import_module(f"astral_toolkit.tasks.{name}")


def _H():
    from .. import hud_state

    return hud_state


def _pub(kind, data):
    return ("bus", kind, data)


def _say(line, tag):
    return ("log", line, tag)


def _set(*args):
    return ("hud.set", *args)


def _del(section):
    return ("hud.clear", section)


def _note(section, text, secs=None):
    return ("note", section, text, secs)


def _foreground():
    """游戏在不在最前面：True / False；判断不了返回 None（照常识别）"""
    return _T("mining")._game_front()


class _Ctx:
    """一个会话自己的识别状态：旧线程停在识别里时，新会话的投票队列不被它清掉 / 混进来"""

    def __init__(self, log, shots, now):
        from ...mining import screen

        self.log = log
        self.shots = shots
        self.recent = collections.deque(maxlen=screen.VOTE_FRAMES)
        self.part = collections.deque(maxlen=screen.VOTE_FRAMES)
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
        self.last_panel_t = now
        self.last_sig_t = now
        self.scan_live = False
        self.sig_live = False
        self.missing = 0
        self.scan_off_cleared = False


class _Live:
    """实时读屏：和命令行版同样的投票逻辑，结果推给窗口和悬浮窗"""

    # ---- 会话循环要的类属性（设计稿 §2.2）
    name = "live"
    retries = 3
    idle_close: float | None = (
        120.0  # 这么多秒没看到扫描面板、也没认到信号：自动关掉采矿助手（切出游戏那段不算）
    )
    stale_after: float | None = (
        20.0  # 扫描面板 / 信号消失这么久：算目标丢失，悬浮窗清掉，窗口里标「已过期」
    )
    needs_foreground = True
    restart_while_stopping = True

    RECHECK_SECONDS = (
        5  # 画面静止省电时，也每隔这么久复核一次（防止面板里的数变了但整屏几乎没变）
    )
    MISS_FRAMES = (
        4  # 看得到扫描面板、却连续这么多帧读不全 / 读不稳：自动留一张图（排查用）
    )
    MISS_GAP = 30  # 两次留图至少隔这么多秒
    MISS_KEEP = 10  # 最多留这么多张（userdata\\shots\\miss，每张 5MB 左右）

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

    def __init__(self, results=None, output=None, clock=None):
        self.results = results if results is not None else ResultStore()
        self.gear_rev = (
            0  # 配置改了几次：变了就把正在显示的石头按新配置重算一遍（2026-10-26）
        )
        self._ctx: dict[int, _Ctx] = {}
        self._error = ""
        self._hotkey: str | None = None
        self._empty_ev = threading.Event()
        self.loop: Any = SessionLoop(
            self,
            results=self.results,
            output=output if output is not None else BusOutput(),
            foreground=_foreground,
            clock=clock,
            settings_flag="live_on",
        )

    # ---------------------------------------------------------------- 兼容转发（RT-B7 删）
    def running(self):  # RT-B7 删
        return self.loop.running()

    @property
    def paused(self):  # RT-B7 删
        return self.loop.state().state is RunState.PAUSED

    @property
    def stop_ev(self):  # RT-B7 删
        session = self.loop._session
        return session.cancel if session is not None else self._empty_ev

    @property
    def session_id(self):  # RT-B7 删
        return self.loop.state().session_id

    @property
    def epoch(self):  # RT-B7 删
        return self.loop.state().epoch

    @property
    def lock(self):  # RT-B7 删
        return self.loop._lock

    def start(self):
        if self.loop.running():
            return
        from ...core import run_records

        run_records.record("MINING", "采矿助手引擎已启动", ui_tag="LIVE")
        self.loop.start()

    def stop(self):
        from ...core import run_records

        run_records.record("MINING", "采矿助手引擎已停止", ui_tag="LIVE")
        self.loop.request_stop("user")
        self.loop.join()

    def config_changed(self):
        """配装变了：正在算的结果作废，正在显示的石头按新配装重算（采矿助手最多 5 秒后重新发布）"""
        self.gear_rev += 1
        self.loop.config_changed()

    # ---------------------------------------------------------------- Worker：会话循环调这些
    def setup(self, session):
        from ...core import paths

        log = open(paths.log("live_log.txt"), "a", encoding="utf-8")
        self._ctx[session.id] = _Ctx(log, paths.shots("live"), time.time())
        if self._hotkey is None:
            self._hotkey = _T("navigation").settings_key("live_key", "F5")

    def teardown(self, session):
        ctx = self._ctx.pop(session.id, None)
        if ctx is not None:
            ctx.log.close()

    def start_ops(self, session):
        return [_pub("live", {"running": True})]

    def retry_ops(self, session):
        """重来前把上一轮的旧结果清掉（新一轮的过期清理不认旧的）"""
        return [_del("信号"), _del("扫描"), _del("矿袋")]

    def on_error(self, attempt, exc):
        import traceback

        from ...core import paths

        self._error = str(exc)
        msg = f"采矿助手出错（第 {attempt + 1} 次）：{exc!r}"
        try:
            with open(paths.log("live_log.txt"), "a", encoding="utf-8") as f:
                f.write(
                    f"{time.strftime('%F %T')} ERROR {msg}\n{traceback.format_exc()}"
                )
        except OSError:
            pass
        print(msg)

    def on_stop(self, session, reason):
        if reason != "idle":
            return
        ctx = self._ctx.get(session.id)
        if ctx is None:
            return
        try:
            ctx.log.write(
                f"{time.strftime('%F %T')} AUTO_OFF {self.idle_close or 0:.0f} 秒没看到扫描面板和信号，采矿助手自动关闭\n"
            )
            ctx.log.flush()
        except (OSError, ValueError):
            pass

    def finish_ops(self, session, reason):
        """会话结束时要发的东西（循环在锁内按序套用）：清三块悬浮窗 + 窗口状态 + 一句提示"""
        ops = [
            _del("信号"),
            _del("扫描"),
            _del("矿袋"),
            _pub("scan_hint", {"why": "", "text": ""}),
        ]
        key = self._hotkey or "F5"
        if reason == "error":
            ops.append(_pub("live", {"running": False, "error": self._error}))
            ops.append(
                _note("采矿助手", f"采矿助手出错已关闭｜按 {key} 重开（详情见日志）")
            )
        elif reason == "idle":
            ops.append(_pub("live", {"running": False, "auto_off": True}))
            ops.append(_note("采矿助手", f"采矿助手已关闭｜按 {key} 开启"))
        else:
            ops.append(_pub("live", {"running": False}))
        return ops

    def on_pause(self, session):
        ctx = self._ctx.get(session.id)
        if ctx is None:
            return
        ctx.miss_n = ctx.unstable_n = 0
        self._set_paused(session, ctx, True)

    def on_resume(self, session, gap):
        ctx = self._ctx.get(session.id)
        if ctx is None:
            return
        ctx.prev_small = ctx.prev_panel = (
            None  # 回来的第一帧一定重新认，不按「画面没变」跳过
        )
        self._set_paused(session, ctx, False, gap)

    def on_stale(self, session, slot):
        ctx = self._ctx.get(session.id)
        if ctx is None:
            return
        if slot == MINING_SIGNALS and ctx.sig_live:
            ctx.sig_live, ctx.sig_shown = (
                False,
                None,
            )  # 信号没了：悬浮窗清掉，窗口里标过期
            since = time.strftime("%H:%M:%S", time.localtime(ctx.last_sig_t))
            shown_sig = self.results.get(MINING_SIGNALS)
            self.loop.commit(
                session,
                _del("信号"),
                _pub(
                    "signals",
                    {
                        **(shown_sig.value["view"] if shown_sig else {"lines": []}),
                        "stale": since,
                    },
                ),
            )
        elif slot == MINING_SCAN:
            if ctx.hint["why"]:
                self._hint(
                    session, ctx, None, clear_hud=True
                )  # 面板不在了：读不全提示也收起
            if ctx.scan_live:
                ctx.scan_live, ctx.last_shown, ctx.last_key = False, None, None
                ctx.recent.clear()
                ctx.part.clear()
                since = time.strftime("%H:%M:%S", time.localtime(ctx.last_panel_t))
                shown_scan = self.results.get(MINING_SCAN)
                self.loop.commit(
                    session,
                    _del("扫描"),
                    _del("矿袋"),
                    _pub(
                        "scan",
                        {**(shown_scan.value if shown_scan else {}), "stale": since},
                    ),
                )

    # ---------------------------------------------------------------- 一轮识别
    def tick(self, session, now):
        import numpy as np

        from ...mining import screen
        from ...mining.signals import describe_all, find_signatures, match_signature

        ctx = self._ctx[session.id]
        log = ctx.log
        img = screen.grab()
        l, t, r, b = screen.SEARCH  # noqa: E741
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
            return Tick(screen.INTERVAL, False, frozenset())
        ctx.last_full = now
        stamp = self.loop.stamp(session, now)
        if stamp is None:
            return Tick(screen.INTERVAL, False, frozenset())
        # ---- 扫描面板（先看有没有面板：有面板时屏幕上的质量等数字会被当成信号，信号识别就暂停）
        scan, bag = screen.analyse(img)
        raw = (
            screen.LAST_RAW.get("scan") if screen.LAST_RAW.get("t", 0) >= now else None
        )
        # 真有面板才算（读全了，或认出面板上的字 / 带矿名的成分）。只读到几个零散数字不算：勘探者驾驶舱右边的
        # 高度表、气压会被拼成「质量 0.7、抗性 76」，以前因此一直当面板开着，信号识别整段暂停（2026-10-23 Calliope）
        panel_now = screen.panel_seen(scan, raw)
        if panel_now:  # 看着面板：读位置别占识别引擎（2026-10-27 悬浮窗晚 10–18 秒）
            from ...navigation.displayinfo import yield_ocr

            yield_ocr()
        scan_off = bool(_H()._off("scan"))
        if (
            scan_off
        ):  # 远程关了：面板在不在照样判断（雷达靠它避开面板上的数字），结果不用；
            from ...mining.parse import parse_bag, parse_scan

            scan, bag = parse_scan([]), parse_bag([])
            ctx.recent.clear()
            ctx.part.clear()
            if not ctx.scan_off_cleared:
                ctx.scan_off_cleared = True
                self.loop.commit(session, _del("扫描"), _del("矿袋"))
        else:
            ctx.scan_off_cleared = False
        # 面板顶着屏幕右边、被挡住一截（16:10 屏幕上鼹鼠炮塔的面板，2026-10-23 用户反馈）：品质和总 SCU 在屏幕外面，
        # 质量、抗性、不稳定性读到了就照样算破碎方案（part 队列，两帧一致才出）
        cut = panel_now and bool(screen.LAST_PANEL.get("cut"))
        part_ok = (
            not scan.valid
            and cut
            and scan.complete
            and (scan.mass or 0) >= 500
            and scan.resistance is not None
            and 0 <= scan.resistance <= 100
        )
        if part_ok:
            screen.enqueue_rock(ctx.part, scan)  # 同一块石头才进投票队列
        elif scan.valid or not panel_now:
            ctx.part.clear()
        # 面板在却读不全：连续几帧这样就留一张图，并告诉玩家可能的原因（被屏幕挡住 / 字有色差重影）
        ctx.miss_n = (
            0
            if (scan_off or scan.valid or not panel_now or part_ok)
            else ctx.miss_n + 1
        )
        if ctx.miss_n >= self.MISS_FRAMES and now - ctx.miss_t > self.MISS_GAP:
            ctx.miss_t, ctx.miss_n = now, 0
            self._save_miss(ctx, img, "读不全", raw)
            why = screen.miss_reason(img)
            if why and why != ctx.hint["why"]:
                self._hint(session, ctx, why)
        if panel_now and ctx.sig_live:
            ctx.sig_live, ctx.sig_shown, ctx.sig_prev = (
                False,
                None,
                None,
            )  # 对着石头看面板：悬浮窗收起信号
            self.loop.commit(session, _del("信号"))
        # ---- 雷达信号（扫描面板开着时不认，2026-10-23 用户反馈把石头质量 13,586 当成了信号）
        seen: set[str] = set()
        try:
            found = [] if panel_now or _H()._off("radar") else find_signatures(img)
            sigs = frozenset(v for v, *_ in found)
            if sigs:
                ctx.last_sig_t = now
                from ...navigation.displayinfo import yield_ocr

                yield_ocr()
            area = (
                _T("navigation")._area_now() if sigs and sigs == ctx.sig_prev else None
            )
            # 产矿区变了（飞进矿带、跳跃）也要重新发：以前只看信号数值，同样的 7,200 会一直停在旧地点的说法
            from ...core.paths import file_stamp
            from ...mining.mining_area import rocks_stamp
            from ...mining.signals import _mine_file

            shown_key = (
                sigs,
                frozenset((v, f) for v, f, *_ in found),
                (area or {}).get("name"),
                (area or {}).get("zh"),
                rocks_stamp(),
                file_stamp(_mine_file()),
            )  # 换了石头表、读数改没改过、自己起了名都重发
            if (
                sigs
                and sigs == ctx.sig_prev
                and shown_key != ctx.sig_shown
                and session.alive()
            ):
                where = (
                    _T("navigation")._where_now()
                    if any(not match_signature(v) for v in sigs)
                    else None
                )
                lines = _T("goals")._mark_goal_lines(describe_all(found, where, area))
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
                    slot=MINING_SIGNALS,
                    value={"view": msg, "values": sorted(sigs)},
                    stamp=stamp,
                ):
                    ctx.sig_shown, ctx.sig_live = shown_key, True
                    log.write(
                        f"{time.strftime('%F %T')} SIG {sorted(sigs)} 产矿区={(area or {}).get('zh') or '未知'}\n"
                    )
                    log.flush()
            ctx.sig_prev = sigs
        except Exception as e:  # noqa: BLE001 —— 信号识别出错只丢这一轮的结果，不能拖垮面板识别
            self.loop.commit(
                session, _pub("log", {"task": "live", "line": f"信号识别失败：{e}"})
            )
        ctx.done_here += 1
        if panel_now and not scan_off:
            ctx.last_panel_t, ctx.missing = now, 0
            seen.add(MINING_SCAN)
        else:
            ctx.missing += 1
            if ctx.missing >= 3:
                ctx.recent.clear()  # 目标丢了（连续 3 帧没面板）：投票队列重来，别把下一块石头混进来
            if not scan.valid:
                ctx.settled = ctx.same >= 2  # 画面里没有扫描面板，静止时不用一直认
        if scan.valid:
            self._tick_scan(session, ctx, scan, bag, img, now, stamp, seen)
        elif part_ok and len(ctx.part) >= 2:
            self._tick_part(session, ctx, bag, now, stamp, seen)
        return Tick(screen.INTERVAL, bool(seen), frozenset(seen))

    def _tick_scan(self, session, ctx, scan, bag, img, now, stamp, seen):
        from ...mining import screen

        log = ctx.log
        if screen.enqueue_rock(ctx.recent, scan, bag):
            ctx.unstable_n = 0  # 换了石头：投票队列重计
        # 这一帧和队列里的石头对不上、被当成可疑帧先记下（没进队列）：这次不投票、不发结果。
        # 以前照样拿队列里上一块石头的帧投票，换石头后的第一帧会把上一块的结果又发一遍（2026-10-24 玩家反馈：
        # 画面是 5561 / 18.35 SCU 的新石头，发出去的是上一块 10187 / 33.71 SCU）
        accepted = bool(ctx.recent) and ctx.recent[-1][0] is scan
        if accepted and len(ctx.recent) >= 2:
            best, stable = screen.vote([x[0] for x in ctx.recent])
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
                self.gear_rev,
            )
            if stable and best.valid and shown != ctx.last_shown and session.alive():
                view = _T("mining").scan_view(
                    best, ctx.recent[-1][1]
                )  # 慢：算完再看一次有没有停
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
                if not self.loop.commit(
                    session, *ops, slot=MINING_SCAN, value=view, stamp=stamp
                ):
                    # 算的时候停了 / 配装变了：这份作废，下一帧按新配装重算
                    ctx.settled = False
                    return
                if ctx.hint["why"]:
                    self._hint(session, ctx, None)
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
        ctx.settled = ctx.last_shown is not None and ctx.done_here >= screen.VOTE_FRAMES

    def _tick_part(self, session, ctx, bag, now, stamp, seen):
        from ...mining import screen

        best, stable = screen.vote_partial([x[0] for x in ctx.part])
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
            self.gear_rev,
        )
        if stable and shown != ctx.last_shown and session.alive():
            view = _T("mining").scan_view(best, bag, cut=True)
            if not self.loop.commit(
                session,
                _pub("scan", view),
                _set("扫描", view["hud"], view.get("hud_rich")),
                slot=MINING_SCAN,
                value=view,
                stamp=stamp,
                quality="partial",
            ):
                ctx.settled = False
                return
            if ctx.hint["why"]:
                self._hint(session, ctx, None)
            ctx.last_key, ctx.last_shown, ctx.scan_live = None, shown, True
            ctx.log.write(
                f"{time.strftime('%F %T')} PART 面板被屏幕挡住，只算破碎 {best}\n"
            )
            ctx.log.flush()
        ctx.settled = ctx.last_shown is not None and ctx.done_here >= screen.VOTE_FRAMES

    # ---------------------------------------------------------------- 小动作
    def _save_miss(self, ctx, img, why, raw):
        """采矿助手没出结果的画面自动存下来：之后从这些图找原因（2026-10-23 用户反馈「部分矿物扫描失败」，当时没有图）"""
        from ...core import paths

        stamp = time.strftime("%H%M%S")
        try:
            ctx.log.write(f"{time.strftime('%F %T')} MISS {why} {raw}\n")
            ctx.log.flush()
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

        threading.Thread(target=save, daemon=True).start()  # L183 存截图的小线程，保留

    def _hint(self, session, ctx, why, clear_hud=False):
        """采矿助手读不全时告诉玩家原因（采矿助手页 + 悬浮窗）；why=None 收起（clear_hud：悬浮窗上的提示也擦掉；
        刚发了新结果时不擦，悬浮窗上已经是新结果了）"""
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
        self.loop.commit(session, *ops)

    def _set_paused(self, session, ctx, on, gap=0.0):
        """暂停 / 继续：记一行日志，告诉窗口（采矿助手页和左边的小灯）"""
        from ...core import run_records

        run_records.record(
            "MINING",
            "采矿助手已暂停" if on else "采矿助手已继续",
            "游戏不在最前面" if on else f"暂停了 {gap:.0f} 秒",
            level="WARN" if on else "INFO",
            ui_tag="LIVE",
        )
        try:
            ctx.log.write(
                f"{time.strftime('%F %T')} "
                + (
                    "PAUSE 游戏不在最前面，暂停识别"
                    if on
                    else f"RESUME 回到游戏，继续识别（暂停了 {gap:.0f} 秒）"
                )
                + "\n"
            )
            ctx.log.flush()
        except (OSError, ValueError):
            pass
        self.loop.commit(session, _pub("live", {"running": True, "paused": on}))
