from datetime import datetime, timedelta, timezone
from decimal import Decimal  # noqa: F401
import threading
from ..models import Item, PriceKey, PriceStats, ProviderResult, Quote
from .http import HttpTransport, SourceError, decimal_price, uex_data

BASE = "https://api.uexcorp.uk/2.0/"
HISTORY_NOTE = "来源统计；7 天均价完整覆盖未验证，历史不足时可能回退为当前值"


class UexProvider:
    source = "uex"

    def __init__(self, transport: HttpTransport | None = None):
        self.http = transport or HttpTransport()

    def lookup(self, query: str) -> list[Item]:
        rows = uex_data(
            self.http.get_json(
                BASE + "marketplace_prices_averages", {"item_name": query}
            )
        )
        found = {}
        for r in rows:
            if not r.get("item_name") or r.get("id_item") is None:
                continue
            uid = r.get("item_uuid")
            item = Item(uid or "uex:" + str(r["id_item"]), r["item_name"], uid)
            found[item.id] = item
        return sorted(found.values(), key=lambda i: i.name)

    def fetch(
        self, item: Item, quality_group: str, operation: str, now: datetime
    ) -> ProviderResult:
        try:
            if quality_group not in {f"q{i}" for i in range(8)}:
                return ProviderResult(
                    "uex",
                    "empty",
                    message="UEX 品质未知时不匹配为 Q0；请明确选择品质档",
                )
            if operation not in ("sell", "buy"):
                raise ValueError("invalid operation")
            params = {"item_uuid": item.uuid} if item.uuid else {"item_name": item.name}
            params.update(operation=operation, quality_tier=quality_group[1:])
            params_history = {
                **params,
                "date_start": (now - timedelta(days=7)).strftime("%Y-%m-%d"),
            }
            box = {}

            def get_history():  # 和均价同时查，省一次来回的时间
                try:
                    box["rows"] = uex_data(
                        self.http.get_json(
                            BASE + "marketplace_prices_history", params_history
                        )
                    )
                except SourceError:
                    box["rows"] = None
                except Exception:
                    box["rows"] = None

            th = threading.Thread(target=get_history, daemon=True)
            th.start()
            try:
                averages = uex_data(
                    self.http.get_json(BASE + "marketplace_prices_averages", params)
                )
            finally:
                th.join()
            history_error = ""
            history = box.get("rows")
            if history is None:
                history = []
                history_error = "；最低价采样暂不可用"
            latest = {}
            for r in history:
                if not self._matches(r, item, quality_group, operation):
                    continue
                ident = str(r.get("id_listing", ""))
                if ident and (
                    ident not in latest
                    or int(r["date_added"]) > int(latest[ident]["date_added"])
                ):
                    latest[ident] = r
            quotes = []
            for ident, r in latest.items():
                price = decimal_price(r.get("price"))
                if r.get("date_removed") != 0 or price is None:
                    continue
                key = self._key(r, item)
                quotes.append(
                    Quote(
                        ident,
                        key,
                        price,
                        "fixed",
                        None,
                        "https://uexcorp.space/marketplace/home/?id_item="
                        + str(r["id_item"]),
                    )
                )
            stats = []
            for r in averages:
                if not self._matches(r, item, quality_group, operation):
                    continue
                key = self._key(r, item)
                count = max(0, int(r.get("listings_count") or 0))
                mean = decimal_price(r.get("price_avg")) if count else None
                minima = [q.price for q in quotes if q.key == key]
                # A truncated history cannot establish the minimum of the complete active market.
                minimum = (
                    min(minima)
                    if minima and len(history) < 1000 and len(minima) == count
                    else None
                )
                stamp = datetime.fromtimestamp(int(r["date_modified"]), timezone.utc)
                stats.append(
                    PriceStats(
                        key,
                        mean,
                        minimum,
                        count,
                        stamp,
                        decimal_price(r.get("price_avg_week")),
                        HISTORY_NOTE
                        + history_error
                        + ("；最低价仅在活跃样本覆盖当前挂牌数时显示"),
                    )
                )
            return ProviderResult(
                "uex",
                "ok" if stats else "empty",
                tuple(stats),
                tuple(quotes),
                (item,),
                message="Powered by UEX · 玩家挂牌价；按品质和单位分组",
            )
        except SourceError as e:
            return ProviderResult(
                "uex", e.state, retry_after=e.retry_after, message=str(e)
            )
        except (KeyError, ValueError, TypeError, OverflowError):
            return ProviderResult(
                "uex", "schema_error", message="UEX 字段无法解析，已停止使用该响应"
            )

    @staticmethod
    def _matches(r, item, quality, operation):
        same = (
            r.get("item_uuid") == item.uuid
            if item.uuid
            else str(r.get("item_name", "")).casefold() == item.name.casefold()
        )
        return (
            same
            and str(r.get("quality_tier")) == quality[1:]
            and r.get("operation") == operation
        )

    @staticmethod
    def _key(r, item):
        return PriceKey(
            "uex",
            item.id,
            "q" + str(r["quality_tier"]),
            str(r["currency"]),
            str(r["unit"]),
            str(r["game_version"]),
            str(r["operation"]),
        )
