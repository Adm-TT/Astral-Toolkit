"""少占电脑资源，别拖慢游戏

- 天枢自己的进程（窗口和后台辅助）都降成「低于正常」优先级：游戏要用 CPU 时让着游戏
- 文字识别（RapidOCR）全程序只加载一份，并且只用 2 个线程（默认会占满所有 CPU 核心）；
  装了 onnxruntime-directml 就让找字、认字在显卡上算（DirectML），没装照旧用 CPU
- 截图只截需要的那一块，不截整个屏幕
- 你按 F8 这种「等着看结果」的识别插队、并临时用正常优先级跑完；后台的识别（扫描、驾驶位检查、读位置）照旧让着游戏
"""
import contextlib
import os
import sys
import threading
import time

OCR_THREADS = 2
USE_GPU = os.environ.get("DUBHE_OCR_CPU") != "1"   # 能用显卡（DirectML）就用；用不了自动用 CPU。环境变量 DUBHE_OCR_CPU=1 强制 CPU（对比测速用）
# 哪几步放显卡：det 找字（整块大图，显卡快 4 倍）、rec 认字（很多小块、每块尺寸不同，显卡反而慢一倍）。
# 环境变量 DUBHE_OCR_DML=det,rec 可以改（对比测速用）
GPU_PARTS = [p for p in os.environ.get("DUBHE_OCR_DML", "det").split(",") if p in ("det", "rec")]
_engine = None


def gpu_available():
    """onnxruntime 里有 DirectML（装的是 onnxruntime-directml，Windows 10 以上）"""
    try:
        import onnxruntime
        return "DmlExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:
        return False


def ocr_device():
    """识别现在实际在哪算：「显卡」/「CPU」。主程序：显卡 OCR 小进程开着就是显卡（2026-10-27）"""
    from . import gpu_ocr
    if not gpu_ocr.is_worker():
        return gpu_ocr.device()
    try:
        eng = rapidocr().eng
        sess = eng.text_det.infer.session if hasattr(eng.text_det, "infer") else eng.text_det.session
        return "显卡" if "DmlExecutionProvider" in sess.get_providers() else "CPU"
    except Exception:
        return "CPU"
_lock = threading.Lock()


def lower_priority():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)      # BELOW_NORMAL_PRIORITY_CLASS
    except Exception:
        pass


_boost = {"n": 0, "lock": threading.Lock()}


@contextlib.contextmanager
def boost():
    """你在等结果的那一下（F8）：临时恢复正常优先级，跑完马上降回去。
    平时天枢是「低于正常」优先级，游戏占满 CPU 时识别会被挤得很慢"""
    if sys.platform != "win32":
        yield
        return
    import ctypes
    k32 = ctypes.windll.kernel32
    with _boost["lock"]:
        _boost["n"] += 1
        if _boost["n"] == 1:
            k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00000020)      # NORMAL_PRIORITY_CLASS
    try:
        yield
    finally:
        with _boost["lock"]:
            _boost["n"] -= 1
            if _boost["n"] == 0:
                k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS


class _Locked:
    """多个功能（扫描、F8、读位置）可能同时要识别：排队用同一个识别引擎，互不干扰。
    F8 用 urgent()：插到后台识别前面（后台正在跑的那一次跑完就轮到它）"""

    def __init__(self, eng):
        self.eng = eng
        self.kind = type(eng).__module__
        self.lock = threading.Lock()
        self.cv = threading.Condition()
        self.waiting = 0                      # 正在排队的 F8 识别个数

    def __call__(self, *a, **kw):
        with self.cv:
            while self.waiting:               # 有 F8 在等：后台先让一让
                self.cv.wait(0.5)
        with self.lock:
            return self._run(a, kw)

    def urgent(self, *a, **kw):
        with self.cv:
            self.waiting += 1
        try:
            with self.lock:
                return self._run(a, kw, urgent=True)
        finally:
            with self.cv:
                self.waiting -= 1
                self.cv.notify_all()

    def _run(self, a, kw, urgent=False):
        """_native=True：找字的那一步按原尺寸做。默认会把窄于 736 像素的小图先放大再找，
        小块截图（驾驶位 HUD、右上角调试信息）白白多算 2~3 倍"""
        native = kw.pop("_native", False)
        td = getattr(self.eng, "text_det", None)
        t0 = time.perf_counter()
        if a and kw.get("use_det", True) is not False:   # 要找字：显卡 OCR 小进程开着就交给它（采矿助手开着时）
            from . import gpu_ocr
            if not gpu_ocr.is_worker():
                gpu_ocr.revive()
            if not gpu_ocr.is_worker() and gpu_ocr.active():
                r = gpu_ocr.run(a[0], dict(kw, _native=native), urgent)
                if r is not None:
                    return r
        try:
            if not native or td is None or not hasattr(td, "limit_side_len") or not a:
                return self.eng(*a, **kw)
            old = (td.limit_side_len, td.limit_type)
            try:
                td.limit_type, td.limit_side_len = "max", max(a[0].shape[:2])
                return self.eng(*a, **kw)
            finally:
                td.limit_side_len, td.limit_type = old
        finally:
            try:                              # 记一笔：性能记录里看各功能识别花了多少时间
                from .perfmon import note_ocr
                note_ocr(time.perf_counter() - t0)
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self.eng, name)


def rapidocr():
    """全程序共用的一个 RapidOCR 实例（第一次调用时加载）"""
    global _engine
    with _lock:
        if _engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError:
                from rapidocr import RapidOCR
            # 游戏里的字都是正的：关掉「文字是不是倒过来」的判断（每行文字少算一次）
            opts = {"intra_op_num_threads": OCR_THREADS, "inter_op_num_threads": 1, "use_cls": False}
            from .gpu_ocr import is_worker
            # 显卡（DirectML）只在显卡 OCR 小进程里用：主程序一载入显卡驱动就多占 300 多 MB、关了也不还（2026-10-27）
            if USE_GPU and is_worker() and gpu_available():
                opts.update({f"{part}_use_dml": True for part in GPU_PARTS})
            try:
                eng = RapidOCR(**opts)
            except Exception:
                try:
                    eng = RapidOCR(intra_op_num_threads=OCR_THREADS, inter_op_num_threads=1)
                except Exception:
                    eng = RapidOCR()
            _engine = _Locked(eng)
    return _engine


def overlay_rect():
    """悬浮窗现在在屏幕上的位置 (左, 上, 右, 下)，物理像素；没显示返回 None"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        from . import overlay
        HWND = overlay.HWND
        u32 = ctypes.windll.user32
        if not HWND or not overlay.SHOWN or not u32.IsWindowVisible(HWND):     # 没内容时窗口全透明，不用涂
            return None
        r = wintypes.RECT()
        u32.GetWindowRect(HWND, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


def own_window_rects():
    """天枢自己的主窗口盖在游戏上时的位置：只算「在最前面」或「置顶」的（在游戏后面的窗口看不见，涂黑反而挡住游戏）。
    2026-10-23 全量样本测试：窗口里的实时栏写着信号值 / 石头质量，盖在游戏上会被当成游戏里的字"""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        import os
        from ctypes import wintypes
        from . import overlay
        u32 = ctypes.windll.user32
        pid, fg, out = os.getpid(), u32.GetForegroundWindow(), []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def each(h, _):
            p = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(p))
            if p.value == pid and h != overlay.HWND and u32.IsWindowVisible(h) and not u32.IsIconic(h):
                top = u32.GetWindowLongW(h, -20) & 0x8                  # GWL_EXSTYLE / WS_EX_TOPMOST
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
    """截图里悬浮窗（和盖在最前面的天枢主窗口）那块涂黑：img 是从屏幕 (left, top) 开始截的；scale = 截图像素 / 窗口坐标像素"""
    rects = [rect or overlay_rect()] + (own_window_rects() if own is None else list(own))
    from PIL import ImageDraw
    for rc in rects:
        if not rc:
            continue
        l, t, r, b = (int(v * scale) for v in rc)
        l, t, r, b = l - left, t - top, r - left, b - top
        if r <= 0 or b <= 0 or l >= img.width or t >= img.height:
            continue
        ImageDraw.Draw(img).rectangle((max(0, l), max(0, t), min(img.width, r) - 1, min(img.height, b) - 1), fill=(0, 0, 0))
    return img


def _scale(mon):
    """窗口坐标 → 截图像素的比例（天枢没开高 DPI 感知时，Windows 给的窗口坐标是缩放过的）"""
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
    except Exception:                         # 显示器变了（改分辨率、插拔）：重建一次再截
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
        from . import showloc
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
                area = {"left": int(pt.x * s), "top": int(pt.y * s), "width": w, "height": h}
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
    return mask_overlay(img, a["left"], a["top"], scale=_scale(_sct().monitors[1])) if sys.platform == "win32" else img


def grab_region(box):
    """只截游戏画面的一块：box = (左, 上, 右, 下)，都是占画面的比例。返回 PIL 图片"""
    a = game_area()
    l, t, r, b = box
    area = {"left": a["left"] + int(a["width"] * l), "top": a["top"] + int(a["height"] * t),
            "width": max(1, int(a["width"] * (r - l))), "height": max(1, int(a["height"] * (b - t)))}
    img = _shot(area)
    if sys.platform == "win32":
        img = mask_overlay(img, area["left"], area["top"], scale=_scale(_sct().monitors[1]))
    return img


def cursor_on_image(img):
    """鼠标位置换算成截图（游戏画面）里的像素坐标；鼠标不在画面里也照样换算（可能是负数或超出）"""
    import ctypes
    from ctypes import wintypes
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    a = game_area()
    s = _scale(_sct().monitors[1])
    return int(pt.x * s - a["left"]) * img.width // max(1, a["width"]), int(pt.y * s - a["top"]) * img.height // max(1, a["height"])
