"""接口路由（2026-10-30 重构阶段 0）

routes()：先放 services.API（过渡期兜底），再收集 sc_mining/app/api/ 下每个 Controller 模块的 ROUTES，
后收集的覆盖先放的。HTTP（server.do_POST）和 PyWebview（bridge）都走 call()，返回格式一样。

Controller 写法（阶段 1–3）：sc_mining/app/api/<领域>.py 里写接口函数，文件末尾
    ROUTES = {"接口名": 函数, …}
不用改 router 和 bridge。
"""
import importlib
import json
import pkgutil
import threading
import traceback

_SKIP = {"router", "bridge", "__init__"}
_cache = None
_lock = threading.Lock()


def routes():
    """接口名 → 函数。结果缓存，reset() 清掉"""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is None:
            from .. import services                 # 在函数里 import：services 也会 import 这一层，顶层 import 会循环引用
            from .. import api as _pkg
            table = dict(services.API)
            for m in sorted(pkgutil.iter_modules(_pkg.__path__), key=lambda m: m.name):
                if m.name in _SKIP:
                    continue
                mod = importlib.import_module(f"{_pkg.__name__}.{m.name}")
                table.update(getattr(mod, "ROUTES", None) or {})
            _cache = table
    return _cache


def reset():
    """清缓存（测试往 routes 里塞东西、加了 Controller 模块后用）"""
    global _cache
    with _lock:
        _cache = None


def call(name, args=None):
    """调一个接口，返回 {"ok": True, "data": …} / {"ok": False, "error": …}（和原来 HTTP 返回的一样）"""
    fn = routes().get(name)
    if not fn:
        return {"ok": False, "error": f"没有 {name}"}
    try:
        result = fn(**(args or {}))
        data = json.loads(json.dumps(result, ensure_ascii=False, default=str))   # Decimal、Path 变字符串，和 HTTP 一样
        return {"ok": True, "data": data}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}
