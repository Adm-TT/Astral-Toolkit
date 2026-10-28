"""向后兼容垫片：sc_mining.displayinfo -> sc_mining.navigation.displayinfo"""
import sys
from .navigation import displayinfo as _mod
from .navigation.displayinfo import *  # noqa: F401, F403

sys.modules[__name__] = _mod
