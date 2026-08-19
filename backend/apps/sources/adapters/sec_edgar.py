from __future__ import annotations

from typing import Iterator

import httpx

from ..authenticity import SourceAuthenticity, SourceCapability
from ..record import SourceRecord


class SECEdgarAdapter:
    id = "sec-edgar"
    category = "company"
    capability = SourceCapability.RESEARCH
    authenticity = SourceAuthenticity.REAL
    requires_api_key = False
    rate_limit = 10
    enabled = True

    SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

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
        count = min(int(options.get("count", 10)), 50)
        response = self.client.get(
            self.SEARCH_URL,
            params={
                "q": query,
                "dateRange": "custom",
                "startdt": options.get("startdt", "2020-01-01"),
                "enddt": options.get("enddt", "2026-12-31"),
                "size": count,
            },
        )
        response.raise_for_status()
        hits = (response.json().get("hits") or {}).get("hits") or []
        for hit in hits:
            yield self._to_record(hit.get("_source") or {}, query)

    def _to_record(self, source: dict, query: str) -> SourceRecord:
        entity_name = source.get("entity_name", "")
        cik = (source.get("ciks") or [None])[0]
        payload = {
            "company_name": entity_name,
            "external_id": cik,
            "website": (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
                if cik
                else ""
            ),
            "metadata": {
                "entity_type": source.get("entity_type", ""),
                "file_date": source.get("file_date", ""),
                "form_type": source.get("form_type", ""),
                "description": source.get("file_description", ""),
            },
        }
        return SourceRecord(
            source=self.id,
            capability=self.capability,
            authenticity=self.authenticity,
            confidence=0.7,
            evidence={"source_url": "https://efts.sec.gov", "query": query},
            payload=payload,
            usage_rights="SEC EDGAR public data",
        )
