"""截游戏画面：只截需要的那一块，并把 AT 自己的窗涂黑，免得读到自己的字"""

import sys
import threading
import time

# 悬浮窗的窗口句柄和「现在有没有显示内容」由装配接进来（bootstrap.bind_all，CL-C5）：
# core 不再反过来 import 界面。没接（不是桌面程序：工具、测试）当没有悬浮窗，和以前读到 HWND 是 None 一样
_overlay_state = None


def set_overlay_state(probe):
    """装配时接一个 () -> (悬浮窗句柄, 显示着没有)；截图时用它找悬浮窗那块涂黑"""
    global _overlay_state
    _overlay_state = probe


def _overlay():
    probe = _overlay_state
    return probe() if probe else (None, False)


def overlay_rect():
    """悬浮窗现在在屏幕上的位置 (左, 上, 右, 下)，物理像素；没显示返回 None"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        HWND, shown = _overlay()
        u32 = ctypes.windll.user32
        if (
            not HWND or not shown or not u32.IsWindowVisible(HWND)
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

        overlay_hwnd = _overlay()[0]
        u32 = ctypes.windll.user32
        pid, fg, out = os.getpid(), u32.GetForegroundWindow(), []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def each(h, _):
            p = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if (
                p.value == pid
                and h != overlay_hwnd
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


def _window_area(m):
    """游戏窗口的客户区 → (截图像素坐标 {left, top, width, height}, True)；找不到游戏窗口、窗口最小化或太小 →
    (主显示器整屏, False)"""
    try:
        import ctypes
        from ctypes import wintypes
        from ...system import showloc

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
                return {
                    "left": int(pt.x * s),
                    "top": int(pt.y * s),
                    "width": w,
                    "height": h,
                }, True
    except Exception:
        pass
    return dict(m), False


def game_area():
    """截图的范围：游戏窗口的客户区（截图像素坐标 {left, top, width, height}），游戏在副显示器、窗口模式时也截对地方
    （1.6.46，以前一律截主显示器整屏）。找不到游戏窗口、窗口最小化或太小 → 主显示器整屏（和以前一样）。
    窗口里只有一块是画面、其余是黑边（无边框 + 游戏分辨率比显示器小）→ 只算有画面的那一块（_padded）。
    每 0.5 秒最多查一次窗口位置"""
    m = _sct().monitors[1]
    if sys.platform != "win32":
        return dict(m)
    now = time.time()
    if now - _game_area_cache["t"] < 0.5 and _game_area_cache["area"]:
        return _game_area_cache["area"]
    area, found = _window_area(m)
    if found:  # 找不到游戏窗口时截的是整个桌面：不在桌面上找黑边
        try:
            box = _padded(area)
        except Exception:
            box = None
        if box:
            area = {
                "left": area["left"] + box[0],
                "top": area["top"] + box[1],
                "width": box[2],
                "height": box[3],
            }
    _game_area_cache.update(t=now, area=area, found=found)
    return area


# 游戏画面常见的大小（截图像素）：认黑边时，有画面的那一块要正好是其中一个才算数（暗场景里碰巧框出一块别的大小不算）
_FRAME_SIZES = frozenset(
    (
        (1280, 720),
        (1280, 800),
        (1280, 1024),
        (1366, 768),
        (1440, 900),
        (1600, 900),
        (1600, 1200),
        (1680, 1050),
        (1920, 1080),
        (1920, 1200),
        (2048, 1152),
        (2560, 1080),
        (2560, 1440),
        (2560, 1600),
        (3200, 1800),
        (3440, 1440),
        (3840, 1080),
        (3840, 1600),
        (3840, 2160),
        (5120, 1440),
    )
)
_BLACK = 8  # 三个颜色都不超过这个数算黑


def _lit(img):
    """这张图里有没有不黑的像素"""
    return max(hi for _, hi in img.convert("RGB").getextrema()) > _BLACK


def _lit_box(img):
    """不黑的像素的外接框 (左, 上, 右, 下)，像素；全黑返回 None"""
    import numpy as np

    lit = np.asarray(img.convert("RGB")).max(axis=2) > _BLACK
    cols, rows = np.flatnonzero(lit.any(axis=0)), np.flatnonzero(lit.any(axis=1))
    if not cols.size or not rows.size:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _frame_of(lit, size):
    """亮像素的外接框正好是一个常见的游戏画面大小、又没占满整张图 → 有画面的那一块 (左, 上, 宽, 高)；不是返回 None。
    无边框模式下游戏分辨率比显示器小，游戏窗口占满整个屏幕、画面只画在一角，其余是纯黑（2026-11-13 老大实测：
    2K 屏上开 1080p 无边框，采矿扫描一次都读不出）"""
    left, top, right, bottom = lit
    w, h = right - left, bottom - top
    if (w, h) == tuple(size):
        return None
    for fw, fh in _FRAME_SIZES:
        if abs(w - fw) <= 2 and abs(h - fh) <= 2:
            return left, top, w, h
    return None


def _shot_masked(area):
    """截一块，悬浮窗和盖在最前面的 AT 窗口涂黑（它们盖在黑边上时，不涂就永远认不出黑边）"""
    img = _shot(area)
    if sys.platform == "win32":
        img = mask_overlay(
            img, area["left"], area["top"], scale=_scale(_sct().monitors[1])
        )
    return img


def _frame_hint():
    """游戏设置里的画面大小 (宽, 高)，像素：读游戏自己存的设置文件 attributes.xml（只读，不改）；读不到返回 None。
    游戏目录按设置里 Game.log 的位置找"""
    import re
    from pathlib import Path

    from ...core import settings

    log = settings.load().get("game_log") or ""
    if not log:
        return None
    f = Path(log).parent / "user" / "client" / "0" / "Profiles" / "default"
    try:
        text = (f / "attributes.xml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    mw = re.search(r'name="Width"\s+value="(\d+)"', text)
    mh = re.search(r'name="Height"\s+value="(\d+)"', text)
    if not mw or not mh:
        return None
    w, h = int(mw.group(1)), int(mh.group(1))
    return (w, h) if w >= 640 and h >= 360 else None


_pad = {"t": -1e9, "win": None, "box": None, "seen": None}
_pad_lock = threading.Lock()
_PAD_EVERY = 3.0  # 秒：黑边多久重新看一次


def _padded(area):
    """游戏窗口里有画面的那一块（相对窗口左上角的 (左, 上, 宽, 高)）；窗口里全是画面返回 None。每 3 秒看一次：
    先截右边、下边两条细线，都亮就是没有黑边，不用截整块；有一条是黑的才截整块找画面的边。
    - 游戏设置里写着画面大小（_frame_hint）、它比窗口小、亮的地方又都在左上角那么大一块里：就是它，马上采用
      （不靠画面边上亮不亮，夜里、太空里也认得出）
    - 读不到设置、或对不上（画面不在左上角）：看亮像素的外接框，要正好是常见的画面大小，
      而且连着两次看到一样的才采用（暗场景里亮的那块碰巧是个常见大小，不会连着两次都一样）
    - 采用以后，一时框不准（画面边上正好全黑、加载中全黑）就沿用；框外面亮了（玩家改了游戏分辨率）、
      窗口位置大小变了才作废
    好几个线程都会来问（采矿、读位置、F8）：整段加锁，一次只让一个去截"""
    with _pad_lock:
        key = (area["left"], area["top"], area["width"], area["height"])
        now = time.monotonic()
        if _pad["win"] != key:
            _pad.update(win=key, box=None, seen=None, t=-1e9)
        if now - _pad["t"] < _PAD_EVERY:
            return _pad["box"]
        _pad["t"] = now
        w, h = area["width"], area["height"]
        edges = (
            {"left": area["left"] + w - 2, "top": area["top"], "width": 2, "height": h},
            {"left": area["left"], "top": area["top"] + h - 2, "width": w, "height": 2},
        )
        if all(_lit(_shot_masked(e)) for e in edges):
            _pad.update(box=None, seen=None)
            return None
        img = _shot_masked(area)
        lit = _lit_box(img)
        if lit is None:
            return _pad["box"]
        old = _pad["box"]
        if old and (
            lit[0] < old[0] - 2
            or lit[1] < old[1] - 2
            or lit[2] > old[0] + old[2] + 2
            or lit[3] > old[1] + old[3] + 2
        ):
            old = _pad["box"] = None
        try:
            hint = _frame_hint()
        except Exception:
            hint = None
        if (
            hint
            and hint != (w, h)
            and hint[0] <= w
            and hint[1] <= h
            and lit[2] <= hint[0] + 2
            and lit[3] <= hint[1] + 2
        ):
            _pad["box"] = _pad["seen"] = (0, 0, hint[0], hint[1])
            return _pad["box"]
        box = _frame_of(lit, img.size)
        if box and box in (old, _pad["seen"]):
            _pad["box"] = box
        _pad["seen"] = box
        return _pad["box"]


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


def cursor_pos():
    """读一次 Windows 光标位置（GetCursorPos，屏幕像素）→ (x, y)；读不了照样抛出去。
    全项目读光标只这一份（目录迁移收尾）：下面截图换算、盘点线程（infrastructure/platform/cursor 转过来）、
    悬浮窗「物品」挪开就收（app/hud_state，bootstrap 接）都用它"""
    import ctypes
    from ctypes import wintypes

    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


def cursor_on_image(img):
    """鼠标位置换算成截图（游戏画面）里的像素坐标；鼠标不在画面里也照样换算（可能是负数或超出）"""
    x, y = cursor_pos()
    a = game_area()
    s = _scale(_sct().monitors[1])
    return int(x * s - a["left"]) * img.width // max(1, a["width"]), int(
        y * s - a["top"]
    ) * img.height // max(1, a["height"])
