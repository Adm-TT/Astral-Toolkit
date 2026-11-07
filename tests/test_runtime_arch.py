"""运行结构的依赖检查（架构稿 §4.3、§11.3，RT-B1 / RT-B2）：领域计算不碰运行环境，呈现层不取数据，导入不创建引擎"""

import ast
import re
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
        "    count._count,\n"
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
    "astral_toolkit.bootstrap",
    # 目录迁移章程 §9：工作线程要的读屏、分析、平台判断由 bootstrap 接进来，不直接拿这些混着读屏 / 资料 / 业务的实现；
    # 以后要用里面的纯值、纯计算，按符号单独放行，不整包豁免
    "astral_toolkit.navigation",
    "astral_toolkit.mining",
    "astral_toolkit.trade",
    "astral_toolkit.crafting",
    "astral_toolkit.system",
    "astral_toolkit.ocr",
    "astral_toolkit.infrastructure",
    "astral_toolkit.core.capture",
    "astral_toolkit.core.settings",
)


# 允许清单（R1 审查）：runtime 里绑到名字上的本项目模块只许 runtime 自己、contracts、core.run_records（lifecycle 写退出记录）；
# 先拿包再取属性（from ... import core → core.capture）、没列进上面禁止清单的包（update、run……）也挡得住
_RUNTIME_ALLOWED = (
    "astral_toolkit.runtime",
    "astral_toolkit.contracts",
    "astral_toolkit.core.run_records",
)


def _runtime_bound_outside(source, pkg):
    out = []
    for m in _bound_modules(source, pkg):
        if m != "astral_toolkit" and not m.startswith("astral_toolkit."):
            continue  # 标准库、第三方
        if not any(m == a or m.startswith(a + ".") for a in _RUNTIME_ALLOWED):
            out.append(m)
    return out


def _runtime_violations(source, pkg="astral_toolkit.runtime"):
    mods = list(_imports_in_source(source, pkg))
    dynamic = [d for d in _dynamic_imports(source) if d != "open"]
    return (
        _forbidden(mods, _RUNTIME_FORBIDDEN)
        + dynamic
        + _runtime_bound_outside(source, pkg)
    )


def test_runtime_layer_stays_below_app():
    """runtime/ 是新层：不依赖界面、业务和游戏数据（架构稿 §4.3、§11.3），也不直接拿读屏、资料、业务的具体实现
    （目录迁移章程 §9）；runtime/workers 这些子目录按各自的包算相对导入，函数里 import、字符串导入一样查"""
    files = list((_ROOT / "runtime").rglob("*.py"))
    assert any(f.parent.name == "workers" for f in files), files
    for f in files:
        pkg = ".".join(("astral_toolkit", *f.relative_to(_ROOT).parent.parts))
        if f.parent.name == "workers":  # 包算错了相对导入会解析到别处，就漏查了
            assert pkg == "astral_toolkit.runtime.workers", pkg
        assert _runtime_violations(f.read_text(encoding="utf-8"), pkg) == [], f.name
    for bad in (
        "from ..app import bus",
        "from astral_toolkit.tasks import mining",
        "from ..gamedata import snapshot",
        "import importlib\nimportlib.import_module('astral_toolkit.app')",
    ):
        assert _runtime_violations(bad), bad
    workers = "astral_toolkit.runtime.workers"
    for bad in (
        "from ...navigation import navigate",
        "def f():\n    from ...navigation.displayinfo import Reader\n",
        "from ...system.showloc import game_foreground",
        "from ...core.capture import game_area",
        "from ...mining import screen",
        "from ...trade import console",
        "from ...tasks import position",
        "from ...app import bus",
        "from ... import bootstrap",
        "from ... import core\ncore.capture.game_area()\n",
        "import astral_toolkit.core as core\n",
        "import astral_toolkit\n",
        "from ...update import data_pack",
        "from ... import run",
    ):
        assert _runtime_violations(bad, workers), bad
    for ok in (
        "from ...contracts.position import PositionRead",
        "from ..session import Session",
        "from ...core import run_records",
        "import threading\nfrom collections.abc import Callable\n",
    ):
        assert _runtime_violations(ok, workers) == [], ok


def test_position_worker_import_is_light():
    """导入定位线程（runtime/workers/position）不带进 navigation、app、tasks、system（R1）；
    再导入定位分析（tasks/position，属于 tasks 层，带进 tasks 包是允许的）也不起线程"""
    code = (
        "import sys, threading\n"
        "n = threading.active_count()\n"
        "import astral_toolkit.runtime.workers.position\n"
        "heavy = ('astral_toolkit.navigation', 'astral_toolkit.app', 'astral_toolkit.tasks', 'astral_toolkit.system')\n"
        "a = sorted(m for m in sys.modules if m.startswith(heavy))\n"
        "import astral_toolkit.tasks.position\n"
        "print(threading.active_count() == n, a)\n"
    )
    assert _run(code) == "True []"


def test_navigation_workers_import_is_light():
    """导入导航线程（runtime/workers/navigation）、游戏事件线程（runtime/workers/game_events）不带进 navigation、app、
    tasks、system（目录迁移 R2）；再导入导航分析（tasks/navigation_analysis）也不起线程"""
    code = (
        "import sys, threading\n"
        "n = threading.active_count()\n"
        "import astral_toolkit.runtime.workers.navigation\n"
        "import astral_toolkit.runtime.workers.game_events\n"
        "heavy = ('astral_toolkit.navigation', 'astral_toolkit.app', 'astral_toolkit.tasks', 'astral_toolkit.system')\n"
        "a = sorted(m for m in sys.modules if m.startswith(heavy))\n"
        "import astral_toolkit.tasks.navigation_analysis\n"
        "print(threading.active_count() == n, a)\n"
    )
    assert _run(code) == "True []"


_NAV_ANALYSIS_FORBIDDEN = (
    "astral_toolkit.app",
    "astral_toolkit.runtime",
    "astral_toolkit.bootstrap",
    "astral_toolkit.infrastructure",
    "astral_toolkit.system",
)
_NAV_MARKER_FORBIDDEN = (
    "astral_toolkit.tasks",
    "astral_toolkit.runtime",
    "astral_toolkit.bootstrap",
)


def _nav_layer_violations(source, pkg, forbidden):
    mods = list(_imports_in_source(source, pkg))
    bare = [m for m in _bound_modules(source, pkg) if m in _BARE_FORBIDDEN]
    dynamic = [
        d for d in _dynamic_imports(source) if d != "open"
    ]  # 写文件的 .open( 不算
    return _forbidden(mods, forbidden) + bare + dynamic


def test_navigation_analysis_and_marker_stay_in_their_layers():
    """目录迁移 R2 拆出来的两块：导航分析（tasks/navigation_analysis）只往下转给 navigation，不碰界面、runtime、装配、
    平台、系统，文件顶上只 import typing（navigate 调用时才取）；HUD 记号（app/nav_marker）不碰 tasks、runtime、装配。
    都不许字符串导入、不许裸 import astral_toolkit 再走属性"""
    path = _ROOT / "tasks" / "navigation_analysis.py"
    source = path.read_text(encoding="utf-8")
    assert (
        _nav_layer_violations(source, "astral_toolkit.tasks", _NAV_ANALYSIS_FORBIDDEN)
        == []
    )
    top = [
        n for n in ast.parse(source).body if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    assert [ast.unparse(n) for n in top] == ["from typing import Any"]
    path = _ROOT / "app" / "nav_marker.py"
    source = path.read_text(encoding="utf-8")
    assert (
        _nav_layer_violations(source, "astral_toolkit.app", _NAV_MARKER_FORBIDDEN) == []
    )
    for bad in (
        "def f():\n    from ..app import bus\n",
        "from ..runtime.workers import navigation\n",
        "import importlib\nimportlib.import_module('astral_toolkit.app')\n",
        "import astral_toolkit\n",
    ):
        assert _nav_layer_violations(
            bad, "astral_toolkit.tasks", _NAV_ANALYSIS_FORBIDDEN
        ), bad
    for bad in (
        "from ..tasks import navigation\n",
        "def f():\n    from ..runtime.workers import navigation\n",
        "from .. import bootstrap\n",
    ):
        assert _nav_layer_violations(
            bad, "astral_toolkit.app", _NAV_MARKER_FORBIDDEN
        ), bad


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


# 下载适配（providers）、本机存取适配（persistence）另外不许碰业务、数据层和更新流程（目录迁移章程 §3、Q3）
_INFRA_ADAPTER_FORBIDDEN = _INFRA_FORBIDDEN + (
    "astral_toolkit.gamedata",
    "astral_toolkit.catalog",
    "astral_toolkit.crafting",
    "astral_toolkit.update",
    "astral_toolkit.trade",
    "astral_toolkit.mining",
    "astral_toolkit.navigation",
    "astral_toolkit.system",
    "astral_toolkit.run",
    "astral_toolkit.selftest",
    "astral_toolkit.frozen_main",
)


def _infra_adapter_violations(source, pkg):
    """适配层碰了不该碰的：禁用清单里的模块（函数里的 import 也算）、裸 import astral_toolkit 再走属性（等于绕开清单）"""
    mods = list(_imports_in_source(source, pkg))
    bare = [m for m in _bound_modules(source, pkg) if m in _BARE_FORBIDDEN]
    return _forbidden(mods, _INFRA_ADAPTER_FORBIDDEN) + bare


def test_infrastructure_adapters_stay_below_domain():
    """下载 / 本机存取适配只管发请求、读写文件和资源：不碰业务、数据层和更新流程，也不自己起线程
    （并行下载由调用方的更新流程起）。函数里的 import 也算"""
    files = [
        p
        for d in ("providers", "persistence")
        for p in sorted((_ROOT / "infrastructure" / d).rglob("*.py"))
    ]
    assert len(files) >= 4, files
    for f in files:
        rel = f.relative_to(_ROOT).as_posix()
        source = f.read_text(encoding="utf-8")
        pkg = ".".join(("astral_toolkit", *f.relative_to(_ROOT).parent.parts))
        assert _infra_adapter_violations(source, pkg) == [], rel
        assert _thread_makers_in_source(source) == [], rel
    for bad in (
        "from ...gamedata import loot",
        "def f():\n    from ...update import loot\n",
        "def f():\n    from ...crafting import acquire\n",
        "from ...tasks.catalog_queries import loot",
        "def f():\n    from ... import run\n    run.update()\n",
        "import astral_toolkit\nastral_toolkit.gamedata.loot.rows()\n",
    ):
        assert _infra_adapter_violations(
            bad, "astral_toolkit.infrastructure.providers"
        ), bad
    assert _thread_makers_in_source(
        "from concurrent.futures import ThreadPoolExecutor\nThreadPoolExecutor(4)\n"
    )


def test_core_stays_below_app():
    """core/ 是基础工具：不反向依赖界面、用例、runtime 和装配入口（CL-C5 去掉了截图读悬浮窗、运行记录推面板
    这两处，改成装配接进来）。函数里的 import 也算"""
    files = list((_ROOT / "core").rglob("*.py"))
    assert files
    for f in files:
        assert _forbidden(list(_imports_in(f)), _INFRA_FORBIDDEN) == [], f.name
        assert _core_dynamic_up(f.read_text(encoding="utf-8")) == [], f.name
    mods = list(_imports_in_source("from ..app import bus", "astral_toolkit.core"))
    assert _forbidden(mods, _INFRA_FORBIDDEN)  # 检查本身认得出来
    for bad in (
        "import importlib\nimportlib.import_module('astral_toolkit.app.bus')\n",
        "__import__('astral_toolkit.app.bus')\n",
        "import importlib\nimportlib.import_module('..app', __package__)\n",
    ):
        assert _core_dynamic_up(bad), bad
    assert _core_dynamic_up("_lock = __import__('threading').Lock()\n") == []


def _core_dynamic_up(source):
    """core 里字符串导入（__import__ / import_module）的目标：往上拿界面 / 用例 / runtime / 装配入口的、
    相对的（core 里用不着）都算；标准库照常（core/settings 里有 __import__("threading")）"""
    return [
        t
        for t in _dynamic_import_targets(source)
        if t.startswith(".") or _forbidden([t], _INFRA_FORBIDDEN)
    ]


_GAMEDATA_TEXTKEY_FORBIDDEN = (
    ("astral_toolkit.tasks.catalog_queries.loot", {"_fold"}),
    ("astral_toolkit.crafting.wikelo", {"_fold"}),
    ("astral_toolkit.tasks.catalog_queries.shops", {"_fold"}),
    ("astral_toolkit.tasks.catalog_queries.search", {"en_key", "zh_key"}),
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
        "def f():\n    from ..tasks.catalog_queries.loot import _fold\n",
        "astral_toolkit.gamedata",
    ) == ["astral_toolkit.tasks.catalog_queries.loot: _fold"]
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


# 制造 / 维科洛的纯规则文件（CR-B2、B3）：只吃传进来的数据
_CRAFTING_RULE_FILES = (
    "labels",
    "classify",
    "materials",
    "quality",
    "mix",
    "listing",
    "reverse",
    "wikelo_rules",
)
_CRAFTING_RULE_MODULES = {f"astral_toolkit.crafting.{n}" for n in _CRAFTING_RULE_FILES}


def _crafting_rule_ok(module):
    return (
        module in _CRAFTING_RULE_MODULES
        or _module_under(module, "astral_toolkit.contracts")
        or (
            not _module_under(module, "astral_toolkit")
            and module.split(".", 1)[0] in sys.stdlib_module_names
        )
    )


def _crafting_rule_bad_imports(source, package):
    """纯规则文件里不许的 import：标准库、contracts、同批纯规则文件以外的；函数里面的 import 也不许。"""
    tree = ast.parse(source)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    bad.append(f"{node.name} 里面 import（第 {sub.lineno} 行）")
        elif isinstance(node, ast.ImportFrom):
            module = _textkeys_resolve_from(node, package)
            for alias in node.names:
                if not (
                    _crafting_rule_ok(module)
                    or _crafting_rule_ok(f"{module}.{alias.name}")
                ):
                    bad.append(f"{module}: {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not _crafting_rule_ok(alias.name):
                    bad.append(alias.name)
    return bad


def test_crafting_rules_import_stdlib_contracts_or_each_other():
    """制造 / 维科洛纯规则（CR-B2、B3）只依赖标准库、contracts 和彼此：不读库、不读文件、不读汉化、不许函数里面 import。"""
    pkg = "astral_toolkit.crafting"
    assert (
        _crafting_rule_bad_imports(
            "import re\nfrom collections import Counter\nfrom . import labels\n"
            "from .quality import group_mods\nfrom ..contracts.textkeys import blueprint_norm\n",
            pkg,
        )
        == []
    )
    for bad in (
        "from .. import gamedata\n",
        "from . import crafting\n",
        "from .itemstats import base_value\n",
        "from ..mining.quality import tier_values\n",
        "from ..core.i18n import mineral_zh\n",
        "import astral_toolkit.gamedata\n",
        "def f():\n    import math\n",
    ):
        assert _crafting_rule_bad_imports(bad, pkg), bad
    for name in _CRAFTING_RULE_FILES:
        source = (_ROOT / "crafting" / f"{name}.py").read_text(encoding="utf-8")
        assert _dynamic_imports(source) == [], name
        assert _crafting_rule_bad_imports(source, pkg) == [], name


_GAMEDATA_REVERSE_ROOTS = ("astral_toolkit.crafting", "astral_toolkit.trade")


def _module_under(module, root):
    return module == root or module.startswith(root + ".")


def _reverse_target(module):
    return any(_module_under(module, root) for root in _GAMEDATA_REVERSE_ROOTS)


def _gamedata_reverse_imports(source, package):
    """gamedata 里对 crafting / trade 的 import（函数体里的、「from .. import crafting」这种也算）。"""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = _textkeys_resolve_from(node, package)
            for alias in node.names:
                if _reverse_target(module) or _reverse_target(f"{module}.{alias.name}"):
                    bad.append(f"{module}: {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _reverse_target(alias.name):
                    bad.append(f"{alias.name}: <module>")
    return bad


def test_gamedata_has_no_reverse_imports():
    """gamedata 不许反过来 import crafting / trade：CR-B1 把制造的名字键和蓝图编号也搬进了 contracts，一个都不剩。"""
    assert _gamedata_reverse_imports(
        "def f():\n    from ..crafting.itemsearch import _has_cjk\n",
        "astral_toolkit.gamedata",
    )
    assert _gamedata_reverse_imports(
        "def f():\n    from ..crafting.crafting import assign_keys\n",
        "astral_toolkit.gamedata",
    ) == ["astral_toolkit.crafting.crafting: assign_keys"]
    assert _gamedata_reverse_imports(
        "from .. import crafting\n", "astral_toolkit.gamedata"
    )
    assert _gamedata_reverse_imports(
        "from ..trade.names import _junk\n", "astral_toolkit.gamedata"
    )
    assert (
        _gamedata_reverse_imports(
            "from ..contracts.blueprints import assign_keys\nfrom .. import contracts\n",
            "astral_toolkit.gamedata",
        )
        == []
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
    "astral_toolkit.crafting.crafting": {"_fold_name", "_search_norm"},
    "astral_toolkit.tasks.catalog_queries.shops": {"_fold"},
    "astral_toolkit.tasks.catalog_queries.loot": {"_fold"},
    "astral_toolkit.crafting.wikelo": {"_fold"},
    "astral_toolkit.trade.gamekey": {"_fold"},
    "astral_toolkit.trade.names": {"_fold_en", "_norm_zh"},
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
        "from ..tasks.catalog_queries import shops\nshops._fold('a')\n",
        "astral_toolkit.crafting",
    )
    assert _product_code_key_imports(
        "from ..crafting.crafting import _search_norm\n", "astral_toolkit.tasks"
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
    """导航线程（目录迁移 R2 起在 runtime/workers/navigation）只在 bootstrap 接好的依赖上跑：不再静态 / 动态导入 tasks，
    也不再留 _T / _H（runtime 门禁另外只许 runtime、contracts、core.run_records）。"""
    path = _ROOT / "runtime/workers/navigation.py"
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


# 查询内部实现（tasks/catalog_queries，目录迁移章程 §4）另外不许绕回旧的 crafting 取数文件
_CATALOG_QUERIES_FORBIDDEN = _CATALOG_USE_CASE_FORBIDDEN + (
    "astral_toolkit.crafting.acquire",
    "astral_toolkit.crafting.itemsearch",
    "astral_toolkit.crafting.shops",
    "astral_toolkit.crafting.loot",
)


def _catalog_use_case_violations(source, pkg="astral_toolkit.tasks"):
    mods = list(_imports_in_source(source, pkg))
    forbidden = (
        _CATALOG_QUERIES_FORBIDDEN
        if pkg.startswith("astral_toolkit.tasks.catalog_queries")
        else _CATALOG_USE_CASE_FORBIDDEN
    )
    return _forbidden(mods, forbidden) + _dynamic_imports(source)


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
    """物品查询用例不反向拿 app / runtime / bootstrap，也不动态导入；内部实现 tasks/catalog_queries 整个目录一起查
    （目录迁移章程 §9：新目录要进门禁），还不许绕回旧的 crafting 取数文件。"""
    files = [_ROOT / "tasks" / "catalog.py"] + sorted(
        (_ROOT / "tasks" / "catalog_queries").rglob("*.py")
    )
    assert len(files) >= 3, files  # catalog.py + __init__ + search
    for path in files:
        source = path.read_text(encoding="utf-8")
        pkg = ".".join(("astral_toolkit", *path.relative_to(_ROOT).parent.parts))
        if (
            path.parent.name == "catalog_queries"
        ):  # 包算错了相对导入会解析到别处，就漏查了
            assert pkg == "astral_toolkit.tasks.catalog_queries", pkg
        assert _catalog_use_case_violations(source, pkg) == [], path.name
    sub = "astral_toolkit.tasks.catalog_queries"
    for bad in (
        "from ...app import bus",
        "def f():\n    from ...runtime import session\n",
        "from ...crafting.acquire import info",
        "from ...crafting import itemsearch",
        "def f():\n    from ...crafting.shops import where\n",
        "def f():\n    from ...crafting.loot import detail\n",
    ):
        assert _catalog_use_case_violations(bad, sub), bad
    for bad in (
        "from ..app.presenters import catalog",
        "from ..app import bus",
        "def f():\n    from ..runtime import session\n",
        "from ..bootstrap import build",
        "import importlib\nimportlib.import_module('astral_toolkit.gamedata')",
    ):
        assert _catalog_use_case_violations(bad), bad


def test_catalog_queries_import_starts_no_thread():
    """导入物品查询内部实现不起线程（一闪就结束的也算）、不开库、不建库、不建索引：搜索预热线程由 bootstrap 起
    （目录迁移章程 §9，Q1）。按目录逐个查 catalog_queries 包和下面每个模块、子包里的模块也算（Q2 起；后面搬进来的自动算上）。
    tasks、gamedata 包先导入好，只看 catalog_queries 自己导入时做了什么；
    先确认被测模块都还没被别处带进来，不然这条什么都测不到"""
    code = (
        "import importlib, sqlite3, sys, threading\n"
        "from pathlib import Path\n"
        "import astral_toolkit.tasks, astral_toolkit.catalog.search\n"
        "import astral_toolkit.gamedata as g\n"
        "import astral_toolkit.gamedata._ready as ready\n"
        "pkg = 'astral_toolkit.tasks.catalog_queries'\n"
        "here = Path(astral_toolkit.tasks.__file__).parent / 'catalog_queries'\n"
        "files = (p.relative_to(here).with_suffix('').parts for p in here.rglob('*.py'))\n"
        "names = sorted({'.'.join(f[:-1] if f[-1] == '__init__' else f) for f in files} - {''})\n"
        "mods = [pkg] + [pkg + '.' + n for n in names]\n"
        "fresh = all(m not in sys.modules for m in mods)\n"
        "started, touched = [], []\n"
        "_start = threading.Thread.start\n"
        "threading.Thread.start = lambda self: (started.append(self.name), _start(self))[1]\n"
        "g.ensure = lambda *a, **k: touched.append('ensure')\n"
        "g.snapshot = lambda *a, **k: touched.append('snapshot')\n"
        "ready.ensure = lambda *a, **k: touched.append('ready')\n"
        "sqlite3.connect = lambda *a, **k: touched.append('connect')\n"
        "for m in mods:\n"
        "    importlib.import_module(m)\n"
        "s = sys.modules[pkg + '.search']\n"
        "print(fresh, started, touched, s._cache._has, ','.join(names))\n"
    )
    out = _run(code)
    flags, _, names = out.rpartition(" ")
    assert flags == "True [] [] False", out
    assert {"search", "shops"} <= set(names.split(",")), out


_THREAD_MAKERS = (
    "Thread",
    "Timer",
    "ThreadPoolExecutor",
    "ProcessPoolExecutor",
    "ThreadPool",
    "Pool",
    "start_new_thread",
    "to_thread",
    "run_in_executor",
)


def _thread_makers_in_source(source):
    """起线程 / 线程池的调用，按被调的名字认：threading.Thread、from threading import Thread、
    __import__('threading').Thread、Timer、concurrent.futures 的池子、multiprocessing 的 Pool / ThreadPool、
    _thread.start_new_thread、asyncio.to_thread、run_in_executor 都算；继承 Thread 的类也算（Q3a 审查补）"""
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in _THREAD_MAKERS:
                out.append(name)
        elif isinstance(node, ast.ClassDef):
            for b in node.bases:
                if (
                    b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
                ) == "Thread":
                    out.append(f"{node.name}(Thread)")
    return out


def test_catalog_queries_code_starts_no_threads():
    """查询内部实现里不自己起线程、线程池（预热线程由 bootstrap 起，Q1）：怎么导入的都算，函数里起的也算。
    Q2、Q3 搬进来的并发下载要用线程池的话，按文件、按函数写明放行和理由，不整目录放开"""
    files = sorted((_ROOT / "tasks" / "catalog_queries").rglob("*.py"))
    assert len(files) >= 2, files
    for path in files:
        assert _thread_makers_in_source(path.read_text(encoding="utf-8")) == [], (
            path.name
        )
    for bad in (
        "import threading\nthreading.Thread(target=f).start()\n",
        "from threading import Thread\ndef f():\n    Thread(target=g).start()\n",
        "__import__('threading').Timer(1, f).start()\n",
        "from concurrent.futures import ThreadPoolExecutor\nThreadPoolExecutor(4)\n",
        "import _thread\n_thread.start_new_thread(f, ())\n",
        "import asyncio\nasync def f():\n    await asyncio.to_thread(g)\n",
        "from multiprocessing import Pool\nPool(2)\n",
        "import threading\nclass W(threading.Thread):\n    pass\n",
    ):
        assert _thread_makers_in_source(bad), bad
    assert (
        _thread_makers_in_source("import threading\n_lock = threading.Lock()\n") == []
    )


def _reaches_up_into_tasks(source, pkg):
    """一个文件往上碰 tasks 的地方 → (导入到的 tasks 模块, 绕法)。导入：函数里的也算；绕法：字符串导入
    （__import__ / import_module）本项目的模块（往上往下都算）、裸 import astral_toolkit 再走属性（等于绕开清单，Q3b 审查补的；
    不带 as 的 import astral_toolkit.x 绑的也是整个包，一样算，和适配层门禁的认法相同——产品代码一律写相对导入）"""
    up = {
        m
        for m in _imports_in_source(source, pkg)
        if m == "astral_toolkit.tasks" or m.startswith("astral_toolkit.tasks.")
    }
    sneaky = [
        t
        for t in _dynamic_import_targets(source)
        if t.startswith((".", "astral_toolkit"))
    ]
    sneaky += [m for m in _bound_modules(source, pkg) if m == "astral_toolkit"]
    return up, sneaky


def test_crafting_reaches_up_into_tasks_only_where_listed():
    """crafting 在 tasks 下层，不该反过来导入 tasks（目录迁移章程：兼容只许有明确调用者和删除批次），只许减不许加：
    acquire 往上调物品搜索（Q1）、商店查询（Q2）、掉落查询（Q3a）那三条临时边，Q3b 把 acquire 搬进 catalog_queries 时删了；
    goals → tasks.trade 是老的，目标业务这轮不动。字符串导入（__import__ / import_module）本项目的模块、
    裸 import astral_toolkit 再走属性一律算（见 _reaches_up_into_tasks），免得绕过这条。"""
    allowed = {
        "goals.py": {"astral_toolkit.tasks.trade", "astral_toolkit.tasks.trade.trade"},
    }
    seen, sneaky = {}, []
    for path in sorted((_ROOT / "crafting").rglob("*.py")):
        rel = path.relative_to(_ROOT / "crafting").as_posix()
        pkg = ".".join(("astral_toolkit", *path.relative_to(_ROOT).parent.parts))
        up, how = _reaches_up_into_tasks(path.read_text(encoding="utf-8"), pkg)
        if up:
            seen[rel] = up
        sneaky += [f"{rel}: {t}" for t in how]
    assert seen == allowed, seen
    assert sneaky == [], sneaky


def test_trade_reaches_up_into_tasks_only_where_listed():
    """trade 在 tasks 下层，不该反过来导入 tasks，只许减不许加：console.material_source 转给
    tasks/catalog_queries/acquire 是目录迁移 Q3b 搬走获取途径以后留的转发（目标链 crafting/goals 还在用；
    老大 11-07 定留着转发、钉住这一条），目标改用新实现时删。字符串导入本项目的模块、裸 import astral_toolkit 一律算"""
    allowed = {
        "console.py": {
            "astral_toolkit.tasks.catalog_queries.acquire",
            "astral_toolkit.tasks.catalog_queries.acquire.material_source",
        },
    }
    seen, sneaky = {}, []
    files = sorted((_ROOT / "trade").rglob("*.py"))
    assert files
    for path in files:
        rel = path.relative_to(_ROOT / "trade").as_posix()
        pkg = ".".join(("astral_toolkit", *path.relative_to(_ROOT).parent.parts))
        up, how = _reaches_up_into_tasks(path.read_text(encoding="utf-8"), pkg)
        if up:
            seen[rel] = up
        sneaky += [f"{rel}: {t}" for t in how]
    assert seen == allowed, seen
    assert sneaky == [], sneaky
    for bad in (  # 检查本身认得出这几种往上碰 tasks 的写法
        "def f():\n    from ..tasks import catalog\n",
        "from .. import tasks\n",
        "import astral_toolkit.tasks.catalog\n",
        "import astral_toolkit\n\n\ndef f():\n    return astral_toolkit.tasks.catalog.get_item_info()\n",
        "import importlib\n\n\ndef f():\n    return importlib.import_module('astral_toolkit.tasks.catalog')\n",
    ):
        up, how = _reaches_up_into_tasks(bad, "astral_toolkit.trade")
        assert up or how, bad
    ok = "from .. import gamedata\nfrom ..core import paths\n"
    assert _reaches_up_into_tasks(ok, "astral_toolkit.trade") == (set(), [])


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


# ---------------------------------------------------------------- CR-B4：制造 / 维科洛的用例、排版、接口
_CRAFTING_PRESENTER_MODULES = {
    "astral_toolkit.app.presenters.crafting",
    "astral_toolkit.app.presenters.wikelo",
}


def _crafting_presenter_bad_imports(source):
    """制造 / 维科洛排版不许的 import：照物品查询排版那张表，crafting 下只放行纯规则文件。"""
    pkg = "astral_toolkit.app.presenters"
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = _textkeys_resolve_from(node, pkg)
            for alias in node.names:
                full = f"{module}.{alias.name}"
                if module in _CRAFTING_RULE_MODULES or full in _CRAFTING_RULE_MODULES:
                    continue
                if _forbidden([module, full], _CATALOG_PRESENTER_FORBIDDEN):
                    bad.append(f"{module}: {alias.name}")
        elif isinstance(node, ast.Import):
            bad += [
                a.name
                for a in node.names
                if _forbidden([a.name], _CATALOG_PRESENTER_FORBIDDEN)
            ]
    return bad + _dynamic_imports(source)


def test_crafting_presenters_only_format():
    """制造 / 维科洛排版（CR-B4）只排版：不取数据，不碰任务 / 运行环境 / 设置；crafting 下只许拿纯规则文件。"""
    for name in ("crafting", "wikelo"):
        source = (_ROOT / "app" / "presenters" / f"{name}.py").read_text(
            encoding="utf-8"
        )
        assert _crafting_presenter_bad_imports(source) == [], name
    assert (
        _crafting_presenter_bad_imports(
            "from ...crafting.labels import GEAR_ZH\nfrom ...crafting import quality, wikelo_rules\n"
        )
        == []
    )
    for bad in (
        "from ...crafting import crafting\n",
        "from ...crafting.wikelo import load\n",
        "from ...tasks import crafting\n",
        "from ...gamedata import crafting\n",
        "from ...mining.locations import where\n",
        "from ...trade.console import material_source\n",
        "def f():\n    from ...runtime.session import Tick\n",
        "import threading\n",
    ):
        assert _crafting_presenter_bad_imports(bad), bad


def test_crafting_use_cases_stay_below_app():
    """制造 / 维科洛用例（CR-B4）不反向拿 app / runtime / bootstrap，也不动态导入。"""
    for name in ("crafting", "wikelo"):
        source = (_ROOT / "tasks" / f"{name}.py").read_text(encoding="utf-8")
        assert _catalog_use_case_violations(source) == [], name


def _crafting_presenter_imports(source, pkg):
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            module = _textkeys_resolve_from(node, pkg)
            for alias in node.names:
                hits += [
                    m
                    for m in (module, f"{module}.{alias.name}")
                    if m in _CRAFTING_PRESENTER_MODULES
                ]
        elif isinstance(node, ast.Import):
            hits += [
                a.name for a in node.names if a.name in _CRAFTING_PRESENTER_MODULES
            ]
    return hits


def test_only_goals_shell_imports_crafting_presenters():
    """CR-B4 过渡：tasks 里只有 tasks/goals.py 旧壳能 import 制造 / 维科洛排版；B5、B6 删壳后收紧成一个都不许。"""
    pkg = "astral_toolkit.tasks"
    assert _crafting_presenter_imports(
        "from ..app.presenters import crafting as p", pkg
    )
    assert _crafting_presenter_imports(
        "from ..app.presenters.wikelo import present_search", pkg
    )
    assert (
        _crafting_presenter_imports("from ..app.presenters import catalog", pkg) == []
    )
    bad = []
    for path in (_ROOT / "tasks").rglob("*.py"):
        sub = ".".join(("astral_toolkit", *path.relative_to(_ROOT).parent.parts))
        if _crafting_presenter_imports(path.read_text(encoding="utf-8"), sub):
            rel = path.relative_to(_ROOT).as_posix()
            if rel != "tasks/goals.py":
                bad.append(rel)
    assert bad == [], bad


def test_api_route_names_unique():
    """接口名在 app/api 各模块之间不许重复：router 按模块名合表，后加载的会悄悄盖掉前面的（CR-B4 起制造 / 维科洛接口单独成文件）。"""
    import importlib
    import pkgutil

    from astral_toolkit.app import api

    seen, dup = {}, []
    for m in sorted(pkgutil.iter_modules(api.__path__), key=lambda m: m.name):
        if m.name in ("router", "__init__"):
            continue
        mod = importlib.import_module(f"{api.__name__}.{m.name}")
        for name in getattr(mod, "ROUTES", None) or {}:
            if name in seen:
                dup.append(f"{name}: {seen[name]} / {m.name}")
            seen[name] = m.name
    assert dup == [], dup
    assert (
        seen.get("craft_detail") == "crafting" and seen.get("wikelo_detail") == "wikelo"
    )


_F8_FORBIDDEN_IMPORTS = (
    "astral_toolkit.tasks.trade",
    "astral_toolkit.crafting.loot",
    "astral_toolkit.tasks.catalog_queries.loot",
    "astral_toolkit.crafting.crafting",
    "astral_toolkit.crafting.wikelo",
    "astral_toolkit.trade.console.match_tooltip",
    "astral_toolkit.trade.console.hud_market",
    "astral_toolkit.trade.matching.match_tooltip",
    "astral_toolkit.trade.market_text.hud_market",
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
        "def f():\n    from .catalog_queries.loot import info\n",
        "def f():\n    from ..crafting import wikelo\n",
        "def f():\n    from ..crafting.crafting import craft_text\n",
        "def f():\n    from ..trade.console import hud_market\n",
        "from ..trade.console import match_tooltip",
        "from ..trade.matching import match_tooltip",
        "def f():\n    from ..trade.market_text import hud_market\n",
        "t = trade()",
        "C.match_tooltip(t, zh, en)",
        't.catalog.add_alias(1, "甲")',
        '_market_rows(1, "q6")',
    ):
        assert _f8_link_violations(bad), bad
    ok = "m = links.market()\nm.match(zh, en)\nm.remember_alias(1, zh)\nlinks.hud_market([])\n"
    assert _f8_link_violations(ok) == []
    assert (
        _f8_link_violations("def f():\n    from ..crafting.reverse import craft_text\n")
        == []
    )


_B5_OLD_CRAFT_NAMES = (
    "GEAR_ZH",
    "SUB_ZH",
    "PROP_KEY",
    "LOWER_BETTER",
    "prop_zh",
    "slot_zh",
    "category_zh",
    "part_of",
    "needs",
    "group_mods",
    "curve_value",
    "curve_text",
    "laser_total",
    "mix_plan",
    "parse_mods",
    "craft_text",
    "_clean_title",
)

_B5_OLD_WIKELO_NAMES = ("note_for", "req_label", "describe", "_same")

_B5_FILES = (
    ("mining/laser.py", "astral_toolkit.mining"),
    ("mining/locations.py", "astral_toolkit.mining"),
    ("tasks/hover.py", "astral_toolkit.tasks"),
    ("tasks/mining.py", "astral_toolkit.tasks"),
    ("tasks/trade.py", "astral_toolkit.tasks"),
    ("tasks/crafting.py", "astral_toolkit.tasks"),
    ("tasks/wikelo.py", "astral_toolkit.tasks"),
)


def _b5_violations(source, pkg):
    """经 crafting.crafting / crafting.wikelo 旧名字的地方（函数里的 import、wikelo.<旧名字> 属性也算）"""
    bad = {f"astral_toolkit.crafting.crafting.{n}" for n in _B5_OLD_CRAFT_NAMES}
    bad |= {f"astral_toolkit.crafting.wikelo.{n}" for n in _B5_OLD_WIKELO_NAMES}
    out = [m for m in _imports_in_source(source, pkg) if m in bad]
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "wikelo"
            and node.attr in _B5_OLD_WIKELO_NAMES
        ):
            out.append(f"wikelo.{node.attr}")
    return out


def test_b5_callers_use_new_homes():
    """CR-B5：采矿、物品查询、F8 首屏和两个用例不再经 crafting.crafting / crafting.wikelo 的旧名字拿纯规则。"""
    for name, pkg in _B5_FILES:
        path = _ROOT / name
        source = path.read_text(encoding="utf-8")
        assert _b5_violations(source, pkg) == [], name
    for bad in (
        "def f():\n    from ..crafting.crafting import GEAR_ZH\n",
        "def f():\n    from ..crafting.wikelo import note_for\n",
        "wikelo.note_for(x)",
        "wikelo._same(a, b)",
    ):
        assert _b5_violations(bad, "astral_toolkit.tasks"), bad


_B6_RULE_ROOTS = {
    "_labels",
    "_quality",
    "_reverse",
    "_classify",
    "_materials",
    "_mix",
    "_listing",
    "_rules",
}
_B6_CRAFTING = "astral_toolkit.crafting.crafting"
_B6_WIKELO = "astral_toolkit.crafting.wikelo"
_B6_OLD_ALIASES = {
    f"{_B6_CRAFTING}.slot_zh": {"crafting/goals.py", "tasks/goals.py"},
    f"{_B6_CRAFTING}.laser_total": {"tasks/goals.py"},
    f"{_B6_CRAFTING}.parse_mods": {"trade/inspector.py"},
    f"{_B6_CRAFTING}.craft_text": {"tasks/stock.py"},
}
_B6_DELETED = {
    f"{_B6_CRAFTING}.{name}"
    for name in (
        "GEAR_ZH",
        "SUB_ZH",
        "PROP_KEY",
        "LOWER_BETTER",
        "prop_zh",
        "category_zh",
        "part_of",
        "needs",
        "group_mods",
        "curve_value",
        "curve_text",
        "mix_plan",
        "_clean_title",
        "_fold_name",
        "_search_norm",
    )
} | {
    f"{_B6_WIKELO}.{name}"
    for name in (
        "describe",
        "note_for",
        "req_label",
        "_same",
    )
}
# crafting/__init__.py 有 from .crafting import *：经包拿（astral_toolkit.crafting.名字）也算
# 这三个模块谁都不许 import *（crafting/__init__.py 自己那一句除外）
_B6_STAR_FORBIDDEN = {_B6_CRAFTING, _B6_WIKELO, "astral_toolkit.crafting"}
_B6_PKG = "astral_toolkit.crafting"
_B6_OLD_ALIASES.update(
    {
        k.replace(_B6_CRAFTING, _B6_PKG): v
        for k, v in list(_B6_OLD_ALIASES.items())
        if k.startswith(_B6_CRAFTING + ".")
    }
)
_B6_DELETED |= {
    k.replace(_B6_CRAFTING, _B6_PKG)
    for k in _B6_DELETED
    if k.startswith(_B6_CRAFTING + ".")
}


def _b6_import_from_module(node, pkg):
    if node.level:
        base = pkg.split(".")
        base = base[: len(base) - node.level + 1]
        return ".".join(base + ([node.module] if node.module else []))
    return node.module or ""


def _b6_rule_aliases(path):
    out = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id in _B6_RULE_ROOTS
        ):
            out.add(target.id)
    return out


def _b6_attr_name(node, bindings):
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    root = bindings.get(cur.id, cur.id)
    if root != "astral_toolkit" and not root.startswith("astral_toolkit."):
        return None
    parts.append(root)
    return ".".join(reversed(parts))


def _b6_scope_refs(nodes, pkg, targets, outer, refs, stars=False):
    """一层作用域（模块 / 函数 / 类）：先收这一层自己的 import（不进里层的函数、类），再查这一层的「模块.名字」；
    里层各算一层、看得见外层的绑定。不同函数里同一个名字绑到不同模块时不会串"""
    bindings = dict(outer)
    own, inner, todo = [], [], list(nodes)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner.append(node)
            continue
        own.append(node)
        todo.extend(ast.iter_child_nodes(node))
    for node in own:
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    bindings[a.asname] = a.name
                else:
                    root = a.name.split(".")[0]
                    bindings[root] = root
        elif isinstance(node, ast.ImportFrom):
            mod = _b6_import_from_module(node, pkg)
            for a in node.names:
                if a.name == "*":
                    # 名字全带进来就查不清谁用了旧名字：stars=True 那一圈专门查
                    if stars and mod in _B6_STAR_FORBIDDEN:
                        refs.add(f"{mod}.*")
                    continue
                full = f"{mod}.{a.name}" if mod else a.name
                if full in targets:
                    refs.add(full)
                local = a.asname or a.name
                if full == "astral_toolkit.crafting" or full.startswith(
                    "astral_toolkit.crafting."
                ):
                    bindings[local] = full
                else:
                    bindings.pop(local, None)  # 这一层把这个名字绑到了别处
    for node in own:
        if isinstance(node, ast.Attribute):
            full = _b6_attr_name(node, bindings)
            if full in targets:
                refs.add(full)
        elif (  # getattr(模块, "名字") 也算
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            obj = node.args[0]
            base = (
                _b6_attr_name(obj, bindings)
                if isinstance(obj, ast.Attribute)
                else bindings.get(obj.id)
                if isinstance(obj, ast.Name)
                else None
            )
            if base and f"{base}.{node.args[1].value}" in targets:
                refs.add(f"{base}.{node.args[1].value}")
    for node in inner:
        _b6_scope_refs(node.body, pkg, targets, bindings, refs, stars)


def _b6_old_refs(source, pkg, targets, stars=False):
    refs = set()
    _b6_scope_refs(ast.parse(source).body, pkg, targets, {}, refs, stars)
    return refs


def _b6_pkg(path, root):
    return ".".join([root.name, *path.relative_to(root).parts[:-1]])


def test_crafting_old_names_whitelist():
    """CR-B6：旧名字只剩白名单，删掉的谁都不许再拿。"""
    assert _b6_rule_aliases(_ROOT / "crafting/crafting.py") == {
        "slot_zh",
        "laser_total",
        "parse_mods",
        "craft_text",
    }
    assert _b6_rule_aliases(_ROOT / "crafting/wikelo.py") == set()

    allowed = _B6_OLD_ALIASES
    for path in _ROOT.rglob("*.py"):
        rel = path.relative_to(_ROOT).as_posix()
        if rel in ("crafting/crafting.py", "crafting/wikelo.py"):
            continue
        refs = _b6_old_refs(
            path.read_text(encoding="utf-8"), _b6_pkg(path, _ROOT), set(allowed)
        )
        for ref in refs:
            assert rel in allowed[ref], (rel, ref)

    for root in (_ROOT, _ROOT.parent / "tests", _ROOT.parent / "tools"):
        for path in root.rglob("*.py"):
            refs = _b6_old_refs(
                path.read_text(encoding="utf-8"), _b6_pkg(path, root), _B6_DELETED
            )
            assert not refs, (path, refs)

    for root in (_ROOT, _ROOT.parent / "tests", _ROOT.parent / "tools"):
        for path in root.rglob("*.py"):
            if path == _ROOT / "crafting" / "__init__.py":
                continue
            stars = _b6_old_refs(
                path.read_text(encoding="utf-8"), _b6_pkg(path, root), set(), stars=True
            )
            assert not stars, (path, stars)  # 只剩 import * 那种（targets 是空的）

    all_targets = set(allowed) | _B6_DELETED
    for bad, want in (
        (
            "from astral_toolkit.crafting.crafting import slot_zh\n",
            f"{_B6_CRAFTING}.slot_zh",
        ),
        (
            "from astral_toolkit.crafting import wikelo as w\nw.describe(x)\n",
            f"{_B6_WIKELO}.describe",
        ),
        (
            "import astral_toolkit.crafting as c\nc.wikelo.describe(x)\n",
            f"{_B6_WIKELO}.describe",
        ),
        (
            "from astral_toolkit.crafting.wikelo import note_for\n",
            f"{_B6_WIKELO}.note_for",
        ),
        (
            "from astral_toolkit import crafting as c\nc.mix_plan(1, 2, [])\n",
            f"{_B6_PKG}.mix_plan",
        ),
        (
            "from astral_toolkit.crafting import GEAR_ZH\n",
            f"{_B6_PKG}.GEAR_ZH",
        ),
    ):
        assert _b6_old_refs(bad, "astral_toolkit.tasks", all_targets) == {want}, bad
    assert _b6_old_refs(
        "from astral_toolkit.crafting import *\n",
        "astral_toolkit.tasks",
        set(),
        stars=True,
    ) == {"astral_toolkit.crafting.*"}
    assert _b6_old_refs(
        "from astral_toolkit.crafting import crafting as C\ngetattr(C, 'GEAR_ZH')\n",
        "astral_toolkit.tasks",
        all_targets,
    ) == {f"{_B6_CRAFTING}.GEAR_ZH"}
    # 两个函数里同一个名字 c 绑到不同模块：各认各的，不串
    two_scopes = (
        "def f():\n    from astral_toolkit.crafting import mix as c\n    return c.mix_plan\n\n"
        "def g():\n    from astral_toolkit import crafting as c\n    return c.by_key\n"
    )
    assert _b6_old_refs(two_scopes, "astral_toolkit.tasks", all_targets) == set()


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


_FS_B1_CONSOLE = "astral_toolkit.trade.console"
_FS_B1_OLD_ALIASES = {
    f"{_FS_B1_CONSOLE}._cursor_on_image": {"astral_toolkit/app/engines/count.py"},
    f"{_FS_B1_CONSOLE}.SOURCE_ZH": {"astral_toolkit/tasks/goals.py"},
    f"{_FS_B1_CONSOLE}.material_source": {"astral_toolkit/crafting/goals.py"},
}
_FS_B1_DELETED = {
    f"{_FS_B1_CONSOLE}.{name}"
    for name in (
        "STATE_ZH",
        "hud_market",
        "_money",
        "_group",
        "_fold",
        "_similar",
        "match_tooltip",
        "_match_names",
        "VK",
        "loot_source",
        "_hover_log",
        "tooltip_pick",
        "tooltip_name",
        "plausible_name",
    )
}


def _fs_b1_scope_refs(nodes, pkg, targets, outer, refs):
    """一层作用域里从 trade.console 拿名字的地方：直接 import 的、以及先拿 console 模块再取属性的。"""
    bindings = dict(outer)
    own, inner, todo = [], [], list(nodes)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            inner.append(node)
            continue
        own.append(node)
        todo.extend(ast.iter_child_nodes(node))
    for node in own:
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    bindings[a.asname] = a.name
                else:
                    root = a.name.split(".")[0]
                    bindings[root] = root
        elif isinstance(node, ast.ImportFrom):
            mod = _b6_import_from_module(node, pkg)
            for a in node.names:
                if a.name == "*":
                    continue
                full = f"{mod}.{a.name}" if mod else a.name
                if full in targets:
                    refs.add(full)
                local = a.asname or a.name
                if full == "astral_toolkit" or full.startswith("astral_toolkit."):
                    bindings[local] = full
                else:
                    bindings.pop(local, None)
    for node in own:
        if isinstance(node, ast.Attribute):
            full = _b6_attr_name(node, bindings)
            if full in targets:
                refs.add(full)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            obj = node.args[0]
            base = (
                _b6_attr_name(obj, bindings)
                if isinstance(obj, ast.Attribute)
                else bindings.get(obj.id)
                if isinstance(obj, ast.Name)
                else None
            )
            if base and f"{base}.{node.args[1].value}" in targets:
                refs.add(f"{base}.{node.args[1].value}")
    for node in inner:
        _fs_b1_scope_refs(node.body, pkg, targets, bindings, refs)


def _fs_b1_console_refs(source, pkg, targets):
    refs = set()
    _fs_b1_scope_refs(ast.parse(source).body, pkg, targets, {}, refs)
    return refs


def test_fs_b1_console_old_names():
    """FS-B1：旧总入口只剩库存那半边；搬走的名字不许再从 trade.console 拿。"""
    all_targets = set(_FS_B1_OLD_ALIASES) | _FS_B1_DELETED
    project = _ROOT.parent
    for root in (_ROOT, project / "tools"):
        for path in root.rglob("*.py"):
            rel = path.relative_to(project).as_posix()
            refs = _fs_b1_console_refs(
                path.read_text(encoding="utf-8"), _b6_pkg(path, root), all_targets
            )
            for ref in refs:
                assert rel in _FS_B1_OLD_ALIASES.get(ref, set()), (rel, ref)

    for bad, want in (
        (
            "from astral_toolkit.trade.console import _hover_log\n",
            f"{_FS_B1_CONSOLE}._hover_log",
        ),
        (
            "from astral_toolkit.trade import console as C\nC.hud_market([])\n",
            f"{_FS_B1_CONSOLE}.hud_market",
        ),
        (
            "def f():\n    from ..trade.console import match_tooltip\n",
            f"{_FS_B1_CONSOLE}.match_tooltip",
        ),
        (
            "from astral_toolkit.trade import console as C\nC._cursor_on_image(x)\n",
            f"{_FS_B1_CONSOLE}._cursor_on_image",
        ),
        (
            "from astral_toolkit.trade.console import material_source\n",
            f"{_FS_B1_CONSOLE}.material_source",
        ),
    ):
        assert _fs_b1_console_refs(bad, "astral_toolkit.tasks", all_targets) == {
            want
        }, bad


def test_fs_b2_market_users_do_not_hold_trade():
    """FS-B2：市场接口、物品查询、F8 只经 tasks/trade.market()（trade/market.Market）拿目录、显示名、查价，碰不到库存"""
    from astral_toolkit.trade.market import Market

    assert not {"inventory", "db", "history", "market"} & set(vars(Market))
    src = (_ROOT / "tasks" / "catalog.py").read_text(encoding="utf-8")
    for bad in ("trade_tasks.trade(", ".inventory", ".db"):
        assert bad not in src, bad
    tree = ast.parse((_ROOT / "tasks" / "trade.py").read_text(encoding="utf-8"))
    names = ("market_lookup", "market_prices", "_market_rows", "market_label")
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(fns) == len(names)
    for fn in fns:
        calls = {
            n.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "trade" not in calls, fn.name


_FS_B4_MOVED = {
    "update_preview",
    "get_preview_bytes",
    "install_router",
    "current_task",
    "adopt_task",
    "run_task",
    "run_task_once",
    "task_running",
    "_running",
}
_FS_B4_BUS_NAMES = _FS_B4_MOVED | {
    "_preview_thumb_bytes",
    "_preview_full_bytes",
    "_preview_meta",
    "_last_preview_t",
    "_preview_lock",
    "_task",
    "_router_guard",
    "_Router",
    "_run_lock",
    "_run_seq",
    "_run_seq_lock",
    "_next_run_id",
}


def _fs_b4_bus_refs(source):
    refs = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _FS_B4_MOVED
            and isinstance(node.value, ast.Name)
            and node.value.id == "bus"
        ):
            refs.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "bus"
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in _FS_B4_MOVED
        ):
            refs.add(node.args[1].value)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            m = re.fullmatch(r"(?:\w+\.)*bus\.(\w+)", node.value.strip())
            if m and m.group(1) in _FS_B4_MOVED:
                refs.add(m.group(1))
    return refs


def _fs_b4_direct_bus_imports(source, names=("publish", "runtime_log")):
    """from (.|..app.|astral_toolkit.app.)bus import 名字：names 里的那些"""
    refs = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        mod = node.module or ""
        if not (mod == "bus" and node.level == 1 or mod.endswith("app.bus")):
            continue
        for alias in node.names:
            if alias.name in names:
                refs.add(alias.name)
    return refs


def test_fs_b4_bus_split():
    """FS-B4：截图预览、后台任务从 bus 拆出；调用方按新模块取，不准再走 bus。"""
    tree = ast.parse((_ROOT / "app" / "bus.py").read_text(encoding="utf-8"))
    defined = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):  # 转出来的也算
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
    assert not (defined & _FS_B4_BUS_NAMES)
    assert {"publish", "runtime_log"} <= defined

    project = _ROOT.parent
    bad = []
    for root in (_ROOT, project / "tools"):
        for path in root.rglob("*.py"):
            rel = path.relative_to(project).as_posix()
            source = path.read_text(encoding="utf-8")
            for name in _fs_b4_bus_refs(source):
                bad.append((rel, name))
            for name in _fs_b4_direct_bus_imports(source, _FS_B4_BUS_NAMES):
                bad.append((rel, name))
    assert not bad, bad

    for name in ("preview.py", "task_runner.py"):
        path = _ROOT / "app" / name
        assert not _fs_b4_direct_bus_imports(path.read_text(encoding="utf-8")), name

    assert _fs_b4_bus_refs("from . import bus\nbus.run_task('x', f)\n") == {"run_task"}
    assert _fs_b4_bus_refs("from . import bus\ngetattr(bus, 'update_preview')\n") == {
        "update_preview"
    }
    assert _fs_b4_bus_refs('"astral_toolkit.app.bus.install_router"') == {
        "install_router"
    }
    assert _fs_b4_direct_bus_imports("from .bus import runtime_log\n") == {
        "runtime_log"
    }
    assert _fs_b4_direct_bus_imports(
        "from ...app.bus import run_task, publish\n", _FS_B4_BUS_NAMES
    ) == {"run_task"}
    assert not _fs_b4_bus_refs('"""见 bus.run_task 拆出去的说明"""')


_FS_B5_GONE = {
    "mining.py": {"_live", "_UNBOUND", "bind", "_need_live"},
    "hover.py": {"_links", "_UNBOUND", "bind", "_need_links"},
    "system/common.py": {
        "_status",
        "_start",
        "_UNBOUND",
        "bind",
        "_need_status",
        "_need_start",
    },
    "navigation.py": {
        "_nav",
        "_pos",
        "_game_events",
        "_results",
        "_UNBOUND",
        "bind",
        "_need_nav",
        "_need_pos",
        "_need_events",
        "_need_results",
    },
}
_FS_B5_FIRST_ARG = {
    "mining.py": {
        "live_start": "live*",
        "live_stop": "live*",
        "set_mining_gear": "live*",
        "set_mining_gadgets": "live*",
    },
    "hover.py": {
        "hover_once": "links*",
        "item_info": "links*",
        "_hover_lines": "links",
        "_hover_more": "links",
    },
    "system/status.py": {"status": "sources*"},
    "system/feedback.py": {"feedback_report": "sources*"},
    "system/settings.py": {"set_settings": "sources*"},
    "system/about.py": {"agree": "sources*"},
    "navigation.py": {
        "nav_near": "deps*",
        "nav_site": "deps*",
        "nav_start": "deps*",
        "nav_mode": "deps*",
        "nav_stop": "deps*",
        "nav_refresh": "deps*",
        "waypoint_add": "deps*",
        "waypoint_preview": "deps*",
        "waypoint_from_text": "deps*",
        "mark_here": "deps*",
        "ore_record": "deps*",
        "ore_go": "deps*",
        "halo_pin": "deps*",
        "fix_here": "deps*",
        "_start_nav": "deps",
        "_pos_current": "deps",
        "_pos_latest": "deps",
        "_where_now": "deps",
        "_area_now": "deps",
        "_hints_near": "deps",
        "_save_here": "deps",
        "_start_here_watch": "deps",
        "_coord_desc": "deps",
        "_halo_watch": "deps",
    },
    "trade.py": {"nav_shop": "deps*"},
}
_FS_B5_BOUND = {
    "mining.py": {
        "live_start",
        "live_stop",
        "set_mining_gear",
        "set_mining_gadgets",
    },
    "vision.py": {"hover_trigger"},
    "system.py": {"status", "feedback_report", "set_settings", "agree"},
    "navigation.py": {
        "nav_near",
        "nav_site",
        "nav_start",
        "nav_mode",
        "nav_stop",
        "nav_refresh",
        "waypoint_add",
        "waypoint_preview",
        "waypoint_from_text",
        "ore_record",
        "ore_go",
        "halo_pin",
    },
    "trade.py": {"nav_shop"},
}


def _fs_b5_defined_names(source):
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _fs_b5_globals(source):
    return {
        name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Global)
        for name in node.names
    }


def _fs_b5_first_arg_bad(source, expected):
    """按 {函数名: 第一个参数} 查；带 * 的还必须在 posonlyargs 里。返回不合的函数名。"""
    funcs = {
        node.name: node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef)
    }
    bad = set()
    for name, want in expected.items():
        node = funcs.get(name)
        if node is None:
            bad.add(name)
            continue
        posonly = [a.arg for a in node.args.posonlyargs]
        first = (
            (posonly + [a.arg for a in node.args.args])[0]
            if (posonly or node.args.args)
            else None
        )
        if want.endswith("*"):
            if want[:-1] not in posonly:
                bad.add(name)
        elif first != want:
            bad.add(name)
    return bad


def _fs_b5_bind_all_refs(source, mods=("mining", "hover", "system")):
    tree = ast.parse(source)
    fn = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "bind_all"
        ),
        None,
    )
    if fn is None:
        return set()

    mods = set(mods)

    def task_imports(node):
        got = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom):
                for alias in sub.names:
                    if alias.name in mods:
                        got.add(alias.asname or alias.name)
            elif isinstance(sub, ast.Import):
                for alias in sub.names:
                    if any(alias.name.endswith(f"tasks.{mod}") for mod in mods):
                        got.add(alias.asname or alias.name.rsplit(".", 1)[-1])
        return got

    known = task_imports(tree) | {
        name for mod in mods for name in (mod, f"{mod}_tasks")
    }
    bad = set(task_imports(fn))
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "bind"
            and isinstance(node.func.value, ast.Name)
        ):
            name = node.func.value.id
            if name in known:
                bad.add(name)
    return bad


def _fs_b5_route_names(source):
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ROUTES" for t in node.targets
        ):
            if isinstance(node.value, ast.Dict):
                return {
                    key.value
                    for key in node.value.keys
                    if isinstance(key, ast.Constant)
                }
    return set()


def test_fs_b5_tasks_without_module_binding():
    """FS-B5：采矿、F8、系统、导航的 tasks 没有模块级绑定；接口表里要后台对象的接口（含物品查询的商店导航）由 bound 给。"""
    for name, gone in _FS_B5_GONE.items():
        source = (_ROOT / "tasks" / name).read_text(encoding="utf-8")
        assert not (_fs_b5_defined_names(source) & gone), name
        assert not _fs_b5_globals(source), name

    settings_source = (_ROOT / "tasks" / "system" / "settings.py").read_text(
        encoding="utf-8"
    )
    assert "start_background" not in settings_source

    for name, expected in _FS_B5_FIRST_ARG.items():
        source = (_ROOT / "tasks" / name).read_text(encoding="utf-8")
        assert not _fs_b5_first_arg_bad(source, expected), name

    bootstrap_source = (_ROOT / "bootstrap.py").read_text(encoding="utf-8")
    assert not _fs_b5_bind_all_refs(
        bootstrap_source, ("mining", "hover", "system", "navigation")
    )
    bind_fn = next(
        node
        for node in ast.parse(bootstrap_source).body
        if isinstance(node, ast.FunctionDef) and node.name == "bind_all"
    )
    assert {
        node.func.value.id
        for node in ast.walk(bind_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "bind"
        and isinstance(node.func.value, ast.Name)
    } == {"count_tasks"}

    for name, names in _FS_B5_BOUND.items():
        api_source = (_ROOT / "app" / "api" / name).read_text(encoding="utf-8")
        assert "bound" in _fs_b5_defined_names(api_source), name
        assert not _fs_b5_route_names(api_source) & names, name

    # 反例：旧写法查得出来
    assert "_live" in _fs_b5_defined_names("_live = None\n")
    old_bind = "def bind(x):\n    global _live\n    _live = x\n"
    assert "bind" in _fs_b5_defined_names(old_bind)
    assert _fs_b5_globals(old_bind) == {"_live"}
    assert _fs_b5_first_arg_bad(
        "def hover_once(links, img=None):\n    pass\n", {"hover_once": "links*"}
    ) == {"hover_once"}
    assert _fs_b5_bind_all_refs(
        "def bind_all(app):\n    mining_tasks.bind(app.live)\n"
    ) == {"mining_tasks"}
    assert _fs_b5_bind_all_refs(
        "def bind_all(app):\n    from .tasks import mining as mining_tasks\n"
    ) == {"mining_tasks"}
    assert _fs_b5_bind_all_refs(
        "def bind_all(app):\n    hover_tasks.bind(x)\n", ("hover",)
    ) == {"hover_tasks"}
    assert _fs_b5_bind_all_refs(
        "def bind_all(app):\n    from .tasks import hover as hover_tasks\n", ("hover",)
    ) == {"hover_tasks"}
