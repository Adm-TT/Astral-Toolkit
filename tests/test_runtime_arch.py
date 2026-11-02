"""运行结构的依赖检查（架构稿 §4.3、§11.3，RT-B1 / RT-B2）：领域计算不碰运行环境，呈现层不取数据，导入不创建引擎"""

import ast
import subprocess
import sys
from pathlib import Path

from tests.test_gamedata_arch import _imports_in, _imports_in_source

_ROOT = Path(__file__).resolve().parent.parent / "astral_toolkit"

# 领域计算不能碰的：上层、运行环境、数据和设置；laser / data / refinery 读全局表，要用经 MiningInputs 传
_ANALYSIS_FORBIDDEN = (
    "astral_toolkit.app",
    "astral_toolkit.tasks",
    "astral_toolkit.runtime",
    "astral_toolkit.gamedata",
    "astral_toolkit.crafting",
    "astral_toolkit.core.settings",
    "astral_toolkit.core.paths",
    "astral_toolkit.mining.laser",
    "astral_toolkit.mining.data",
    "astral_toolkit.mining.refinery",
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
    "sys",
)
_BARE_FORBIDDEN = (
    "astral_toolkit",
    "astral_toolkit.core",
)  # 裸导入后走属性访问，等于绕开上面的清单
_DYNAMIC_IMPORTS = ("__import__", "import_module", "open", "exec", "eval")


def _forbidden(mods, forbidden):
    return [m for m in mods if any(m == f or m.startswith(f + ".") for f in forbidden)]


def _dynamic_imports(source):
    """__import__(...)、importlib.import_module(...)、import_module(...) 这种字符串导入"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id == "__import__":  # f = __import__
            out.append(node.id)
        elif isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in _DYNAMIC_IMPORTS:
                out.append(name)
    return out


def _bound_modules(source, pkg):
    """import 真正绑定到名字上的东西：import a.b 绑 a，import a.b as c 绑 a.b，from a import b 绑 a.b"""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                base = pkg.split(".")
                base = base[: len(base) - node.level + 1]
                mod = ".".join(base + ([mod] if mod else []))
            for a in node.names:
                yield f"{mod}.{a.name}"


def _analysis_violations(source):
    pkg = "astral_toolkit.mining"
    mods = list(_imports_in_source(source, pkg))
    bare = [m for m in _bound_modules(source, pkg) if m in _BARE_FORBIDDEN]
    return _forbidden(mods, _ANALYSIS_FORBIDDEN) + bare + _dynamic_imports(source)


def _toplevel_engine_calls(source):
    """模块顶层（不算函数和类里面）调用 _engines / EngineManager 的地方"""
    out = []
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                names = {n.id for n in ast.walk(call.func) if isinstance(n, ast.Name)}
                out += sorted(names & {"_engines", "EngineManager"})
    return out


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
        "from astral_toolkit import gamedata",
        "from .. import runtime",
        "def f():\n    import time",
        "import importlib\nimportlib.import_module('astral_toolkit.mining.laser')",
        "from importlib import import_module\nimport_module('x')",
        "__import__('astral_toolkit.mining.data')",
        "import pathlib",
        "import json",
        "from .. import core",
        "import astral_toolkit",
        "open('x')",
        "exec('import os')",
        "import sys",
        "import sys\nsys.modules['astral_toolkit.mining.data']",
        "f = __import__",
    ):
        assert _analysis_violations(src), src
    for src in (
        "from .quality import tier_of",
        "from ..core import i18n",
        "from ..core.i18n import mineral_zh",
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
            "astral_toolkit.gamedata",
            "astral_toolkit.mining.laser",
            "astral_toolkit.mining.data",
            "astral_toolkit.mining.refinery",
            "astral_toolkit.crafting",
            "astral_toolkit.tasks",
            "astral_toolkit.core.settings",
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
        "import sys, threading, astral_toolkit.mining.analysis;"
        "print([m for m in sys.modules if m.startswith(('astral_toolkit.gamedata',"
        "'astral_toolkit.core.settings','astral_toolkit.core.paths','astral_toolkit.tasks','astral_toolkit.app',"
        "'astral_toolkit.runtime','astral_toolkit.mining.laser','astral_toolkit.mining.data','astral_toolkit.mining.refinery',"
        "'sqlite3'))], threading.active_count())"
    )
    assert _run(code) == "[] 1"


def test_tasks_mining_import_creates_no_engine():
    """导入 tasks.mining 本身不创建引擎。tasks/__init__.py 还会连带导入 count、navigation，
    它们导入时仍在取引擎（count.py:55、navigation.py:76），所以 import astral_toolkit.tasks 目前**会**创建引擎——这里换掉包入口只测 mining 本身。
    待办：count 归 RT-B5a、navigation 归 RT-B5b（见 RT 会话循环设计稿 §4.3），两处改完后去掉假包，直接测 import astral_toolkit.tasks"""
    code = (
        "import sys, types, pathlib, astral_toolkit;"
        "pkg = types.ModuleType('astral_toolkit.tasks');"
        "pkg.__path__ = [str(pathlib.Path(astral_toolkit.__file__).parent / 'tasks')];"
        "sys.modules['astral_toolkit.tasks'] = pkg;"
        "import astral_toolkit.tasks.mining;"
        "from astral_toolkit.app.engines.manager import EngineManager;"
        "print(EngineManager._instance is None, 'astral_toolkit.tasks.count' in sys.modules,"
        " 'astral_toolkit.tasks.navigation' in sys.modules)"
    )
    assert _run(code) == "True False False"


def test_tasks_mining_gets_engine_only_inside_functions():
    source = (_ROOT / "tasks" / "mining.py").read_text(encoding="utf-8")
    assert _toplevel_engine_calls(source) == []
    for bad in (
        "_pos = _engines().pos",
        "_M = EngineManager.get_instance()",
        "if True:\n    x = EngineManager.get_instance().live",
    ):
        assert _toplevel_engine_calls(bad), bad
    assert _toplevel_engine_calls("def f():\n    return _engines().pos") == []


_RUNTIME_FORBIDDEN = (
    "astral_toolkit.app",
    "astral_toolkit.tasks",
    "astral_toolkit.gamedata",
)


def _runtime_violations(source, pkg="astral_toolkit.runtime"):
    mods = list(_imports_in_source(source, pkg))
    dynamic = [d for d in _dynamic_imports(source) if d != "open"]
    return _forbidden(mods, _RUNTIME_FORBIDDEN) + dynamic


def test_runtime_layer_stays_below_app():
    """runtime/ 是新层：不依赖界面、业务和游戏数据（架构稿 §4.3、§11.3）"""
    files = list((_ROOT / "runtime").rglob("*.py"))
    assert files
    for f in files:
        assert _runtime_violations(f.read_text(encoding="utf-8")) == [], f.name
    for bad in (
        "from ..app import bus",
        "from astral_toolkit.tasks import mining",
        "from ..gamedata import snapshot",
        "import importlib\nimportlib.import_module('astral_toolkit.app')",
    ):
        assert _runtime_violations(bad), bad


_MUTABLE = (
    ast.Dict,
    ast.List,
    ast.Set,
    ast.DictComp,
    ast.ListComp,
    ast.SetComp,
    ast.Call,
)


def _mutable_globals(source):
    """模块顶层绑定的可变容器：字典、列表、集合，包在元组里的、调用构造的（dict()、defaultdict、类实例）也算"""
    out = []
    for node in ast.parse(source).body:
        if (
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and node.value is not None
            and any(isinstance(n, _MUTABLE) for n in ast.walk(node.value))
        ):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            out += [getattr(t, "id", "?") for t in targets]
    return out


def test_system_common_has_no_shared_state():
    """跨模块共享的最近结果只在 ResultStore：common.py 不再放可变的模块级状态"""
    source = (_ROOT / "tasks" / "system" / "common.py").read_text(encoding="utf-8")
    assert _mutable_globals(source) == []
    for bad in ("_L = {'a': None}", "_L = dict()", "_L = ({},)", "_L = Foo()"):
        assert _mutable_globals(bad) == ["_L"], bad


def test_old_result_globals_are_gone():
    for f in _ROOT.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "_FB_LAST" not in text and "_ORE_LAST" not in text, f.name


def _thread_starts_in_source(source):
    """模块里 threading.Thread(...) 的调用，落在哪个函数里（顶层返回 "<模块>"）"""
    tree = ast.parse(source)
    owner = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                owner[id(node)] = fn.name
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "Thread"
                and isinstance(f.value, ast.Name)
                and f.value.id == "threading"
            ):
                out.append(owner.get(id(node), "<模块>"))
    return out


def test_live_engine_does_not_start_its_own_scan_loop():
    """RT-B4：采矿助手的工作线程由会话循环起（runtime/session.py），live.py 里只剩存截图的小线程"""
    source = (_ROOT / "app" / "engines" / "live.py").read_text(encoding="utf-8")
    assert _thread_starts_in_source(source) == ["_save_miss"]
    for bad in (
        "threading.Thread(target=self._run)",
        "def f():\n    threading.Thread(target=g)",
    ):
        assert _thread_starts_in_source(bad), bad
    assert "SessionLoop(" in source, "采矿助手要接会话循环"
