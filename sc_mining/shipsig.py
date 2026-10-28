"""向后兼容垫片：sc_mining.shipsig -> sc_mining.mining.shipsig"""
import sys
from .mining import shipsig as _mod
from .mining.shipsig import *  # noqa: F401, F403

sys.modules[__name__] = _mod
