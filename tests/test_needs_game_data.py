"""云端 CI 跳过名单（tests/needs_game_data.py）和 minipytest 的跳过参数"""

import contextlib
import importlib
import io
import sys
import types

from tests import minipytest
from tests.needs_game_data import NEEDS_GAME_DATA


def test_list_names_real_tests_in_run_all():
    """名单里的模块都在 run_all 的 MODULES 里、测试函数都还在：改名或删了要同步改名单"""
    from tests.run_all import MODULES

    for mod, names in NEEDS_GAME_DATA.items():
        assert mod in MODULES, mod
        m = importlib.import_module(mod)
        for n in names:
            assert n.startswith("test_") and callable(getattr(m, n, None)), (mod, n)


def _run_fake(skip):
    """临时塞一个有 test_a / test_b 的模块进 sys.modules 跑一遍，返回（结果，跑了哪些）"""
    ran = []
    m = types.ModuleType("tests._fake_skip_mod")

    def test_a():
        ran.append("a")

    def test_b():
        ran.append("b")

    m.test_a, m.test_b = test_a, test_b  # type: ignore[attr-defined]
    sys.modules[m.__name__] = m
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):  # 别往全量日志里打这里故意造的 FAIL
            got = minipytest.run_module(m.__name__, skip)
        return got, sorted(ran), out.getvalue()
    finally:
        del sys.modules[m.__name__]


def test_run_module_skips_listed_tests():
    got, ran, out = _run_fake({"test_b": "没有数据"})
    assert (got, ran) == ((1, 0, 1), ["a"]) and "SKIP" in out and "没有数据" in out


def test_run_module_fails_on_stale_skip_name():
    """名单里写了不存在的测试：记一个失败，其余照跑"""
    got, ran, out = _run_fake({"test_gone": "没有数据"})
    assert (got, ran) == ((2, 1, 0), ["a", "b"]) and "test_gone" in out
