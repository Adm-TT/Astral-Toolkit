"""向后兼容垫片：sc_mining.gpu_ocr -> sc_mining.system.gpu_ocr"""
import sys
from .system import gpu_ocr as _mod
from .system.gpu_ocr import *  # noqa: F401, F403

sys.modules[__name__] = _mod
