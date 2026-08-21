from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.runtime import get_social_provider_runtime
from apps.common.tenancy import tenant_atomic

from .models import ConnectorCredential, SocialAccount


class ProviderLifecycleError(RuntimeError):
    SAFE_CODES = frozenset({
        "INVALID_GRANT", "INSUFFICIENT_CAPABILITY", "PROVIDER_UNAVAILABLE",
        "CONFIGURATION_REQUIRED",
    })

    def __init__(self, code: str):
        self.code = code if code in self.SAFE_CODES else "PROVIDER_UNAVAILABLE"
        super().__init__(self.code)


class LifecycleAdapterRegistry:
    def __init__(self, adapters=None):
        self._adapters = dict(adapters or {})

    def resolve(self, platform_code: str):
        try:
            return self._adapters[platform_code]
        except KeyError as error:
            raise ProviderLifecycleError("CONFIGURATION_REQUIRED") from error


def _official(account: SocialAccount) -> bool:
    return account.connector_metadata.get("connection_kind") == "official_oauth"


@transaction.atomic
def probe_social_account(*, account, adapter, token_store, actor):
    del actor
    locked = SocialAccount.objects.select_for_update().select_related("credential").get(pk=account.pk)
    if not _official(locked) or locked.credential is None:
        raise ProviderLifecycleError("CONFIGURATION_REQUIRED")
    try:
        token = token_store.resolve(locked.credential.secret_reference)
        adapter.probe(token, locked.external_id)
    except ProviderLifecycleError as error:
        locked.connection_state = (
            SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED
            if error.code == "INVALID_GRANT"
            else SocialAccount.ConnectionState.PROVIDER_UNAVAILABLE
        )
        locked.lifecycle_error_code = error.code
        locked.save(update_fields=["connection_state", "lifecycle_error_code", "updated_at"])
        raise
    locked.connection_state = SocialAccount.ConnectionState.CONNECTED
    locked.last_probe_at = timezone.now()
    locked.lifecycle_error_code = ""
    locked.save(update_fields=["connection_state", "last_probe_at", "lifecycle_error_code", "updated_at"])
    return locked


def _default_dependencies():
    runtime = get_social_provider_runtime()
    return LifecycleAdapterRegistry(), runtime.token_store


@transaction.atomic
def start_reauthorization(*, account, actor):
    del actor
    locked = SocialAccount.objects.select_for_update().get(pk=account.pk)
    if not _official(locked):
        raise ProviderLifecycleError("CONFIGURATION_REQUIRED")
    locked.connection_state = SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED
    locked.reauthorization_required_at = timezone.now()
    locked.lifecycle_error_code = ""
    locked.save(update_fields=[
        "connection_state", "reauthorization_required_at", "lifecycle_error_code", "updated_at",
    ])
    return locked


@dataclass(frozen=True, repr=False)
class _CredentialRefreshCall:
    account_id: object
    credential_id: object
    credential_reference: str = field(repr=False)
    credential_updated_at: object
    token: object = field(repr=False)
    adapter: object = field(repr=False)


def refresh_due_credentials(
    *, adapter_registry=None, token_store=None, organization=None, organization_id=None,
    now=None, limit=100,
):
    if adapter_registry is None or token_store is None:
        default_registry, default_store = _default_dependencies()
        adapter_registry = adapter_registry or default_registry
        token_store = token_store or default_store
    now = now or timezone.now()
    context_id = organization_id or (organization.id if organization is not None else None)
    if context_id is None:
        raise ValueError("organization_id is required for credential refresh.")
    with tenant_atomic(context_id):
        queryset = SocialAccount.objects.filter(
            status=SocialAccount.Status.ACTIVE,
            connector_metadata__connection_kind="official_oauth",
            credential__isnull=False,
            credential__expires_at__lte=now + timedelta(minutes=15),
            credential__expires_at__gt=now,
            organization_id=context_id,
        ).select_related("platform", "credential").order_by(
            "credential__expires_at", "id"
        )
        candidate_ids = list(
            queryset.values_list("id", flat=True)[:max(0, min(limit, 100))]
        )
    counters = {"examined": 0, "refreshed": 0, "reauthorization_required": 0, "failed": 0}
    for candidate_id in candidate_ids:
        counters["examined"] += 1
        call = None
        try:
            with tenant_atomic(context_id):
                account = SocialAccount.objects.select_for_update().select_related(
                    "platform", "credential"
                ).get(pk=candidate_id, organization_id=context_id)
                if account.credential.expires_at > now + timedelta(minutes=15):
                    continue
                credential = account.credential
                call = _CredentialRefreshCall(
                    account_id=account.id,
                    credential_id=credential.id,
                    credential_reference=credential.secret_reference,
                    credential_updated_at=credential.updated_at,
                    token=None,
                    adapter=None,
                )
                adapter = adapter_registry.resolve(account.platform.code)
                token = token_store.resolve(credential.secret_reference)
                call = _CredentialRefreshCall(
                    account_id=call.account_id,
                    credential_id=call.credential_id,
                    credential_reference=call.credential_reference,
                    credential_updated_at=call.credential_updated_at,
                    token=token,
                    adapter=adapter,
                )
            refreshed = call.adapter.refresh(call.token)
            outcome = ("SUCCESS", refreshed)
        except ProviderLifecycleError as error:
            outcome = (error.code, None)
        except ConnectorConfigurationRequired:
            outcome = ("CONFIGURATION_REQUIRED", None)

        if call is None:
            # Preparation could not produce a credential snapshot; no result is safe to apply.
            continue
        with tenant_atomic(context_id):
            account = SocialAccount.objects.select_for_update().get(
                pk=call.account_id,
                organization_id=context_id,
            )
            if account.credential_id is None:
                continue
            credential = ConnectorCredential.objects.select_for_update().get(
                pk=account.credential_id,
                organization_id=context_id,
            )
            if (
                account.credential_id != call.credential_id
                or credential.secret_reference != call.credential_reference
                or credential.updated_at != call.credential_updated_at
            ):
                continue

            code, refreshed = outcome
            if code == "SUCCESS":
                credential.secret_reference = token_store.replace(
                    credential.secret_reference,
                    refreshed,
                )
                credential.expires_at = refreshed.expires_at
                credential.save(
                    update_fields=["secret_reference", "expires_at", "updated_at"]
                )
                account.connection_state = SocialAccount.ConnectionState.CONNECTED
                account.last_refresh_at = now
                account.lifecycle_error_code = ""
                account.save(update_fields=[
                    "connection_state",
                    "last_refresh_at",
                    "lifecycle_error_code",
                    "updated_at",
                ])
                counters["refreshed"] += 1
            elif code == "INVALID_GRANT":
                account.connection_state = (
                    SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED
                )
                account.reauthorization_required_at = now
                account.lifecycle_error_code = code
                account.save(update_fields=[
                    "connection_state",
                    "reauthorization_required_at",
                    "lifecycle_error_code",
                    "updated_at",
                ])
                counters["reauthorization_required"] += 1
            elif code == "CONFIGURATION_REQUIRED":
                account.connection_state = (
                    SocialAccount.ConnectionState.CONFIGURATION_REQUIRED
                )
                account.lifecycle_error_code = code
                account.save(update_fields=[
                    "connection_state",
                    "lifecycle_error_code",
                    "updated_at",
                ])
                counters["failed"] += 1
            else:
                account.connection_state = SocialAccount.ConnectionState.PROVIDER_UNAVAILABLE
                account.lifecycle_error_code = code
                account.save(update_fields=[
                    "connection_state",
                    "lifecycle_error_code",
                    "updated_at",
                ])
                counters["failed"] += 1
    return counters


@transaction.atomic
def disconnect_social_account(*, account, adapter, token_store, actor, confirmed: bool):
    del actor
    if not confirmed:
        raise ValueError("DISCONNECT_CONFIRMATION_REQUIRED")
    locked = SocialAccount.objects.select_for_update().select_related("credential").get(pk=account.pk)
    error_code = ""
    if locked.credential is not None:
        try:
            token = token_store.resolve(locked.credential.secret_reference)
            adapter.revoke(token)
        except (ProviderLifecycleError, ConnectorConfigurationRequired) as error:
            error_code = getattr(error, "code", "PROVIDER_UNAVAILABLE")
        try:
            token_store.delete(locked.credential.secret_reference)
        except ConnectorConfigurationRequired:
            error_code = error_code or "CONFIGURATION_REQUIRED"
    locked.status = SocialAccount.Status.INACTIVE
    locked.connection_state = SocialAccount.ConnectionState.DISCONNECTED
    locked.disconnected_at = timezone.now()
    locked.lifecycle_error_code = error_code
    locked.save(update_fields=[
        "status", "connection_state", "disconnected_at", "lifecycle_error_code", "updated_at",
    ])
    return locked
