"""向后兼容垫片：sc_mining.signals -> sc_mining.mining.signals"""
import sys
from .mining import signals as _mod
from .mining.signals import *  # noqa: F401, F403

sys.modules[__name__] = _mod
