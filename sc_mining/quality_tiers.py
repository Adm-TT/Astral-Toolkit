"""向后兼容垫片：sc_mining.quality_tiers -> sc_mining.mining.quality_tiers"""
import sys
from .mining import quality_tiers as _mod
from .mining.quality_tiers import *  # noqa: F401, F403

sys.modules[__name__] = _mod
