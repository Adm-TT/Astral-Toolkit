from dataclasses import dataclass, field  # noqa: F401
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    uuid: str | None = None


@dataclass(frozen=True)
class PriceKey:
    source: str
    item_id: str
    quality_group: str
    currency: str
    unit: str
    version: str
    operation: str


@dataclass(frozen=True)
class Quote:
    id: str
    key: PriceKey
    price: Decimal
    kind: str
    expires_at: datetime | None
    url: str


@dataclass(frozen=True)
class PriceStats:
    key: PriceKey
    mean: Decimal | None
    minimum: Decimal | None
    count: int
    observed_at: datetime
    week_mean: Decimal | None = None
    history_note: str = ""


@dataclass(frozen=True)
class Snapshot:
    key: PriceKey
    at: datetime
    mean: Decimal
    minimum: Decimal | None = None


@dataclass(frozen=True)
class ProviderResult:
    source: str
    state: str
    stats: tuple[PriceStats, ...] = ()
    quotes: tuple[Quote, ...] = ()
    items: tuple[Item, ...] = ()
    retry_after: datetime | None = None
    message: str = ""


@dataclass(frozen=True)
class StockKey:
    item_id: str
    quality: str
    location: str
    unit: str = "unit"


@dataclass(frozen=True)
class StockLine:
    key: StockKey
    quantity: int


@dataclass(frozen=True)
class ImportPreview:
    lines: tuple[StockLine, ...]
    before: tuple[StockLine, ...]
    mode: str
    image_hash: str | None = None
    duplicate: bool = False
    revision: int = 0


@dataclass(frozen=True)
class ImportRow:
    raw_name: str
    item_id: str | None
    quantity: int | None
    quality: str | None
    unit: str = "unit"
    confirmed: bool = False
    candidates: tuple[Item, ...] = ()


__all__ = [
    "Item",
    "PriceKey",
    "PriceStats",
    "ProviderResult",
    "StockKey",
    "StockLine",
    "ImportRow",
]
