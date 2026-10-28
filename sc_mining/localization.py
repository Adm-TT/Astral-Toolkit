"""向后兼容垫片：sc_mining.localization -> sc_mining.update.localization"""
import sys
from .update import localization as _mod
from .update.localization import *  # noqa: F401, F403

sys.modules[__name__] = _mod
