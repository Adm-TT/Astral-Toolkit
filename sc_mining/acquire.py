"""向后兼容垫片：sc_mining.acquire -> sc_mining.crafting.acquire"""
import sys
from .crafting import acquire as _mod
from .crafting.acquire import *  # noqa: F401, F403

sys.modules[__name__] = _mod
