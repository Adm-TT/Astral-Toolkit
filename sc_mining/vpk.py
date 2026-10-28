"""向后兼容垫片：sc_mining.vpk -> sc_mining.update.vpk"""
import sys
from .update import vpk as _mod
from .update.vpk import *  # noqa: F401, F403

sys.modules[__name__] = _mod
