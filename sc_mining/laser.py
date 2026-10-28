"""向后兼容垫片：sc_mining.laser -> sc_mining.mining.laser"""
import sys
from .mining import laser as _mod
from .mining.laser import *  # noqa: F401, F403

sys.modules[__name__] = _mod
