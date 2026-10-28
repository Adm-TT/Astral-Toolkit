"""向后兼容垫片：sc_mining.update_check -> sc_mining.update.update_check"""
import sys
from .update import update_check as _mod
from .update.update_check import *  # noqa: F401, F403

sys.modules[__name__] = _mod
