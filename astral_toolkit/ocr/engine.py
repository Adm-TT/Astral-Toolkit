"""OCR 核心识别与推理管道"""

from typing import Any, Callable, List, Tuple, Union
import numpy as np
from PIL import Image

from .models import OcrQuad, OcrToken

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from .runtime import rapidocr

        _engine = rapidocr()
    return _engine


def _rows(result) -> list:
    """引擎一次检测 + 识别的结果 → [(四点, 文字, 把握), …]。两种引擎：rapidocr_onnxruntime 给 (结果, 耗时) 元组，
    结果没字时是 None；rapidocr 3.x 给对象，没字时 boxes 是 None（以前 recognize 在这种情况下会因为 zip(None) 出错，11-09 修）"""
    if isinstance(result, tuple):
        return list(result[0] or [])
    if getattr(result, "boxes", None) is None:
        return []
    return list(zip(result.boxes.tolist(), result.txts, result.scores))


def detect(arr: np.ndarray) -> List[OcrQuad]:
    """检测 + 识别一块图（numpy 数组，原样送引擎，不换通道）→ [OcrQuad(四点, 文字, 把握 0~1)]。
    给要看斜度的读屏用（采矿扫描面板）；只要文字和正框的用 recognize。
    2026-11-09 取代 raw_detector()：别处不再拿引擎的原始格式，统一从这里拿（以后换引擎只改 ocr 包）"""
    eng: Any = _get_engine()
    return [OcrQuad(q, t, c) for q, t, c in _rows(eng(arr))]


def _line_reader() -> Callable[[np.ndarray], Tuple[str, float]]:
    """单行识别（跳过检测）：func(arr) -> (text, conf 0~1)。两种引擎的写法不一样，这里分开（原 raw_recognizer，11-09 收成内部的）"""
    eng: Any = _get_engine()
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

    rows = _rows(result)
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
    rec = _line_reader()
    if isinstance(image, np.ndarray):
        arr = image
    else:
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1]
    return rec(arr)
