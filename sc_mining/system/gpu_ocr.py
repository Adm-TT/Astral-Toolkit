"""显卡 OCR 小进程（2026-10-27 老大定：内存压下去，但采矿助手还要用显卡）

用显卡（DirectML）找字时，显卡驱动一载入就一直占着 300 多 MB 实际内存（提交量 1 GB 以上），会话关了也不还，
只有进程退出才还（onnxruntime 官方问题区的结论，本机实测一样）。所以：
- AT 主程序只用 CPU 跑 OCR（F8、地点名、雷达信号这些零碎的小图）
- 采矿助手开着时，起一个只做 OCR 的小进程用显卡找字；采矿助手关了就结束它，内存全部还给系统
- 小进程活着时，主程序里要「找字」的识别都转给它（F8 也借用）；它出错或没起来，自动退回主程序的 CPU，不会认不出
通信：Windows 命名管道（multiprocessing.connection，带随机密钥）；AT 主程序退出管道就断，小进程跟着退出
"""
import os
import secrets
import subprocess
import sys
import threading
import time

WORKER_ENV = "AT_OCR_WORKER"          # 小进程里这个环境变量是 "1"：perf.rapidocr() 才会用显卡
START_TIMEOUT = 30                     # 小进程启动（载入模型 + 显卡驱动）最多等这么久
RUN_TIMEOUT = 20                       # 一次识别最多等这么久，超时就当它坏了
RETRY_AFTER = 60                       # 起不来 / 坏了：这么多秒内不再试，直接用 CPU

_lock = threading.Lock()               # 管理小进程（启动、结束）
_io = threading.Lock()                 # 一次只送一张图
_st = {"proc": None, "conn": None, "users": 0, "bad_at": 0.0, "device": "", "permanent": None, "last_error": ""}


def is_worker():
    return os.environ.get(WORKER_ENV) == "1"


def wanted():
    """这台电脑能用显卡找字（装的是 onnxruntime-directml、没强制 CPU）"""
    if os.environ.get("DUBHE_OCR_CPU") == "1" or sys.platform != "win32":
        return False
    from ..core.perf import gpu_available
    return gpu_available()


def active():
    p = _st["proc"]
    return bool(_st["conn"] is not None and p is not None and p.poll() is None)


def device():
    return "显卡" if active() else "CPU"


def _cmd():
    from ..core import paths
    if paths.FROZEN:
        return [sys.executable, "ocrworker"]
    return [sys.executable, "-X", "utf8", "-m", "sc_mining.system.gpu_ocr"]


def _start():
    """起小进程，等它连上管道、载好模型；不成功返回 False（调用方照常用 CPU）"""
    from multiprocessing.connection import Listener, Client
    addr = rf"\\.\pipe\at_ocr_{os.getpid()}_{secrets.token_hex(6)}"
    key = secrets.token_bytes(16)
    try:
        lst = Listener(addr, family="AF_PIPE", authkey=key)
    except OSError:
        return False
    env = dict(os.environ, AT_OCR_PIPE=addr, AT_OCR_KEY=key.hex(), **{WORKER_ENV: "1"})
    from ..core import paths
    try:
        proc = subprocess.Popen(_cmd(), env=env, creationflags=0x08000000,       # CREATE_NO_WINDOW
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                cwd=str(paths.ROOT))          # Python 版：-m sc_mining.gpu_ocr 要在项目根目录（二审 2026-10-27）
    except OSError:
        lst.close()
        return False
    _bind_job(proc)
    got = {}

    def accept():
        try:
            got["conn"] = lst.accept()
        except Exception:
            pass
    t = threading.Thread(target=accept, daemon=True)
    t.start()
    end = time.time() + START_TIMEOUT
    while t.is_alive() and time.time() < end and proc.poll() is None:   # 小进程刚起就死了：马上放弃，不干等（二审）
        t.join(0.1)
    if "conn" not in got:                               # 没连上：自己连一下把 accept 放出来，再收拾
        try:
            Client(addr, family="AF_PIPE", authkey=key).close()
        except Exception:
            pass
        t.join(2)
        lst.close()
        _st["last_error"] = f"小进程管道未连接（退出码：{proc.poll()}）"
        _kill(proc)
        return False
    lst.close()
    conn = got["conn"]
    try:
        while not conn.poll(0.2):                          # 等它载好模型；中途死了马上放弃
            if proc.poll() is not None or time.time() > end:
                raise TimeoutError("小进程未就绪超时或意外退出")
        tag, dev = conn.recv()
    except Exception as e:                                      # 没起来 / 中途崩了（管道断了 poll 也会报错）：收尾、退回 CPU（复审 2026-10-27）
        tag, dev = "fail", str(e)
    if tag != "ready" or dev != "显卡":                 # 小进程里显卡没用上：留着也没意义
        _st["last_error"] = f"小进程启动失败：tag={tag}, dev={dev}"
        conn.close()
        _kill(proc)
        return False
    _st.update(proc=proc, conn=conn, device=dev, last_error="")
    return True


def info():
    return {
        "active": active(),
        "device": device(),
        "wanted": wanted(),
        "permanent": is_permanent(),
        "last_error": _st.get("last_error", "")
    }


_job = {"h": None}


def _bind_job(proc):
    """把小进程放进 Windows 作业对象（KILL_ON_JOB_CLOSE）：AT 退出 / 被强关时系统自动结束它，
    不会留下占显卡和内存的孤儿进程（二审 2026-10-27）"""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if _job["h"] is None:
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            h = k32.CreateJobObjectW(None, None)
            if not h:
                return

            class BASIC(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

            class IOC(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rt", "wt", "ot")]

            class EXT(ctypes.Structure):
                _fields_ = [("Basic", BASIC), ("Io", IOC), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]
            info = EXT()
            info.Basic.LimitFlags = 0x2000                 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(wintypes.HANDLE(h), 9, ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(wintypes.HANDLE(h))
                return
            _job["h"] = h                                  # 句柄留在主程序里不关（关了小进程就被结束）
        k32.AssignProcessToJobObject(wintypes.HANDLE(_job["h"]), wintypes.HANDLE(int(proc._handle)))
    except Exception:
        pass


def _kill(proc):
    try:
        proc.kill()
        proc.wait(5)
    except Exception:
        pass


def _stop():
    conn, proc = _st["conn"], _st["proc"]
    _st.update(conn=None, proc=None, device="")
    if conn is not None:
        try:
            conn.close()                                # 小进程读到管道断了会自己退出
        except Exception:
            pass
    if proc is not None:
        try:
            proc.wait(3)
        except Exception:
            _kill(proc)


def is_permanent():
    """是否开启常驻显卡 OCR（默认由 settings.json 的 always_use_gpu 决定）"""
    if _st.get("permanent") is None:
        try:
            from ..core import settings
            _st["permanent"] = bool(settings.load().get("always_use_gpu", True))
        except Exception:
            _st["permanent"] = True
    return bool(_st.get("permanent"))


def ensure_active(blocking=True):
    """常驻启用显卡 OCR：小进程启动并在后台常驻，不随采矿助手退出而关闭。
    blocking=False 时在后台异步启动，不卡顿主流程。"""
    with _lock:
        _st["permanent"] = True
    if active() or not wanted() or time.time() - _st["bad_at"] < RETRY_AFTER:
        return active()
    if not blocking:
        revive()
        return active()
    with _lock:
        if active():
            return True
        if not _start():
            _st["bad_at"] = time.time()
        return active()


def release_permanent():
    """取消常驻显卡 OCR：如果当前采矿助手也没在用，则停止小进程归还系统内存"""
    with _lock:
        _st["permanent"] = False
        if _st["users"] <= 0:
            with _io:
                _stop()


def shutdown():
    """主程序退出时彻底关闭小进程并清空状态"""
    with _lock:
        _st["permanent"] = None
        _st["users"] = 0
        with _io:
            _stop()


def acquire():
    """采矿助手开始：要用显卡（引用计数）。起不来不报错，照常用 CPU。返回现在是不是显卡"""
    with _lock:
        _st["users"] += 1
        if active() or not wanted() or time.time() - _st["bad_at"] < RETRY_AFTER:
            return active()
        if not _start():
            _st["bad_at"] = time.time()
        return active()


def revive():
    """采矿助手还开着或设置了常驻、小进程坏了：过了 RETRY_AFTER 秒在后台重新拉起（不挡识别，二审 2026-10-27）"""
    need = _st["users"] > 0 or is_permanent()
    if not need or active() or time.time() - _st["bad_at"] < RETRY_AFTER or not wanted():
        return
    if not _lock.acquire(blocking=False):
        return

    def go():
        try:
            if (_st["users"] > 0 or is_permanent()) and not active() and not _start():
                _st["bad_at"] = time.time()
        finally:
            _lock.release()
    _st["bad_at"] = time.time()                            # 拉起期间别再重复拉
    threading.Thread(target=go, daemon=True, name="gpu-ocr-revive").start()


def release():
    """采矿助手结束：没人用了就结束小进程（内存还给系统，若常驻开启则保留）"""
    with _lock:
        _st["users"] = max(0, _st["users"] - 1)
        if _st["users"] == 0 and not is_permanent():
            with _io:
                _stop()


URGENT_TIMEOUT = 8                     # F8（玩家在等）最多等小进程这么久，超时用 CPU


def run(arr, kw, urgent=False):
    """送一张图给小进程识别 → 和 RapidOCR 一样的结果；小进程不在 / 出错 / 超时返回 None（调用方用 CPU）。
    urgent：F8，小进程临时用正常优先级、超时更短"""
    if not active():
        return None
    with _io:
        conn = _st["conn"]
        if conn is None:
            return None
        proc = _st["proc"]
        # 看门狗：发图、等结果整段超时就按 PID 结束小进程——小进程不读管道时 send() 本身会堵住，只给 poll 设超时没用（二审 2026-10-27）
        dog = threading.Timer(URGENT_TIMEOUT if urgent else RUN_TIMEOUT, _kill, (proc,)) if proc is not None else None
        if dog is not None:
            dog.daemon = True
            dog.start()
        try:
            conn.send((arr, kw, bool(urgent)))
            if not conn.poll(URGENT_TIMEOUT if urgent else RUN_TIMEOUT):
                raise TimeoutError
            tag, res = conn.recv()
            if dog is not None:
                dog.cancel()
            if tag == "ok":
                return res
            return None                                 # 这张图在小进程里出错：这次用 CPU，小进程留着
        except Exception:
            if dog is not None:
                dog.cancel()
            # 管道坏了 / 超时：结束小进程，过一会儿再试。已经拿着 _io，不再拿 _lock——release() 是先 _lock 后 _io，
            # 两边反着拿会死锁（二审 2026-10-27）。只收拾这次用的那个：期间可能已经起了新的（复审）
            _st["bad_at"] = time.time()
            if _st["proc"] is proc:
                _stop()
            else:
                try:
                    conn.close()
                except Exception:
                    pass
                if proc is not None:
                    _kill(proc)
            return None


def worker_main():
    """小进程：连上管道 → 载入显卡 OCR → 一张张识别，主程序断开就退出"""
    from ..core import paths
    paths.crash_log("crash_log_ocr.txt")       # 显卡驱动 / DirectML 最可能在这里直接崩（输出是 DEVNULL，不记就什么都留不下）
    from multiprocessing.connection import Client
    conn = Client(os.environ["AT_OCR_PIPE"], family="AF_PIPE", authkey=bytes.fromhex(os.environ["AT_OCR_KEY"]))
    from ..core import perf
    perf.lower_priority()
    try:
        eng = perf.rapidocr()
        import numpy as np
        eng(np.zeros((32, 64, 3), dtype=np.uint8))       # 先跑一次：显卡驱动在这里载入，别让第一张图等
        conn.send(("ready", perf.ocr_device()))
    except Exception as e:
        conn.send(("fail", repr(e)))
        return
    while True:
        try:
            msg = conn.recv()
            arr, kw = msg[0], msg[1]
            urgent = len(msg) > 2 and msg[2]
        except (EOFError, OSError):
            return
        except Exception:
            continue
        try:
            if urgent:                                  # F8：玩家在等，临时正常优先级（和主程序的 perf.boost 一样）
                with perf.boost():
                    res = eng(arr, **kw)
            else:
                res = eng(arr, **kw)
            conn.send(("ok", res))
        except (EOFError, OSError):
            return
        except Exception as e:
            try:
                conn.send(("err", repr(e)))
            except Exception:
                return


if __name__ == "__main__":
    worker_main()
