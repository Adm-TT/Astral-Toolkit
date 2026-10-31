"""让 AT 窗口在任务栏上是「AT」而不是「Edge」

窗口是 Edge 开的，Windows 默认把它算成 Edge（固定到任务栏也变成 Edge）。
这里给窗口单独设置任务栏身份（AppUserModelID）和「从任务栏重新打开时运行什么」：
  身份       Adm_TT.Dubhe
  重新打开   Dubhe.exe
  名字/图标  天枢 Dubhe、罗盘星
这样任务栏上它是独立的天枢图标；固定到任务栏后点它会运行 Dubhe.exe。只用 Windows 自带接口。
"""
import ctypes
import sys
import threading
import time
from pathlib import Path
from ctypes import wintypes

APP_ID = "Adm_TT.Dubhe"
# 安装版的任务栏身份。1.0.1 用 Adm_TT.AT（和旧版天枢分开）；1.0.4 起改成 Velopack 快捷方式用的 velopack.AT：
# 窗口和开始菜单 / 桌面快捷方式算同一个程序，固定到任务栏也对得上。
# 2026-10-28 任务栏图标变白纸的原因就在这：Windows 按身份记着上一次的图标来源（旧安装版的 AT.exe，卸载后没了），
# 换了身份才重新读；图标也改成明确指到 shell\icon.ico（从 PyInstaller 打的 AT.exe 里取图标，任务栏取不出来）
APP_ID_FROZEN = "velopack.AT"
TITLE = "AT 星际公民助手"     # 和 index.html 的 <title> 一样（按标题找窗口）


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        import uuid
        u = uuid.UUID(text)
        super().__init__(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("pwszVal", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]


_FMT = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
PKEY_ID, PKEY_RELAUNCH_CMD, PKEY_RELAUNCH_ICON, PKEY_RELAUNCH_NAME = 5, 2, 3, 4
IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"


def _set_props(hwnd, values):
    """values: {pid: 字符串}；成功返回 True"""
    shell = ctypes.windll.shell32
    store = ctypes.c_void_p()
    hr = shell.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(GUID(IID_IPropertyStore)),
                                           ctypes.byref(store))
    if hr != 0 or not store:
        return False
    vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    SetValue = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                                  ctypes.POINTER(PROPVARIANT))(vtbl[6])
    Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
    ok = True
    try:
        # 先设重新打开的命令和图标，最后设身份（Windows 在身份变化时读取前面几项）
        for pid in sorted(values, key=lambda p: p == PKEY_ID):
            key = PROPERTYKEY(GUID(_FMT), pid)
            var = PROPVARIANT()
            var.vt = 31                                                   # VT_LPWSTR
            var.pwszVal = values[pid]
            ok = SetValue(store, ctypes.byref(key), ctypes.byref(var)) == 0 and ok
    finally:
        Release(store)
    return ok


def _find_window(title=TITLE):
    u32 = ctypes.windll.user32
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith(title):
                    found.append(hwnd)
        return True
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def brand_window(root, timeout=20.0):
    """后台等天枢窗口出现，给它打上天枢的任务栏身份"""
    if sys.platform != "win32":
        return

    def run():
        from ..core.paths import FROZEN
        if FROZEN:                      # 安装版：从任务栏重新打开运行 AT.exe
            exe = Path(sys.executable)
            # 图标用 shell\icon.ico：任务栏从 PyInstaller 打的 AT.exe 里取不出图标，会显示成白纸（2026-10-28 用户反馈，实测 .ico 正常）
            ico = root / "shell" / "icon.ico"
            icon, app_id = (ico if ico.exists() else exe), APP_ID_FROZEN
        else:
            exe = root / "Dubhe.exe"
            icon, app_id = root / "sc_mining" / "app" / "icon.ico", APP_ID
        values = {PKEY_RELAUNCH_NAME: TITLE, PKEY_RELAUNCH_ICON: f"{icon},0", PKEY_ID: app_id}
        if exe.exists():
            values[PKEY_RELAUNCH_CMD] = f'"{exe}"'
        done = set()
        end = time.time() + timeout
        while time.time() < end:
            for hwnd in _find_window():
                if hwnd not in done:
                    try:
                        if _set_props(hwnd, values):
                            done.add(hwnd)
                    except Exception:
                        pass
            if done:
                return
            time.sleep(0.3)
    threading.Thread(target=run, daemon=True, name="taskbar-id").start()


def focus_window(title=TITLE):
    """已经开着的天枢窗口：最小化了就还原，拉到最前面。找到返回 True"""
    if sys.platform != "win32":
        return False
    u32 = ctypes.windll.user32
    wins = _find_window(title)
    if not wins:
        return False
    hwnd = wins[0]
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)                                   # SW_RESTORE
    else:
        u32.ShowWindow(hwnd, 5)                                   # SW_SHOW
    if not u32.SetForegroundWindow(hwnd):
        # Windows 不让后台程序抢前台：让任务栏图标闪一下（1.1.2 起不再模拟按 Alt）
        u32.FlashWindow(hwnd, True)
    return True


def _exe_of(hwnd):
    """窗口属于哪个程序（只要文件名，小写）"""
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = k32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        k32.CloseHandle(h)


def _pid_of(hwnd):
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def profile_pids(profile, exes=("msedge.exe", "chrome.exe")):
    """命令行里带 --user-data-dir=<AT 专用的浏览器资料夹> 的 Edge / Chrome 进程号：这些才是 AT 开的窗口"""
    if sys.platform != "win32" or not profile:
        return set()
    import subprocess
    names = " OR ".join(f"Name='{e}'" for e in exes)
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
           f"Get-CimInstance Win32_Process -Filter \"{names}\" | "
           "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=5, creationflags=0x08000000).stdout
    except Exception:
        return set()
    want = str(profile).lower().rstrip("\\/")
    pids = set()
    for line in out.splitlines():
        pid, _, cl = line.partition("\t")
        cl = cl.lower().replace('"', "")
        if pid.strip().isdigit() and f"--user-data-dir={want}" in cl:
            pids.add(int(pid))
    return pids


def close_windows(pids, title=TITLE, exes=("msedge.exe", "chrome.exe", "atshell.exe")):
    """关掉 AT 自己开的 Edge / Chrome 窗口（AT 退出时用；不碰 WebView2 的新窗口）。返回关了几个。
    只关进程号在 pids 里的：用户在自己的浏览器里开着 AT 页面时，标题一样，但不能把用户的整个浏览器窗口关掉（Codex 2026-10-27 补审）"""
    if sys.platform != "win32" or not pids:
        return 0
    n = 0
    for hwnd in _find_window(title):
        if _pid_of(hwnd) in pids and _exe_of(hwnd) in exes:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)     # WM_CLOSE
            n += 1
    return n


def allow_focus():
    """第二次双击的那个天枢调用：允许已经开着的天枢把窗口拉到最前面"""
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)   # ASFW_ANY
        except Exception:
            pass
