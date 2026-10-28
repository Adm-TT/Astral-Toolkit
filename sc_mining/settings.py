"""向后兼容垫片：sc_mining.settings -> sc_mining.core.settings"""
import sys
from .core import settings as _mod
from .core.settings import *  # noqa: F401, F403

sys.modules[__name__] = _mod
