"""向后兼容垫片：sc_mining.itemstats -> sc_mining.crafting.itemstats"""
import sys
from .crafting import itemstats as _mod
from .crafting.itemstats import *  # noqa: F401, F403

sys.modules[__name__] = _mod
