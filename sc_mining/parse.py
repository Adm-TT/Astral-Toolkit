"""向后兼容垫片：sc_mining.parse -> sc_mining.mining.parse"""
import sys
from .mining import parse as _mod
from .mining.parse import *  # noqa: F401, F403

sys.modules[__name__] = _mod
