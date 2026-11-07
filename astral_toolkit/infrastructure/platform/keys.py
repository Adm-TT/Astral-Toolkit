"""热键要的原始按键读数（目录迁移 R4，从 app/engines/hover 的热键线程拆出来）：键名对应的键码、这个键现在按着没有。

只读按键状态，不模拟输入；由 bootstrap 接给热键线程（runtime/workers/hotkeys）。
"""

import ctypes

# F1～F12 的虚拟键码（以前在 trade/console，后来在 app/engines/hover）
VK = {f"F{i}": 0x6F + i for i in range(1, 13)}


def code(key: str) -> int | None:
    """键名（大写，如 F8）→ 虚拟键码；热键只认 F1～F12，别的给 None"""
    return VK.get(key)


def down(vk: int) -> bool:
    """这个键现在是不是按着（GetAsyncKeyState 的最高位）。只在 Windows 上用；读不了照样抛出去，
    热键线程会记一笔、1 秒后重来"""
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
