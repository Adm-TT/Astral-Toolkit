"""PyWebview 的 js_api（2026-10-30 重构阶段 0）

前端：await window.pywebview.api.call(name, args) → 和 HTTP /api/<name> 一样的 {"ok", "data" / "error"}。
和 NGU 设计 4.1 节「每个接口一个 staticmethod」不同：一百多个接口逐个列会和各 Controller 的 ROUTES 重复两份，
这里只留一个 call，接口表由 router 统一管（合并请求里请 NGU 定）。
PyWebview 会把 js_api 对象上所有公开方法暴露给网页，所以这里只放 call 一个。
"""
from . import router


class BackendBridge:
    def call(self, name, args=None):
        return router.call(name, args or {})
