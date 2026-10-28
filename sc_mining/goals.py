"""向后兼容垫片：sc_mining.goals -> sc_mining.crafting.goals"""
import sys
from .crafting import goals as _mod
from .crafting.goals import *  # noqa: F401, F403

sys.modules[__name__] = _mod
