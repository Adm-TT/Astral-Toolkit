"""接口路由（2026-10-30 重构阶段 0）

routes()：收集 astral_toolkit/app/api/ 下每个 Controller 模块的 ROUTES（不用后台对象的接口）。
模块级 call()：只调 routes() 里的（测试、自检），统一返回 {"ok", "data" / "error"}。

Controller 写法（阶段 1–3）：astral_toolkit/app/api/<领域>.py 里写接口函数，文件末尾
    ROUTES = {"接口名": 函数, …}
不用改 router。

要后台对象的接口由 Controller 的 bound(对象…) 返回 {"接口名": 函数}，bootstrap.routes(app)
把这个 app 的对象交进去、和 routes() 拼成一张 Api；网页服务拿着它（http_server.Server 的 api），
HTTP（http_server.Handler.do_POST）走 Api.call，返回格式和模块级 call 一样。
"""

import importlib
import json
import pkgutil
import threading
import traceback

_SKIP = {"router", "__init__"}
_cache = None
_lock = threading.Lock()


def routes():
    """接口名 → 函数。结果缓存，reset() 清掉"""
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is None:
            from .. import api as _pkg

            table = {}
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


def _call(fn, name, args):
    if not fn:
        return {"ok": False, "error": f"没有 {name}"}
    try:
        result = fn(**(args or {}))
        data = json.loads(
            json.dumps(result, ensure_ascii=False, default=str)
        )  # Decimal、Path 变字符串，和 HTTP 一样
        return {"ok": True, "data": data}
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


def call(name, args=None):
    """只调不用后台对象的接口（测试、自检）"""
    return _call(routes().get(name), name, args)


class Api:
    """一张接口表（F 段 B5）：table = 接口名 → 函数。bootstrap.routes(app) 造这个 app 的全套，网页服务拿着；
    不给 table 就是 routes()（只有不用后台对象的接口，测试里直接起的网页服务用）"""

    def __init__(self, table=None):
        self._table = None if table is None else dict(table)

    @property
    def table(self):
        return routes() if self._table is None else self._table

    def call(self, name, args=None):
        """返回格式和模块级 call 一样"""
        return _call(self.table.get(name), name, args)
