"""没有装 pytest 的电脑上也能跑测试：实现测试里用到的那一小部分 pytest 接口"""
import contextlib
import importlib
import inspect
import sys
import tempfile
import traceback
from pathlib import Path


class Skip(Exception):
    pass


def fixture(fn=None, **_):
    def mark(f):
        f._is_fixture = True
        return f
    return mark(fn) if fn else mark


def skip(msg=''):
    raise Skip(msg)


class _ExcInfo:
    value = None


@contextlib.contextmanager
def raises(exc, match=None):
    info = _ExcInfo()
    try:
        yield info
    except exc as e:
        info.value = e
        return
    raise AssertionError(f'没有抛出 {exc}')


class _Mark:
    @staticmethod
    def parametrize(names, values):
        def deco(f):
            f._params = ([n.strip() for n in names.split(',')], values)
            return f
        return deco

    def __getattr__(self, _):
        return lambda *a, **k: (lambda f: f)


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


def install():
    """没有真 pytest 时，把本模块当成 pytest"""
    try:
        import pytest  # noqa
    except ImportError:
        sys.modules['pytest'] = sys.modules[__name__]


def run_module(modname):
    install()
    m = importlib.import_module(modname)
    fixtures = {n: f for n, f in vars(m).items() if getattr(f, '_is_fixture', False)}
    fails = skips = passed = 0
    for name, fn in list(vars(m).items()):
        if not (name.startswith('test_') and callable(fn)):
            continue
        cases = [{}]
        if hasattr(fn, '_params'):
            names, values = fn._params
            cases = [dict(zip(names, v if len(names) > 1 else (v,))) for v in values]
        for case in cases:
            mp = MonkeyPatch()
            tmp = Path(tempfile.mkdtemp())
            avail = {'tmp_path': tmp, 'monkeypatch': mp}
            try:
                kwargs = {}
                for p in inspect.signature(fn).parameters:
                    if p in case:
                        kwargs[p] = case[p]
                    elif p in avail:
                        kwargs[p] = avail[p]
                    elif p in fixtures:
                        fx = fixtures[p]
                        kwargs[p] = fx(**{q: avail[q] for q in inspect.signature(fx).parameters if q in avail})
                    else:
                        raise Skip(f'需要 {p}')
                fn(**kwargs)
                passed += 1
            except Skip:
                skips += 1
            except Exception:
                fails += 1
                mp.restore()                     # 先撤掉补丁：测试若替换了 print，FAIL 这行也要能打出来
                print('FAIL', modname, name, case or '')
                traceback.print_exc()
            finally:
                mp.restore()
    return passed, fails, skips


def run_all(modules):
    total = [0, 0, 0]
    for mod in modules:
        for i, n in enumerate(run_module(mod)):
            total[i] += n
    print(f'tests: {total[0]} passed, {total[1]} failed, {total[2]} skipped')
    return total[1]
