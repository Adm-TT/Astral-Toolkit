"""热键按下去做什么：键盘入口（HotkeyCommands；目录迁移 R4 把看键的线程拆去了 runtime/workers/hotkeys）

热键线程只管看键：约 1.8 秒从这里的 bindings() 重读一次绑定，看到刚按下一个键就调 pressed(热键名, 键名)，
出错重来之前调 failed()（都由 bootstrap 接）。这里定每个热键做什么——F8 物品识别、记录路标、一键定位、问题反馈、
采矿助手开关、盘点、原矿记录；要不要占着「忙」（要截屏的同一时间只跑一个）；F8 / 盘点键切出游戏时按只提示、不动作。
动作本身在 tasks（F8 识别 tasks/hover，采矿 tasks/mining，导航 tasks/navigation，盘点 tasks/count），用到时才导入，避免互相 import。
self._live / self._count = 构造时注入的引擎，self._links = F8 物品查询接线（HoverLinks，F 段 B5），
self._feedback = 问题反馈（bootstrap 接好状态源的 feedback_report，F 段 B5），self._nav = 导航任务要的后台对象（NavDeps，F 段 B5）。
"""

import threading

from .. import bus, task_runner
from ..lifecycle_gate import is_closing


class HotkeyCommands:
    GAME_ONLY = ("trade_capture_key", "count_key")  # 只在星际公民在最前面时才响应的热键

    def __init__(self, *, live, count, links, feedback, nav):
        self._live = live
        self._count = count
        self._links = links
        self._feedback = feedback
        self._nav = nav
        self.busy = False
        self.label = {}  # 热键名 → 刚按的键（如 trade_capture_key → F8；玩家可能改了键位，提示里用）

    def bindings(self):
        """现在的热键绑定，按生效顺序：[(键名, 热键名)]，没绑的键名是空字符串（tasks/system 的热键表 + 设置）"""
        from ...core import settings
        from ...tasks import system as system_tasks

        return [
            (key, name) for key, _, name in system_tasks._hotkey_values(settings.load())
        ]

    def failed(self):
        """热键线程出错、1 秒后重来之前：别让「忙」卡死（二审 2026-10-28）"""
        self.busy = False

    def pressed(self, name, key):
        """热键线程看到刚按下 key（绑在热键 name 上）：切出游戏时的 F8 / 盘点键只提示；占着「忙」的同一时间只跑一个"""
        self.label[name] = key
        if name in self.GAME_ONLY and self._game_front() is False:
            # 切出游戏时按的 F8 / F6（比如在浏览器里 F6 是跳地址栏）：不截屏、不开关盘点（判断不了时照常）
            bus.runtime_log(
                f"不在游戏里，{key} {'识别' if name == 'trade_capture_key' else '盘点'}没响应：回到游戏再按"
                + (
                    "，或在窗口点「结束盘点」"
                    if name == "count_key" and self._count.running()
                    else ""
                ),
                tag="HOVER" if name == "trade_capture_key" else "COUNT",
                level="INFO",
            )
            return
        busy, act = self._acts()[name]
        if not busy:
            act()
        elif not self.busy:
            self.busy = True
            if name == "trade_capture_key":
                bus.runtime_log(
                    f"捕获到 {key} 快捷键，触发悬停识别...",
                    tag="HOVER",
                    level="INFO",
                )
            act()
        elif name == "trade_capture_key":
            bus.runtime_log(
                f"{key} 正在识别中，请稍候...",
                tag="HOVER",
                level="WARN",
            )

    def _game_front(self):
        """游戏窗口在不在最前面（tasks/mining：True / False；判断不了是 None，照常响应）"""
        from ...tasks import mining as mining_tasks

        return mining_tasks._game_front()

    def _acts(self):
        # 每个热键按下去做什么：(要不要占着「忙」, 动作)。占着忙的同一时间只跑一个（要截屏的）；
        # 记路标 / 一键定位 / 原矿记录只等玩家自己输 /showlocation（最多 60 秒，AT 不替玩家打字），不占着忙，免得这段时间 F8 用不了；
        # 同名任务只起一个（照 1.1.2 的 7c686a6）
        return {
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

    def _toggle_live(self):
        """采矿助手开关键：开着就关，关着就开；悬浮窗上按实际结果显示（正在停止时说清楚）"""
        try:
            from .. import hud_state
            from ...tasks import mining as mining_tasks
            from ...tasks import navigation as navigation_tasks

            k = navigation_tasks.settings_key("live_key", "F5")
            if self._live.running():
                mining_tasks.live_stop(self._live)
                hud_state._note_hud("采矿助手", f"采矿助手已关闭｜按 {k} 开启")
            else:
                if is_closing():
                    hud_state._note_hud("采矿助手", "正在退出")
                    return
                res = mining_tasks.live_start(self._live) or {}
                if res.get("error"):
                    # 正在停止 / 正在退出：别说「已开启」（3-2）
                    hud_state._note_hud("采矿助手", res["error"])
                else:
                    hud_state._note_hud("采矿助手", f"采矿助手已开启｜按 {k} 关闭")
        except Exception as e:
            bus.publish("log", {"task": "live", "line": f"采矿助手开关失败：{e}"})

    def _toggle_count(self):
        from .. import hud_state
        from ...tasks import count as count_tasks

        if not self._count.running() and is_closing():
            hud_state._note_hud("盘点", "正在退出")
            return {"error": "正在退出"}
        return count_tasks.count_toggle()

    def _report(self):
        try:
            return self._feedback(kind="auto")
        finally:
            self.busy = False

    def _mark(self):  # 不占着忙，结束时也不能清别人（F8、F10）的忙
        from ...tasks import navigation as navigation_tasks

        if is_closing():
            return {"error": "正在退出"}
        return navigation_tasks.mark_here(self._nav)

    def _ore(self):
        from ...tasks import navigation as navigation_tasks

        if is_closing():
            return {"error": "正在退出"}
        return navigation_tasks.ore_record(self._nav, here=True)

    def _fix(self):
        from ...tasks import navigation as navigation_tasks

        if is_closing():
            return {"error": "正在退出"}
        return navigation_tasks.fix_here(self._nav)

    def _start_hover(self):
        """F8：和窗口里的「识别」接口共用同一个任务名，已经在识别就不再起第二个（两个同时跑会互相清掉 _last_hover）"""
        from .. import hud_state

        hud_state.item_key_pressed()
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
            from ...tasks import hover as hover_tasks

            return hover_tasks.hover_once(self._links)
        finally:
            self.busy = False
