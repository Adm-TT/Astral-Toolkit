"""向后兼容垫片：sc_mining.data_pack -> sc_mining.update.data_pack"""
import sys
from .update import data_pack as _mod
from .update.data_pack import *  # noqa: F401, F403

sys.modules[__name__] = _mod
