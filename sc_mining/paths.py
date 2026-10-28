"""向后兼容垫片：sc_mining.paths -> sc_mining.core.paths"""
import sys
from .core import paths as _mod
from .core.paths import *  # noqa: F401, F403

sys.modules[__name__] = _mod
