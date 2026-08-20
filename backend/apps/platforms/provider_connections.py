from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.identity.models import Organization
from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.buffer_client import BufferGraphQLClient, BufferHttpTransport
from integrations.platforms.buffer_connector import BufferConnector
from integrations.platforms.buffer_types import BufferDiscoveryRequest, BufferIgnoredChannel
from integrations.platforms.token_store import OAuthTokenSet, TokenStoreContext

from .models import (
    Platform,
    ProviderConnection,
    ProviderConnectionEvent,
    SocialAccount,
    provider_event_writes,
)


logger = logging.getLogger(__name__)


SAFE_ERROR_MESSAGES = {
    "BUFFER_ALREADY_CONNECTED": "Buffer 已连接，请先断开后再重新连接。",
    "BUFFER_CONNECTION_NOT_FOUND": "尚未配置 Buffer 连接。",
    "BUFFER_CONFIGURATION_REQUIRED": "Buffer 连接尚未完成配置。",
    "BUFFER_AUTHENTICATION_REQUIRED": "Buffer 授权已失效，请重新连接。",
    "BUFFER_ORGANIZATION_NOT_FOUND": "未找到匹配的 Buffer 组织。",
    "BUFFER_RATE_LIMITED": "Buffer 请求过于频繁，请稍后重试。",
    "BUFFER_PROVIDER_UNAVAILABLE": "Buffer 服务暂时不可用，请稍后重试。",
    "BUFFER_CONTRACT_ERROR": "Buffer 返回了无法识别的数据。",
    "BUFFER_CONNECTION_CHANGED": "Buffer 连接已发生变化，请重试。",
    "BUFFER_CHANNEL_MAPPING_CONFLICT": "Buffer 渠道映射发生冲突，无法同步。",
}

_ERROR_HTTP_STATUS = {
    "BUFFER_ALREADY_CONNECTED": 409,
    "BUFFER_CONNECTION_NOT_FOUND": 404,
    "BUFFER_CONFIGURATION_REQUIRED": 409,
    "BUFFER_AUTHENTICATION_REQUIRED": 409,
    "BUFFER_ORGANIZATION_NOT_FOUND": 400,
    "BUFFER_RATE_LIMITED": 429,
    "BUFFER_PROVIDER_UNAVAILABLE": 503,
    "BUFFER_CONTRACT_ERROR": 502,
    "BUFFER_CONNECTION_CHANGED": 409,
    "BUFFER_CHANNEL_MAPPING_CONFLICT": 409,
}


class BufferConnectionError(Exception):
    def __init__(self, code: str, *, message: str | None = None, http_status: int | None = None):
        self.code = code
        self.message = message or SAFE_ERROR_MESSAGES.get(code, "Buffer 连接操作失败。")
        self.http_status = http_status or _ERROR_HTTP_STATUS.get(code, 409)
        super().__init__(self.message)


@dataclass(frozen=True)
class BufferSyncResult:
    created_count: int
    updated_count: int
    disconnected_count: int
    ignored_channels: tuple[BufferIgnoredChannel, ...]
    synced_at: datetime


def build_buffer_connector(token_store) -> BufferConnector:
    return BufferConnector(BufferGraphQLClient(BufferHttpTransport()), token_store)


def _buffer_connection(organization, *, for_update: bool = False) -> ProviderConnection:
    queryset = ProviderConnection.objects.filter(
        organization=organization,
        provider=ProviderConnection.Provider.BUFFER,
    )
    if for_update:
        queryset = queryset.select_for_update()
    try:
        return queryset.get()
    except ProviderConnection.DoesNotExist as error:
        raise BufferConnectionError("BUFFER_CONNECTION_NOT_FOUND") from error


def get_buffer_connection(organization) -> ProviderConnection:
    return _buffer_connection(organization)


def _lock_organization(organization) -> None:
    Organization.objects.select_for_update().get(pk=organization.pk)


def _map_buffer_error_code(code: str) -> BufferConnectionError:
    normalized = code if code in _ERROR_HTTP_STATUS else "BUFFER_CONTRACT_ERROR"
    return BufferConnectionError(normalized)


def _probe_state(code: str) -> tuple[str, bool]:
    if code == "BUFFER_CONFIGURATION_REQUIRED":
        return ProviderConnection.ConnectionState.CONFIGURATION_REQUIRED, False
    if code in {"BUFFER_AUTHENTICATION_REQUIRED", "BUFFER_ORGANIZATION_NOT_FOUND"}:
        return ProviderConnection.ConnectionState.REAUTHORIZATION_REQUIRED, True
    return ProviderConnection.ConnectionState.PROVIDER_UNAVAILABLE, False


def _record_event(
    *,
    organization,
    provider_connection,
    actor,
    action: str,
    outcome: str,
    error_code: str = "",
    metadata: dict | None = None,
) -> None:
    with provider_event_writes():
        ProviderConnectionEvent.objects.create(
            organization=organization,
            provider_connection=provider_connection,
            provider=ProviderConnection.Provider.BUFFER,
            actor=actor,
            action=action,
            outcome=outcome,
            error_code=error_code,
            metadata=metadata or {},
        )


def _record_event_quietly(
    *,
    organization,
    provider_connection,
    actor,
    action: str,
    outcome: str,
    error_code: str = "",
    metadata: dict | None = None,
) -> None:
    try:
        _record_event(
            organization=organization,
            provider_connection=provider_connection,
            actor=actor,
            action=action,
            outcome=outcome,
            error_code=error_code,
            metadata=metadata,
        )
    except Exception:
        return


def _store_credential(token_store, organization, actor, api_key: str, attempt_id) -> str:
    try:
        return token_store.store(
            OAuthTokenSet(access_token=api_key, token_type="Bearer"),
            TokenStoreContext(
                organization_id=organization.id,
                actor_id=actor.id,
                platform_code="BUFFER",
                attempt_id=attempt_id,
            ),
        )
    except Exception:
        raise BufferConnectionError("BUFFER_CONFIGURATION_REQUIRED") from None


def _delete_credential(token_store, reference: str) -> None:
    """Delete a credential, treating "already gone" as success and propagating real failures."""
    if not reference:
        return
    try:
        token_store.delete(reference)
    except ConnectorConfigurationRequired:
        return


def _delete_credential_quietly(token_store, reference: str) -> None:
    try:
        _delete_credential(token_store, reference)
    except Exception:
        logger.warning("Buffer credential cleanup deferred for orphan reclamation.")
        return


def _matched_organization_name(probe_result, organization_id: str) -> str:
    account = probe_result.account
    if account is None:
        return ""
    for organization in account.organizations:
        if organization.provider_organization_id == organization_id:
            return organization.name
    return account.name


def _connected_values(*, reference, external_id, display_name, now):
    return {
        "credential_reference": reference,
        "external_id": external_id,
        "display_name": display_name,
        "connection_state": ProviderConnection.ConnectionState.CONNECTED,
        "last_probe_at": now,
        "disconnected_at": None,
        "reauthorization_required_at": None,
        "lifecycle_error_code": "",
    }


def connect_buffer(
    *,
    organization,
    actor,
    api_key: str,
    organization_id: str,
    token_store,
    connector,
    clock=timezone.now,
) -> ProviderConnection:
    if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 4096:
        raise BufferConnectionError("BUFFER_CONFIGURATION_REQUIRED")
    if not isinstance(organization_id, str) or not organization_id.strip() or len(organization_id.strip()) > 255:
        raise BufferConnectionError("BUFFER_ORGANIZATION_NOT_FOUND")
    organization_id = organization_id.strip()

    existing = ProviderConnection.objects.filter(
        organization=organization,
        provider=ProviderConnection.Provider.BUFFER,
    ).first()
    if existing is not None and existing.connection_state == ProviderConnection.ConnectionState.CONNECTED:
        raise BufferConnectionError("BUFFER_ALREADY_CONNECTED")
    connection_id = existing.id if existing is not None else uuid4()

    temporary_reference = _store_credential(
        token_store, organization, actor, api_key, connection_id,
    )
    try:
        probe_result = connector.probe_connection(
            BufferDiscoveryRequest(
                credential_reference=temporary_reference,
                expected_organization_id=organization_id,
            )
        )
    except Exception:
        _delete_credential_quietly(token_store, temporary_reference)
        raise BufferConnectionError("BUFFER_PROVIDER_UNAVAILABLE") from None
    if not probe_result.ok:
        _delete_credential_quietly(token_store, temporary_reference)
        _record_event_quietly(
            organization=organization,
            provider_connection=existing,
            actor=actor,
            action=ProviderConnectionEvent.Action.CONNECT,
            outcome=ProviderConnectionEvent.Outcome.FAILED,
            error_code=probe_result.error_code,
        )
        raise _map_buffer_error_code(probe_result.error_code)

    display_name = _matched_organization_name(probe_result, organization_id)
    now = clock()
    try:
        with transaction.atomic():
            _lock_organization(organization)
            locked = ProviderConnection.objects.filter(
                organization=organization,
                provider=ProviderConnection.Provider.BUFFER,
            ).select_for_update().first()
            if locked is not None and locked.connection_state == ProviderConnection.ConnectionState.CONNECTED:
                raise BufferConnectionError("BUFFER_ALREADY_CONNECTED")
            old_reference = locked.credential_reference if locked is not None else ""
            if locked is None:
                connection = ProviderConnection.objects.create(
                    organization=organization,
                    provider=ProviderConnection.Provider.BUFFER,
                    **_connected_values(
                        reference=temporary_reference,
                        external_id=organization_id,
                        display_name=display_name,
                        now=now,
                    ),
                )
            else:
                _apply_connected(locked, temporary_reference, organization_id, display_name, now)
                connection = locked
                if old_reference and old_reference != temporary_reference:
                    _delete_credential(token_store, old_reference)
            _record_event(
                organization=organization,
                provider_connection=connection,
                actor=actor,
                action=ProviderConnectionEvent.Action.CONNECT,
                outcome=ProviderConnectionEvent.Outcome.SUCCESS,
            )
    except Exception:
        _delete_credential_quietly(token_store, temporary_reference)
        raise
    return connection


def _apply_connected(connection, reference, external_id, display_name, now) -> None:
    connection.credential_reference = reference
    connection.external_id = external_id
    connection.display_name = display_name
    connection.connection_state = ProviderConnection.ConnectionState.CONNECTED
    connection.last_probe_at = now
    connection.disconnected_at = None
    connection.reauthorization_required_at = None
    connection.lifecycle_error_code = ""
    connection.save(update_fields=[
        "credential_reference", "external_id", "display_name", "connection_state",
        "last_probe_at", "disconnected_at", "reauthorization_required_at",
        "lifecycle_error_code", "updated_at",
    ])


def rotate_buffer_credential(
    *,
    organization,
    actor,
    api_key: str,
    token_store,
    connector,
    clock=timezone.now,
) -> ProviderConnection:
    if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 4096:
        raise BufferConnectionError("BUFFER_CONFIGURATION_REQUIRED")
    connection = _buffer_connection(organization)
    old_reference = connection.credential_reference
    external_id = connection.external_id
    if not old_reference or not external_id:
        raise BufferConnectionError("BUFFER_CONFIGURATION_REQUIRED")

    new_reference = _store_credential(token_store, organization, actor, api_key, uuid4())
    try:
        probe_result = connector.probe_connection(
            BufferDiscoveryRequest(
                credential_reference=new_reference,
                expected_organization_id=external_id,
            )
        )
    except Exception:
        _delete_credential_quietly(token_store, new_reference)
        raise BufferConnectionError("BUFFER_PROVIDER_UNAVAILABLE") from None
    if not probe_result.ok:
        _delete_credential_quietly(token_store, new_reference)
        _record_event_quietly(
            organization=organization,
            provider_connection=connection,
            actor=actor,
            action=ProviderConnectionEvent.Action.ROTATE,
            outcome=ProviderConnectionEvent.Outcome.FAILED,
            error_code=probe_result.error_code,
        )
        raise _map_buffer_error_code(probe_result.error_code)

    now = clock()
    try:
        with transaction.atomic():
            locked = _buffer_connection(organization, for_update=True)
            if locked.credential_reference != old_reference:
                raise BufferConnectionError("BUFFER_CONNECTION_CHANGED")
            locked.credential_reference = new_reference
            locked.connection_state = ProviderConnection.ConnectionState.CONNECTED
            locked.last_probe_at = now
            locked.disconnected_at = None
            locked.reauthorization_required_at = None
            locked.lifecycle_error_code = ""
            locked.save(update_fields=[
                "credential_reference", "connection_state", "last_probe_at",
                "disconnected_at", "reauthorization_required_at",
                "lifecycle_error_code", "updated_at",
            ])
            _record_event(
                organization=organization,
                provider_connection=locked,
                actor=actor,
                action=ProviderConnectionEvent.Action.ROTATE,
                outcome=ProviderConnectionEvent.Outcome.SUCCESS,
            )
            if old_reference != new_reference:
                _delete_credential(token_store, old_reference)
    except Exception:
        _delete_credential_quietly(token_store, new_reference)
        raise
    return locked


def probe_buffer_connection(
    *,
    organization,
    actor,
    connector,
    clock=timezone.now,
) -> ProviderConnection:
    snapshot = _buffer_connection(organization)
    snapshot_reference = snapshot.credential_reference
    snapshot_external_id = snapshot.external_id
    snapshot_state = snapshot.connection_state
    snapshot_updated_at = snapshot.updated_at
    if not snapshot_reference or not snapshot_external_id:
        raise BufferConnectionError("BUFFER_CONFIGURATION_REQUIRED")

    probe_result = connector.probe_connection(
        BufferDiscoveryRequest(
            credential_reference=snapshot_reference,
            expected_organization_id=snapshot_external_id,
        )
    )
    now = clock()
    if probe_result.ok:
        with transaction.atomic():
            locked = _buffer_connection(organization, for_update=True)
            _assert_probe_snapshot_unchanged(
                locked, snapshot_reference, snapshot_external_id,
                snapshot_state, snapshot_updated_at,
            )
            locked.connection_state = ProviderConnection.ConnectionState.CONNECTED
            locked.last_probe_at = now
            locked.disconnected_at = None
            locked.reauthorization_required_at = None
            locked.lifecycle_error_code = ""
            locked.save(update_fields=[
                "connection_state", "last_probe_at", "disconnected_at",
                "reauthorization_required_at", "lifecycle_error_code", "updated_at",
            ])
            _record_event(
                organization=organization,
                provider_connection=locked,
                actor=actor,
                action=ProviderConnectionEvent.Action.PROBE,
                outcome=ProviderConnectionEvent.Outcome.SUCCESS,
            )
        return locked

    state, set_reauth = _probe_state(probe_result.error_code)
    with transaction.atomic():
        locked = _buffer_connection(organization, for_update=True)
        _assert_probe_snapshot_unchanged(
            locked, snapshot_reference, snapshot_external_id,
            snapshot_state, snapshot_updated_at,
        )
        locked.connection_state = state
        locked.lifecycle_error_code = probe_result.error_code
        if set_reauth:
            locked.reauthorization_required_at = now
        locked.save(update_fields=[
            "connection_state", "lifecycle_error_code", "reauthorization_required_at",
            "updated_at",
        ])
    _record_event_quietly(
        organization=organization,
        provider_connection=locked,
        actor=actor,
        action=ProviderConnectionEvent.Action.PROBE,
        outcome=ProviderConnectionEvent.Outcome.FAILED,
        error_code=probe_result.error_code,
    )
    raise _map_buffer_error_code(probe_result.error_code)


def _assert_probe_snapshot_unchanged(
    connection, reference, external_id, state, updated_at,
) -> None:
    if (
        connection.credential_reference != reference
        or connection.external_id != external_id
        or connection.connection_state != state
        or connection.updated_at != updated_at
    ):
        raise BufferConnectionError("BUFFER_CONNECTION_CHANGED")


def sync_buffer_channels(
    *,
    organization,
    actor,
    connector,
    clock=timezone.now,
) -> BufferSyncResult:
    snapshot = _buffer_connection(organization)
    snapshot_reference = snapshot.credential_reference
    snapshot_external_id = snapshot.external_id
    if not snapshot_reference or not snapshot_external_id:
        raise BufferConnectionError("BUFFER_CONFIGURATION_REQUIRED")

    discover_result = connector.discover_channels(
        BufferDiscoveryRequest(
            credential_reference=snapshot_reference,
            expected_organization_id=snapshot_external_id,
        )
    )
    if not discover_result.ok:
        _record_event_quietly(
            organization=organization,
            provider_connection=snapshot,
            actor=actor,
            action=ProviderConnectionEvent.Action.SYNC,
            outcome=ProviderConnectionEvent.Outcome.FAILED,
            error_code=discover_result.error_code,
        )
        raise _map_buffer_error_code(discover_result.error_code)

    platforms = _resolve_platforms(discover_result)
    now = clock()
    with transaction.atomic():
        locked = _buffer_connection(organization, for_update=True)
        if (
            locked.credential_reference != snapshot_reference
            or locked.external_id != snapshot_external_id
            or locked.connection_state == ProviderConnection.ConnectionState.DISCONNECTED
        ):
            raise BufferConnectionError("BUFFER_CONNECTION_CHANGED")

        _assert_no_channel_conflicts(organization, locked, discover_result, platforms)
        created, updated = _upsert_channels(organization, locked, discover_result, platforms, now)
        disconnected_count = _deactivate_missing_channels(
            organization, locked, discover_result, now
        )
        locked.last_sync_at = now
        locked.save(update_fields=["last_sync_at", "updated_at"])
        _record_event(
            organization=organization,
            provider_connection=locked,
            actor=actor,
            action=ProviderConnectionEvent.Action.SYNC,
            outcome=ProviderConnectionEvent.Outcome.SUCCESS,
            metadata={
                "created_count": created,
                "updated_count": updated,
                "disconnected_count": disconnected_count,
                "ignored_count": len(discover_result.ignored_channels),
            },
        )

    return BufferSyncResult(
        created_count=created,
        updated_count=updated,
        disconnected_count=disconnected_count,
        ignored_channels=discover_result.ignored_channels,
        synced_at=now,
    )


def disconnect_buffer(
    *,
    organization,
    actor,
    token_store,
    clock=timezone.now,
) -> ProviderConnection:
    _buffer_connection(organization)
    now = clock()
    with transaction.atomic():
        locked = _buffer_connection(organization, for_update=True)
        if locked.connection_state == ProviderConnection.ConnectionState.DISCONNECTED and not locked.credential_reference:
            _record_event(
                organization=organization,
                provider_connection=locked,
                actor=actor,
                action=ProviderConnectionEvent.Action.DISCONNECT,
                outcome=ProviderConnectionEvent.Outcome.SUCCESS,
            )
            return locked
        reference = locked.credential_reference
        if reference:
            _delete_credential(token_store, reference)
        locked.credential_reference = ""
        locked.connection_state = ProviderConnection.ConnectionState.DISCONNECTED
        locked.disconnected_at = now
        locked.save(update_fields=[
            "credential_reference", "connection_state", "disconnected_at", "updated_at",
        ])
        SocialAccount.objects.filter(
            organization=organization,
            provider_connection=locked,
        ).update(
            status=SocialAccount.Status.INACTIVE,
            connection_state=SocialAccount.ConnectionState.DISCONNECTED,
            disconnected_at=now,
        )
        _record_event(
            organization=organization,
            provider_connection=locked,
            actor=actor,
            action=ProviderConnectionEvent.Action.DISCONNECT,
            outcome=ProviderConnectionEvent.Outcome.SUCCESS,
        )
    return locked


def _resolve_platforms(discover_result) -> dict[str, Platform]:
    platforms: dict[str, Platform] = {}
    for channel in discover_result.channels:
        code = channel.platform_code
        if code in platforms:
            continue
        platform = Platform.objects.filter(code=code).first()
        if platform is None:
            raise BufferConnectionError("BUFFER_CHANNEL_MAPPING_CONFLICT")
        platforms[code] = platform
    return platforms


def _assert_no_channel_conflicts(organization, connection, discover_result, platforms) -> None:
    for channel in discover_result.channels:
        platform = platforms[channel.platform_code]
        existing = SocialAccount.objects.filter(
            organization=organization,
            provider_connection=connection,
            provider_account_id=channel.provider_account_id,
        ).first()
        if existing is not None and existing.platform_id != platform.id:
            raise BufferConnectionError("BUFFER_CHANNEL_MAPPING_CONFLICT")
        direct_conflict = SocialAccount.objects.filter(
            organization=organization,
            platform=platform,
            external_id=channel.external_id,
            provider=SocialAccount.Provider.DIRECT,
        ).exists()
        if direct_conflict:
            raise BufferConnectionError("BUFFER_CHANNEL_MAPPING_CONFLICT")


def _upsert_channels(organization, connection, discover_result, platforms, now) -> tuple[int, int]:
    created = 0
    updated = 0
    for channel in discover_result.channels:
        platform = platforms[channel.platform_code]
        connection_state, lifecycle_error, reauth_at, disconnected_at = _channel_lifecycle(channel, now)
        account, was_created = SocialAccount.objects.update_or_create(
            organization=organization,
            provider_connection=connection,
            provider_account_id=channel.provider_account_id,
            defaults={
                "provider": SocialAccount.Provider.BUFFER,
                "platform": platform,
                "external_id": channel.external_id,
                "display_name": channel.display_name,
                "credential": None,
                "publish_mode": SocialAccount.PublishMode.API_AUTO,
                "connector_metadata": _channel_metadata(channel),
                "status": SocialAccount.Status.ACTIVE,
                "connection_state": connection_state,
                "lifecycle_error_code": lifecycle_error,
                "reauthorization_required_at": reauth_at,
                "disconnected_at": disconnected_at,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated


def _deactivate_missing_channels(organization, connection, discover_result, now) -> int:
    discovered_ids = {channel.provider_account_id for channel in discover_result.channels}
    return SocialAccount.objects.filter(
        organization=organization,
        provider_connection=connection,
    ).exclude(provider_account_id__in=discovered_ids).update(
        status=SocialAccount.Status.INACTIVE,
        connection_state=SocialAccount.ConnectionState.DISCONNECTED,
        disconnected_at=now,
    )


def _channel_lifecycle(channel, now) -> tuple[str, str, datetime | None, datetime | None]:
    if channel.is_disconnected:
        return (
            SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED,
            "",
            now,
            None,
        )
    if channel.is_locked:
        return (
            SocialAccount.ConnectionState.INSUFFICIENT_CAPABILITY,
            "BUFFER_CHANNEL_LOCKED",
            None,
            None,
        )
    return (SocialAccount.ConnectionState.CONNECTED, "", None, None)


def _channel_metadata(channel) -> dict:
    return {
        "connection_kind": "buffer",
        "service": channel.service,
        "channel_type": channel.channel_type,
        "avatar": channel.avatar,
        "external_link": channel.external_link,
        "is_locked": channel.is_locked,
        "is_queue_paused": channel.is_queue_paused,
        "allowed_actions": list(channel.allowed_actions),
        "products": list(channel.products),
        "scopes": list(channel.scopes),
    }
