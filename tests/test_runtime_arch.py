"""运行结构的依赖检查（架构稿 §4.3、§11.3，RT-B1 / RT-B2）：领域计算不碰运行环境，呈现层不取数据，导入不创建引擎"""

import ast
import subprocess
import sys
from pathlib import Path

from tests.test_gamedata_arch import _imports_in, _imports_in_source

_ROOT = Path(__file__).resolve().parent.parent / "sc_mining"

# 领域计算不能碰的：上层、运行环境、数据和设置；laser / data / refinery 读全局表，要用经 MiningInputs 传
_ANALYSIS_FORBIDDEN = (
    "sc_mining.app",
    "sc_mining.tasks",
    "sc_mining.runtime",
    "sc_mining.gamedata",
    "sc_mining.crafting",
    "sc_mining.core.settings",
    "sc_mining.core.paths",
    "sc_mining.mining.laser",
    "sc_mining.mining.data",
    "sc_mining.mining.refinery",
    "threading",
    "time",
    "datetime",
    "os",
    "sqlite3",
    "importlib",
    "pathlib",
    "io",
    "json",
    "subprocess",
    "socket",
)
_BARE_FORBIDDEN = (
    "sc_mining",
    "sc_mining.core",
)  # 裸导入后走属性访问，等于绕开上面的清单
_DYNAMIC_IMPORTS = ("__import__", "import_module", "open", "exec", "eval")


def _forbidden(mods, forbidden):
    return [m for m in mods if any(m == f or m.startswith(f + ".") for f in forbidden)]


def _dynamic_imports(source):
    """__import__(...)、importlib.import_module(...)、import_module(...) 这种字符串导入"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in _DYNAMIC_IMPORTS:
                out.append(name)
    return out


def _analysis_violations(source):
    mods = list(_imports_in_source(source, "sc_mining.mining"))
    bare = [m for m in mods if m in _BARE_FORBIDDEN]
    return _forbidden(mods, _ANALYSIS_FORBIDDEN) + bare + _dynamic_imports(source)


def test_analysis_imports():
    path = _ROOT / "mining" / "analysis.py"
    assert _analysis_violations(path.read_text(encoding="utf-8")) == []


def test_analysis_check_catches_known_gaps():
    """RT-B1 审查实测漏掉的写法，每一种都要拦住；正常的 import 不误报"""
    for src in (
        "import datetime",
        "from datetime import datetime",
        "from .laser import recommend",
        "from . import data",
        "from . import refinery",
        "from ..core import paths",
        "from ..core.paths import USER",
        "from ..core import settings",
        "import sqlite3",
        "import os",
        "import os.path",
        "from sc_mining import gamedata",
        "from .. import runtime",
        "def f():\n    import time",
        "import importlib\nimportlib.import_module('sc_mining.mining.laser')",
        "from importlib import import_module\nimport_module('x')",
        "__import__('sc_mining.mining.data')",
        "import pathlib",
        "import json",
        "from .. import core",
        "import sc_mining",
        "open('x')",
        "exec('import os')",
    ):
        assert _analysis_violations(src), src
    for src in (
        "from .quality import tier_of",
        "from collections import defaultdict",
        "from dataclasses import dataclass",
        "from types import MappingProxyType",
        "from typing import Any",
        "from enum import Enum",
    ):
        assert _analysis_violations(src) == [], src


def test_presenter_imports():
    path = _ROOT / "app" / "presenters" / "mining.py"
    bad = _forbidden(
        _imports_in(path),
        (
            "sc_mining.gamedata",
            "sc_mining.mining.laser",
            "sc_mining.mining.data",
            "sc_mining.mining.refinery",
            "sc_mining.crafting",
            "sc_mining.tasks",
            "sc_mining.core.settings",
        ),
    )
    assert bad == [] and _dynamic_imports(path.read_text(encoding="utf-8")) == [], bad


def _run(code):
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=_ROOT.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


def test_analysis_import_is_clean_transitively():
    """新进程只导入 analysis：不能间接带进数据层、设置、读全局表的模块、任务实现，也不能启动线程"""
    code = (
        "import sys, threading, sc_mining.mining.analysis;"
        "print([m for m in sys.modules if m.startswith(('sc_mining.gamedata',"
        "'sc_mining.core.settings','sc_mining.core.paths','sc_mining.tasks','sc_mining.app',"
        "'sc_mining.runtime','sc_mining.mining.laser','sc_mining.mining.data','sc_mining.mining.refinery',"
        "'sqlite3'))], threading.active_count())"
    )
    assert _run(code) == "[] 1"


def test_tasks_mining_import_creates_no_engine():
    """导入 tasks.mining 本身不创建引擎。tasks/__init__.py 还会连带导入 count、navigation（它们导入时还在取引擎，
    已写进 RT-B2 PR「需要别人改」），这里换掉包入口只测这个模块；那两处改完后去掉假包，直接 import sc_mining.tasks.mining"""
    code = (
        "import sys, types, pathlib, sc_mining;"
        "pkg = types.ModuleType('sc_mining.tasks');"
        "pkg.__path__ = [str(pathlib.Path(sc_mining.__file__).parent / 'tasks')];"
        "sys.modules['sc_mining.tasks'] = pkg;"
        "import sc_mining.tasks.mining;"
        "from sc_mining.app.engines.manager import EngineManager;"
        "print(EngineManager._instance is None, 'sc_mining.tasks.count' in sys.modules,"
        " 'sc_mining.tasks.navigation' in sys.modules)"
    )
    assert _run(code) == "True False False"


def test_tasks_mining_gets_engine_only_inside_functions():
    tree = ast.parse((_ROOT / "tasks" / "mining.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            assert not (isinstance(sub, ast.Attribute) and sub.attr == "get_instance")
