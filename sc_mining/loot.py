"""向后兼容垫片：sc_mining.loot -> sc_mining.crafting.loot"""
import sys
from .crafting import loot as _mod
from .crafting.loot import *  # noqa: F401, F403

sys.modules[__name__] = _mod
