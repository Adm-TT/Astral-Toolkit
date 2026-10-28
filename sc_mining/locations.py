"""向后兼容垫片：sc_mining.locations -> sc_mining.mining.locations"""
import sys
from .mining import locations as _mod
from .mining.locations import *  # noqa: F401, F403

sys.modules[__name__] = _mod
