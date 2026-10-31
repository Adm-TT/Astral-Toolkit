from datetime import datetime
from typing import Protocol
from ..models import Item, ProviderResult


class Provider(Protocol):
    source: str
    def fetch(self, item: Item, quality_group: str, operation: str, now: datetime) -> ProviderResult: ...
    def lookup(self, query: str) -> list[Item]: ...
