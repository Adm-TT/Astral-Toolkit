"""游戏窗口相关的小工具：找游戏窗口、游戏在不在最前面、管理员身份、当前按着哪些键

自定义路标只用 /showlocation 的坐标：玩家自己在聊天框输入 /showlocation，游戏把坐标复制到剪贴板，AT 读剪贴板。
1.1.2 起 AT 不再替玩家输入（删掉了全部模拟按键）。导航实时方位仍然读右上角
"""
import sys
import time
from pathlib import Path

GAME_EXE = "starcitizen.exe"
_MOUSE_VK = (0x01, 0x02, 0x04, 0x05, 0x06)

WIN = sys.platform == "win32"
if WIN:
    import ctypes
    from ctypes import wintypes

    _u32 = ctypes.windll.user32
    _k32 = ctypes.windll.kernel32
    _adv = ctypes.windll.advapi32
    _ULONG_PTR = ctypes.c_size_t

    _u32.GetForegroundWindow.restype = wintypes.HWND
    _k32.OpenProcess.restype = wintypes.HANDLE
    _u32.GetAsyncKeyState.restype = ctypes.c_short
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


# ---------------------------------------------------------------- /showlocation（只读剪贴板，不按键）

TYPE_WAIT = 60              # 等玩家自己输入 /showlocation 最多多少秒
_WAITING = __import__("threading").Lock()     # 同一时间只等一份（连按热键不会记重复的路标）


def wait_new_coords(old, timeout):
    """等剪贴板里出现和 old 不同的新坐标；返回 (星系坐标, 原文) 或 (None, None)"""
    from .navigate import read_clipboard, parse_clip
    end = time.time() + timeout
    while time.time() < end:
        clip = read_clipboard()
        g = parse_clip(clip)
        if g and clip != old:
            return g, clip
        time.sleep(0.1)
    return None, None


def showlocation(log=None):
    """等玩家自己在聊天框输入 /showlocation，读回剪贴板里的坐标。返回 (星系坐标米, 原文)；失败返回 (None, 原因)。
    1.1.2 起 AT 不再替玩家按键"""
    from .navigate import read_clipboard
    log = log or (lambda m: None)
    if not _WAITING.acquire(blocking=False):
        return None, "已经在等你输入 /showlocation 了"
    try:
        old = read_clipboard()
        log(f"开始等玩家输入 /showlocation（{TYPE_WAIT} 秒）")
        g, clip = wait_new_coords(old, TYPE_WAIT)
    finally:
        _WAITING.release()
    log(f"等玩家输入 /showlocation → {clip!r}")
    if g:
        return g, clip
    return None, f"{TYPE_WAIT} 秒内没读到坐标：请在游戏聊天框输入 /showlocation 后回车"


def _window_text(hwnd, fn):
    buf = ctypes.create_unicode_buffer(256)
    fn(hwnd, buf, 256)
    return buf.value


def _is_game_window(hwnd):
    title = _window_text(hwnd, _u32.GetWindowTextW).lower()
    cls = _window_text(hwnd, _u32.GetClassNameW).lower()
    return title.startswith("star citizen") or "cryengine" in cls


def _exe_of(hwnd):
    return _exe_path(hwnd).replace("/", "\\").rsplit("\\", 1)[-1].lower()


def _exe_path(hwnd):
    """窗口所属程序的完整路径（读不到返回空字符串）"""
    pid = wintypes.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = _k32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if not _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value
    finally:
        _k32.CloseHandle(h)


_fg_cache = {"hwnd": None, "ok": False}


def game_foreground():
    """最前面的窗口是不是星际公民（先看窗口标题/类名，再看进程名）。同一个窗口只判断一次"""
    if not WIN:
        return False
    try:
        hwnd = _u32.GetForegroundWindow()
        if not hwnd:
            return False
        if _fg_cache["hwnd"] != hwnd:
            _fg_cache.update(hwnd=hwnd, ok=_is_game_window(hwnd) or _exe_of(hwnd) == GAME_EXE)
        return _fg_cache["ok"]
    except Exception:
        return False


def game_front():
    """最前面的窗口是不是星际公民：True / False；判断不了（不是 Windows、这一刻没有前台窗口、出错）返回 None。
    和 game_foreground 同一套判断，只是判断不了时不当成「不在」——采矿助手用它决定要不要暂停，判断坏了也不能把采矿助手停掉"""
    if not WIN:
        return None
    try:
        hwnd = _u32.GetForegroundWindow()
        if not hwnd:
            return None
        if _fg_cache["hwnd"] != hwnd:
            _fg_cache.update(hwnd=hwnd, ok=_is_game_window(hwnd) or _exe_of(hwnd) == GAME_EXE)
        return _fg_cache["ok"]
    except Exception:
        return None


def find_game_window():
    if not WIN:
        return None
    found = []

    def cb(hwnd, _):
        # 先按标题/类名认；认不出再看是不是 StarCitizen.exe 的窗口（和自动跑判断「在游戏里」用同一套）
        if _u32.IsWindowVisible(hwnd) and (_is_game_window(hwnd) or
                                           (_u32.GetWindowTextLengthW(hwnd) and _exe_of(hwnd) == GAME_EXE)):
            found.append(hwnd)
            return False
        return True
    try:
        _u32.EnumWindows(_WNDENUMPROC(cb), 0)
    except Exception:
        pass
    return found[0] if found else None


def is_admin():
    if not WIN:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def game_elevated():
    """游戏开着并且是管理员权限运行 → True；没开/读不到 → None"""
    if not WIN:
        return None
    hwnd = find_game_window()
    if not hwnd:
        return None
    try:
        pid = wintypes.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = _k32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return None
        tok = wintypes.HANDLE()
        try:
            if not _adv.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):     # TOKEN_QUERY
                return None
            elev, n = wintypes.DWORD(), wintypes.DWORD()
            ok = _adv.GetTokenInformation(tok, 20, ctypes.byref(elev), 4, ctypes.byref(n))   # TokenElevation
            _k32.CloseHandle(tok)
            return bool(elev.value) if ok else None
        finally:
            _k32.CloseHandle(h)
    except Exception:
        return None


def blocked_by_admin():
    """游戏是管理员权限、助手不是 → 按键会被 Windows 挡掉"""
    return bool(game_elevated()) and not is_admin()


def relaunch_as_admin(entry="nav"):
    """用管理员身份另开一个窗口直接进某个功能（会弹出 Windows 的确认框）"""
    from .paths import FROZEN, ROOT
    root = str(ROOT)
    if FROZEN:                                    # 独立打包版：AT.exe admin <入口>
        params = f"admin {entry}"
    else:
        code = (f"import os,sys; os.chdir(r'{root}'); sys.path.insert(0, r'{root}'); "
                f"from sc_mining import run; run.run_entry('{entry}')")
        params = f'-X utf8 -c "{code}"'
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, root, 1)
    return r > 32


# ---------------------------------------------------------------- 键盘状态

def _down(vk):
    return bool(_u32.GetAsyncKeyState(vk) & 0x8000)


def held_keys():
    """当前按着的键（虚拟键码列表），排查用"""
    if not WIN:
        return []
    return [vk for vk in list(_MOUSE_VK) + list(range(0x08, 0xFF)) if _down(vk)]


def keys_idle():
    """没有按着任何键盘键和鼠标键（按着的话聊天框会被打进多余的字）"""
    if not WIN:
        return False
    return not any(_down(vk) for vk in list(_MOUSE_VK) + list(range(0x08, 0xFF)))
