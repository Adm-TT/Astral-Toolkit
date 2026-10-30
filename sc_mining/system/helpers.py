"""游戏辅助（后台进程，主菜单打开时自动启动，菜单关掉它也退出）

双击 W 自动跑：在游戏里快速按两下 W，程序替你按住 W（和 Shift 冲刺）；再按一下 W 或 S 停下，
   切出游戏也会自动松开。只在步行时生效：读游戏日志 Game.log，在飞船/载具上（含在大船里走动）
   双击 W 不会触发，免得开船时被按住 W + Shift 加力撞船。

替代原来的 AutorunToggle 小工具，逻辑相同。2026-10-30 老大定：删掉防挂机（自动化挂机风险最高）。
游戏是管理员权限运行时，助手也要管理员身份，按键才送得进游戏。
用法（主菜单会自动启动）：python -m sc_mining.helpers <主程序进程号>
"""
import sys
import threading
import time
from pathlib import Path

from ..core import settings
from . import showloc as S

from ..core.paths import LOGS, USER, ROOT, self_cmd
LOG = LOGS / "helpers_log.txt"
MUTEX = "Local\\sc_assistant_helpers"
FLAG = USER / ".autorun_on"          # 自动跑中（导航和悬浮窗会看这个文件）

VK_W, VK_S = 0x57, 0x53
SC_W, SC_SHIFT = 0x11, 0x2A

_log_lock = threading.Lock()


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with _log_lock:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


if S.WIN:
    import ctypes
    from ctypes import wintypes

    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


    u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    u32.SetWindowsHookExW.restype = wintypes.HHOOK
    u32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    u32.CallNextHookEx.restype = LRESULT
    u32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    k32.GetModuleHandleW.restype = wintypes.HMODULE
    k32e = ctypes.WinDLL("kernel32", use_last_error=True)
    k32e.CreateMutexW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    u32.GetForegroundWindow.restype = wintypes.HWND


def _scan(code, up=False):
    S._send(0, code, 0x0008 | (0x0002 if up else 0))


def parent_alive(pid):
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == 259            # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


# ---------------------------------------------------------------- 双击 W 自动跑

class AutoRun:
    def __init__(self, cfg, game=None):
        self.game = game                # GameLog：在载具上就不触发
        self.sprint = cfg["autorun_sprint"]
        self.window = cfg["double_tap_ms"] / 1000
        self.engaged = False
        self.w_down = False
        self.last_tap = 0.0
        self.arm = False                # 第二下按下了，等它松开就开始自动跑
        self.todo = []                  # "on" / "off"，由工作线程执行（钩子回调里不直接发键）
        self.lock = threading.Lock()
        self.check_hud = S.WIN               # 开始自动跑前、跑的过程中看屏幕有没有飞行 HUD
        self.hud_at = 0.0

    def on_key(self, vk, down, injected):
        if injected or not S.game_foreground():
            if vk == VK_W:
                self.w_down = down if not injected else self.w_down
            return
        now = time.time()
        if vk == VK_W:
            if down and not self.w_down:               # 新按下（不是按住的连发）
                if self.engaged:
                    self._req("off")
                elif now - self.last_tap <= self.window and not self.aboard():
                    self.arm = True
                self.last_tap = now
            elif not down and self.arm:
                self.arm = False
                self._req("on")
            self.w_down = down
        elif vk == VK_S and down and self.engaged:
            self._req("off")

    def aboard(self):
        return bool(self.game and self.game.aboard)

    def _req(self, what):
        with self.lock:
            self.todo.append(what)

    def step(self):
        with self.lock:
            todo, self.todo = self.todo, []
        for what in todo:
            if what == "on" and not self.engaged and not self.aboard():
                if self.check_hud:
                    from . import cockpit
                    if cockpit.flying():             # 日志没记下坐上驾驶位时的第二道保险
                        log("自动跑：屏幕上有飞行 HUD（坐在驾驶位上），不触发")
                        continue
                if self.sprint:
                    _scan(SC_SHIFT)
                _scan(SC_W)
                self.engaged = True
                _flag(True)
                log("自动跑：开始")
            elif what == "off" and self.engaged:
                self.release()
                log("自动跑：停下")
        if self.engaged and self.check_hud and time.time() - self.hud_at > 2.0:
            self.hud_at = time.time()           # 跑着跑着坐进了驾驶位：屏幕上出现飞行 HUD 就马上松开
            from . import cockpit
            if cockpit.flying(timeout=0):
                self.release()
                log("自动跑：屏幕上出现飞行 HUD（坐进驾驶位了），已松开")
                return
        if self.engaged and not S.game_foreground():
            self.release()
            log("自动跑：切出游戏，已松开")
        elif self.engaged and self.aboard():
            self.release()
            log("自动跑：坐上驾驶位，已松开")

    def release(self):
        if self.engaged:
            _scan(SC_W, up=True)
            if self.sprint:
                _scan(SC_SHIFT, up=True)
            self.engaged = False
            _flag(False)


def _flag(on):
    try:
        if on:
            FLAG.write_text("1", encoding="utf-8")
        elif FLAG.exists():
            FLAG.unlink()
    except OSError:
        pass


def autorun_on():
    return FLAG.exists()


# ---------------------------------------------------------------- 主程序

RESTART_REQUEST = USER / "restart_request"


def _restart_requested():
    """userdata 里有 restart_request 这个文件：替主程序「重新启动」一次（和托盘菜单的重新启动一样，
    用 AT 自己的管理员身份开新的，不弹 Windows 确认框）。远程帮你重启时用"""
    if not RESTART_REQUEST.exists():
        return False
    try:
        RESTART_REQUEST.unlink()
    except OSError:
        return False
    import subprocess
    subprocess.Popen(self_cmd("restart"), cwd=str(ROOT),
                     creationflags=0x08000000 if S.WIN else 0)
    log("收到重启请求：已经让 AT 重新启动")
    return True


def main(parent_pid):
    if _restart_requested():
        return
    cfg = settings.load()
    if not cfg["autorun"]:
        return
    from ..core.perf import lower_priority
    lower_priority()
    # 只能有一个辅助进程（新开的管理员窗口要等旧的退出，最多等 15 秒）
    for _ in range(30):
        h = k32e.CreateMutexW(None, True, MUTEX)
        if h and ctypes.get_last_error() != 183:      # ERROR_ALREADY_EXISTS
            break
        if h:
            k32.CloseHandle(h)                      # 不关的话互斥量一直存在，永远拿不到
        time.sleep(0.5)
    else:
        return
    LOG.write_text("", encoding="utf-8")
    _flag(False)
    log(f"辅助已启动：双击W自动跑 {'开' if cfg['autorun'] else '关'}，"
        f"管理员身份 {'是' if S.is_admin() else '否'}")
    if S.game_elevated() and not S.is_admin():
        log("注意：游戏是管理员权限运行，助手不是，按键会被 Windows 挡掉。请用管理员身份打开助手")

    stop = threading.Event()
    game = None
    if cfg["autorun"]:
        from .gamelog import GameLog, find_log
        path = find_log()
        game = GameLog(path)
        game.poll()
        if path:
            log(f"游戏日志：{path}；现在{'坐在 ' + game.vehicle + ' 驾驶位上' if game.vehicle else '没在开船'}")
        else:
            log("没找到游戏日志 Game.log：判断不了是不是在开船，开着游戏时会再找")
    run = AutoRun(cfg, game) if cfg["autorun"] else None
    # 双击 W 时看飞行 HUD：问主程序（它有识别引擎）；辅助进程自己不再预加载引擎（2026-10-26，省约 100 MB 内存）

    hook_tid = k32.GetCurrentThreadId()

    def watcher():
        n = 0
        while not stop.is_set():
            n += 1
            if game and n % 10 == 0:                 # 每 0.5 秒读一次新日志
                if game.poll():
                    log(f"双击W自动跑：{'坐在 ' + game.vehicle + ' 驾驶位上，暂停' if game.vehicle else '没在开船，可用'}")
            if run:
                run.step()
            if n % 20 == 0 and not parent_alive(parent_pid):         # 主程序还在不在：1 秒看一次就够
                stop.set()
                u32.PostThreadMessageW(hook_tid, 0x0012, 0, 0)       # WM_QUIT
                return
            time.sleep(0.05)
    threading.Thread(target=watcher, daemon=True).start()

    if run:
        def proc(n, wparam, lparam):
            try:
                if n == 0:
                    kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if kb.vkCode in (VK_W, VK_S):
                        down = wparam in (0x0100, 0x0104)                 # WM_KEYDOWN / WM_SYSKEYDOWN
                        run.on_key(kb.vkCode, down, bool(kb.flags & 0x10))  # LLKHF_INJECTED
            except Exception as e:
                log(f"键盘监听出错：{e}")
            return u32.CallNextHookEx(None, n, wparam, lparam)
        cb = HOOKPROC(proc)
        hook = u32.SetWindowsHookExW(13, cb, k32.GetModuleHandleW(None), 0)    # WH_KEYBOARD_LL
        if not hook:
            log(f"双击W自动跑：键盘监听没装上（错误码 {ctypes.GetLastError()}）")
    msg = wintypes.MSG()
    try:
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
    finally:
        stop.set()
        if run:
            run.release()
        _flag(False)
        log("辅助已退出")


# ---------------------------------------------------------------- 主菜单用

_proc = None


def start():
    """主菜单调用：启动后台辅助进程（已经在跑就先停掉重启）"""
    import os
    import subprocess
    global _proc
    if not S.WIN:
        return False
    stop_helpers()
    cfg = settings.load()
    if not cfg.get("agreed"):              # 第一次打开还没确认免费声明：先不启动
        return False
    if not cfg["autorun"]:
        return False
    _proc = subprocess.Popen(self_cmd("helpers", os.getpid()),
                             cwd=str(ROOT), creationflags=0x08000000)        # CREATE_NO_WINDOW
    return True


def stop_helpers():
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(3)
        except Exception:
            pass
        try:                                   # 自动跑可能正按着 W / Shift，子进程被结束来不及松：主进程替它松开（老大审查 2026-10-28）
            _scan(SC_W, up=True)
            _scan(SC_SHIFT, up=True)
            _flag(False)                       # 「自动跑中」标记也清掉（悬浮窗 / 定位都看它）
        except Exception:
            pass
    _proc = None


def status_line():
    cfg = settings.load()
    parts = [f"双击W自动跑 {'开' if cfg['autorun'] else '关'}"]
    line = "辅助：" + "｜".join(parts)
    if S.WIN and not S.is_admin() and S.game_elevated():
        line += "｜游戏是管理员权限，助手不是，自动按键会失效"
    return line


def menu():
    """主菜单第 7 项：开关设置"""
    while True:
        cfg = settings.load()
        print(status_line())
        print(f"  1. 双击W自动跑：{'开' if cfg['autorun'] else '关'}（{'带冲刺' if cfg['autorun_sprint'] else '不冲刺'}）")
        print(f"  2. 自动跑时冲刺（按住 Shift）：{'开' if cfg['autorun_sprint'] else '关'}")
        print(f"  3. 管理员身份：{ {True: '每次都用', False: '不用', None: '没设置'}[cfg['admin']] }")
        print("  回车返回")
        c = input("> ").strip()
        if not c:
            return
        if c == "1":
            settings.update(autorun=not cfg["autorun"])
        elif c == "2":
            settings.update(autorun_sprint=not cfg["autorun_sprint"])
        elif c == "3":
            settings.update(admin={None: True, True: False, False: True}[cfg["admin"]])
            print("下次打开助手生效")
        else:
            continue
        start()
        print("（已应用）\n")


if __name__ == "__main__":
    from ..core import paths as _p
    _p.crash_log()
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
