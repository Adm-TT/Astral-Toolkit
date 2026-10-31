"""没有装 pytest 的电脑上也能跑测试：实现测试里用到的那一小部分 pytest 接口。
不支持的用法（别的 mark、fixture 参数、yield 式 fixture）直接报错，不悄悄当成没写（2026-10-31 审查）"""
import contextlib
import importlib
import inspect
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

# 这一轮所有临时目录都建在这下面；全部通过就整个删掉，有失败留着查（以前每轮留下 400 多个目录，从不清理）
ROOT = Path(tempfile.mkdtemp(prefix='at_tests_'))


def tmpdir():
    return Path(tempfile.mkdtemp(dir=ROOT))


class Skip(Exception):
    pass


def fixture(fn=None, **kw):
    if kw:
        raise TypeError(f'minipytest 不支持 fixture 参数 {sorted(kw)}')

    def mark(f):
        if inspect.isgeneratorfunction(f):
            raise TypeError(f'minipytest 不支持 yield 式 fixture：{f.__name__}（收尾不会执行）')
        f._is_fixture = True
        return f
    return mark(fn) if fn else mark


def skip(msg=''):
    raise Skip(msg)


class _ExcInfo:
    value = None
    type = None


@contextlib.contextmanager
def raises(exc, match=None):
    info = _ExcInfo()
    try:
        yield info
    except exc as e:
        if match is not None and not re.search(match, str(e)):      # 和真 pytest 一样核对报错信息（以前 match 收了不用）
            raise AssertionError(f'报错信息 {str(e)!r} 不匹配 {match!r}') from e
        info.value, info.type = e, type(e)
        return
    raise AssertionError(f'没有抛出 {exc}')


class _Mark:
    @staticmethod
    def parametrize(names, values):
        def deco(f):
            f._params = ([n.strip() for n in names.split(',')], values)
            return f
        return deco

    def __getattr__(self, name):
        raise AttributeError(f'minipytest 不支持 mark.{name}（以前会被悄悄忽略，skip / skipif 的测试照样跑）')


mark = _Mark()


class MonkeyPatch:
    def __init__(self):
        self.undo = []

    def setattr(self, target, name, value=None, raising=True):
        if isinstance(target, str):
            mod, _, attr = target.rpartition('.')
            target, name, value = importlib.import_module(mod), attr, name
        self.undo.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def setenv(self, k, v):
        import os
        self.undo.append((os.environ, k, os.environ.get(k)))
        os.environ[k] = v

    def restore(self):
        for target, name, old in reversed(self.undo):
            if target.__class__.__name__ == '_Environ':
                if old is None:
                    target.pop(name, None)
                else:
                    target[name] = old
            else:
                setattr(target, name, old)
        self.undo.clear()


def install():
    """没有真 pytest 时，把本模块当成 pytest"""
    try:
        import pytest  # noqa: F401
    except ImportError:
        sys.modules['pytest'] = sys.modules[__name__]


def run_module(modname):
    install()
    fails = skips = passed = 0
    try:
        m = importlib.import_module(modname)
    except KeyboardInterrupt:
        raise
    except BaseException:                        # 模块导入失败：记一条失败，接着跑别的模块（以前整轮中断）
        print('FAIL', modname, '（导入失败）')
        traceback.print_exc()
        return 0, 1, 0
    fixtures = {n: f for n, f in vars(m).items() if getattr(f, '_is_fixture', False)}
    for name, fn in list(vars(m).items()):
        if not (name.startswith('test_') and callable(fn)):
            continue
        cases = [{}]
        if hasattr(fn, '_params'):
            names, values = fn._params
            cases = [dict(zip(names, v if len(names) > 1 else (v,))) for v in values]
        for case in cases:
            mp = MonkeyPatch()
            avail = {'tmp_path': tmpdir(), 'monkeypatch': mp}
            try:
                kwargs = {}
                for p, prm in inspect.signature(fn).parameters.items():
                    if p in case:
                        kwargs[p] = case[p]
                    elif prm.default is not inspect.Parameter.empty:
                        continue                 # 和真 pytest 一样：有默认值的参数不当 fixture，用默认值（以前当成缺 fixture 整个跳过）
                    elif p in avail:
                        kwargs[p] = avail[p]
                    elif p in fixtures:
                        fx = fixtures[p]
                        kwargs[p] = fx(**{q: avail[q] for q in inspect.signature(fx).parameters if q in avail})
                    else:
                        raise LookupError(f'找不到 fixture {p}')    # 和真 pytest 一样算出错（以前算跳过，拼错名字就悄悄不跑）
                fn(**kwargs)
                passed += 1
            except Skip as e:
                skips += 1
                print('SKIP', modname, name, case or '', e)
            except KeyboardInterrupt:
                raise
            except BaseException:                # 含 SystemExit：记这一个失败，接着跑（以前 SystemExit(0) 会结束整轮还以 0 退出）
                fails += 1
                mp.restore()                     # 先撤掉补丁：测试若替换了 print，FAIL 这行也要能打出来
                print('FAIL', modname, name, case or '')
                traceback.print_exc()
            finally:
                mp.restore()
    # unittest.TestCase 写的测试（这个模块里定义的类）：用 unittest 自己跑，计入同一份结果
    import unittest
    for cname, cls in list(vars(m).items()):
        if not (isinstance(cls, type) and issubclass(cls, unittest.TestCase) and cls.__module__ == m.__name__):
            continue
        for tname in unittest.defaultTestLoader.getTestCaseNames(cls):
            res = unittest.TestResult()
            cls(tname).run(res)
            if res.failures or res.errors or res.unexpectedSuccesses:
                fails += 1
                print('FAIL', modname, f'{cname}.{tname}')
                for _, tb in res.failures + res.errors:
                    print(tb)
            elif res.skipped:
                skips += 1
                print('SKIP', modname, f'{cname}.{tname}', res.skipped[0][1])
            else:
                passed += 1
    return passed, fails, skips


def run_all(modules):
    total = [0, 0, 0]
    for mod in modules:
        for i, n in enumerate(run_module(mod)):
            total[i] += n
    print(f'tests: {total[0]} passed, {total[1]} failed, {total[2]} skipped')
    if total[1]:
        print(f'临时文件留着查：{ROOT}')
    else:
        shutil.rmtree(ROOT, ignore_errors=True)
    return total[1]
