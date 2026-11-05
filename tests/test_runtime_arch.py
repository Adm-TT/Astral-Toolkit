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
