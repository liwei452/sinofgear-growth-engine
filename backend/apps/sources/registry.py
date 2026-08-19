from __future__ import annotations

from .authenticity import SourceAuthenticity, SourceCapability
from .adapter import SourceAdapter


class SourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        if adapter.authenticity is SourceAuthenticity.SYNTHETIC:
            raise ValueError(f"SYNTHETIC source {adapter.id!r} cannot be registered.")
        if adapter.id in self._sources:
            raise ValueError(f"Source {adapter.id!r} is already registered.")
        self._sources[adapter.id] = adapter

    def get(self, source_id: str) -> SourceAdapter:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise KeyError(f"Unknown source {source_id!r}.") from exc

    def for_capability(self, capability: SourceCapability) -> list[SourceAdapter]:
        return [source for source in self._sources.values() if source.capability is capability]

    def real_only(self) -> list[SourceAdapter]:
        return [
            source
            for source in self._sources.values()
            if source.authenticity is not SourceAuthenticity.SYNTHETIC
        ]

    def all(self) -> list[SourceAdapter]:
        return list(self._sources.values())
