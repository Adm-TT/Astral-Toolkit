"""向后兼容垫片：sc_mining.perf -> sc_mining.core.perf"""
import sys
from .core import perf as _mod
from .core.perf import *  # noqa: F401, F403

sys.modules[__name__] = _mod
