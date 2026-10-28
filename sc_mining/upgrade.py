"""向后兼容垫片：sc_mining.upgrade -> sc_mining.update.upgrade"""
import sys
from .update import upgrade as _mod
from .update.upgrade import *  # noqa: F401, F403

sys.modules[__name__] = _mod
