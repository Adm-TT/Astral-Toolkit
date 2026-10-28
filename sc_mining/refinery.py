"""向后兼容垫片：sc_mining.refinery -> sc_mining.mining.refinery"""
import sys
from .mining import refinery as _mod
from .mining.refinery import *  # noqa: F401, F403

sys.modules[__name__] = _mod
