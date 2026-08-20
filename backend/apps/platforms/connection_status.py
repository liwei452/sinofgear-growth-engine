from dataclasses import dataclass

from django.utils import timezone

from .models import ProviderConnection, SocialAccount


@dataclass(frozen=True)
class ConnectionSummary:
    status: str
    connection_label: str
    recovery_action: str
    account_id: str = ""
    mode: str = ""


def _summary(status: str, account=None, *, mode: str = "") -> ConnectionSummary:
    labels = {
        "NOT_CONNECTED": ("未连接", "连接账号"),
        "CONNECTED": ("已连接", ""),
        "REAUTHORIZATION_REQUIRED": ("需要重新授权", "重新连接"),
        "CONFIGURATION_REQUIRED": ("未连接", "连接账号"),
        "PROVIDER_UNAVAILABLE": ("平台暂时不可用", "稍后重试"),
        "INSUFFICIENT_CAPABILITY": ("权限不足", "重新授权"),
    }
    label, recovery = labels[status]
    return ConnectionSummary(
        status=status,
        connection_label=label,
        recovery_action=recovery,
        account_id=str(account.id) if account is not None else "",
        mode=mode,
    )


def connection_summary(*, organization, platform_code: str) -> ConnectionSummary:
    accounts = list(SocialAccount.objects.filter(
        organization=organization,
        platform__code=platform_code,
        status=SocialAccount.Status.ACTIVE,
    ).select_related("credential", "platform", "provider_connection").order_by("id"))
    if not accounts:
        return _summary("NOT_CONNECTED")
    buffer_accounts = [
        account for account in accounts
        if account.provider == SocialAccount.Provider.BUFFER
    ]
    if buffer_accounts and len(buffer_accounts) == len(accounts):
        return _buffer_platform_summary(buffer_accounts)
    if len(accounts) != 1:
        return _summary("CONFIGURATION_REQUIRED")

    account = accounts[0]
    if account.connection_state in {
        SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED,
        SocialAccount.ConnectionState.PROVIDER_UNAVAILABLE,
        SocialAccount.ConnectionState.INSUFFICIENT_CAPABILITY,
    }:
        return _summary(account.connection_state, account, mode="OFFICIAL")
    metadata = account.connector_metadata if isinstance(account.connector_metadata, dict) else {}
    connection_kind = metadata.get("connection_kind", "")
    if not connection_kind and metadata.get("fixture") == "phase-a-e2e":
        connection_kind = "demo_fake"
    if connection_kind == "demo_fake":
        if account.publish_mode not in {
            SocialAccount.PublishMode.API_AUTO,
            SocialAccount.PublishMode.API_CONFIRM,
        }:
            return _summary("CONFIGURATION_REQUIRED", account, mode="DEMO_FAKE")
        return _summary("CONNECTED", account, mode="DEMO_FAKE")
    if connection_kind != "official_oauth" or account.publish_mode not in {
        SocialAccount.PublishMode.API_AUTO,
        SocialAccount.PublishMode.API_CONFIRM,
    }:
        return _summary("CONFIGURATION_REQUIRED", account, mode="OFFICIAL")
    if account.credential is None or not account.credential.secret_reference:
        return _summary("CONFIGURATION_REQUIRED", account, mode="OFFICIAL")
    if account.credential.expires_at and account.credential.expires_at <= timezone.now():
        return _summary("REAUTHORIZATION_REQUIRED", account, mode="OFFICIAL")
    return _summary("CONNECTED", account, mode="OFFICIAL")


def _buffer_platform_summary(accounts: list[SocialAccount]) -> ConnectionSummary:
    connection = accounts[0].provider_connection
    single = accounts[0] if len(accounts) == 1 else None
    if connection is None:
        return _summary("CONFIGURATION_REQUIRED", single, mode="BUFFER")
    parent_state = connection.connection_state
    if parent_state == ProviderConnection.ConnectionState.CONNECTED:
        return _summary(_aggregate_buffer_channels(accounts), single, mode="BUFFER")
    if parent_state == ProviderConnection.ConnectionState.DISCONNECTED:
        return _summary("NOT_CONNECTED", mode="BUFFER")
    if parent_state in {
        ProviderConnection.ConnectionState.REAUTHORIZATION_REQUIRED,
        ProviderConnection.ConnectionState.PROVIDER_UNAVAILABLE,
        ProviderConnection.ConnectionState.INSUFFICIENT_CAPABILITY,
        ProviderConnection.ConnectionState.CONFIGURATION_REQUIRED,
    }:
        return _summary(parent_state, single, mode="BUFFER")
    # REFRESH_DUE and any unknown future state fall back to configuration required.
    return _summary("CONFIGURATION_REQUIRED", single, mode="BUFFER")


def _aggregate_buffer_channels(accounts: list[SocialAccount]) -> str:
    states = {account.connection_state for account in accounts}
    for state in (
        SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED,
        SocialAccount.ConnectionState.INSUFFICIENT_CAPABILITY,
        SocialAccount.ConnectionState.PROVIDER_UNAVAILABLE,
    ):
        if state in states:
            return state
    if SocialAccount.ConnectionState.CONNECTED in states:
        return SocialAccount.ConnectionState.CONNECTED
    return SocialAccount.ConnectionState.CONFIGURATION_REQUIRED
