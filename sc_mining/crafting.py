"""向后兼容垫片：sc_mining.crafting -> sc_mining.crafting.crafting"""
import sys
from .crafting import crafting as _mod
from .crafting.crafting import *  # noqa: F401, F403

sys.modules[__name__] = _mod
