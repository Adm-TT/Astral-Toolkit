"""向后兼容垫片：sc_mining.train_data -> sc_mining.system.train_data"""
import sys
from .system import train_data as _mod
from .system.train_data import *  # noqa: F401, F403

sys.modules[__name__] = _mod
