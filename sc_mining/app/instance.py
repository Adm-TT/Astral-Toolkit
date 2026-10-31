"""只开一个 AT（从 server.py 拆出来，2026-10-31 控制台指令第 1 批）：锁住 userdata/instance.lock；已经开着就叫它打开窗口或退出"""

import sys
import time


def _call_old(url, action):
    """给已经开着的 AT 发命令：show = 打开窗口，quit = 退出"""
    import urllib.request
    from urllib.parse import urlparse

    u = urlparse(url)
    token = u.fragment.split("t=", 1)[-1] if "t=" in u.fragment else ""
    req = urllib.request.Request(
        f"{u.scheme}://{u.netloc}/api/{action}",
        data=b"{}",
        headers={"Content-Type": "application/json", "X-Token": token},
    )
    urllib.request.urlopen(req, timeout=3).read()


def _try_lock():
    """只开一个 AT 的锁：锁住 userdata/instance.lock 这个文件。锁上了返回打开的文件，已经被别的 AT 锁着返回 None。
    AT 退出（哪怕是被强制结束）时 Windows 会自动解锁；管理员身份、普通身份开的都认这同一把锁"""
    from ..core import paths

    f = open(paths.USER / "instance.lock", "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def release_instance():
    """放开锁（换管理员身份重开前用，让新开的那个能拿到）"""
    f = getattr(_single_instance, "lock", None)
    if f:
        try:
            f.close()
        except Exception:
            pass
    _single_instance.lock = None
    _single_instance.mine = False


def _single_instance(restart=False):
    """只允许一个 AT 在运行。已经开着一个：平时只是把它的窗口打开；restart=True 时请它退出、等它退完再启动。
    返回 True 表示这次要启动"""
    if getattr(_single_instance, "mine", False):
        return True
    from ..core import paths

    f = _try_lock()
    if f:
        _single_instance.lock, _single_instance.mine = f, True
        return True
    try:
        url = (paths.USER / "window_url.txt").read_text(encoding="utf-8").strip()
    except Exception:
        url = ""
    if not restart:
        try:
            from .winid import allow_focus

            allow_focus()
        except Exception:
            pass
        try:
            _call_old(url, "show")  # 已经开着的天枢把窗口打开
            return False
        except Exception:
            time.sleep(3)  # 可能刚好也在启动：等它起来再叫一次
            try:
                _call_old(
                    (paths.USER / "window_url.txt").read_text(encoding="utf-8").strip(),
                    "show",
                )
                return False
            except Exception:
                pass  # 旧天枢卡住了：请它退出，重新开
    try:
        _call_old(url, "quit")
    except Exception:
        pass
    for _ in range(
        240
    ):  # 最多等 60 秒（旧进程要关窗口、停助手；慢机器 / 杀毒扫描时 15 秒不够，2026-10-28）
        time.sleep(0.25)
        f = _try_lock()
        if f:
            _single_instance.lock, _single_instance.mine = f, True
            return True
    try:  # 一分钟还没放锁：别悄悄退出，告诉玩家怎么办（终审 2026-10-28）
        from ..run import _error_box

        _error_box(
            "上一个 AT 还没退出。在屏幕右下角托盘右键 AT 图标选「退出」，再打开。"
        )
    except Exception:
        pass
    return False  # 拿不到锁就不开第二个
