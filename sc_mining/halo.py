"""向后兼容垫片：sc_mining.halo -> sc_mining.navigation.halo"""
import sys
from .navigation import halo as _mod
from .navigation.halo import *  # noqa: F401, F403

sys.modules[__name__] = _mod
