"""RapidOCR 引擎宿主：单例、排队与设备切换。

从 :mod:`astral_toolkit.core.perf` 迁入，识别行为保持不变。
"""

import os
import threading
import time

# 默认占用不超过 6 个核心，既保证多核文字识别速度（比 2 线程快 2~3 倍），又避免吃满所有 CPU 核心导致游戏掉帧
OCR_THREADS = max(2, min(6, (os.cpu_count() or 4)))
USE_GPU = (
    os.environ.get("DUBHE_OCR_CPU") != "1"
)  # 能用显卡（DirectML）就用；用不了自动用 CPU。环境变量 DUBHE_OCR_CPU=1 强制 CPU（对比测速用）
# 哪几步放显卡：det 找字（整块大图，显卡快 4 倍）、rec 认字（很多小块、每块尺寸不同，显卡反而慢一倍）。
# 环境变量 DUBHE_OCR_DML=det,rec 可以改（对比测速用）
GPU_PARTS = [
    p for p in os.environ.get("DUBHE_OCR_DML", "det").split(",") if p in ("det", "rec")
]
_engine = None


def gpu_available():
    """onnxruntime 里有 DirectML（装的是 onnxruntime-directml，Windows 10 以上）"""
    try:
        import onnxruntime

        return "DmlExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:
        return False


_last_error = ""


def last_ocr_error():
    return _last_error


def is_gpu_preferred():
    if os.environ.get("DUBHE_OCR_CPU") == "1":
        return False
    try:
        from ..core import settings

        cfg = settings.load()
        dev = cfg.get("ocr_device")
        if dev is not None:
            return str(dev).lower() == "gpu"
        return bool(cfg.get("always_use_gpu", True))
    except Exception:
        return True


_cpu_fallback = (
    False  # 显卡版认字出过错、已换成 CPU 版：之后一直用 CPU，直到玩家在设置里再切一次
)


def ocr_device():
    """识别现在实际在哪算：「显卡」/「CPU」"""
    try:
        eng = rapidocr().eng
        sess = (
            eng.text_det.infer.session
            if hasattr(eng.text_det, "infer")
            else eng.text_det.session
        )
        return "显卡" if "DmlExecutionProvider" in sess.get_providers() else "CPU"
    except Exception:
        return "CPU"


_lock = threading.RLock()


class _Locked:
    """多个功能（扫描、F8、读位置）可能同时要识别：排队用同一个识别引擎，互不干扰。
    F8 用 urgent()：插到后台识别前面（后台正在跑的那一次跑完就轮到它）"""

    def __init__(self, eng, gpu=False):
        self.eng = eng
        self.kind = type(eng).__module__
        self.gpu = gpu  # 这个引擎是不是按显卡（DirectML）建的
        self.lock = threading.Lock()
        self.cv = threading.Condition()
        self.waiting = 0  # 正在排队的 F8 识别个数

    def __call__(self, *a, **kw):
        with self.cv:
            while self.waiting:  # 有 F8 在等：后台先让一让
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

    def swap(self, eng, gpu=False):
        """换内层引擎（切显卡 / CPU）：等正在跑的那次识别跑完再换。
        外面各处拿到的都是这同一个对象，换完以后所有识别自动用新的"""
        with self.lock:
            self.eng, self.kind, self.gpu = eng, type(eng).__module__, gpu

    def _infer(self, a, kw, native):
        td = getattr(self.eng, "text_det", None)
        if not native or td is None or not hasattr(td, "limit_side_len") or not a:
            return self.eng(*a, **kw)
        old = (td.limit_side_len, td.limit_type)
        try:
            td.limit_type, td.limit_side_len = "max", max(a[0].shape[:2])
            return self.eng(*a, **kw)
        finally:
            td.limit_side_len, td.limit_type = old

    def _run(self, a, kw, urgent=False):
        """_native=True：找字的那一步按原尺寸做。默认会把窄于 736 像素的小图先放大再找，
        小块截图（驾驶位 HUD、右上角调试信息）白白多算 2~3 倍。
        显卡版出错（驱动出问题、显存不够…）：换成 CPU 版重试一次，之后一直用 CPU，直到玩家在设置里再切"""
        global _cpu_fallback, _last_error
        native = kw.pop("_native", False)
        t0 = time.perf_counter()
        try:
            try:
                return self._infer(a, kw, native)
            except Exception as e:
                if not self.gpu:
                    raise
                old = self.eng
                try:
                    eng, _gpu, _err = _new_engine(False)
                except Exception:
                    raise e  # CPU 版建不起来：报原来显卡的错，引擎不动
                self.eng = eng  # 调用方已拿着 self.lock，直接换
                try:
                    out = self._infer(a, kw, native)
                except Exception:
                    self.eng = old  # CPU 版也认不了：多半不是显卡的问题，换回显卡版，报原来的错
                    raise e
                self.kind, self.gpu = type(eng).__module__, False
                _cpu_fallback = True  # CPU 版重试成功了才算「改用 CPU」
                _last_error = f"显卡识别出错，已改用 CPU：{e}"
                return out
        finally:
            try:  # 记一笔：性能记录里看各功能识别花了多少时间
                from ..core.perfmon import note_ocr

                note_ocr(time.perf_counter() - t0)
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self.eng, name)


def _new_engine(gpu):
    """新建一个 RapidOCR 引擎；gpu=True 时 GPU_PARTS 那几步放显卡（DirectML）。
    返回 (引擎, 是否显卡版, 出错原因)；显卡版建不起来就退回 CPU 版"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        from rapidocr import RapidOCR
    opts = {
        "intra_op_num_threads": OCR_THREADS,
        "inter_op_num_threads": 1,
        "use_cls": False,
    }
    if gpu:
        opts.update({f"{part}_use_dml": True for part in GPU_PARTS})
    try:
        return RapidOCR(**opts), bool(gpu), ""
    except Exception as e:
        try:
            return (
                RapidOCR(
                    intra_op_num_threads=OCR_THREADS,
                    inter_op_num_threads=1,
                    use_cls=False,
                ),
                False,
                str(e),
            )
        except Exception:
            return RapidOCR(), False, str(e)


def rapidocr():
    """全程序共用的一个 RapidOCR 实例（按用户设置在主进程直接加载 DirectML 或 CPU）。
    切显卡 / CPU 只换它里面的引擎，这个对象本身不换：各处缓存的引用一直有效"""
    global _engine, _last_error
    if (
        _engine is not None
    ):  # 建好以后不会再设回 None（切换只换里面的引擎）：不用排队等锁。
        return _engine  # 不然切显卡 / CPU 时等着正在跑的识别，每秒的状态查询（ocr_device）也跟着卡住
    with _lock:
        if _engine is None:
            eng, gpu, err = _new_engine(
                USE_GPU and not _cpu_fallback and is_gpu_preferred() and gpu_available()
            )
            if err:
                _last_error = err
            _engine = _Locked(eng, gpu)
    return _engine


def set_ocr_device(target):
    """切换 OCR 识别模式：'gpu' 或 'cpu'。在同一个共享对象里换内层引擎（以前是整个换掉，
    采矿读屏、交易识别各自缓存了旧对象，切了不生效）"""
    global _engine, _last_error, _cpu_fallback
    with _lock:
        target = (target or "gpu").lower()
        from ..core import settings

        settings.update(ocr_device=target, always_use_gpu=(target == "gpu"))
        _last_error = ""
        if _engine is None:
            _cpu_fallback = False
            rapidocr()
        else:
            eng, gpu, err = _new_engine(
                USE_GPU and is_gpu_preferred() and gpu_available()
            )
            if err:
                _last_error = err
            _engine.swap(eng, gpu)
            _cpu_fallback = False  # 玩家自己切过：以前显卡出错改用 CPU 的那次不算了
        return ocr_device()


def warmup():
    """启动暖机：确保识别引擎已加载；不返回引擎对象。"""
    rapidocr()
