"""OCR 核心识别与推理管道"""

from typing import Any, Callable, List, Sequence, Tuple, Union
import numpy as np
from PIL import Image

from .models import OcrToken

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from .runtime import rapidocr

        _engine = rapidocr()
    return _engine


def _as_rows(result: Any) -> Sequence[Tuple[Any, str, float]]:
    """把 RapidOCR 返回值收成 [(quad, text, conf), ...]。空结果为 []。"""
    if result is None:
        return []
    if isinstance(result, tuple):
        return result[0] or []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    txts = getattr(result, "txts", None) or ()
    scores = getattr(result, "scores", None) or ()
    return list(
        zip(boxes.tolist() if hasattr(boxes, "tolist") else boxes, txts, scores)
    )


def raw_detector() -> Callable[[np.ndarray], Sequence[Tuple[Any, str, float]]]:
    """返回底层四点检测识别函数：func(arr) -> [(quad, text, conf), ...]"""
    eng: Any = _get_engine()

    def run(arr: np.ndarray):
        return _as_rows(eng(arr))

    return run


def raw_recognizer() -> Callable[[np.ndarray], Tuple[str, float]]:
    """返回底层单行识别函数：func(arr) -> (text, conf)"""
    eng: Any = _get_engine()

    def run(arr: np.ndarray) -> Tuple[str, float]:
        r = eng(arr, use_det=False, use_cls=False, use_rec=True)
        if isinstance(r, tuple):
            res = r[0] or []
            return (res[0][0], float(res[0][1])) if res else ("", 0.0)
        txts = getattr(r, "txts", None)
        scores = getattr(r, "scores", None)
        if not txts:
            return ("", 0.0)
        return (txts[0], float(scores[0]) if scores is not None else 0.0)

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
    eng: Any = _get_engine()
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

    rows = _as_rows(result)
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
