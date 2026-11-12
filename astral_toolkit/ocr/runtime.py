"""OCR 引擎宿主：进程内唯一 RapidOCR、排队插队、GPU/CPU 切换。

业务认字走 astral_toolkit.ocr 门面；本模块供门面与测试/测速工具使用。
"""

from __future__ import annotations

import os
import threading
import time

# 默认占用不超过 6 个核心，既保证多核文字识别速度（比 2 线程快 2~3 倍），又避免吃满所有 CPU 核心导致游戏掉帧
OCR_THREADS = max(2, min(6, (os.cpu_count() or 4)))
USE_GPU = (
    os.environ.get("DUBHE_OCR_CPU") != "1"
)  # 设置里选了显卡、电脑也能用显卡（DirectML）才用，用不了自动用 CPU。环境变量 DUBHE_OCR_CPU=1 强制 CPU（对比测速用）
# PP-OCRv6 档位：small（det+rec 一致）。11-12 老大定：tiny 样本对比不达标（右上角 Stanton 的 S 认成 5、雷达少读、
# 中文名更糊、扫描面板抗性 0 认成 9），按方案 §7 改 small；small 295 张样本不比旧引擎差、还快
OCR_VERSION = "PP-OCRv6"
MODEL_TYPE = "small"
_engine = None
_lock = threading.RLock()
_last_error = ""
_cpu_fallback = (
    False  # 显卡版认字出过错、已换成 CPU 版：之后一直用 CPU，直到玩家在设置里再切一次
)


def gpu_available():
    """onnxruntime 里有 DirectML（装的是 onnxruntime-directml，Windows 10 以上）"""
    try:
        import onnxruntime

        return "DmlExecutionProvider" in onnxruntime.get_available_providers()
    except Exception:
        return False


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
        return bool(cfg.get("always_use_gpu", False))
    except Exception:
        return False  # 默认处理器（2026-11-08 老大定）


def _ort_session(eng):
    """从 RapidOCR 取出底层 InferenceSession（text_det.session.session；懒加载未就绪则 None）"""
    td = getattr(eng, "text_det", None)
    if td is None:
        return None
    wrap = getattr(td, "session", None)
    if wrap is None:
        return None
    return getattr(wrap, "session", wrap)


def ocr_device():
    """识别现在实际在哪算：「显卡」/「CPU」"""
    try:
        locked = rapidocr()
        sess = _ort_session(locked.eng)
        if sess is not None and hasattr(sess, "get_providers"):
            return "显卡" if "DmlExecutionProvider" in sess.get_providers() else "CPU"
        return "显卡" if locked.gpu else "CPU"
    except Exception:
        return "CPU"


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

    def _call_eng(self, a, kw):
        # rapidocr 3.x 的 use_det/use_cls/use_rec 会写进引擎状态、调用结束不还原；
        # 每次都显式带默认，调用方要关检测（read_line）再覆盖，避免认完一行后整段识别永远空结果
        call_kw = {"use_det": True, "use_cls": False, "use_rec": True, **kw}
        return self.eng(*a, **call_kw)

    def _infer(self, a, kw, native):
        td = getattr(self.eng, "text_det", None)
        if native and td is None:
            load = getattr(self.eng, "_load_det_model", None)
            if callable(load):
                try:
                    load()
                except Exception:
                    pass
            td = getattr(self.eng, "text_det", None)
        if not native or td is None or not hasattr(td, "limit_side_len") or not a:
            return self._call_eng(a, kw)
        old = (td.limit_side_len, td.limit_type)
        try:
            td.limit_type, td.limit_side_len = "max", max(a[0].shape[:2])
            return self._call_eng(a, kw)
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


def _engine_params(gpu: bool) -> dict:
    """新版 rapidocr 构造参数：PP-OCRv6 MODEL_TYPE（small）+ 线程 + 关 cls；显卡时整引擎 use_dml。"""
    from rapidocr import EngineType, ModelType, OCRVersion

    params = {
        "Global.use_cls": False,
        "EngineConfig.onnxruntime.intra_op_num_threads": OCR_THREADS,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Det.engine_type": EngineType.ONNXRUNTIME,
        "Det.ocr_version": OCRVersion(OCR_VERSION),
        "Det.model_type": ModelType(MODEL_TYPE),
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Rec.ocr_version": OCRVersion(OCR_VERSION),
        "Rec.model_type": ModelType(MODEL_TYPE),
    }
    if gpu:
        params["EngineConfig.onnxruntime.use_dml"] = True
    return params


def _new_engine(gpu):
    """新建一个 RapidOCR 引擎；gpu=True 时整引擎开 DirectML（use_dml）。
    返回 (引擎, 是否显卡版, 出错原因)；显卡版建不起来就退回 CPU 版"""
    from rapidocr import RapidOCR

    try:
        return RapidOCR(params=_engine_params(gpu)), bool(gpu), ""
    except Exception as e:
        if not gpu:
            raise
        return RapidOCR(params=_engine_params(False)), False, str(e)


def rapidocr():
    """全程序共用的一个 RapidOCR 实例（按用户设置在主进程直接加载 DirectML 或 CPU）。
    切显卡 / CPU 只换它里面的引擎，这个对象本身不换：各处缓存的引用一直有效。

    仅供本包门面与测试/测速使用；业务代码请用 warmup / recognize 等公共 API。
    """
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


# 模型下载：底层 DownloadFile 单次请求已有 timeout；外层再有限重试，避免 CDN 抖一下就整条安装失败
_MODEL_DL_ATTEMPTS = 3
_MODEL_DL_BACKOFF_CAP_S = 30.0  # 退避等待合计封顶（不含单次下载本身）


def _download_with_retry(run, *, log, what: str) -> None:
    """run() 失败则指数退避重试，最多 _MODEL_DL_ATTEMPTS 次；退避合计不超过约 30 秒。"""
    last: Exception | None = None
    waited = 0.0
    for attempt in range(1, _MODEL_DL_ATTEMPTS + 1):
        try:
            run()
            return
        except Exception as e:
            last = e
            if attempt >= _MODEL_DL_ATTEMPTS:
                break
            delay = min(2**attempt, max(0.0, _MODEL_DL_BACKOFF_CAP_S - waited))
            if delay <= 0:
                break
            log.warning(
                "%s失败（第 %s/%s 次）：%s；%.0f 秒后重试",
                what,
                attempt,
                _MODEL_DL_ATTEMPTS,
                e,
                delay,
            )
            time.sleep(delay)
            waited += delay
    raise RuntimeError(f"{what}失败（已试 {_MODEL_DL_ATTEMPTS} 次）：{last}") from last


def ensure_models() -> None:
    """把 PP-OCRv6 MODEL_TYPE 档的 det/rec onnx 下进 rapidocr/models（已存在则校验跳过）。
    打包和源码安装都要调，避免玩家第一次认字时联网。"""
    from pathlib import Path

    from rapidocr import ModelType, OCRVersion, RapidOCR
    from rapidocr.inference_engine.base import FileInfo, InferSession
    from rapidocr.utils.download_file import DownloadFile, DownloadFileInput
    from rapidocr.utils.log import logger
    from rapidocr.utils.typings import EngineType, TaskType

    eng = RapidOCR(params=_engine_params(False))
    root = Path(eng.cfg.Global.model_root_dir)
    root.mkdir(parents=True, exist_ok=True)
    for task, lang in (
        (TaskType.DET, eng.cfg.Det.lang_type),
        (TaskType.REC, eng.cfg.Rec.lang_type),
    ):
        info = InferSession.get_model_url(
            FileInfo(
                EngineType.ONNXRUNTIME,
                OCRVersion(OCR_VERSION),
                task,
                lang,
                ModelType(MODEL_TYPE),
            )
        )
        url = info["model_dir"]
        dest = root / Path(url).name
        name = dest.name

        def _one(url=url, dest=dest, sha=info.get("SHA256")):
            DownloadFile.run(
                DownloadFileInput(
                    file_url=url,
                    save_path=dest,
                    logger=logger,
                    sha256=sha,
                )
            )
            if not dest.is_file():
                raise FileNotFoundError(f"OCR 模型未就绪：{dest}")

        _download_with_retry(_one, log=logger, what=f"下载 OCR 模型 {name}")


def warmup() -> None:
    """启动时预加载识别引擎和 det/rec 模型。不返回引擎对象。"""
    locked = rapidocr()
    for name in ("_load_det_model", "_load_rec_model"):
        load = getattr(locked.eng, name, None)
        if callable(load):
            load()


def set_ocr_device(target):
    """切换 OCR 识别模式：'gpu' 或 'cpu'。在同一个共享对象里换内层引擎（以前是整个换掉，
    采矿读屏、交易识别各自缓存了旧对象，切了不生效）"""
    global _engine, _last_error, _cpu_fallback
    with _lock:
        target = (target or "cpu").lower()
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
