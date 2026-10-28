"""向后兼容垫片：sc_mining.version -> sc_mining.core.version"""
import sys
from .core import version as _mod
from .core.version import *  # noqa: F401, F403

sys.modules[__name__] = _mod
