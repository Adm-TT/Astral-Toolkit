"""向后兼容垫片：sc_mining.ore_log -> sc_mining.mining.ore_log"""
import sys
from .mining import ore_log as _mod
from .mining.ore_log import *  # noqa: F401, F403

sys.modules[__name__] = _mod
