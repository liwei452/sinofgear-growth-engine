from __future__ import annotations

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
)


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
