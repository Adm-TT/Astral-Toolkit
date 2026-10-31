from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request


class SourceError(Exception):
    def __init__(self, state: str, message: str, retry_after: datetime | None = None):
        super().__init__(message)
        self.state, self.retry_after = state, retry_after


def decimal_price(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
        # Prevent absurd exponents from creating huge strings or UI resources.
        if not result.is_finite() or result <= 0 or abs(result.adjusted()) > 30:
            return None
        return result
    except (InvalidOperation, ValueError):
        return None


def quality_group(value) -> str:
    if value is None or isinstance(value, bool):
        return 'unknown'
    try:
        n = int(value)
        if n != float(value) or not 0 <= n <= 1000:
            return 'unknown'
        return 'q' + str(0 if n == 0 else 1 if n < 500 else 2 if n < 600 else 3 if n < 700 else 4 if n < 800 else 5 if n < 900 else 6 if n < 950 else 7)
    except (ValueError, TypeError, OverflowError):
        return 'unknown'


class HTTPStatusError(Exception):
    pass


class RequestError(Exception):
    pass


class _Response:
    def __init__(self, status_code, headers, text):
        self.status_code, self.text = status_code, text
        self.headers = {str(k).lower(): v for k, v in dict(headers or {}).items()}     # 头名统一小写（十审 2026-10-28）

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPStatusError(self.status_code)


class UrllibClient:
    """标准库实现的最小 HTTP 客户端（不依赖第三方库）"""
    UA = 'SCAssistant-Trade/0.2 (read-only community tool)'

    def get(self, url, params=None, headers=None, timeout=15):
        full = url + ('?' + urllib.parse.urlencode(params) if params else '')
        req = urllib.request.Request(full, headers={'User-Agent': self.UA, 'Accept': 'application/json',
                                                   'Accept-Encoding': 'gzip, deflate', **(headers or {})})
        from ...core.net import decode
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = decode(r.read(), r.headers.get('Content-Encoding'))
                return _Response(r.status, dict(r.headers), body.decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            body = decode(e.read() or b'', (e.headers or {}).get('Content-Encoding'))
            return _Response(e.code, dict(e.headers or {}), body.decode('utf-8', 'replace'))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RequestError(str(e)) from None

    def close(self):
        pass


class HttpTransport:
    def __init__(self, client=None, sleep=time.sleep, token: str | None = None):
        self.client = client or UrllibClient()
        self.sleep = sleep
        self.token = token
        self.cancel_event = None

    def check_cancel(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise SourceError('cancelled','请求已取消')

    def backoff(self,seconds):
        if self.cancel_event is not None:
            self.cancel_event.wait(seconds)
            self.check_cancel()
        else:self.sleep(seconds)

    def get_json(self, url: str, params: dict[str, str]):
        headers = {'Authorization': f'Bearer {self.token}'} if self.token else {}
        for attempt in range(3):
            self.check_cancel()
            try:
                r = self.client.get(url, params=params, headers=headers, timeout=15)
                self.check_cancel()
                if r.status_code in (401, 403):
                    raise SourceError('forbidden', '来源拒绝访问，需在浏览器中打开网站检查')
                if r.status_code == 429:
                    raw = r.headers.get('retry-after', '3600')     # 头名统一小写（老大审查 2026-10-28）
                    try:
                        at = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(raw)))
                    except ValueError:
                        try:
                            at = parsedate_to_datetime(raw).astimezone(timezone.utc)
                        except (ValueError, TypeError):
                            at = datetime.now(timezone.utc) + timedelta(hours=1)
                    raise SourceError('rate_limited', '来源限制了请求频率，稍后重试', at)
                if r.status_code >= 500 and attempt < 2:
                    self.backoff(attempt + 1)
                    continue
                r.raise_for_status()
                return json.loads(r.text, parse_float=Decimal)
            except RequestError:
                if attempt < 2:
                    self.backoff(attempt + 1)
                    continue
                raise SourceError('offline', '连接超时或网络不可用') from None
            except (HTTPStatusError, json.JSONDecodeError):
                raise SourceError('schema_error', '来源响应异常，暂时无法读取') from None

    def close(self):
        self.client.close()


def uex_data(payload):
    if not isinstance(payload, dict) or payload.get('status') != 'ok' or not isinstance(payload.get('data'), list):
        raise SourceError('schema_error', 'UEX 数据格式已变化或请求无效')
    return payload['data']


def scm_data(payload):
    if not isinstance(payload, dict) or payload.get('code') != 0 or payload.get('data') is None:
        raise SourceError('schema_error', 'SCM 数据格式已变化或请求无效')
    return payload['data']
