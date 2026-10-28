"""向后兼容垫片：sc_mining.position -> sc_mining.navigation.position"""
import sys
from .navigation import position as _mod
from .navigation.position import *  # noqa: F401, F403

sys.modules[__name__] = _mod
