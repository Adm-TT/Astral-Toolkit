"""右下角托盘图标：关掉 AT 窗口后，AT 在后台继续工作（F8 识别、游戏悬浮窗）

- 双击图标 / 菜单「打开 AT」：重新打开窗口
- 菜单「重新启动」：改过代码或出问题时用
- 菜单「退出 AT」：彻底关掉
只用 Windows 自带的接口（ctypes），不用另装东西。
"""
import ctypes
import sys
import threading
from ctypes import wintypes

WIN = sys.platform == "win32"
WM_USER_TRAY = 0x0400 + 20
WM_COMMAND, WM_DESTROY, WM_CLOSE = 0x0111, 0x0002, 0x0010
WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_LBUTTONUP = 0x0203, 0x0205, 0x0202
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 1, 2, 4, 0x10
ID_OPEN, ID_RESTART, ID_QUIT = 1001, 1002, 1003

if WIN:
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                    ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                    ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                    ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


class Tray:
    def __init__(self, icon_path, on_open, on_restart, on_quit, tip="AT 星际公民助手"):
        self.icon_path, self.tip = str(icon_path), tip
        self.on = {ID_OPEN: on_open, ID_RESTART: on_restart, ID_QUIT: on_quit}
        self.hwnd = None
        self.ok = False
        self._ready = threading.Event()

    def start(self):
        if not WIN:
            return False
        threading.Thread(target=self._run, daemon=True, name="tray").start()
        self._ready.wait(5)
        return self.ok

    # ---------------------------------------------------------------- 托盘线程
    def _run(self):
        u32, k32, shell = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.shell32
        u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u32.DefWindowProcW.restype = LRESULT
        u32.CreateWindowExW.restype = wintypes.HWND
        u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                        wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u32.LoadImageW.restype = wintypes.HANDLE
        u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                   wintypes.UINT]
        u32.CreatePopupMenu.restype = wintypes.HMENU
        u32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        u32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       wintypes.HWND, wintypes.LPVOID]
        shell.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        try:
            self._proc = WNDPROC(self._wndproc)
            hinst = k32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.lpszClassName = "DubheTrayWindow"
            u32.RegisterClassW(ctypes.byref(wc))
            self.hwnd = u32.CreateWindowExW(0, "DubheTrayWindow", "Dubhe", 0, 0, 0, 0, 0, None, None, hinst, None)
            icon = u32.LoadImageW(None, self.icon_path, 1, 0, 0, 0x10 | 0x40)    # IMAGE_ICON, LR_LOADFROMFILE|LR_DEFAULTSIZE
            nid = self._nid()
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_USER_TRAY
            nid.hIcon = icon
            nid.szTip = self.tip
            self.ok = bool(shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        except Exception:
            self.ok = False
        self._ready.set()
        if not self.ok:
            return
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _wndproc(self, hwnd, msg, wparam, lparam):
        u32 = ctypes.windll.user32
        if msg == WM_USER_TRAY:
            event = lparam & 0xFFFF
            if event in (WM_LBUTTONDBLCLK, WM_LBUTTONUP):
                self._call(ID_OPEN)
            elif event == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_COMMAND:
            self._call(wparam & 0xFFFF)
            return 0
        if msg == WM_DESTROY:
            u32.PostQuitMessage(0)
            return 0
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        u32 = ctypes.windll.user32
        menu = u32.CreatePopupMenu()
        u32.AppendMenuW(menu, 0, ID_OPEN, "打开 AT")
        u32.AppendMenuW(menu, 0, ID_RESTART, "重新启动")
        u32.AppendMenuW(menu, 0x800, 0, None)                       # 分隔线
        u32.AppendMenuW(menu, 0, ID_QUIT, "退出 AT")
        pt = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(pt))
        u32.SetForegroundWindow(self.hwnd)
        u32.TrackPopupMenu(menu, 0, pt.x, pt.y, 0, self.hwnd, None)
        u32.DestroyMenu(menu)

    def _call(self, cmd):
        fn = self.on.get(cmd)
        if fn:
            threading.Thread(target=fn, daemon=True).start()

    def notify(self, title, text):
        """右下角弹一个气泡提示（第一次关掉窗口时告诉你 AT 还在后台）"""
        if not self.ok:
            return
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def remove(self):
        if self.ok:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.ok = False
