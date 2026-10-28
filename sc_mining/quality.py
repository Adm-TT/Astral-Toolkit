"""向后兼容垫片：sc_mining.quality -> sc_mining.mining.quality"""
import sys
from .mining import quality as _mod
from .mining.quality import *  # noqa: F401, F403

sys.modules[__name__] = _mod
