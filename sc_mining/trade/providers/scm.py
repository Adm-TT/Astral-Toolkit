from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import threading
import time
from ..models import Item, PriceKey, PriceStats, ProviderResult, Quote
from .http import HttpTransport, SourceError, decimal_price, quality_group, scm_data
from ..decimal_math import precise

BASE = "https://scms.flowcld.com/app-api"
ORDERS_TTL = (
    600  # SCM 的挂单列表（所有物品一起）10 分钟内重复用，查别的物品不用再下载一遍
)
MAX_PAGES = 20


class ScmProvider:
    source = "scm"

    def __init__(self, transport: HttpTransport | None = None):
        self.http = transport or HttpTransport()
        self._orders = None  # (时间, 挂单列表, 是否不全)
        self._orders_lock = threading.Lock()

    def _page(self, page):
        data = scm_data(
            self.http.get_json(
                BASE + "/sc/orders/page", {"pageNo": str(page), "pageSize": "100"}
            )
        )
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise SourceError("schema_error", "SCM 订单格式已变化")
        return data

    def all_orders(self):
        """SCM 全部挂单（不分物品，最多 20 页）。第一页拿到总数后，剩下的页 4 个一起下；10 分钟内直接用上次的"""
        with self._orders_lock:
            if self._orders and time.monotonic() - self._orders[0] < ORDERS_TTL:
                return self._orders[1], self._orders[2]
            first = self._page(1)
            orders = list(first["list"])
            total = int(first["total"])
            pages = min(MAX_PAGES, max(1, -(-total // 100)))
            if pages > 1:
                with ThreadPoolExecutor(max_workers=4) as ex:
                    for data in ex.map(self._page, range(2, pages + 1)):
                        orders.extend(data["list"])
            partial = total > MAX_PAGES * 100
            self._orders = (time.monotonic(), orders, partial)
            return orders, partial

    def lookup(self, query: str) -> list[Item]:
        rows = scm_data(
            self.http.get_json(BASE + "/product/items/item-search", {"name": query})
        )
        if not isinstance(rows, list):
            raise SourceError("schema_error", "SCM 搜索格式已变化")
        return [
            Item("scm:" + str(r["id"]), r.get("itemNameEn") or r["itemName"])
            for r in rows
        ]

    def fetch(
        self, item: Item, quality_group: str, operation: str, now: datetime
    ) -> ProviderResult:
        try:
            if operation not in ("sell", "buy"):
                raise ValueError("invalid operation")
            if item.id.startswith("scm:"):
                ident = item.id.removeprefix("scm:")
            else:
                rows = scm_data(
                    self.http.get_json(
                        BASE + "/product/items/item-search", {"name": item.name}
                    )
                )
                matches = [
                    r
                    for r in rows
                    if (r.get("itemNameEn") or r.get("itemName", "")).casefold()
                    == item.name.casefold()
                ]
                if len(matches) != 1:
                    return ProviderResult(
                        "scm",
                        "empty",
                        message="SCM 未找到唯一同名物品；请从 SCM 搜索结果选择",
                    )
                ident = str(matches[0]["id"])
            orders, partial = self.all_orders()
            quotes = self.normalize_orders(
                orders, item, ident, quality_group, operation, now
            )
            quotes = list({q.id: q for q in quotes}.values())
            with precise([q.price for q in quotes]):
                stats = (
                    [
                        PriceStats(
                            quotes[0].key,
                            sum(q.price for q in quotes) / len(quotes),
                            min(q.price for q in quotes),
                            len(quotes),
                            now,
                            history_note="有效单件挂牌算术平均；7 天历史从本地采集累计",
                        )
                    ]
                    if quotes
                    else []
                )
            return ProviderResult(
                "scm",
                "partial" if partial else "ok" if quotes else "empty",
                tuple(stats),
                tuple(quotes),
                (item,),
                message="SCM 活跃玩家挂牌；版本未提供；历史按品质隔离，从本地首次采集累计"
                + ("；订单分页达到上限，非全市场统计" if partial else ""),
            )
        except SourceError as e:
            return ProviderResult(
                "scm", e.state, retry_after=e.retry_after, message=str(e)
            )
        except (KeyError, ValueError, TypeError, OverflowError):
            return ProviderResult(
                "scm", "schema_error", message="SCM 字段无法解析，已停止使用该响应"
            )

    @staticmethod
    def normalize_orders(rows, item, ident, group, operation, now):
        result = []
        for r in rows:
            if (
                r.get("status") != 1
                or r.get("creatorType") != (1 if operation == "sell" else 0)
                or int(r.get("remainingQuantity") or 0) <= 0
            ):
                continue
            details = r.get("itemDetails") or []
            if len(details) != 1 or str(details[0].get("itemId")) != ident:
                continue
            detail = details[0]
            # Only simple single-item manifests have a verified per-piece meaning.
            if int(detail.get("quantity") or 0) != 1:
                continue
            try:
                quality = (
                    json.loads(detail["qualityData"])
                    if detail.get("qualityData")
                    else {}
                )
            except (json.JSONDecodeError, TypeError):
                quality = {}
            q = quality_group(quality.get("quality"))
            price = decimal_price(detail.get("unitPrice"))
            if q != group or price is None:
                continue
            expiry = (
                datetime(1970, 1, 1, tzinfo=timezone.utc)
                + timedelta(milliseconds=int(r["expireTime"]))
                if r.get("expireTime")
                else None
            )
            if expiry and expiry <= now:
                continue
            key = PriceKey("scm", item.id, q, "UEC", "unit", "unspecified", operation)
            result.append(
                Quote(
                    str(r["orderNumber"]),
                    key,
                    price,
                    "fixed",
                    expiry,
                    "https://scm.flowcld.com/market",
                )
            )
        return result
