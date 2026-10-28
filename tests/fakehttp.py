"""测试用：模拟 httpx 的最小接口，适配助手里 urllib 版本的 HttpTransport"""
import json as _json
from types import SimpleNamespace
from urllib.parse import urlparse
from sc_mining.trade.providers.http import _Response


def Response(status, json=None, headers=None, text=None):
    return _Response(status, headers or {}, text if text is not None else _json.dumps(json))


class MockTransport:
    def __init__(self, handler):
        self.handler = handler


class Client:
    def __init__(self, transport):
        self.transport = transport

    def get(self, url, params=None, headers=None, timeout=15):
        req = SimpleNamespace(url=SimpleNamespace(path=urlparse(url).path, params=params or {}), headers=headers or {})
        return self.transport.handler(req)

    def close(self):
        pass
