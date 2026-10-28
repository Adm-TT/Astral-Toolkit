"""向后兼容垫片：sc_mining.legacy -> sc_mining.update.legacy"""
import sys
from .update import legacy as _mod
from .update.legacy import *  # noqa: F401, F403

sys.modules[__name__] = _mod
