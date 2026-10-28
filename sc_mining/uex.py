"""向后兼容垫片：sc_mining.uex -> sc_mining.update.uex"""
import sys
from .update import uex as _mod
from .update.uex import *  # noqa: F401, F403

sys.modules[__name__] = _mod
