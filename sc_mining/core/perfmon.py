"""性能记录：每分钟往 userdata/logs/perf_log.txt 写一行，看天枢到底占了多少电脑资源

  天枢（主程序）、窗口（Edge）各自的 CPU 占用和内存（辅助进程 1.1.2 起没有了），
  以及这一分钟里各种文字识别做了几次、一共花了多少秒。
只在 Windows 上读进程信息（用系统自带接口，不装别的东西）；统计本身几乎不占资源。
"""
import os
import sys
import threading
import time

EVERY = 60.0
MAX_BYTES = 300_000
_ocr = {}                     # 识别用途 → [次数, 秒]
_ocr_lock = threading.Lock()

# 线程名 → 中文用途（识别是在哪个线程里做的，就算在谁头上）
KIND = {"task-hover": "F8", "hover-more": "F8", "displayinfo": "导航读位置", "live": "采矿助手",
        "task-manual_scan": "采矿助手"}


def note_ocr(seconds):
    name = threading.current_thread().name
    kind = KIND.get(name) or ("采矿助手" if name.startswith("live") else "其他")
    with _ocr_lock:
        n = _ocr.setdefault(kind, [0, 0.0])
        n[0] += 1
        n[1] += seconds


def _take_ocr():
    with _ocr_lock:
        out = dict(_ocr)
        _ocr.clear()
    return out


# ---------------------------------------------------------------- Windows 进程信息

def _win_procs():
    """[(pid, 父进程 pid, exe 名)]"""
    import ctypes
    from ctypes import wintypes

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)                    # TH32CS_SNAPPROCESS
    out = []
    try:
        pe = PE()
        pe.dwSize = ctypes.sizeof(PE)
        ok = k32.Process32FirstW(snap, ctypes.byref(pe))
        while ok:
            out.append((pe.th32ProcessID, pe.th32ParentProcessID, pe.szExeFile.lower()))
            ok = k32.Process32NextW(snap, ctypes.byref(pe))
    finally:
        k32.CloseHandle(snap)
    return out


def _open(pid):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    return k32.OpenProcess(0x1000, False, pid)                     # PROCESS_QUERY_LIMITED_INFORMATION


def _win_usage(pid):
    """(累计 CPU 秒, 实占内存 MB, 提交内存 MB)；进程不在了返回 None"""
    import ctypes
    from ctypes import wintypes

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + \
                   [(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                   "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                   "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                                                   "PrivateUsage")]
    k32 = ctypes.windll.kernel32
    h = _open(pid)
    if not h:
        return None
    try:
        c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
            return None
        cpu = sum(((t.dwHighDateTime << 32) | t.dwLowDateTime) for t in (kt, ut)) / 1e7
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        ws = priv = 0.0
        if k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            ws, priv = pmc.WorkingSetSize / 2 ** 20, pmc.PrivateUsage / 2 ** 20
        return cpu, ws, priv
    finally:
        k32.CloseHandle(h)


def _cmdline(pid):
    """进程的命令行（Windows 8.1 以上可读）；读不到返回空字符串"""
    import ctypes

    class US(ctypes.Structure):
        _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort), ("Buffer", ctypes.c_void_p)]
    h = _open(pid)
    if not h:
        return ""
    try:
        nt = ctypes.WinDLL("ntdll")
        need = ctypes.c_ulong(0)
        buf = ctypes.create_string_buffer(65536)                       # Edge 子进程的命令行很长
        st = nt.NtQueryInformationProcess(ctypes.c_void_p(h), 60, buf, len(buf), ctypes.byref(need))
        if st != 0 and need.value > len(buf):                          # 还不够：按它要的大小再来一次
            buf = ctypes.create_string_buffer(need.value)
            st = nt.NtQueryInformationProcess(ctypes.c_void_p(h), 60, buf, len(buf), ctypes.byref(need))
        if st != 0:
            return ""
        us = US.from_buffer(buf)
        return ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer else ""
    except Exception:
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def _tree(root, kids):
    todo, seen = [root], set()
    while todo:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.add(pid)
        todo += kids.get(pid, [])
    return seen


def _groups():
    """{名字: [pid…]}：天枢自己、辅助进程、窗口（用天枢自己那个 Edge 配置文件夹的 Edge 进程）"""
    me = os.getpid()
    out = {"天枢": [me]}
    helper = None
    try:
        from ..system import helpers
        if helpers._proc and helpers._proc.poll() is None:
            helper = helpers._proc.pid
    except Exception:
        pass
    if sys.platform != "win32":
        if helper:
            out["辅助进程"] = [helper]
        return out
    try:
        procs = _win_procs()
    except Exception:
        return out
    kids = {}
    for pid, ppid, exe in procs:
        kids.setdefault(ppid, []).append(pid)
    if helper:                       # .venv 里的 pythonw 只是个启动器，真正干活的是它开的子进程
        out["辅助进程"] = sorted(_tree(helper, kids))
    try:
        from .paths import USER
        profile = str(USER / "window").lower()
        edge = [pid for pid, _, exe in procs if exe in ("msedge.exe", "chrome.exe")
                and profile in _cmdline(pid).lower()]
        if edge:
            out["窗口(Edge)"] = edge
    except Exception:
        pass
    return out


class Monitor:
    def __init__(self):
        self.thread = None
        self.prev = {}

    def start(self):
        if not self.thread:
            self.thread = threading.Thread(target=self._run, daemon=True, name="perfmon")
            self.thread.start()

    def sample(self):
        """{名字: (累计 CPU 秒, 实占内存 MB, 提交内存 MB)}"""
        out = {}
        for name, pids in _groups().items():
            cpu = ws = priv = 0.0
            for pid in pids:
                if sys.platform == "win32":
                    u = _win_usage(pid)
                elif pid == os.getpid():
                    t = os.times()
                    u = (t.user + t.system, 0.0, 0.0)
                else:
                    u = None
                if u:
                    cpu += u[0]
                    ws += u[1]
                    priv += u[2]
            out[name] = (cpu, ws, priv)
        return out

    def line(self, now, cur, dt):
        cores = os.cpu_count() or 1
        parts = []
        for name, (cpu, ws, priv) in cur.items():
            was = self.prev.get(name)
            pct = max(0.0, (cpu - was[0]) / dt / cores * 100) if was else None
            parts.append(f"{name} CPU {pct:.1f}%" if pct is not None else f"{name} CPU —")
            if ws or priv:
                parts[-1] += f" 内存 {ws:.0f}MB（提交 {priv:.0f}MB）"
        ocr = _take_ocr()
        if ocr:
            parts.append("识别 " + "，".join(f"{k} {n} 次 {s:.1f}s" for k, (n, s) in sorted(ocr.items())))
        return time.strftime("%F %T", time.localtime(now)) + " " + "｜".join(parts)

    def _run(self):
        from .paths import log
        path = log("perf_log.txt")
        last = time.time()
        self.prev = self.sample()
        while True:
            time.sleep(EVERY)
            try:
                now = time.time()
                cur = self.sample()
                text = self.line(now, cur, now - last)
                self.prev, last = cur, now
                if path.exists() and path.stat().st_size > MAX_BYTES:
                    keep = path.read_text(encoding="utf-8").splitlines()[-500:]
                    path.write_text("\n".join(keep) + "\n", encoding="utf-8")
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
            except Exception:
                pass


monitor = Monitor()
