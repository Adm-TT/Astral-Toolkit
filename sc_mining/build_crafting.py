"""向后兼容垫片：sc_mining.build_crafting -> sc_mining.crafting.build_crafting"""
import sys
from .crafting import build_crafting as _mod
from .crafting.build_crafting import *  # noqa: F401, F403

sys.modules[__name__] = _mod
