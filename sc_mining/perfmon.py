"""向后兼容垫片：sc_mining.perfmon -> sc_mining.core.perfmon"""
import sys
from .core import perfmon as _mod
from .core.perfmon import *  # noqa: F401, F403

sys.modules[__name__] = _mod
