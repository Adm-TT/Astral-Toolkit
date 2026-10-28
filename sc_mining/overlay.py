"""向后兼容垫片：sc_mining.overlay -> sc_mining.app.overlay"""
import sys
from .app import overlay as _mod
from .app.overlay import *  # noqa: F401, F403

sys.modules[__name__] = _mod
