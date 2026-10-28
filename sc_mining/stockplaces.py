"""向后兼容垫片：sc_mining.stockplaces -> sc_mining.crafting.stockplaces"""
import sys
from .crafting import stockplaces as _mod
from .crafting.stockplaces import *  # noqa: F401, F403

sys.modules[__name__] = _mod
