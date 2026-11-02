"""少占电脑资源，别拖慢游戏

- AT 自己的进程（窗口和后台辅助）都降成「低于正常」优先级：游戏要用 CPU 时让着游戏
- 截图只截需要的那一块，不截整个屏幕
- 你按 F8 这种「等着看结果」的识别临时用正常优先级跑完（boost）；识别插队和引擎本身在 ocr/runtime.py
"""

import contextlib
import sys
import threading
import time


def lower_priority():
    if sys.platform != "win32":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(
            k32.GetCurrentProcess(), 0x00004000
        )  # BELOW_NORMAL_PRIORITY_CLASS
    except Exception:
        pass


_boost = {"n": 0, "lock": threading.Lock()}


@contextlib.contextmanager
def boost():
    """你在等结果的那一下（F8）：临时恢复正常优先级，跑完马上降回去。
    平时 AT 是「低于正常」优先级，游戏占满 CPU 时识别会被挤得很慢"""
    if sys.platform != "win32":
        yield
        return
    import ctypes

    k32 = ctypes.windll.kernel32
    with _boost["lock"]:
        _boost["n"] += 1
        if _boost["n"] == 1:
            k32.SetPriorityClass(
                k32.GetCurrentProcess(), 0x00000020
            )  # NORMAL_PRIORITY_CLASS
    try:
        yield
    finally:
        with _boost["lock"]:
            _boost["n"] -= 1
            if _boost["n"] == 0:
                k32.SetPriorityClass(
                    k32.GetCurrentProcess(), 0x00004000
                )  # BELOW_NORMAL_PRIORITY_CLASS


def overlay_rect():
    """悬浮窗现在在屏幕上的位置 (左, 上, 右, 下)，物理像素；没显示返回 None"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        from ..app import overlay

        HWND = overlay.HWND
        u32 = ctypes.windll.user32
        if (
            not HWND or not overlay.SHOWN or not u32.IsWindowVisible(HWND)
        ):  # 没内容时窗口全透明，不用涂
            return None
        r = wintypes.RECT()
        u32.GetWindowRect(HWND, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


def own_window_rects():
    """AT 自己的主窗口盖在游戏上时的位置：只算「在最前面」或「置顶」的（在游戏后面的窗口看不见，涂黑反而挡住游戏）。
    2026-10-23 全量样本测试：窗口里的实时栏写着信号值 / 石头质量，盖在游戏上会被当成游戏里的字"""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        import os
        from ctypes import wintypes
        from ..app import overlay

        u32 = ctypes.windll.user32
        pid, fg, out = os.getpid(), u32.GetForegroundWindow(), []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def each(h, _):
            p = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if (
                p.value == pid
                and h != overlay.HWND
                and u32.IsWindowVisible(h)
                and not u32.IsIconic(h)
            ):
                top = u32.GetWindowLongW(h, -20) & 0x8  # GWL_EXSTYLE / WS_EX_TOPMOST
                if h == fg or top:
                    r = wintypes.RECT()
                    u32.GetWindowRect(h, ctypes.byref(r))
                    if r.right - r.left > 50 and r.bottom - r.top > 50:
                        out.append((r.left, r.top, r.right, r.bottom))
            return True

        u32.EnumWindows(each, 0)
        return out
    except Exception:
        return []


def mask_overlay(img, left, top, rect=None, scale=1.0, own=None):
    """截图里悬浮窗（和盖在最前面的 AT 主窗口）那块涂黑：img 是从屏幕 (left, top) 开始截的；scale = 截图像素 / 窗口坐标像素"""
    rects = [rect or overlay_rect()] + (
        own_window_rects() if own is None else list(own)
    )
    from PIL import ImageDraw

    for rc in rects:
        if not rc:
            continue
        l, t, r, b = (int(v * scale) for v in rc)  # noqa: E741
        l, t, r, b = l - left, t - top, r - left, b - top  # noqa: E741
        if r <= 0 or b <= 0 or l >= img.width or t >= img.height:
            continue
        ImageDraw.Draw(img).rectangle(
            (max(0, l), max(0, t), min(img.width, r) - 1, min(img.height, b) - 1),
            fill=(0, 0, 0),
        )
    return img


def _scale(mon):
    """窗口坐标 → 截图像素的比例（AT 没开高 DPI 感知时，Windows 给的窗口坐标是缩放过的）"""
    try:
        import ctypes

        w = ctypes.windll.user32.GetSystemMetrics(0)
        return mon["width"] / w if w else 1.0
    except Exception:
        return 1.0


_tls = threading.local()


def _sct():
    """每个线程留一个截图对象重复用（每次新建要重新枚举显示器，白白多花时间）"""
    sct = getattr(_tls, "sct", None)
    if sct is None:
        import mss

        sct = _tls.sct = mss.mss()
    return sct


def _shot(area):
    from PIL import Image

    try:
        shot = _sct().grab(area)
    except Exception:  # 显示器变了（改分辨率、插拔）：重建一次再截
        _tls.sct = None
        shot = _sct().grab(area)
    return Image.frombytes("RGB", shot.size, shot.rgb)


_game_area_cache = {"t": 0.0, "area": None, "found": False}


def game_area():
    """截图的范围：游戏窗口的客户区（截图像素坐标 {left, top, width, height}），游戏在副显示器、窗口模式时也截对地方
    （1.6.46，以前一律截主显示器整屏）。找不到游戏窗口、窗口最小化或太小 → 主显示器整屏（和以前一样）。
    每 0.5 秒最多查一次窗口位置"""
    m = _sct().monitors[1]
    if sys.platform != "win32":
        return dict(m)
    now = time.time()
    if now - _game_area_cache["t"] < 0.5 and _game_area_cache["area"]:
        return _game_area_cache["area"]
    area, found = dict(m), False
    try:
        import ctypes
        from ctypes import wintypes
        from ..system import showloc

        u32 = ctypes.windll.user32
        hwnd = showloc.find_game_window()
        if hwnd and not u32.IsIconic(hwnd):
            rc = wintypes.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(rc))
            pt = wintypes.POINT(0, 0)
            u32.ClientToScreen(hwnd, ctypes.byref(pt))
            s = _scale(m)
            w, h = int(rc.right * s), int(rc.bottom * s)
            if w >= 640 and h >= 360:
                area = {
                    "left": int(pt.x * s),
                    "top": int(pt.y * s),
                    "width": w,
                    "height": h,
                }
                found = True
    except Exception:
        pass
    _game_area_cache.update(t=now, area=area, found=found)
    return area


def game_size():
    """找到游戏窗口时游戏画面的 (宽, 高)，像素；没找到返回 None。界面上提醒画面太小识别不准用（2026-10-25）"""
    try:
        a = game_area()
        return (a["width"], a["height"]) if _game_area_cache.get("found") else None
    except Exception:
        return None


def grab_screen():
    """截游戏画面（找不到游戏窗口就整屏；悬浮窗那块已涂黑）"""
    a = game_area()
    img = _shot(a)
    return (
        mask_overlay(img, a["left"], a["top"], scale=_scale(_sct().monitors[1]))
        if sys.platform == "win32"
        else img
    )


def grab_region(box):
    """只截游戏画面的一块：box = (左, 上, 右, 下)，都是占画面的比例。返回 PIL 图片"""
    a = game_area()
    l, t, r, b = box  # noqa: E741
    area = {
        "left": a["left"] + int(a["width"] * l),
        "top": a["top"] + int(a["height"] * t),
        "width": max(1, int(a["width"] * (r - l))),
        "height": max(1, int(a["height"] * (b - t))),
    }
    img = _shot(area)
    if sys.platform == "win32":
        img = mask_overlay(
            img, area["left"], area["top"], scale=_scale(_sct().monitors[1])
        )
    return img


def cursor_on_image(img):
    """鼠标位置换算成截图（游戏画面）里的像素坐标；鼠标不在画面里也照样换算（可能是负数或超出）"""
    import ctypes
    from ctypes import wintypes

    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    a = game_area()
    s = _scale(_sct().monitors[1])
    return int(pt.x * s - a["left"]) * img.width // max(1, a["width"]), int(
        pt.y * s - a["top"]
    ) * img.height // max(1, a["height"])
