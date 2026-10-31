"""向后兼容层：该路径已废弃，请统一改用 sc_mining.ocr"""

import sc_mining.ocr.engine as _engine_mod
from ..ocr import OcrToken

_engine = None


def recognize(*args, **kwargs):
    global _engine
    res = _engine_mod.recognize(*args, **kwargs)
    _engine = _engine_mod._engine
    return res


def read_line(*args, **kwargs):
    global _engine
    res = _engine_mod.read_line(*args, **kwargs)
    _engine = _engine_mod._engine
    return res


__all__ = ["OcrToken", "recognize", "read_line", "_engine"]
