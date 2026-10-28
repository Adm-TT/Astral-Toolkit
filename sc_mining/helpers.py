"""向后兼容垫片：sc_mining.helpers -> sc_mining.system.helpers"""
import sys
from .system import helpers as _mod
from .system.helpers import *  # noqa: F401, F403

sys.modules[__name__] = _mod
