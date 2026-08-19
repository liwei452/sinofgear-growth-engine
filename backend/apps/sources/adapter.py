from __future__ import annotations

from typing import Iterator, Protocol

from .authenticity import SourceAuthenticity, SourceCapability
from .record import SourceRecord


class SourceAdapter(Protocol):
    id: str
    category: str
    capability: SourceCapability
    authenticity: SourceAuthenticity
    requires_api_key: bool
    rate_limit: int
    enabled: bool

    def search(self, query: str, options: dict | None = None) -> Iterator[SourceRecord]: ...
    def research(self, target: dict) -> Iterator[SourceRecord]: ...
    def enrich(self, target: dict) -> Iterator[SourceRecord]: ...
    def verify(self, target: dict) -> Iterator[SourceRecord]: ...
