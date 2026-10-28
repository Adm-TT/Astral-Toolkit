"""向后兼容垫片：sc_mining.tray -> sc_mining.app.tray"""
import sys
from .app import tray as _mod
from .app.tray import *  # noqa: F401, F403

sys.modules[__name__] = _mod
