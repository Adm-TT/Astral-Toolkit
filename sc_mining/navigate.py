"""向后兼容垫片：sc_mining.navigate -> sc_mining.navigation.navigate"""
import sys
from .navigation import navigate as _mod
from .navigation.navigate import *  # noqa: F401, F403

sys.modules[__name__] = _mod
