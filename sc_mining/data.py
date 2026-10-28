"""向后兼容垫片：sc_mining.data -> sc_mining.mining.data"""
import sys
from .mining import data as _mod
from .mining.data import *  # noqa: F401, F403

sys.modules[__name__] = _mod
