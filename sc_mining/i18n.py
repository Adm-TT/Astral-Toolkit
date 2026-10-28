"""向后兼容垫片：sc_mining.i18n -> sc_mining.core.i18n"""
import sys
from .core import i18n as _mod
from .core.i18n import *  # noqa: F401, F403

sys.modules[__name__] = _mod
