from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    json_body: dict
    headers: dict[str, str]


class HttpTransport(Protocol):
    def request(
        self, method: str, url: str, *, headers: dict[str, str],
        json: dict | None, timeout_seconds: int,
    ) -> HttpResponse: ...
