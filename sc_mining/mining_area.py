"""向后兼容垫片：sc_mining.mining_area -> sc_mining.mining.mining_area"""
import sys
from .mining import mining_area as _mod
from .mining.mining_area import *  # noqa: F401, F403

sys.modules[__name__] = _mod
