"""测试一律不往服务器发反馈：只要 import 了 tests 包（或用 minipytest 跑），AT_FEEDBACK_OFF 就必须是开的

2026-11-01 服务器收件箱里出现过一条 1.1.3-beta.1、64×32 截图的假反馈——有人没经 run_all 跑测试。以前只有 run_all 设这个变量。"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _child(code):
    env = {k: v for k, v in os.environ.items() if k != "AT_FEEDBACK_OFF"}
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_importing_tests_package_forces_feedback_off():
    out = _child("import os, tests; print(os.environ.get('AT_FEEDBACK_OFF', ''))")
    assert out == "1"


def test_minipytest_install_forces_feedback_off_without_package_import():
    """不经过 tests 包（它自己也会设）直接加载 minipytest.py：install() 必须设变量"""
    out = _child(
        "import os, sys, importlib.util;"
        "spec = importlib.util.spec_from_file_location('mp', r'tests/minipytest.py');"
        "m = importlib.util.module_from_spec(spec); sys.modules['mp'] = m; spec.loader.exec_module(m);"
        "before = os.environ.get('AT_FEEDBACK_OFF', '');"
        "m.install();"
        "print(before + '|' + os.environ.get('AT_FEEDBACK_OFF', ''))"
    )
    assert out == "|1"


def test_feedback_enabled_is_false_under_tests():
    from astral_toolkit.system import feedback_up

    assert feedback_up.enabled() is False
