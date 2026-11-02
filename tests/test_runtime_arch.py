"""运行结构的依赖检查（架构稿 §4.3、§11.3，RT-B1）：领域计算不碰运行环境，呈现层不取数据"""

import subprocess
import sys
from pathlib import Path

from tests.test_gamedata_arch import _imports_in

_ROOT = Path(__file__).resolve().parent.parent / "sc_mining"


def _bad_imports(path, forbidden):
    return [m for m in _imports_in(path) if m.startswith(forbidden) or m in forbidden]


def test_analysis_imports():
    bad = _bad_imports(
        _ROOT / "mining" / "analysis.py",
        (
            "sc_mining.app",
            "sc_mining.tasks",
            "sc_mining.gamedata",
            "sc_mining.core.settings",
            "threading",
            "time",
        ),
    )
    assert bad == [], bad


def test_presenter_imports():
    bad = _bad_imports(
        _ROOT / "app" / "presenters" / "mining.py",
        ("sc_mining.gamedata", "sc_mining.mining.laser", "sc_mining.crafting"),
    )
    assert bad == [], bad


def test_analysis_import_is_clean_transitively():
    """新进程只导入 analysis：不能间接带进数据层、设置和任务实现"""
    code = (
        "import sys, sc_mining.mining.analysis;"
        "print([m for m in sys.modules if m.startswith(('sc_mining.gamedata',"
        "'sc_mining.core.settings','sc_mining.tasks','sc_mining.app'))])"
    )
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=_ROOT.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0 and r.stdout.strip() == "[]", r.stdout + r.stderr
