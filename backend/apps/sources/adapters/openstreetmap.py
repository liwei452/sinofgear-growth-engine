from __future__ import annotations

from typing import Iterator

import httpx

from ..authenticity import SourceAuthenticity, SourceCapability
from ..record import SourceRecord


class OpenStreetMapAdapter:
    id = "openstreetmap"
    category = "local"
    capability = SourceCapability.DISCOVER
    authenticity = SourceAuthenticity.REAL
    requires_api_key = False
    rate_limit = 1
    enabled = True

    SEARCH_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        user_agent: str = "SinofGear/1.0 (contact@sinofgear.com)",
    ) -> None:
        self._client = client
        self.user_agent = user_agent

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": self.user_agent}, timeout=30.0
            )
        return self._client

    def search(self, query: str, options: dict | None = None) -> Iterator[SourceRecord]:
        options = options or {}
        limit = min(int(options.get("count", 10)), 50)
        response = self.client.get(
            self.SEARCH_URL,
            params={"q": query, "format": "json", "addressdetails": 1, "limit": limit},
        )
        response.raise_for_status()
        for item in response.json():
            yield self._to_record(item, query)

    def _to_record(self, item: dict, query: str) -> SourceRecord:
        address = item.get("address") or {}
        name = item.get("name") or (item.get("display_name") or "").split(",")[0].strip()
        latitude = item.get("lat")
        longitude = item.get("lon")
        payload = {
            "company_name": name,
            "country": address.get("country", ""),
            "address": item.get("display_name", ""),
            "latitude": float(latitude) if latitude is not None else None,
            "longitude": float(longitude) if longitude is not None else None,
            "categories": [item.get("type", "")],
            "external_id": f"{item.get('osm_type', '')}/{item.get('osm_id', '')}",
        }
        return SourceRecord(
            source=self.id,
            capability=self.capability,
            authenticity=self.authenticity,
            confidence=0.85,
            evidence={
                "source_url": "https://nominatim.openstreetmap.org",
                "query": query,
                "licence": item.get("licence", ""),
            },
            payload=payload,
            usage_rights="OpenStreetMap ODbL",
        )
