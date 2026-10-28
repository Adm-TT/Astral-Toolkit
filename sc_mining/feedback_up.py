"""向后兼容垫片：sc_mining.feedback_up -> sc_mining.system.feedback_up"""
import sys
from .system import feedback_up as _mod
from .system.feedback_up import *  # noqa: F401, F403

sys.modules[__name__] = _mod
