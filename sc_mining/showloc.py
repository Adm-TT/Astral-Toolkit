"""向后兼容垫片：sc_mining.showloc -> sc_mining.system.showloc"""
import sys
from .system import showloc as _mod
from .system.showloc import *  # noqa: F401, F403

sys.modules[__name__] = _mod
