"""向后兼容垫片：sc_mining.gems -> sc_mining.mining.gems"""
import sys
from .mining import gems as _mod
from .mining.gems import *  # noqa: F401, F403

sys.modules[__name__] = _mod
