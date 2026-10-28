"""向后兼容垫片：sc_mining.gamelog -> sc_mining.system.gamelog"""
import sys
from .system import gamelog as _mod
from .system.gamelog import *  # noqa: F401, F403

sys.modules[__name__] = _mod
