from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class PublishRequest:
    task_id: UUID
    platform_code: str
    account_external_id: str
    content_payload: dict
    scheduled_at: datetime | None


@dataclass(frozen=True)
class PublishResult:
    succeeded: bool
    external_id: str = ""
    error_code: str = ""
    error_message: str = ""
    retry_after_seconds: int | None = None


class PlatformConnector(Protocol):
    def publish(self, request: PublishRequest) -> PublishResult: ...
