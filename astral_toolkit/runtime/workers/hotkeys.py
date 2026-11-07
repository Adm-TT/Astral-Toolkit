"""热键线程（目录迁移 R4，从 app/engines/hover 拆出来）：只管采集按键、轮询间隔、停止／退出。

每 0.03 秒看一遍绑着的键，刚按下去的（上一遍没按着、这一遍按着）交给 pressed(热键名, 键名)，按住不连发；
每看 60 遍（约 1.8 秒）重读一次绑定，玩家改了键位不用重启。撞键时只有排在前面的生效；平台认不了的键
（现在只认 F1～F12）不看。线程出错就记一笔、先叫 failed()、等 1 秒从头再来，别让 F5 / F6 / F8 全失效。

按下去做什么（F8 识别、F5 采矿助手、F6 盘点……，要不要占着「忙」、切出游戏时怎么说）、绑定从设置里怎么读，
在键盘入口（app/inputs/hotkeys 的 HotkeyCommands）；原始按键读数在 infrastructure/platform/keys；都由 bootstrap 接进来，本模块只用标准库。
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class HotkeyLinks:
    """热键线程要的外面的东西（bootstrap 接）"""

    # 现在的热键绑定，按生效顺序：[(键名, 热键名)]，没绑的键名是空字符串（app/inputs/hotkeys 读设置）
    bindings: Callable[[], Iterable[tuple[str, str]]]
    # 键名 → 平台键码，认不了的键给 None（infrastructure/platform/keys）
    code: Callable[[str], int | None]
    # 这个键码现在是不是按着（infrastructure/platform/keys）
    down: Callable[[int], bool]
    # 刚按下一个键：(热键名, 键名)；做什么由 app/inputs/hotkeys 定
    pressed: Callable[[str, str], None]
    # 出错、1 秒后重来之前调一下（app/inputs/hotkeys 清「忙」，别让 F8 一直卡在「正在识别」）
    failed: Callable[[], None]


class HotkeyWorker:
    """links：见 HotkeyLinks；enabled：只有 Windows 起线程"""

    def __init__(self, links: HotkeyLinks, *, enabled: bool) -> None:
        self._links = links
        self._enabled = enabled
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()

    def start(self) -> None:
        if self._enabled and (self.thread is None or not self.thread.is_alive()):
            self.stop_ev.clear()
            self.thread = threading.Thread(
                target=self._guard, daemon=True, name="hover-key"
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

    def _guard(self) -> None:
        """热键线程出错就记一笔、等 1 秒重来，别让 F5/F6/F8 全失效（细查 2026-10-28）"""
        while not self.stop_ev.is_set():
            try:
                self._run()
            except Exception as e:
                print(f"热键监听出错，1 秒后重来：{e!r}")
                self._links.failed()  # 别让「忙」卡死（二审 2026-10-28）
                self.stop_ev.wait(1)

    def _run(self) -> None:
        links = self._links
        prev: dict[str, bool] = {}
        while not self.stop_ev.is_set():
            keys: list[tuple[str, int, str]] = []
            seen: set[str] = set()
            for key, name in links.bindings():
                vk = links.code(key) if key else None
                if vk is not None and key not in seen:  # 撞键时只有排在前面的生效
                    seen.add(key)
                    keys.append((name, vk, key))
            for _ in range(60):
                for name, vk, key in keys:
                    down = links.down(vk)
                    if down and not prev.get(name):
                        links.pressed(name, key)
                    prev[name] = down
                if self.stop_ev.wait(0.03):
                    return
