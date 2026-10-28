"""向后兼容垫片：sc_mining.itemsearch -> sc_mining.crafting.itemsearch"""
import sys
from .crafting import itemsearch as _mod
from .crafting.itemsearch import *  # noqa: F401, F403

sys.modules[__name__] = _mod
