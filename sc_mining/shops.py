"""向后兼容垫片：sc_mining.shops -> sc_mining.crafting.shops"""
import sys
from .crafting import shops as _mod
from .crafting.shops import *  # noqa: F401, F403

sys.modules[__name__] = _mod
