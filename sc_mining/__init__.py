"""星际公民 MOLE 挖矿扫描助手 —— 计算核心"""
import importlib as _importlib
import importlib.abc as _importlib_abc
import importlib.util as _importlib_util
import os as _os
import sys as _sys

# numpy 自带的数学库（OpenBLAS）一加载就按 CPU 线程数给每个线程预留一大块内存：
# 32 线程的电脑上光这一项就占 740MB「提交内存」。我们只做小图片的简单运算，用不着多线程，限成 1 个。
# 必须在任何地方 import numpy 之前设好，所以放在包的最开头。
for _k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_k, "1")

# 顶层向功能子包重定向映射（向下兼容别名）：
_LEGACY_MODULES = {
    "acquire": "sc_mining.crafting.acquire",
    "build_crafting": "sc_mining.crafting.build_crafting",
    "data": "sc_mining.mining.data",
    "data_pack": "sc_mining.update.data_pack",
    "displayinfo": "sc_mining.navigation.displayinfo",
    "feedback_up": "sc_mining.system.feedback_up",
    "gamelog": "sc_mining.system.gamelog",
    "gems": "sc_mining.mining.gems",
    "goals": "sc_mining.crafting.goals",
    "gpu_ocr": "sc_mining.system.gpu_ocr",
    "gridtext": "sc_mining.navigation.gridtext",
    "halo": "sc_mining.navigation.halo",
    "helpers": "sc_mining.system.helpers",
    "i18n": "sc_mining.core.i18n",
    "itemsearch": "sc_mining.crafting.itemsearch",
    "itemstats": "sc_mining.crafting.itemstats",
    "laser": "sc_mining.mining.laser",
    "legacy": "sc_mining.update.legacy",
    "localization": "sc_mining.update.localization",
    "locations": "sc_mining.mining.locations",
    "loot": "sc_mining.crafting.loot",
    "mining_area": "sc_mining.mining.mining_area",
    "navigate": "sc_mining.navigation.navigate",
    "net": "sc_mining.core.net",
    "ore_log": "sc_mining.mining.ore_log",
    "overlay": "sc_mining.app.overlay",
    "parse": "sc_mining.mining.parse",
    "paths": "sc_mining.core.paths",
    "perf": "sc_mining.core.perf",
    "perfmon": "sc_mining.core.perfmon",
    "position": "sc_mining.navigation.position",
    "quality": "sc_mining.mining.quality",
    "quality_tiers": "sc_mining.mining.quality_tiers",
    "refinery": "sc_mining.mining.refinery",
    "screen": "sc_mining.mining.screen",
    "settings": "sc_mining.core.settings",
    "shipsig": "sc_mining.mining.shipsig",
    "shops": "sc_mining.crafting.shops",
    "showloc": "sc_mining.system.showloc",
    "signals": "sc_mining.mining.signals",
    "stockplaces": "sc_mining.crafting.stockplaces",
    "train_data": "sc_mining.system.train_data",
    "tray": "sc_mining.app.tray",
    "uex": "sc_mining.update.uex",
    "update_check": "sc_mining.update.update_check",
    "upgrade": "sc_mining.update.upgrade",
    "version": "sc_mining.core.version",
    "vpk": "sc_mining.update.vpk",
    "wikelo": "sc_mining.crafting.wikelo",
}


class _AliasLoader:
    def __init__(self, target):
        self.target = target

    def create_module(self, spec):
        mod = _importlib.import_module(self.target)
        _sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module):
        pass


class _LegacyFinder(_importlib_abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        parts = fullname.split(".")
        if len(parts) == 2 and parts[0] == "sc_mining" and parts[1] in _LEGACY_MODULES:
            target_mod = _LEGACY_MODULES[parts[1]]
            return _importlib_util.spec_from_loader(fullname, _AliasLoader(target_mod))
        return None


if not any(isinstance(f, _LegacyFinder) for f in _sys.meta_path):
    _sys.meta_path.insert(0, _LegacyFinder())


def __getattr__(name: str):
    if name in _LEGACY_MODULES:
        mod = _importlib.import_module(_LEGACY_MODULES[name])
        _sys.modules[f"{__name__}.{name}"] = mod
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
