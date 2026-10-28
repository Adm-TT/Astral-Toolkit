"""向后兼容垫片：sc_mining.cockpit -> sc_mining.system.cockpit"""
import sys
from .system import cockpit as _mod
from .system.cockpit import *  # noqa: F401, F403

sys.modules[__name__] = _mod
