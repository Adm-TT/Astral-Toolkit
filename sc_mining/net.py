"""向后兼容垫片：sc_mining.net -> sc_mining.core.net"""
import sys
from .core import net as _mod
from .core.net import *  # noqa: F401, F403

sys.modules[__name__] = _mod
