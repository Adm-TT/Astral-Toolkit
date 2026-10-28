"""向后兼容垫片：sc_mining.screen -> sc_mining.mining.screen"""
import sys
from .mining import screen as _mod
from .mining.screen import *  # noqa: F401, F403

sys.modules[__name__] = _mod
