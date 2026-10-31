"""OCR 核心识别与推理管道"""

from typing import Any, Callable, List, Sequence, Tuple, Union
import numpy as np
from PIL import Image

from .models import OcrToken

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from ..core.perf import rapidocr

        _engine = rapidocr()
    return _engine


def raw_detector() -> Callable[[np.ndarray], Sequence[Tuple[Any, str, float]]]:
    """返回底层四点检测识别函数：func(arr) -> [(quad, text, conf), ...]

    兼容 rapidocr_onnxruntime 和 rapidocr (支持 Python 3.13) 两种实现。
    """
    eng = _get_engine()
    if eng.kind.startswith("rapidocr_onnxruntime"):
        return lambda arr: eng(arr)[0] or []

    def run(arr: np.ndarray):
        r = eng(arr)
        if r.boxes is None:
            return []
        return list(zip(r.boxes.tolist(), r.txts, r.scores))

    return run


def raw_recognizer() -> Callable[[np.ndarray], Tuple[str, float]]:
    """返回底层单行识别函数：func(arr) -> (text, conf)"""
    eng = _get_engine()
    if eng.kind.startswith("rapidocr_onnxruntime"):

        def run(arr: np.ndarray) -> Tuple[str, float]:
            res, _ = eng(arr, use_det=False, use_cls=False, use_rec=True)
            return (res[0][0], float(res[0][1])) if res else ("", 0.0)

        return run

    def run(arr: np.ndarray) -> Tuple[str, float]:
        r = eng(arr, use_det=False, use_cls=False, use_rec=True)
        return (r.txts[0], float(r.scores[0])) if r.txts else ("", 0.0)

    return run


def recognize(
    image: Union[Image.Image, np.ndarray],
    urgent: bool = False,
    offset: Tuple[int, int] = (0, 0),
    native: bool = False,
) -> List[OcrToken]:
    """图片识别：输入 PIL 图片或 ndarray → [OcrToken]（逐行文字 + 置信度 + 位置）。

    Args:
        image: PIL 图片或 numpy 数组
        urgent: 是否以最高优先级紧急执行（插到后台识别前面、临时用正常优先级跑）
        offset: 坐标偏移量 (ox, oy)，用于局部裁图后的坐标换算
        native: 小块截图按原尺寸找字（不先放大），快 2 倍多
    """
    eng = _get_engine()
    if isinstance(image, np.ndarray):
        arr = image
    else:
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1]

    kw = {"_native": True} if native and hasattr(eng, "urgent") else {}
    if urgent and hasattr(eng, "urgent"):
        from ..core.perf import boost

        with boost():
            result = eng.urgent(arr, **kw)
    else:
        result = eng(arr, **kw)

    rows = (
        result[0]
        if isinstance(result, tuple)
        else list(zip(result.boxes, result.txts, result.scores))
    )
    ox, oy = offset
    tokens: List[OcrToken] = []
    for box, text, score in rows or []:
        text = (text or "").strip()
        if text:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            left, top = int(min(xs)), int(min(ys))
            tokens.append(
                OcrToken(
                    text,
                    float(score) * 100,
                    (left + ox, top + oy, int(max(xs)) - left, int(max(ys)) - top),
                )
            )
    return tokens


def read_line(image: Union[Image.Image, np.ndarray]) -> Tuple[str, float]:
    """只认一行字（跳过检测）：输入 PIL 单行文字图或 ndarray → (文字, 置信度)。比整块识别快很多"""
    rec = raw_recognizer()
    if isinstance(image, np.ndarray):
        arr = image
    else:
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1]
    return rec(arr)
