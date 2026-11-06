"""F8 物品识别 / 热键（_Hover）

用到的函数 / 变量直接到它们所在的模块取，运行时才取，避免互相 import：
_T("mining").xxx = tasks/mining.py，_H().xxx = app/hud_state.py，self._live / self._count = 构造时注入的引擎，self._links = F8 物品查询接线（HoverLinks，F 段 B5），self._feedback = 问题反馈（bootstrap 接好状态源的 feedback_report，F 段 B5）；self._nav = 导航任务要的后台对象（NavDeps，F 段 B5）。
用到：WIN, _hotkey_values, _live, _note_hud, count_toggle, feedback_report, fix_here, hover_once, item_key_pressed, live_start, live_stop, mark_here, ore_record, settings_key
"""

import importlib
import sys
import threading

from .. import bus, task_runner
from ..lifecycle_gate import is_closing

WIN = sys.platform == "win32"

# F1～F12 的虚拟键码（以前在 trade/console）
VK = {f"F{i}": 0x6F + i for i in range(1, 13)}


def _T(name):
    """astral_toolkit.tasks 里的模块（运行时才取，避免互相 import）"""
    return importlib.import_module(f"astral_toolkit.tasks.{name}")


def _H():
    from .. import hud_state

    return hud_state


class _Hover:
    GAME_ONLY = ("trade_capture_key", "count_key")  # 只在星际公民在最前面时才响应的热键

    def __init__(self, *, live, count, links, feedback, nav):
        self._live = live
        self._count = count
        self._links = links
        self._feedback = feedback
        self._nav = nav
        self.thread = None
        self.busy = False
        self.label = {}  # 热键名 → 当前绑定的键（如 trade_capture_key → F8）
        self.stop_ev = threading.Event()

    def start(self):
        if WIN and (self.thread is None or not self.thread.is_alive()):
            self.stop_ev.clear()
            self.thread = threading.Thread(
                target=self._guard, daemon=True, name="hover-key"
            )
            self.thread.start()

    def request_stop(self):
        self.stop_ev.set()

    def join(self, timeout=None):
        thread = self.thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            return not thread.is_alive()
        thread.join(timeout)
        return not thread.is_alive()

    def _guard(self):
        """热键线程出错就记一笔、等 1 秒重来，别让 F5/F6/F8 全失效（细查 2026-10-28）"""
        while not self.stop_ev.is_set():
            try:
                self._run()
            except Exception as e:
                print(f"热键监听出错，1 秒后重来：{e!r}")
                self.busy = False  # 别让 busy 卡死（二审 2026-10-28）
                self.stop_ev.wait(1)

    def _run(self):
        import ctypes
        from ...core import settings

        # 每个热键按下去做什么：(要不要占着「忙」, 动作)。占着忙的同一时间只跑一个（要截屏的）；
        # 记路标 / 一键定位 / 原矿记录只等玩家自己输 /showlocation（最多 60 秒，AT 不替玩家打字），不占着忙，免得这段时间 F8 用不了；
        # 同名任务只起一个（照 1.1.2 的 7c686a6）
        acts = {
            "trade_capture_key": (True, self._start_hover),
            "mark_key": (
                False,
                lambda: task_runner.run_task_once("mark", self._mark, title="记录路标"),
            ),
            "fix_key": (
                False,
                lambda: task_runner.run_task_once("fix", self._fix, title="一键定位"),
            ),
            "report_key": (
                True,
                lambda: task_runner.run_task(
                    "feedback", self._report, title="问题反馈"
                ),
            ),
            "live_key": (
                False,
                lambda: threading.Thread(
                    target=self._toggle_live, daemon=True, name="live-key"
                ).start(),
            ),
            "count_key": (
                False,
                lambda: threading.Thread(
                    target=self._toggle_count, daemon=True, name="count-key"
                ).start(),
            ),
            "ore_key": (
                False,
                lambda: task_runner.run_task_once("ore", self._ore, title="原矿记录"),
            ),
        }
        prev = {}
        while not self.stop_ev.is_set():
            keys, seen, label = [], set(), {}
            for key, _, name in _T("system")._hotkey_values(settings.load()):
                if key and key in VK and key not in seen:  # 撞键时只有排在前面的生效
                    seen.add(key)
                    keys.append((name, VK[key]))
                    label[name] = key
            self.label = label  # 当前绑定的键名，提示里用（玩家可能改了键位）
            for _ in range(60):
                for name, vk in keys:
                    down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
                    if (
                        down
                        and not prev.get(name)
                        and name in self.GAME_ONLY
                        and _T("mining")._game_front() is False
                    ):
                        # 切出游戏时按的 F8 / F6（比如在浏览器里 F6 是跳地址栏）：不截屏、不开关盘点（判断不了时照常）
                        bus.runtime_log(
                            f"不在游戏里，{label[name]} {'识别' if name == 'trade_capture_key' else '盘点'}没响应：回到游戏再按"
                            + (
                                "，或在窗口点「结束盘点」"
                                if name == "count_key" and self._count.running()
                                else ""
                            ),
                            tag="HOVER" if name == "trade_capture_key" else "COUNT",
                            level="INFO",
                        )
                    elif down and not prev.get(name):
                        busy, act = acts[name]
                        if not busy:
                            act()
                        elif not self.busy:
                            self.busy = True
                            if name == "trade_capture_key":
                                bus.runtime_log(
                                    f"捕获到 {label[name]} 快捷键，触发悬停识别...",
                                    tag="HOVER",
                                    level="INFO",
                                )
                            act()
                        elif name == "trade_capture_key":
                            bus.runtime_log(
                                f"{label[name]} 正在识别中，请稍候...",
                                tag="HOVER",
                                level="WARN",
                            )
                    prev[name] = down
                if self.stop_ev.wait(0.03):
                    return

    def _toggle_live(self):
        """采矿助手开关键：开着就关，关着就开；悬浮窗上按实际结果显示（正在停止时说清楚）"""
        try:
            k = _T("navigation").settings_key("live_key", "F5")
            if self._live.running():
                _T("mining").live_stop(self._live)
                _H()._note_hud("采矿助手", f"采矿助手已关闭｜按 {k} 开启")
            else:
                if is_closing():
                    _H()._note_hud("采矿助手", "正在退出")
                    return
                res = _T("mining").live_start(self._live) or {}
                if res.get("error"):
                    # 正在停止 / 正在退出：别说「已开启」（3-2）
                    _H()._note_hud("采矿助手", res["error"])
                else:
                    _H()._note_hud("采矿助手", f"采矿助手已开启｜按 {k} 关闭")
        except Exception as e:
            bus.publish("log", {"task": "live", "line": f"采矿助手开关失败：{e}"})

    def _toggle_count(self):
        if not self._count.running() and is_closing():
            _H()._note_hud("盘点", "正在退出")
            return {"error": "正在退出"}
        return _T("count").count_toggle()

    def _report(self):
        try:
            return self._feedback(kind="auto")
        finally:
            self.busy = False

    def _mark(self):  # 不占着忙，结束时也不能清别人（F8、F10）的忙
        if is_closing():
            return {"error": "正在退出"}
        return _T("navigation").mark_here(self._nav)

    def _ore(self):
        if is_closing():
            return {"error": "正在退出"}
        return _T("navigation").ore_record(self._nav, here=True)

    def _fix(self):
        if is_closing():
            return {"error": "正在退出"}
        return _T("navigation").fix_here(self._nav)

    def _start_hover(self):
        """F8：和窗口里的「识别」接口共用同一个任务名，已经在识别就不再起第二个（两个同时跑会互相清掉 _last_hover）"""
        _H().item_key_pressed()
        if (
            task_runner.run_task_once("hover", self._recognize, title="识别物品")
            is None
        ):
            # 上一次可能刚识别完、线程还在发「完成」消息：另起个短线程等它一下再试，热键线程不跟着等
            threading.Thread(
                target=self._retry_hover, daemon=True, name="hover-retry"
            ).start()

    def _retry_hover(self):
        old = task_runner._running.get("hover")
        if old is not None:
            old.join(0.3)
        if (
            task_runner.run_task_once("hover", self._recognize, title="识别物品")
            is None
        ):
            self.busy = False
            bus.runtime_log(
                f"{self.label.get('trade_capture_key', 'F8')} 正在识别中，请稍候...",
                tag="HOVER",
                level="WARN",
            )

    def _recognize(self):
        try:
            return _T("hover").hover_once(self._links)
        finally:
            self.busy = False
