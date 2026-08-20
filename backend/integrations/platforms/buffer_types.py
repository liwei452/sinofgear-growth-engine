from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class BufferErrorCode(str, Enum):
    CONFIGURATION_REQUIRED = "BUFFER_CONFIGURATION_REQUIRED"
    AUTHENTICATION_REQUIRED = "BUFFER_AUTHENTICATION_REQUIRED"
    RATE_LIMITED = "BUFFER_RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "BUFFER_PROVIDER_UNAVAILABLE"
    CONTRACT_ERROR = "BUFFER_CONTRACT_ERROR"
    ORGANIZATION_NOT_FOUND = "BUFFER_ORGANIZATION_NOT_FOUND"
    OUTCOME_UNKNOWN = "BUFFER_OUTCOME_UNKNOWN"
    INVALID_INPUT = "BUFFER_INVALID_INPUT"
    CHANNEL_NOT_FOUND = "BUFFER_CHANNEL_NOT_FOUND"
    POST_NOT_FOUND = "BUFFER_POST_NOT_FOUND"


SAFE_BUFFER_MESSAGES: dict[BufferErrorCode, str] = {
    BufferErrorCode.CONFIGURATION_REQUIRED: "Buffer 连接尚未完成配置。",
    BufferErrorCode.AUTHENTICATION_REQUIRED: "Buffer 授权已失效，请重新连接。",
    BufferErrorCode.RATE_LIMITED: "Buffer 请求过于频繁，请稍后重试。",
    BufferErrorCode.PROVIDER_UNAVAILABLE: "Buffer 服务暂时不可用，请稍后重试。",
    BufferErrorCode.CONTRACT_ERROR: "Buffer 返回了无法识别的数据。",
    BufferErrorCode.ORGANIZATION_NOT_FOUND: "未找到匹配的 Buffer 组织。",
    BufferErrorCode.OUTCOME_UNKNOWN: "Buffer 提交结果无法确定，请先对账后再处理。",
    BufferErrorCode.INVALID_INPUT: "Buffer 发布内容未通过校验。",
    BufferErrorCode.CHANNEL_NOT_FOUND: "Buffer 渠道不存在或已失效。",
    BufferErrorCode.POST_NOT_FOUND: "Buffer 帖子不存在或不可访问。",
}


class BufferApiError(Exception):
    """Safe, normalized Buffer provider error.

    The message is always a fixed, safe Chinese prompt. The raw GraphQL
    message, response body and bearer token are never attached here.
    """

    def __init__(
        self,
        code: BufferErrorCode | str,
        *,
        message: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.code = code if isinstance(code, BufferErrorCode) else BufferErrorCode(code)
        self.message = message or SAFE_BUFFER_MESSAGES[self.code]
        self.retry_after_seconds = retry_after_seconds
        super().__init__(self.message)

    def __repr__(self) -> str:
        return (
            "BufferApiError("
            f"code={self.code.value!r}, message={self.message!r}, "
            f"retry_after_seconds={self.retry_after_seconds!r})"
        )


@dataclass(frozen=True)
class BufferOrganization:
    provider_organization_id: str
    name: str


@dataclass(frozen=True)
class BufferAccount:
    id: str
    name: str
    organizations: tuple[BufferOrganization, ...] = ()


@dataclass(frozen=True)
class BufferChannel:
    provider_account_id: str
    external_id: str
    display_name: str
    provider: str = "BUFFER"
    platform_code: str = ""
    service: str = ""
    channel_type: str = ""
    avatar: str = ""
    external_link: str = ""
    organization_id: str = ""
    is_disconnected: bool = False
    is_locked: bool = False
    is_queue_paused: bool = False
    allowed_actions: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BufferIgnoredChannel:
    provider_account_id: str
    service: str
    reason: str


@dataclass(frozen=True)
class BufferDiscoveryRequest:
    credential_reference: str = field(repr=False)
    expected_organization_id: str


@dataclass(frozen=True)
class BufferRateLimitWindow:
    window_seconds: int | None = None
    remaining: int | None = None
    reset_after_seconds: int | None = None
    quota: int | None = None


@dataclass(frozen=True)
class BufferRateLimitResult:
    windows: tuple[BufferRateLimitWindow, ...] = ()
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class BufferProbeResult:
    ok: bool
    error_code: str = ""
    error_message: str = ""
    account: BufferAccount | None = None
    rate_limit: BufferRateLimitResult | None = None


@dataclass(frozen=True)
class BufferDiscoveryResult:
    ok: bool
    error_code: str = ""
    error_message: str = ""
    provider_organization_id: str = ""
    channels: tuple[BufferChannel, ...] = ()
    ignored_channels: tuple[BufferIgnoredChannel, ...] = ()
    rate_limit: BufferRateLimitResult | None = None


@dataclass(frozen=True)
class BufferPostQueryRequest:
    credential_reference: str = field(repr=False)
    provider_submission_id: str


@dataclass(frozen=True)
class BufferPostObservation:
    post_id: str
    channel_id: str
    channel_service: str
    status: str
    due_at: datetime | None = None
    sent_at: datetime | None = None
    external_link: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class BufferPostQueryResult:
    ok: bool
    observation: BufferPostObservation | None = None
    error_code: str = ""
    retry_after_seconds: int | None = None
