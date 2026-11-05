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


def _call_names(source):
    """调用表达式里直接写出的函数名 / 方法名；不扫字符串和注释"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            out.append(func.id)
        elif isinstance(func, ast.Attribute):
            out.append(func.attr)
    return out


def _calls_named(source, names):
    return [name for name in _call_names(source) if name in names]


def _dynamic_import_targets(source):
    """__import__ / importlib.import_module 的第一个字符串参数"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
        else:
            name = getattr(func, "id", "")
        if name not in ("__import__", "import_module"):
            continue
        arg = node.args[0] if node.args else None
        if arg is None:
            for kw in node.keywords:
                if kw.arg == "name":
                    arg = kw.value
                    break
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg.value)
    return out


def _task_import_violations(source, pkg="astral_toolkit.tasks"):
    mods = list(_imports_in_source(source, pkg))
    return _forbidden(
        mods, ("astral_toolkit.bootstrap", "astral_toolkit.app.engines.manager")
    )


def _task_dynamic_import_violations(source):
    return [
        target
        for target in _dynamic_import_targets(source)
        if _forbidden(
            [target], ("astral_toolkit.bootstrap", "astral_toolkit.app.engines")
        )
    ]


def _engine_manager_names(source):
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id == "EngineManager":
            out.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr == "EngineManager":
            out.append(node.attr)
        elif isinstance(node, ast.alias):
            name = node.name.rsplit(".", 1)[-1]
            if "EngineManager" in (name, node.asname):
                out.append("EngineManager")
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "EngineManager":
                out.append("EngineManager")
    return out


def _replace_true_calls(source):
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if (
                kw.arg == "replace"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                out.append("replace=True")
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
    """B7：导入 tasks 不起线程、不产生引擎绑定，管理器模块已经不存在"""
    code = (
        "import sys, threading\n"
        "import astral_toolkit.tasks\n"
        "from astral_toolkit.tasks import mining, navigation, count\n"
        "from astral_toolkit.tasks.system import common\n"
        "from astral_toolkit.app import lifecycle_gate, ui_stream\n"
        "values = [\n"
        "    mining._live,\n"
        "    navigation._nav, navigation._pos,\n"
        "    navigation._game_events, navigation._results,\n"
        "    count._count, common._status, common._start,\n"
        "    lifecycle_gate._CLOSING, ui_stream._SOURCES,\n"
        "]\n"
        "print(threading.active_count(),\n"
        "      'astral_toolkit.app.engines.manager' in sys.modules,\n"
        "      all(value is None for value in values))\n"
        "try:\n"
        "    import astral_toolkit.app.engines.manager\n"
        "except ModuleNotFoundError:\n"
        "    print('missing')\n"
        "else:\n"
        "    print('present')\n"
    )
    assert _run(code) == "1 False True\nmissing"


def test_tasks_have_no_engine_calls():
    files = list((_ROOT / "tasks").rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        bad_calls = _calls_named(source, ("_engines", "_E", "get_instance"))
        assert bad_calls == [], path.name
    for bad in (
        "def f():\n    return _engines().pos",
        "x = _E().live",
        "x = helper.get_instance()",
    ):
        assert _calls_named(bad, ("_engines", "_E", "get_instance")), bad


def test_tasks_do_not_import_bootstrap_or_engine_manager():
    files = list((_ROOT / "tasks").rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        # 相对导入按文件自己所在的包解析：tasks/system/x.py 里的 ... 才是 astral_toolkit
        pkg = ".".join(("astral_toolkit", *path.relative_to(_ROOT).parent.parts))
        assert _task_import_violations(source, pkg) == [], path.name
    for bad in (
        "from ..bootstrap import build",
        "from astral_toolkit.bootstrap import build",
        "from astral_toolkit.app.engines.manager import EngineManager",
        "from astral_toolkit.app.engines import manager",
    ):
        assert _task_import_violations(bad), bad
    assert _task_import_violations("from ..core import paths") == []
    for bad in (
        "from ... import bootstrap",
        "from ...bootstrap import build",
        "from ...app.engines import manager",
    ):  # tasks/system 子包里的写法
        assert _task_import_violations(bad, "astral_toolkit.tasks.system"), bad


def test_tasks_dynamic_imports_stay_out_of_engines():
    files = list((_ROOT / "tasks").rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert _task_dynamic_import_violations(source) == [], path.name
    for bad in (
        "__import__('astral_toolkit.bootstrap')",
        (
            "import importlib\n"
            "importlib.import_module('astral_toolkit.app.engines.manager')"
        ),
        (
            "from importlib import import_module\n"
            "import_module('astral_toolkit.app.engines')"
        ),
    ):
        assert _task_dynamic_import_violations(bad), bad
    assert (
        _task_dynamic_import_violations(
            "__import__('astral_toolkit.core.paths', fromlist=['x'])"
        )
        == []
    )


def test_product_has_no_engine_manager_name():
    files = list(_ROOT.rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert _engine_manager_names(source) == [], path.name
    for bad in (
        "x = EngineManager.get_instance()",
        "from x import EngineManager",
        "class EngineManager:\n    pass",
        "x = manager.EngineManager",
    ):
        assert _engine_manager_names(bad), bad
    assert _engine_manager_names("x = 'EngineManager'") == []


def test_product_has_no_get_instance_calls():
    files = list(_ROOT.rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert _calls_named(source, ("get_instance",)) == [], path.name
    for bad in (
        "EngineManager.get_instance()",
        "helper.get_instance()",
        "get_instance()",
    ):
        assert _calls_named(bad, ("get_instance",)), bad
    assert _calls_named("def get_instance():\n    pass", ("get_instance",)) == []


def test_product_has_no_replace_true_calls():
    files = list(_ROOT.rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert _replace_true_calls(source) == [], path.name
    for bad in ("x.bind(replace=True)", "x.bind(a, replace=True)"):
        assert _replace_true_calls(bad), bad
    assert _replace_true_calls("x.bind(replace=False)") == []
    assert _replace_true_calls("x.bind(replace=flag)") == []


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


_INFRA_FORBIDDEN = (
    "astral_toolkit.app",
    "astral_toolkit.tasks",
    "astral_toolkit.runtime",
    "astral_toolkit.bootstrap",
)


def test_infrastructure_stays_below_app():
    """infrastructure/ 只读平台状态、读写文件 / 网络，不反向依赖界面、业务、runtime 和装配入口"""
    files = list((_ROOT / "infrastructure").rglob("*.py"))
    assert files
    for f in files:
        source = f.read_text(encoding="utf-8")
        mods = list(_imports_in(f))
        assert _forbidden(mods, _INFRA_FORBIDDEN) == [], f.name
        dynamic = [d for d in _dynamic_imports(source) if d != "open"]
        assert dynamic == [], f.name
    for source in (
        "from ...app import hud_state",
        "from ...tasks import mining",
        "from ...runtime.session import Tick",
        "from ... import bootstrap",
    ):
        mods = list(
            _imports_in_source(source, "astral_toolkit.infrastructure.platform")
        )
        assert _forbidden(mods, _INFRA_FORBIDDEN), source


_GAMEDATA_TEXTKEY_FORBIDDEN = (
    ("astral_toolkit.crafting.loot", {"_fold"}),
    ("astral_toolkit.crafting.wikelo", {"_fold"}),
    ("astral_toolkit.crafting.shops", {"_fold"}),
    ("astral_toolkit.crafting.itemsearch", {"en_key", "zh_key"}),
    ("astral_toolkit.trade.names", {"_fold_en", "_norm_zh"}),
)


def _textkeys_resolve_from(node, package):
    """把 ImportFrom 的相对导入还原成绝对模块名（函数里的 import 也照算）。"""
    module = node.module or ""
    if not node.level:
        return module
    parts = package.split(".")
    keep = len(parts) - (node.level - 1)
    base = ".".join(parts[:keep]) if keep > 0 else ""
    return ".".join(part for part in (base, module) if part)


def _gamedata_textkey_imports(source, package):
    """gamedata 里还在直接拿 crafting / trade 名字键的 import（按 (模块, 名字) 报）。"""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = _textkeys_resolve_from(node, package)
        names = {alias.name for alias in node.names}
        for banned_module, banned_names in _GAMEDATA_TEXTKEY_FORBIDDEN:
            if module == banned_module:
                hits = sorted(names & banned_names)
                if hits:
                    found.append(f"{module}: {', '.join(hits)}")
    return found


def _textkeys_package_for(path):
    """文件所属包名：astral_toolkit/gamedata/_import.py → astral_toolkit.gamedata。"""
    rel = path.relative_to(_ROOT.parent).with_suffix("")
    return ".".join(
        rel.parts[:-1]
    )  # 去掉模块名；__init__.py 去掉的是 __init__，剩下的就是包本身


def test_contracts_import_stdlib_only():
    """contracts 只依赖标准库：不回头拿项目模块，也不引第三方。"""
    files = list((_ROOT / "contracts").rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert [d for d in _dynamic_imports(source) if d != "open"] == [], path.name
        for module in _imports_in(path):
            root = module.split(".", 1)[0]
            assert not module.startswith("astral_toolkit"), f"{path.name}: {module}"
            assert root in sys.stdlib_module_names, f"{path.name}: {module}"


def test_gamedata_stops_reaching_into_crafting_and_trade():
    """gamedata 从 contracts.textkeys 拿名字键，不再直接拿 crafting / trade 的实现（函数里的 import 也算）。"""
    # 先自检解析：普通模块和 __init__.py 都按所在的包算相对导入（审查发现过这里形同虚设）
    assert (
        _textkeys_package_for(_ROOT / "gamedata" / "_import.py")
        == "astral_toolkit.gamedata"
    )
    assert (
        _textkeys_package_for(_ROOT / "gamedata" / "__init__.py")
        == "astral_toolkit.gamedata"
    )
    assert _gamedata_textkey_imports(
        "def f():\n    from ..crafting.loot import _fold\n", "astral_toolkit.gamedata"
    ) == ["astral_toolkit.crafting.loot: _fold"]
    files = list((_ROOT / "gamedata").rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        bad = _gamedata_textkey_imports(source, _textkeys_package_for(path))
        assert bad == [], f"{path.name}: {bad}"


_CATALOG_IMPORT_ALLOWED = ("astral_toolkit.contracts",)


def _catalog_import_modules(source, package):
    """catalog 文件里的 import 模块名（相对导入按包还原，函数里的也算）。"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append(_textkeys_resolve_from(node, package))
    return out


def _catalog_import_allowed(module):
    """标准库，或 astral_toolkit.contracts（及其子模块）。"""
    if module == _CATALOG_IMPORT_ALLOWED[0] or module.startswith(
        _CATALOG_IMPORT_ALLOWED[0] + "."
    ):
        return True
    root = module.split(".", 1)[0]
    return root in sys.stdlib_module_names


def _catalog_bad_imports(source, package):
    """catalog 里不允许的 import 模块名。"""
    return [
        m
        for m in _catalog_import_modules(source, package)
        if not _catalog_import_allowed(m)
    ]


def test_catalog_imports_stdlib_or_contracts_only():
    """catalog 只依赖标准库和 contracts（函数里的 import 也算）。"""
    assert (
        _textkeys_package_for(_ROOT / "catalog" / "__init__.py")
        == "astral_toolkit.catalog"
    )
    assert (
        _textkeys_package_for(_ROOT / "catalog" / "search.py")
        == "astral_toolkit.catalog"
    )
    assert _catalog_import_modules(
        "def f():\n    from ..contracts.textkeys import en_key\n",
        "astral_toolkit.catalog",
    ) == ["astral_toolkit.contracts.textkeys"]
    assert _catalog_bad_imports(
        "def f():\n    from ..gamedata import items\n",
        "astral_toolkit.catalog",
    ) == ["astral_toolkit.gamedata"]
    files = list((_ROOT / "catalog").rglob("*.py"))
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert _dynamic_imports(source) == [], path.name
        bad = _catalog_bad_imports(source, _textkeys_package_for(path))
        assert bad == [], f"{path.name}: {bad}"


_GAMEDATA_REVERSE_ROOTS = ("astral_toolkit.crafting", "astral_toolkit.trade")
_GAMEDATA_REVERSE_ALLOWED = {
    "astral_toolkit.crafting.crafting": {"_fold_name", "_search_norm", "assign_keys"}
}


def _module_under(module, root):
    return module == root or module.startswith(root + ".")


def _gamedata_reverse_imports(source, package):
    """gamedata 里对 crafting / trade 的 import：只剩 crafting.crafting 的三个规则名。"""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = _textkeys_resolve_from(node, package)
            if not any(_module_under(module, root) for root in _GAMEDATA_REVERSE_ROOTS):
                continue
            allowed = _GAMEDATA_REVERSE_ALLOWED.get(module, set())
            for alias in node.names:
                if alias.name not in allowed:
                    bad.append(f"{module}: {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(
                    _module_under(alias.name, root) for root in _GAMEDATA_REVERSE_ROOTS
                ):
                    bad.append(f"{alias.name}: <module>")
    return bad


def test_gamedata_reverse_imports_only_crafting_rules_left():
    """gamedata 只还许拿 crafting.crafting 的制造规则，别的 crafting / trade 都不许。"""
    assert _gamedata_reverse_imports(
        "def f():\n    from ..crafting.itemsearch import _has_cjk\n",
        "astral_toolkit.gamedata",
    )
    assert (
        _gamedata_reverse_imports(
            "def f():\n    from ..crafting.crafting import assign_keys\n",
            "astral_toolkit.gamedata",
        )
        == []
    )
    assert _gamedata_reverse_imports(
        "from ..trade.names import _junk\n", "astral_toolkit.gamedata"
    )
    files = list((_ROOT / "gamedata").rglob("*.py"))
    assert files
    bad = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        for hit in _gamedata_reverse_imports(source, _textkeys_package_for(path)):
            bad.append(f"{path.relative_to(_ROOT).as_posix()}: {hit}")
    assert bad == [], bad


_PRODUCT_CODE_KEY_MODULES = {
    "astral_toolkit.crafting.shops": {"_fold"},
    "astral_toolkit.crafting.loot": {"_fold"},
    "astral_toolkit.crafting.wikelo": {"_fold"},
    "astral_toolkit.trade.gamekey": {"_fold"},
    "astral_toolkit.trade.names": {"_fold_en", "_norm_zh"},
}
_PRODUCT_CODE_KEY_DEFINERS = {
    "crafting/shops.py",
    "crafting/loot.py",
    "crafting/wikelo.py",
    "trade/gamekey.py",
    "trade/names.py",
}


def _product_code_module_aliases(tree, package):
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = _textkeys_resolve_from(node, package)
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                if full in _PRODUCT_CODE_KEY_MODULES:
                    aliases[alias.asname or alias.name] = full
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname and alias.name in _PRODUCT_CODE_KEY_MODULES:
                    aliases[alias.asname] = alias.name
    return aliases


def _attr_expr(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _attr_expr(node.value)
        if base:
            return f"{base}.{node.attr}"
    return None


def _product_code_key_imports(source, package):
    tree = ast.parse(source)
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = _textkeys_resolve_from(node, package)
        banned = _PRODUCT_CODE_KEY_MODULES.get(module, set())
        for alias in node.names:
            if alias.name in banned:
                bad.append(f"{module}: {alias.name}")
    aliases = _product_code_module_aliases(tree, package)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        expr = _attr_expr(node.value)
        if not expr:
            continue
        if expr in aliases:
            module = aliases[expr]
        elif expr in _PRODUCT_CODE_KEY_MODULES:
            module = expr
        else:
            head, _, tail = expr.partition(".")
            base = aliases.get(head)
            module = f"{base}.{tail}" if base and tail else (base or expr)
        banned = _PRODUCT_CODE_KEY_MODULES.get(module, set())
        if node.attr in banned:
            bad.append(f"{module}: {node.attr}")
    return bad


def test_product_code_takes_name_keys_from_contracts():
    """产品代码要拿 contracts.textkeys 的名字键，不拿 crafting / trade 里的私有别名。"""
    assert _product_code_key_imports(
        "from ..crafting import shops\nshops._fold('a')\n",
        "astral_toolkit.crafting",
    )
    assert (
        _product_code_key_imports(
            "from ..contracts.textkeys import fold_en_loose\n",
            "astral_toolkit.crafting",
        )
        == []
    )
    files = list(_ROOT.rglob("*.py"))
    assert files
    bad = []
    for path in files:
        rel = path.relative_to(_ROOT).as_posix()
        if rel in _PRODUCT_CODE_KEY_DEFINERS:
            continue
        for hit in _product_code_key_imports(
            path.read_text(encoding="utf-8"), _textkeys_package_for(path)
        ):
            bad.append(f"{rel}: {hit}")
    assert bad == [], bad


def _trade_shell_uses(source, package):
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = _textkeys_resolve_from(node, package)
            if module == "astral_toolkit.tasks.trade":
                for alias in node.names:
                    if alias.name == "item_search":
                        bad.append("astral_toolkit.tasks.trade: item_search")
        elif isinstance(node, ast.Attribute) and node.attr == "item_search":
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_T"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and call.args[0].value == "trade"
            ):
                bad.append('_T("trade").item_search')
    return bad


def test_item_search_shell_only_for_stock_and_global_search():
    """tasks.trade.item_search 旧壳只给库存（新库存做完删），别处拿就是又长回去了。"""
    assert _trade_shell_uses("from .trade import item_search\n", "astral_toolkit.tasks")
    assert (
        _trade_shell_uses(
            "from .trade import trade, mineral_search\n", "astral_toolkit.tasks"
        )
        == []
    )
    assert _trade_shell_uses('_T("trade").item_search("x")\n', "astral_toolkit.tasks")
    files = list(_ROOT.rglob("*.py"))
    assert files
    bad = []
    for path in files:
        rel = path.relative_to(_ROOT).as_posix()
        if rel in ("tasks/trade.py", "tasks/stock.py"):
            continue
        for hit in _trade_shell_uses(
            path.read_text(encoding="utf-8"), _textkeys_package_for(path)
        ):
            bad.append(f"{rel}: {hit}")
    assert bad == [], bad


_NAV_PURE_FORBIDDEN = (
    "astral_toolkit.app",
    "astral_toolkit.tasks",
    "astral_toolkit.runtime",
    "astral_toolkit.bootstrap",
    "astral_toolkit.infrastructure",
    "astral_toolkit.core.settings",
    "astral_toolkit.core.capture",
    "astral_toolkit.core.paths",
    "astral_toolkit.system",
)
_NAV_PRESENTER_FORBIDDEN = (
    "astral_toolkit.runtime",
    "astral_toolkit.infrastructure",
    "astral_toolkit.tasks",
    "astral_toolkit.app.engines",
    "astral_toolkit.app.overlay",
    "astral_toolkit.app.hud_state",
    "astral_toolkit.core.settings",
    "astral_toolkit.core.capture",
    "astral_toolkit.system",
)


def _nav_engine_violations(source):
    mods = list(_imports_in_source(source, "astral_toolkit.app.engines"))
    dynamic = [d for d in _dynamic_imports(source) if d != "open"]
    calls = _calls_named(source, ("_T", "_H"))
    defs = [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in ("_T", "_H")
    ]
    return _forbidden(mods, ("astral_toolkit.tasks",)) + dynamic + calls + defs


def _pure_navigation_violations(source):
    mods = list(_imports_in_source(source, "astral_toolkit.navigation"))
    dynamic = [d for d in _dynamic_imports(source) if d != "open"]
    return _forbidden(mods, _NAV_PURE_FORBIDDEN) + dynamic


def _nav_presenter_violations(source):
    mods = list(_imports_in_source(source, "astral_toolkit.app.presenters"))
    dynamic = [d for d in _dynamic_imports(source) if d != "open"]
    return _forbidden(mods, _NAV_PRESENTER_FORBIDDEN) + dynamic


def test_nav_engine_does_not_reach_into_tasks():
    """导航引擎只在 bootstrap 接好的依赖上跑：不再静态 / 动态导入 tasks，也不再留 _T / _H。"""
    path = _ROOT / "app/engines/nav.py"
    source = path.read_text(encoding="utf-8")
    assert _nav_engine_violations(source) == [], path.name
    for bad in (
        "from ...tasks import navigation",
        "import importlib\nimportlib.import_module('astral_toolkit.tasks.navigation')",
        "def _T(name):\n    return name",
        "x = _T('navigation')",
        "x = _H()",
    ):
        assert _nav_engine_violations(bad), bad


def test_navigation_views_and_marker_stay_pure():
    """视图和记号只算数：不反向拿 app / tasks / runtime / 设置；记号还不读时间。"""
    for name in ("views.py", "marker.py"):
        path = _ROOT / "navigation" / name
        source = path.read_text(encoding="utf-8")
        assert _pure_navigation_violations(source) == [], name
    marker = (_ROOT / "navigation" / "marker.py").read_text(encoding="utf-8")
    marker_mods = list(_imports_in_source(marker, "astral_toolkit.navigation"))
    assert _forbidden(marker_mods, ("time",)) == []
    for bad in (
        "from ..app import bus",
        "from astral_toolkit.tasks import mining",
        "from ..runtime.session import Tick",
        "import importlib\nimportlib.import_module('astral_toolkit.app')",
    ):
        assert _pure_navigation_violations(bad), bad
    for bad_time in ("import time", "from time import monotonic"):
        mods = list(_imports_in_source(bad_time, "astral_toolkit.navigation"))
        assert _forbidden(mods, ("time",)), bad_time


def test_nav_presenter_imports():
    """导航展示层只读展示模型和 navigation 纯计算，不回头拿运行环境 / 任务 / 引擎。"""
    path = _ROOT / "app/presenters/nav.py"
    source = path.read_text(encoding="utf-8")
    assert _nav_presenter_violations(source) == [], path.name
    for bad in (
        "from ...runtime.session import Tick",
        "from ...tasks import navigation",
        "from ..engines import nav",
        "from ..overlay import Overlay",
        "from ..hud_state import _hud",
        "from ...core.settings import load",
        "import importlib\nimportlib.import_module('astral_toolkit.tasks.navigation')",
    ):
        assert _nav_presenter_violations(bad), bad


_CATALOG_PRESENTER_FORBIDDEN = (
    "astral_toolkit.gamedata",
    "astral_toolkit.tasks",
    "astral_toolkit.runtime",
    "astral_toolkit.bootstrap",
    "astral_toolkit.crafting",
    "astral_toolkit.trade",
    "astral_toolkit.mining",
    "astral_toolkit.navigation",
    "astral_toolkit.infrastructure",
    "astral_toolkit.app.engines",
    "astral_toolkit.app.overlay",
    "astral_toolkit.app.hud_state",
    "astral_toolkit.core.settings",
    "astral_toolkit.core.paths",
    "sqlite3",
    "urllib",
    "threading",
)
_CATALOG_USE_CASE_FORBIDDEN = (
    "astral_toolkit.app",
    "astral_toolkit.runtime",
    "astral_toolkit.bootstrap",
)
_CATALOG_PRESENTER_MODULE = "astral_toolkit.app.presenters.catalog"


def _catalog_presenter_violations(source):
    mods = list(_imports_in_source(source, "astral_toolkit.app.presenters"))
    return _forbidden(mods, _CATALOG_PRESENTER_FORBIDDEN) + _dynamic_imports(source)


def _catalog_use_case_violations(source):
    mods = list(_imports_in_source(source, "astral_toolkit.tasks"))
    return _forbidden(mods, _CATALOG_USE_CASE_FORBIDDEN) + _dynamic_imports(source)


def _catalog_presenter_imports(source, pkg):
    return [
        mod
        for mod in _imports_in_source(source, pkg)
        if mod == _CATALOG_PRESENTER_MODULE
        or mod.startswith(_CATALOG_PRESENTER_MODULE + ".")
    ]


def test_catalog_presenter_imports():
    """物品查询展示层只排版：不取数据，不碰任务 / 运行环境 / 设置，也不动态导入。"""
    path = _ROOT / "app" / "presenters" / "catalog.py"
    source = path.read_text(encoding="utf-8")
    assert _catalog_presenter_violations(source) == [], path.name
    for bad in (
        "from ...gamedata import items",
        "from ...tasks import catalog",
        "from ...crafting import acquire",
        "from ...trade.names import table",
        "def f():\n    from ...runtime.session import Tick\n",
        "import sqlite3",
        "import threading",
        "import importlib\nimportlib.import_module('astral_toolkit.tasks.catalog')",
    ):
        assert _catalog_presenter_violations(bad), bad


def test_catalog_use_cases_stay_below_app():
    """物品查询用例不反向拿 app / runtime / bootstrap，也不动态导入。"""
    path = _ROOT / "tasks" / "catalog.py"
    source = path.read_text(encoding="utf-8")
    assert _catalog_use_case_violations(source) == [], path.name
    for bad in (
        "from ..app.presenters import catalog",
        "from ..app import bus",
        "def f():\n    from ..runtime import session\n",
        "from ..bootstrap import build",
        "import importlib\nimportlib.import_module('astral_toolkit.gamedata')",
    ):
        assert _catalog_use_case_violations(bad), bad


def test_only_trade_shell_imports_catalog_presenter():
    """IQ-B5 过渡：tasks 里只有 tasks/trade.py 旧壳能 import 展示层；IQ-B6/B7 删壳后收紧成一个都不许。"""
    files = list((_ROOT / "tasks").rglob("*.py"))
    assert files
    bad = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        # 相对导入按文件自己所在的包解析：tasks/system/x.py 里的 ... 才是 astral_toolkit
        pkg = ".".join(("astral_toolkit", *path.relative_to(_ROOT).parent.parts))
        if _catalog_presenter_imports(source, pkg):
            rel = path.relative_to(_ROOT).as_posix()
            if rel != "tasks/trade.py":
                bad.append(rel)
    assert bad == [], bad
    assert _catalog_presenter_imports(
        "from ..app.presenters import catalog as p", "astral_toolkit.tasks"
    )
    assert (
        _catalog_presenter_imports(
            "from ..app.presenters import mining", "astral_toolkit.tasks"
        )
        == []
    )


_F8_FORBIDDEN_IMPORTS = (
    "astral_toolkit.tasks.trade",
    "astral_toolkit.crafting.loot",
    "astral_toolkit.trade.console.match_tooltip",
    "astral_toolkit.trade.console.hud_market",
)
_F8_FORBIDDEN_CALLS = ("trade", "match_tooltip", "add_alias", "_market_rows")


def _f8_link_violations(source):
    """F8 直接拿 tasks/trade、Trade、掉落、console 报价函数的地方（函数里的 import 也算）"""
    mods = list(_imports_in_source(source, "astral_toolkit.tasks"))
    return _forbidden(mods, _F8_FORBIDDEN_IMPORTS) + _calls_named(
        source, _F8_FORBIDDEN_CALLS
    )


def test_f8_reaches_item_query_through_links():
    """IQ-B6：F8 不再直接拿 tasks/trade 和 Trade，物品查询和玩家市场经 bootstrap 接的 HoverLinks。"""
    path = _ROOT / "tasks" / "hover.py"
    source = path.read_text(encoding="utf-8")
    assert _f8_link_violations(source) == [], path.name
    for bad in (
        "from . import trade as _t_trade",
        "def f():\n    from ..crafting.loot import info\n",
        "def f():\n    from ..trade.console import hud_market\n",
        "from ..trade.console import match_tooltip",
        "t = trade()",
        "C.match_tooltip(t, zh, en)",
        't.catalog.add_alias(1, "甲")',
        '_market_rows(1, "q6")',
    ):
        assert _f8_link_violations(bad), bad
    ok = "m = links.market()\nm.match(zh, en)\nm.remember_alias(1, zh)\nlinks.hud_market([])\n"
    assert _f8_link_violations(ok) == []


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


def test_count_engine_does_not_start_its_own_threads():
    """RT-B5a：盘点线程由会话循环起，app/engines/count.py 里不自己起线程"""
    source = (_ROOT / "app" / "engines" / "count.py").read_text(encoding="utf-8")
    assert _thread_starts_in_source(source) == []


def test_live_engine_does_not_start_its_own_scan_loop():
    """RT-B4：采矿助手的工作线程由会话循环起（runtime/session.py）；RT-B6 起存截图也交给 app/miss_shots.py 的队列，
    live.py 里不再起任何线程"""
    source = (_ROOT / "app" / "engines" / "live.py").read_text(encoding="utf-8")
    assert _thread_starts_in_source(source) == []
    for bad in (
        "threading.Thread(target=self._run)",
        "def f():\n    threading.Thread(target=g)",
    ):
        assert _thread_starts_in_source(bad), bad
    assert "SessionLoop(" in source, "采矿助手要接会话循环"
