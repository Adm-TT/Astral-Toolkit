"""截图识别：复用助手读屏的 RapidOCR，输出交易解析器要的 OcrToken"""
from .models import OcrToken

_engine = None


def recognize(image, urgent=False, offset=(0, 0), native=False):
    """PIL 图片 → [OcrToken]（逐行文字 + 置信度 + 位置）。
    urgent=True：你按 F8 在等结果，插到后台识别前面、临时用正常优先级跑；
    offset：image 是从大图 (x, y) 处裁下来的，返回的位置换算回大图坐标；
    native=True：小块截图按原尺寸找字（不先放大），快 2 倍多"""
    global _engine
    import numpy as np
    if _engine is None:
        from ..perf import rapidocr
        _engine = rapidocr()
    arr = np.asarray(image.convert('RGB'))[:, :, ::-1]
    kw = {'_native': True} if native and hasattr(_engine, 'urgent') else {}
    if urgent and hasattr(_engine, 'urgent'):
        from ..perf import boost
        with boost():
            result = _engine.urgent(arr, **kw)
    else:
        result = _engine(arr, **kw)
    rows = result[0] if isinstance(result, tuple) else list(zip(result.boxes, result.txts, result.scores))
    ox, oy = offset
    tokens = []
    for box, text, score in rows or []:
        text = (text or '').strip()
        if text:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            left, top = int(min(xs)), int(min(ys))
            tokens.append(OcrToken(text, float(score) * 100, (left + ox, top + oy, int(max(xs)) - left, int(max(ys)) - top)))
    return tokens


def read_line(image):
    """只认一行字（不找字的位置）：PIL 单行文字图 → (文字, 置信度)。比整块识别快很多"""
    global _engine
    import numpy as np
    if _engine is None:
        from ..perf import rapidocr
        _engine = rapidocr()
    arr = np.asarray(image.convert('RGB'))[:, :, ::-1]
    result = _engine(arr, use_det=False, use_cls=False, use_rec=True)
    if isinstance(result, tuple):
        res = result[0]
        return (res[0][0], float(res[0][1])) if res else ('', 0.0)
    return (result.txts[0], float(result.scores[0])) if result.txts else ('', 0.0)
