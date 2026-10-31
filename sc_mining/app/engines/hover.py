"""F8 物品识别 / 热键（_Hover）

2026-10-28 从 app/services.py 原样剪出来（逻辑没改）。用到 services 里的函数 / 变量写成 _S().xxx：
运行时才取，避免互相 import；services 里仍保留实例（_nav、_live …）。
用到：WIN, _hotkey_values, _live, _note_hud, count_toggle, feedback_report, fix_here, hover_once, item_key_pressed, live_start, live_stop, mark_here, ore_record, settings_key
"""
import threading
import time

from .. import bus


def _S():
    from .. import services
    return services


class _Hover:
    def __init__(self):
        self.thread = None
        self.busy = False

    def start(self):
        if _S().WIN and not self.thread:
            self.thread = threading.Thread(target=self._guard, daemon=True, name="hover-key")
            self.thread.start()

    def _guard(self):
        """热键线程出错就记一笔、等 1 秒重来，别让 F5/F6/F8 全失效（细查 2026-10-28）"""
        while True:
            try:
                self._run()
            except Exception as e:
                print(f"热键监听出错，1 秒后重来：{e!r}")
                self.busy = False                 # 别让 busy 卡死（二审 2026-10-28）
                time.sleep(1)

    def _run(self):
        import ctypes
        from ... import settings
        from ...trade.console import VK
        # 每个热键按下去做什么：(要不要占着「忙」, 动作)。占着忙的同一时间只跑一个（要截屏的）；
        # 记路标 / 一键定位 / 原矿记录 1.1.2 起只等玩家自己输 /showlocation（最多 60 秒），不占着忙，免得这段时间 F8 用不了
        acts = {"trade_capture_key": (True, lambda: (_S().item_key_pressed(), bus.run_task("hover", self._recognize, title="识别物品"))),
                "mark_key": (False, lambda: bus.run_task_once("mark", self._mark, title="记录路标")),
                "fix_key": (False, lambda: bus.run_task_once("fix", self._fix, title="一键定位")),
                "report_key": (True, lambda: bus.run_task("feedback", self._report, title="问题反馈")),
                "live_key": (False, lambda: threading.Thread(target=self._toggle_live, daemon=True, name="live-key").start()),
                "count_key": (False, lambda: threading.Thread(target=_S().count_toggle, daemon=True, name="count-key").start()),
                "ore_key": (False, lambda: bus.run_task_once("ore", self._ore, title="原矿记录"))}
        prev = {}
        while True:
            keys, seen = [], set()
            for key, _, name in _S()._hotkey_values(settings.load()):
                if key and key in VK and key not in seen:     # 撞键时只有排在前面的生效
                    seen.add(key)
                    keys.append((name, VK[key]))
            for _ in range(60):
                for name, vk in keys:
                    down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
                    if down and not prev.get(name):
                        busy, act = acts[name]
                        if not busy:
                            act()
                        elif not self.busy:
                            self.busy = True
                            act()
                    prev[name] = down
                time.sleep(0.03)

    def _toggle_live(self):
        """采矿助手开关键：开着就关，关着就开；悬浮窗上提示一下"""
        try:
            k = _S().settings_key("live_key", "F5")
            if _S()._live.running():
                _S().live_stop()
                _S()._note_hud("采矿助手", f"采矿助手已关闭｜按 {k} 开启")
            else:
                _S().live_start()
                _S()._note_hud("采矿助手", f"采矿助手已开启｜按 {k} 关闭")
        except Exception as e:
            bus.publish("log", {"task": "live", "line": f"采矿助手开关失败：{e}"})

    def _report(self):
        try:
            return _S().feedback_report(kind="auto")
        finally:
            self.busy = False

    def _mark(self):                      # 不占着忙（1.1.2），结束时也不能清别人的忙
        return _S().mark_here()

    def _ore(self):
        return _S().ore_record(here=True)

    def _fix(self):
        return _S().fix_here()

    def _recognize(self):
        try:
            return _S().hover_once()
        finally:
            self.busy = False
