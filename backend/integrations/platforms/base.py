from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class PublishRequest:
    task_id: UUID
    attempt_number: int
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


class ConnectorConfigurationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class OfficialPublishRequest:
    channel: str
    account_external_id: str
    credential_reference: str
    payload: dict
    idempotency_key: str
    consent: dict


@dataclass(frozen=True)
class OfficialPublishResult:
    status: str
    external_id: str = ""
    external_url: str = ""
    submission_id: str = ""
    error_code: str = ""
    error_message: str = ""
    retryable: bool = False
    retry_after_seconds: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.status in {"SUCCEEDED", "SUCCEEDED_PRIVATE"}

    @property
    def submitted(self) -> bool:
        return self.status == "SUBMITTED"


class OfficialConnector(Protocol):
    def publish(self, request: OfficialPublishRequest) -> OfficialPublishResult: ...


def provider_failure(
    status_code: int, *, retry_after: str | None = None,
) -> OfficialPublishResult:
    retry_after_seconds = None
    if status_code == 401:
        code, retryable = "REAUTHORIZATION_REQUIRED", False
    elif status_code == 429:
        code, retryable = "RATE_LIMITED", True
        try:
            retry_after_seconds = max(0, int(retry_after or ""))
        except ValueError:
            retry_after_seconds = None
    elif status_code >= 500:
        code, retryable = "PROVIDER_UNAVAILABLE", True
    else:
        code, retryable = "VALIDATION_REJECTED", False
    return OfficialPublishResult(
        status="FAILED",
        error_code=code,
        error_message="平台暂时无法接受这次发布，请按提示处理后重试。",
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )


def timeout_failure() -> OfficialPublishResult:
    return OfficialPublishResult(
        status="FAILED",
        error_code="OUTCOME_UNKNOWN",
        error_message="平台响应超时，系统会先核对发布结果再重试。",
        retryable=True,
    )
