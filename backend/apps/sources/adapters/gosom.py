from __future__ import annotations

import time
from typing import Iterator

import httpx

from ..authenticity import SourceAuthenticity, SourceCapability
from ..record import SourceRecord


_OPTION_FIELDS = (
    "lang",
    "max_depth",
    "email",
    "geo_coordinates",
    "zoom",
    "radius",
    "fast_mode",
    "extra_reviews",
    "timeout",
)


class GosomGoogleMapsAdapter:
    id = "gosom-google-maps"
    category = "local"
    capability = SourceCapability.DISCOVER
    authenticity = SourceAuthenticity.REAL
    requires_api_key = True
    rate_limit = 10
    enabled = True

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8080",
        api_key: str = "",
        client: httpx.Client | None = None,
        poll_interval: float = 2.0,
        max_polls: int = 150,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = client
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=30.0)
        return self._client

    def search(self, query: str, options: dict | None = None) -> Iterator[SourceRecord]:
        options = options or {}
        job_id = self._submit(query, options)
        for entry in self._poll(job_id):
            yield self._to_record(entry, query)

    def _submit(self, query: str, options: dict) -> str:
        body: dict = {"keyword": query}
        for field in _OPTION_FIELDS:
            if field in options:
                body[field] = options[field]
        response = self.client.post("/api/v1/scrape", json=body)
        response.raise_for_status()
        return str(response.json()["job_id"])

    def _poll(self, job_id: str) -> list[dict]:
        for _ in range(self.max_polls):
            response = self.client.get(f"/api/v1/jobs/{job_id}")
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "completed":
                return self._extract_results(data)
            if data.get("status") in {"failed", "cancelled", "discarded"}:
                raise RuntimeError(f"Gosom job {job_id} ended as {data.get('status')}.")
            time.sleep(self.poll_interval)
        raise RuntimeError(f"Gosom job {job_id} timed out.")

    def _extract_results(self, data: dict) -> list[dict]:
        results = data.get("results")
        if isinstance(results, list):
            return results
        if isinstance(results, dict):
            for key in ("results", "places", "entries", "items"):
                value = results.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _to_record(self, entry: dict, query: str) -> SourceRecord:
        entry = entry or {}
        complete = entry.get("complete_address") or {}
        longitude = entry.get("longitude")
        if longitude is None:
            longitude = entry.get("longtitude")
        payload = {
            "company_name": entry.get("title", ""),
            "country": complete.get("country", ""),
            "address": entry.get("address", ""),
            "website": entry.get("web_site", "") or entry.get("website", ""),
            "phone": entry.get("phone", ""),
            "latitude": entry.get("latitude"),
            "longitude": longitude,
            "review_rating": entry.get("review_rating"),
            "review_count": entry.get("review_count"),
            "categories": entry.get("categories", []),
            "external_id": entry.get("place_id") or entry.get("cid") or entry.get("data_id", ""),
        }
        return SourceRecord(
            source=self.id,
            capability=self.capability,
            authenticity=self.authenticity,
            confidence=0.9,
            evidence={"source_url": entry.get("link", ""), "query": query},
            payload=payload,
        )
