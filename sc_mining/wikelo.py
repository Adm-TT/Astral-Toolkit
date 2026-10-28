"""向后兼容垫片：sc_mining.wikelo -> sc_mining.crafting.wikelo"""
import sys
from .crafting import wikelo as _mod
from .crafting.wikelo import *  # noqa: F401, F403

sys.modules[__name__] = _mod
