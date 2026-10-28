"""游戏窗口相关的小工具：找游戏窗口、游戏在不在最前面、管理员身份、模拟按键、当前按着哪些键

自定义路标（「用当前位置新建」、游戏里按 F7）只用 /showlocation 的坐标：AT 替你在聊天框输入 /showlocation，
游戏把坐标复制到剪贴板，AT 读剪贴板。比 OCR 右上角调试信息可靠（不会认错数字）。导航实时方位仍然读右上角
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

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR)]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _UNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

    _u32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    _u32.GetForegroundWindow.restype = wintypes.HWND
    _k32.OpenProcess.restype = wintypes.HANDLE
    _u32.GetAsyncKeyState.restype = ctypes.c_short
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


# ---------------------------------------------------------------- 按键

def _send(vk, scan, flags):
    inp = _INPUT(type=1, u=_UNION(ki=_KEYBDINPUT(vk, scan, flags, 0, 0)))
    _u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


# ---------------------------------------------------------------- /showlocation

COMMAND = "/showlocation"
CHAT_KEY = 0x1C             # 打开聊天输入框的键（回车）的扫描码
KEY_HOLD = 0.04             # 每个键按住多久（太短游戏一帧里看不到）
KEY_GAP = 0.03
CHAT_OPEN_WAIT = 0.3        # 按回车后等聊天框打开
CLIP_TIMEOUT = 3.0          # 输入后多少秒内没读到坐标算失败
METHODS = ["scan", "vk", "unicode"]       # 三种按键方式轮流试，成功的记住
_SCAN = {c: s for c, s in zip("qwertyuiop", range(0x10, 0x1A))}
_SCAN.update({c: s for c, s in zip("asdfghjkl", range(0x1E, 0x27))})
_SCAN.update({c: s for c, s in zip("zxcvbnm", range(0x2C, 0x33))})
_SCAN.update({"/": 0x35, " ": 0x39})
_VK = {c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"}
_VK.update({"/": 0xBF, " ": 0x20})


def _method_file():
    from ..core.paths import USER
    return USER / "showlocation_method.txt"


def _press(vk, scan, flags):
    _send(vk, scan, flags)
    time.sleep(KEY_HOLD)
    _send(vk, scan, flags | 0x0002)               # KEYEVENTF_KEYUP
    time.sleep(KEY_GAP)


def _enter(method):
    if method == "vk":
        _press(0x0D, CHAT_KEY, 0)
    else:
        _press(0, CHAT_KEY, 0x0008)               # KEYEVENTF_SCANCODE


def _char(ch, method):
    if method == "scan":
        _press(0, _SCAN[ch], 0x0008)
    elif method == "vk":
        _press(_VK[ch], _SCAN[ch], 0)
    else:
        _press(0, ord(ch), 0x0004)                # KEYEVENTF_UNICODE


def send_showlocation(method="scan"):
    """在游戏里输入 /showlocation（调用前要确认游戏在最前面、没按着键）"""
    _enter(method)
    time.sleep(CHAT_OPEN_WAIT)
    for ch in COMMAND:
        _char(ch, method)
    time.sleep(0.05)
    _enter(method)


def wait_new_coords(old, timeout):
    """等剪贴板里出现和 old 不同的新坐标；返回 (星系坐标, 原文) 或 (None, None)"""
    from ..navigation.navigate import read_clipboard, parse_clip
    end = time.time() + timeout
    while time.time() < end:
        clip = read_clipboard()
        g = parse_clip(clip)
        if g and clip != old:
            return g, clip
        time.sleep(0.1)
    return None, None


def showlocation(log=None):
    """替玩家在游戏里打 /showlocation 并读回坐标。返回 (星系坐标米, 说明)；失败返回 (None, 原因)。
    只在游戏窗口在最前面、没按着键、没开自动跑时打字；三种按键方式轮流试，成功的记住"""
    from ..navigation.navigate import read_clipboard
    log = log or (lambda m: None)
    if not WIN:
        return None, "只有 Windows 能用"
    if blocked_by_admin():
        return None, "游戏是管理员权限：AT 也要用管理员身份打开才能自动输入 /showlocation（或者自己在聊天框输入）"
    try:
        from .helpers import autorun_on
        if autorun_on():
            return None, "双击 W 自动跑开着（按着 Shift 打字会变大写），停下后再试"
    except Exception:
        pass
    end = time.time() + 2.0
    while time.time() < end and not keys_idle():      # 等你松开 F7 等按键
        time.sleep(0.05)
    if not keys_idle():
        return None, f"一直有键按着（键码 {held_keys()[:5]}），松开后再试"
    if not game_foreground():
        return None, "游戏窗口不在最前面"
    try:
        first = METHODS.index(_method_file().read_text(encoding="utf-8").strip())
        known = True
    except Exception:
        first, known = 0, False
    order = [METHODS[first]] + ([m for m in METHODS if m != METHODS[first]] if not known else [])
    for method in order:
        old = read_clipboard()
        send_showlocation(method)
        g, clip = wait_new_coords(old, CLIP_TIMEOUT)
        log(f"/showlocation（{method}）→ {clip!r}")
        if g:
            try:
                _method_file().write_text(method, encoding="utf-8")
            except OSError:
                pass
            return g, clip
        if not game_foreground():
            break
    return None, "输入了 /showlocation 但没读到坐标：检查输入法是英文、没开地图/菜单/mobiGlas，或者自己在聊天框输入 /showlocation"


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
    from ..core.paths import FROZEN, ROOT
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
