"""垃圾代码检查 tools/junk_check.py：合成的小仓库里六样都测得出、基线只放过老问题；真仓库没有新垃圾"""

import contextlib
import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "_junk_check", ROOT / "tools" / "junk_check.py"
)
assert _SPEC is not None and _SPEC.loader is not None
JC = importlib.util.module_from_spec(_SPEC)
sys.modules["_junk_check"] = JC  # dataclass 要从 sys.modules 找到自己的模块
_SPEC.loader.exec_module(JC)

_DUP_BODY = (
    "    total = 0\n    for i in range(x):\n        total += i * i\n    return total\n"
)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _mini(root):
    """一个小仓库：每样垃圾各放一个，再放一个正常被用的作对照"""
    _write(root, "astral_toolkit/__init__.py", "")
    _write(root, "astral_toolkit/pkg/__init__.py", "from .a import used, only_facade\n")
    _write(
        root,
        "astral_toolkit/pkg/a.py",
        "def used():\n    return 1\n\n\n"
        "def never():\n    return 2\n\n\n"
        "def only_tests():\n    return 3\n\n\n"
        "def only_facade():\n    return 4\n\n\n"
        "LIMIT = 5\n\n\n"
        "def dup_one(x):\n" + _DUP_BODY + "\n\ndup_one(3)\n",
    )
    _write(
        root,
        "astral_toolkit/b.py",
        "import os  # noqa: F401\n\nfrom .pkg import used\n\n# 旧的 services.py 说法\nused()\n\n\n"
        "def dup_two(x):\n" + _DUP_BODY + "\n\ndup_two(3)\n",
    )
    _write(
        root,
        "tests/test_x.py",
        "from astral_toolkit.pkg.a import only_tests\n\nonly_tests()\n",
    )
    _write(root, "tools/t.py", "")
    return root


def test_scan_finds_each_kind(tmp_path):
    f = JC.scan(_mini(tmp_path))
    assert set(f.dead) == {
        "astral_toolkit/pkg/a.py::never",
        "astral_toolkit/pkg/a.py::LIMIT",
    }
    assert set(f.test_only) == {"astral_toolkit/pkg/a.py::only_tests"}
    assert list(f.dup) == [
        "astral_toolkit/b.py::dup_two | astral_toolkit/pkg/a.py::dup_one"
    ]
    assert set(f.facade) == {"astral_toolkit/pkg/__init__.py::only_facade"}
    assert f.noqa_f401 == {"astral_toolkit/b.py": 1}
    assert f.stale == {"astral_toolkit/b.py": 1}


def test_string_and_getattr_references_count_as_used(tmp_path):
    """getattr("名字") / 路由表字符串算有人用；__all__ 里列着不算"""
    root = _mini(tmp_path)
    _write(
        root,
        "astral_toolkit/c.py",
        '__all__ = ["only_tests"]\nimport astral_toolkit.pkg.a as m\n\ngetattr(m, "never")\n',
    )
    f = JC.scan(root)
    assert "astral_toolkit/pkg/a.py::never" not in f.dead
    assert "astral_toolkit/pkg/a.py::only_tests" in f.test_only


def test_private_script_not_counted(tmp_path):
    """不进仓库的私有脚本里用到也不算：CI 上没有它，本机和 CI 查出来要一样"""
    root = _mini(tmp_path)
    _write(
        root,
        "tools/publish_hk.py",
        "from astral_toolkit.pkg.a import never\n\nnever()\n",
    )
    assert "astral_toolkit/pkg/a.py::never" in JC.scan(root).dead


def test_baseline_lets_old_items_pass_and_catches_new_ones(tmp_path):
    root = _mini(tmp_path)
    base = JC.as_baseline(JC.scan(root), {})
    assert JC.compare(JC.scan(root), base) == []

    _write(
        root,
        "astral_toolkit/d.py",
        "import sys  # noqa: F401\n\n\ndef brand_new():\n    return 6\n",
    )
    _write(
        root,
        "astral_toolkit/b.py",
        (root / "astral_toolkit/b.py").read_text(encoding="utf-8")
        + "# EngineManager 早删了\n",
    )
    new = JC.compare(JC.scan(root), base)
    assert any("[没人用] astral_toolkit/d.py::brand_new" in line for line in new), new
    assert any("[noqa F401] astral_toolkit/d.py：0 → 1" in line for line in new), new
    assert any("[过时说法] astral_toolkit/b.py：1 → 2" in line for line in new), new

    base["allow"] = {"astral_toolkit/d.py::brand_new": "测试：确实要留"}
    assert not any("brand_new" in line for line in JC.compare(JC.scan(root), base))


def test_main_exit_codes(tmp_path):
    root = _mini(tmp_path)
    baseline = root / "tools" / "junk_baseline.json"
    assert JC.main(["--root", str(root), "--write-baseline"]) == 0
    assert baseline.exists()
    assert JC.main(["--root", str(root)]) == 0
    _write(root, "astral_toolkit/e.py", "def another():\n    return 7\n")
    assert JC.main(["--root", str(root)]) == 1


def test_cleaned_items_ask_to_tighten_baseline(tmp_path):
    """清掉老问题不报错，但提示收紧基线（不然同一处以后再犯查不出来）"""
    root = _mini(tmp_path)
    assert JC.main(["--root", str(root), "--write-baseline"]) == 0
    a = root / "astral_toolkit/pkg/a.py"
    a.write_text(
        a.read_text(encoding="utf-8").replace("def never():\n    return 2\n", ""),
        encoding="utf-8",
    )
    b = root / "astral_toolkit/b.py"
    b.write_text(
        b.read_text(encoding="utf-8").replace("import os  # noqa: F401\n", ""),
        encoding="utf-8",
    )
    base = JC.load_baseline(root / "tools" / "junk_baseline.json")
    assert JC.tightenable(JC.scan(root), base) == 2
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert JC.main(["--root", str(root)]) == 0
    assert "基线里有 2 处已经清掉了" in out.getvalue(), out.getvalue()
    assert JC.main(["--root", str(root), "--write-baseline"]) == 0
    tightened = JC.load_baseline(root / "tools" / "junk_baseline.json")
    assert JC.tightenable(JC.scan(root), tightened) == 0


def test_repo_has_no_new_junk():
    """真仓库：和 tools/junk_baseline.json 比没有新垃圾（CI 也跑同一个检查）"""
    new = JC.compare(
        JC.scan(ROOT), JC.load_baseline(ROOT / "tools" / "junk_baseline.json")
    )
    assert not new, "垃圾代码检查发现新的：\n" + "\n".join(new)
