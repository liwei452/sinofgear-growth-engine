from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from .buffer_client import BufferGraphQLClient
from .buffer_types import (
    BufferAccount,
    BufferApiError,
    BufferChannel,
    BufferDiscoveryRequest,
    BufferDiscoveryResult,
    BufferErrorCode,
    BufferIgnoredChannel,
    BufferOrganization,
    BufferProbeResult,
    BufferPostObservation,
    BufferPostQueryRequest,
    BufferPostQueryResult,
)
from .base import OfficialPublishRequest, OfficialPublishResult


SUPPORTED_BUFFER_SERVICES = {
    "linkedin": "LINKEDIN",
    "facebook": "FACEBOOK",
    "instagram": "INSTAGRAM",
}

_UNSUPPORTED_SERVICE_REASON = "该平台暂不支持通过 Buffer 同步。"

MAX_FIELD_LENGTH = 255
MAX_LIST_ITEMS = 200
MAX_LIST_STRING_LENGTH = 512


class BufferConnector:
    def __init__(self, client: BufferGraphQLClient, token_store) -> None:
        self._client = client
        self._token_store = token_store

    def probe_connection(self, request: BufferDiscoveryRequest) -> BufferProbeResult:
        try:
            token, organization_id = self._resolve(request)
        except BufferApiError as error:
            return _probe_failure(error)
        try:
            response = self._client.fetch_account(token)
        except BufferApiError as error:
            return _probe_failure(error)
        try:
            account = _parse_account(response.data)
            _match_organization(account, organization_id)
        except BufferApiError as error:
            return _probe_failure(error)
        return BufferProbeResult(ok=True, account=account, rate_limit=response.rate_limit)

    def discover_channels(self, request: BufferDiscoveryRequest) -> BufferDiscoveryResult:
        try:
            token, organization_id = self._resolve(request)
        except BufferApiError as error:
            return _discovery_failure(error)
        try:
            account_response = self._client.fetch_account(token)
        except BufferApiError as error:
            return _discovery_failure(error)
        try:
            account = _parse_account(account_response.data)
            _match_organization(account, organization_id)
        except BufferApiError as error:
            return _discovery_failure(error)
        try:
            channels_response = self._client.fetch_channels(token, organization_id)
        except BufferApiError as error:
            return _discovery_failure(error)
        try:
            channels, ignored = _normalize_channels(
                channels_response.data, organization_id
            )
        except BufferApiError as error:
            return _discovery_failure(error)
        return BufferDiscoveryResult(
            ok=True,
            provider_organization_id=organization_id,
            channels=channels,
            ignored_channels=ignored,
            rate_limit=channels_response.rate_limit,
        )

    def publish(self, request: OfficialPublishRequest) -> OfficialPublishResult:
        try:
            token = self._resolve_publish_token(request)
            post_input = _build_post_input(request)
        except BufferApiError as error:
            return _publish_failure(error)
        try:
            response = self._client.create_post(token, post_input)
        except BufferApiError as error:
            return _publish_failure(error)
        return _parse_publish_result(response.data, request.provider_account_id)

    def fetch_post(self, request: BufferPostQueryRequest) -> BufferPostQueryResult:
        try:
            token = self._resolve_query_token(request)
            response = self._client.fetch_post(token, request.provider_submission_id)
            observation = _parse_post_observation(response.data)
        except BufferApiError as error:
            return BufferPostQueryResult(
                ok=False,
                error_code=error.code.value,
                retry_after_seconds=error.retry_after_seconds,
            )
        return BufferPostQueryResult(ok=True, observation=observation)

    def _resolve_query_token(self, request: BufferPostQueryRequest) -> str:
        reference = request.credential_reference
        if type(reference) is not str or not reference.strip():
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        try:
            token = self._token_store.resolve(reference).access_token
        except Exception:
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED) from None
        if type(token) is not str or not token.strip():
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        return token

    def _resolve_publish_token(self, request: OfficialPublishRequest) -> str:
        reference = request.credential_reference
        if not isinstance(reference, str) or not reference.strip():
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        try:
            token = self._token_store.resolve(reference).access_token
        except Exception:
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED) from None
        if not isinstance(token, str) or not token.strip():
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        return token

    def _resolve(self, request: BufferDiscoveryRequest) -> tuple[str, str]:
        expected_organization_id = request.expected_organization_id
        if not isinstance(expected_organization_id, str) or not expected_organization_id.strip():
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        return self._resolve_token(request), expected_organization_id.strip()

    def _resolve_token(self, request: BufferDiscoveryRequest) -> str:
        reference = request.credential_reference
        if not isinstance(reference, str) or not reference.strip():
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        try:
            token = self._token_store.resolve(reference).access_token
        except Exception:
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED) from None
        if not isinstance(token, str) or not token.strip():
            raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
        return token


def _probe_failure(error: BufferApiError) -> BufferProbeResult:
    return BufferProbeResult(
        ok=False,
        error_code=error.code.value,
        error_message=error.message,
    )


def _discovery_failure(error: BufferApiError) -> BufferDiscoveryResult:
    return BufferDiscoveryResult(
        ok=False,
        error_code=error.code.value,
        error_message=error.message,
    )


_SAFE_PUBLISH_MESSAGES = {
    "VALIDATION_REJECTED": "Buffer 发布内容未通过校验。",
    "BUFFER_PROVIDER_CAPACITY": "Buffer 发布容量已达到限制。",
    "BUFFER_CHANNEL_NOT_FOUND": "Buffer 渠道不存在或已失效。",
    "PUBLISH_NOT_ELIGIBLE": "Buffer 发布连接尚未完成配置。",
    "REAUTHORIZATION_REQUIRED": "Buffer 授权已失效，请重新连接。",
    "RATE_LIMITED": "Buffer 请求过于频繁，请稍后重试。",
    "OUTCOME_UNKNOWN": "Buffer 提交结果无法确定，请先对账后再处理。",
}


def _publish_failure(error: BufferApiError) -> OfficialPublishResult:
    mapping = {
        BufferErrorCode.CONFIGURATION_REQUIRED: "PUBLISH_NOT_ELIGIBLE",
        BufferErrorCode.AUTHENTICATION_REQUIRED: "REAUTHORIZATION_REQUIRED",
        BufferErrorCode.RATE_LIMITED: "RATE_LIMITED",
        BufferErrorCode.OUTCOME_UNKNOWN: "OUTCOME_UNKNOWN",
        BufferErrorCode.INVALID_INPUT: "VALIDATION_REJECTED",
        BufferErrorCode.CHANNEL_NOT_FOUND: "BUFFER_CHANNEL_NOT_FOUND",
    }
    code = mapping.get(error.code, "OUTCOME_UNKNOWN")
    return OfficialPublishResult(
        status="FAILED",
        error_code=code,
        error_message=_SAFE_PUBLISH_MESSAGES[code],
        retryable=code == "RATE_LIMITED",
        retry_after_seconds=error.retry_after_seconds,
    )


def _require_publish_text(value) -> str:
    if not isinstance(value, str) or not (value := value.strip()) or len(value) > 50_000:
        raise BufferApiError(BufferErrorCode.INVALID_INPUT)
    return value


def _optional_public_https_url(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not (value := value.strip()):
        raise BufferApiError(BufferErrorCode.INVALID_INPUT)
    if len(value) > 2_048 or not value.startswith("https://"):
        raise BufferApiError(BufferErrorCode.INVALID_INPUT)
    return value


def _build_post_input(request: OfficialPublishRequest) -> dict:
    channel_id = request.provider_account_id
    if (
        not isinstance(channel_id, str)
        or not (channel_id := channel_id.strip())
        or len(channel_id) > MAX_FIELD_LENGTH
        or not isinstance(request.payload, dict)
    ):
        raise BufferApiError(BufferErrorCode.CONFIGURATION_REQUIRED)
    channel = (request.channel or "").strip().upper()
    text_field = {
        "LINKEDIN": "commentary",
        "FACEBOOK": "message",
        "INSTAGRAM": "caption",
    }.get(channel)
    if text_field is None:
        raise BufferApiError(BufferErrorCode.INVALID_INPUT)
    result = {
        "channelId": channel_id,
        "text": _require_publish_text(request.payload.get(text_field)),
        "schedulingType": "automatic",
        "mode": "shareNow",
    }
    image_url = _optional_public_https_url(request.payload.get("image_url"))
    video_url = _optional_public_https_url(request.payload.get("video_url"))
    if image_url and video_url:
        raise BufferApiError(BufferErrorCode.INVALID_INPUT)
    if channel in {"LINKEDIN", "FACEBOOK"} and video_url:
        raise BufferApiError(BufferErrorCode.INVALID_INPUT)
    if channel == "INSTAGRAM" and not (image_url or video_url):
        raise BufferApiError(BufferErrorCode.INVALID_INPUT)
    if image_url:
        result["assets"] = [{"image": {"url": image_url}}]
    elif video_url:
        result["assets"] = [{"video": {"url": video_url}}]
    return result


def _parse_publish_result(data: dict, expected_channel_id: str) -> OfficialPublishResult:
    create_post = data.get("createPost") if isinstance(data, dict) else None
    if not isinstance(create_post, dict):
        return _unknown_publish_result()
    typename = create_post.get("__typename")
    if typename == "PostActionSuccess":
        post = create_post.get("post")
        if not isinstance(post, dict):
            return _unknown_publish_result()
        post_id = post.get("id")
        channel_id = post.get("channelId")
        if (
            not isinstance(post_id, str)
            or not (post_id := post_id.strip())
            or len(post_id) > MAX_FIELD_LENGTH
            or channel_id != expected_channel_id
        ):
            return _unknown_publish_result()
        return OfficialPublishResult(status="SUBMITTED", submission_id=post_id)
    error_mapping = {
        "InvalidInputError": "VALIDATION_REJECTED",
        "LimitReachedError": "BUFFER_PROVIDER_CAPACITY",
        "NotFoundError": "BUFFER_CHANNEL_NOT_FOUND",
    }
    code = error_mapping.get(typename)
    if code is None:
        return _unknown_publish_result()
    return OfficialPublishResult(
        status="FAILED",
        error_code=code,
        error_message=_SAFE_PUBLISH_MESSAGES[code],
    )


def _unknown_publish_result() -> OfficialPublishResult:
    return OfficialPublishResult(
        status="FAILED",
        error_code="OUTCOME_UNKNOWN",
        error_message=_SAFE_PUBLISH_MESSAGES["OUTCOME_UNKNOWN"],
    )


_POST_STATUSES = {"draft", "error", "needs_approval", "scheduled", "sending", "sent"}
_POST_SERVICES = {key for key in SUPPORTED_BUFFER_SERVICES}


def _bounded_native_string(value, *, allow_blank=False, maximum=255) -> str:
    if type(value) is not str:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    value = value.strip()
    if (not allow_blank and not value) or len(value) > maximum:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    return value


def _optional_timestamp(value):
    if value is None:
        return None
    value = _bounded_native_string(value, maximum=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR) from None
    if parsed.tzinfo is None:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    parsed = parsed.astimezone(timezone.utc)
    if not (datetime(2000, 1, 1, tzinfo=timezone.utc) <= parsed <= datetime(2100, 1, 1, tzinfo=timezone.utc)):
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    return parsed


def _optional_public_url(value) -> str:
    if value is None or value == "":
        return ""
    value = _bounded_native_string(value, maximum=2048)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    return value


def _parse_post_observation(data) -> BufferPostObservation:
    post = data.get("post") if type(data) is dict else None
    if type(post) is not dict:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    post_id = _bounded_native_string(post.get("id"))
    channel_id = _bounded_native_string(post.get("channelId"))
    service = _bounded_native_string(post.get("channelService"), maximum=32).lower()
    status = _bounded_native_string(post.get("status"), maximum=32).lower()
    if service not in _POST_SERVICES or status not in _POST_STATUSES:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    return BufferPostObservation(
        post_id=post_id,
        channel_id=channel_id,
        channel_service=service,
        status=status,
        due_at=_optional_timestamp(post.get("dueAt")),
        sent_at=_optional_timestamp(post.get("sentAt")),
        external_link=_optional_public_url(post.get("externalLink")),
        created_at=_optional_timestamp(post.get("createdAt")),
        updated_at=_optional_timestamp(post.get("updatedAt")),
    )


def _parse_account(data: dict) -> BufferAccount:
    account = data.get("account")
    if not isinstance(account, dict):
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    account_id = account.get("id")
    if not isinstance(account_id, str) or not account_id.strip():
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    account_id = account_id.strip()
    name = account.get("name")
    if name is not None and not isinstance(name, str):
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)

    organizations_raw = account.get("organizations")
    if not isinstance(organizations_raw, list):
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    organizations = []
    seen_ids: set[str] = set()
    for item in organizations_raw:
        if not isinstance(item, dict):
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        organization_id = item.get("id")
        if not isinstance(organization_id, str) or not organization_id.strip():
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        organization_id = organization_id.strip()
        if len(organization_id) > MAX_FIELD_LENGTH:
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        organization_name = item.get("name")
        if organization_name is not None and not isinstance(organization_name, str):
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        normalized_name = organization_name or ""
        if len(normalized_name) > MAX_FIELD_LENGTH:
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        if organization_id in seen_ids:
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        seen_ids.add(organization_id)
        organizations.append(
            BufferOrganization(
                provider_organization_id=organization_id,
                name=normalized_name,
            )
        )
    return BufferAccount(
        id=account_id,
        name=name or "",
        organizations=tuple(organizations),
    )


def _match_organization(account: BufferAccount, expected_organization_id: str) -> str:
    for organization in account.organizations:
        if organization.provider_organization_id == expected_organization_id:
            return expected_organization_id
    raise BufferApiError(BufferErrorCode.ORGANIZATION_NOT_FOUND)


def _normalize_channels(
    data: dict, expected_organization_id: str
) -> tuple[tuple[BufferChannel, ...], tuple[BufferIgnoredChannel, ...]]:
    channels_raw = data.get("channels")
    if not isinstance(channels_raw, list):
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)

    channels = []
    ignored = []
    seen_ids: set[str] = set()
    seen_service_ids: dict[str, set[str]] = {}
    for item in channels_raw:
        if not isinstance(item, dict):
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)

        channel_id = _require_nonempty_string(item.get("id"), MAX_FIELD_LENGTH)
        service_id = _require_nonempty_string(item.get("serviceId"), MAX_FIELD_LENGTH)
        name = _require_nonempty_string(item.get("name"), MAX_FIELD_LENGTH)
        service = item.get("service")
        if not isinstance(service, str) or not service:
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        organization_id = item.get("organizationId")
        if not isinstance(organization_id, str) or organization_id != expected_organization_id:
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)

        if channel_id in seen_ids:
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        seen_ids.add(channel_id)
        if service_id in seen_service_ids.setdefault(service, set()):
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        seen_service_ids[service].add(service_id)

        for boolean_field in ("isDisconnected", "isLocked", "isQueuePaused"):
            if not isinstance(item.get(boolean_field), bool):
                raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)

        allowed_actions = _require_string_list(item.get("allowedActions"))
        products = _require_string_list(item.get("products"))
        scopes = _require_string_list(item.get("scopes"))
        display_name = _optional_string(item.get("displayName"))
        avatar = _optional_string(item.get("avatar"))
        external_link = _optional_string(item.get("externalLink"))
        channel_type = _optional_string(item.get("type"))

        platform_code = SUPPORTED_BUFFER_SERVICES.get(service)
        if platform_code is None:
            ignored.append(
                BufferIgnoredChannel(
                    provider_account_id=channel_id,
                    service=service,
                    reason=_UNSUPPORTED_SERVICE_REASON,
                )
            )
            continue

        final_display_name = (display_name or name).strip()
        if len(final_display_name) > MAX_FIELD_LENGTH:
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        channels.append(
            BufferChannel(
                provider_account_id=channel_id,
                external_id=service_id,
                display_name=final_display_name,
                provider="BUFFER",
                platform_code=platform_code,
                service=service,
                channel_type=channel_type,
                avatar=avatar,
                external_link=external_link,
                organization_id=expected_organization_id,
                is_disconnected=bool(item["isDisconnected"]),
                is_locked=bool(item["isLocked"]),
                is_queue_paused=bool(item["isQueuePaused"]),
                allowed_actions=allowed_actions,
                products=products,
                scopes=scopes,
            )
        )
    return tuple(channels), tuple(ignored)


def _require_nonempty_string(value, max_length: int) -> str:
    if not isinstance(value, str):
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    stripped = value.strip()
    if not stripped:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    if len(stripped) > max_length:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    return stripped


def _optional_string(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    return value


def _require_string_list(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    if len(value) > MAX_LIST_ITEMS:
        raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
    items = []
    for item in value:
        if not isinstance(item, str):
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        if len(item) > MAX_LIST_STRING_LENGTH:
            raise BufferApiError(BufferErrorCode.CONTRACT_ERROR)
        items.append(item)
    return tuple(items)
