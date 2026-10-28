"""向后兼容垫片：sc_mining.gridtext -> sc_mining.navigation.gridtext"""
import sys
from .navigation import gridtext as _mod
from .navigation.gridtext import *  # noqa: F401, F403

sys.modules[__name__] = _mod
