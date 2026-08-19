from __future__ import annotations

from typing import Iterator

import httpx

from ..authenticity import SourceAuthenticity, SourceCapability
from ..record import SourceRecord


_PROVIDERS = (
    ("google", "Google Workspace"),
    ("gmail", "Google Workspace"),
    ("outlook", "Microsoft 365"),
    ("microsoft", "Microsoft 365"),
    ("proton", "ProtonMail"),
    ("zoho", "Zoho"),
    ("amazon", "Amazon SES"),
    ("ses", "Amazon SES"),
)


class DnsLookupAdapter:
    id = "dns-lookup"
    category = "email"
    capability = SourceCapability.VERIFY
    authenticity = SourceAuthenticity.REAL
    requires_api_key = False
    rate_limit = 120
    enabled = True

    DNS_URL = "https://dns.google/resolve"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=30.0)
        return self._client

    def verify(self, target: dict, options: dict | None = None) -> Iterator[SourceRecord]:
        del options
        domain = self._domain(target)
        if not domain:
            return
        mx = self._resolve(domain, "MX")
        a = self._resolve(domain, "A")
        mx_servers = [ans["data"].split()[-1] for ans in mx.get("Answer", [])]
        ip_addresses = [ans["data"] for ans in a.get("Answer", [])]
        has_mx = mx.get("Status") == 0 and bool(mx_servers)
        has_a = a.get("Status") == 0 and bool(ip_addresses)
        yield SourceRecord(
            source=self.id,
            capability=self.capability,
            authenticity=self.authenticity,
            confidence=0.7 if has_mx else 0.3,
            evidence={"source_url": "https://dns.google/resolve", "domain": domain},
            payload={
                "domain": domain,
                "has_mx": has_mx,
                "has_a": has_a,
                "mx_servers": mx_servers,
                "ip_addresses": ip_addresses,
                "email_provider": self._provider(mx_servers[0]) if mx_servers else "",
            },
        )

    def _domain(self, target: dict) -> str:
        domain = (target.get("domain") or "").strip()
        if not domain and target.get("email"):
            domain = target["email"].split("@")[-1]
        return domain if domain and "." in domain else ""

    def _resolve(self, domain: str, record_type: str) -> dict:
        response = self.client.get(
            self.DNS_URL, params={"name": domain, "type": record_type}
        )
        response.raise_for_status()
        return response.json()

    def _provider(self, mx_host: str) -> str:
        lower = mx_host.lower()
        for needle, label in _PROVIDERS:
            if needle in lower:
                return label
        return "custom"
