from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from integrations.platforms.base import ConnectorConfigurationRequired
from integrations.platforms.runtime import get_social_provider_runtime

from .models import SocialAccount


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


def refresh_due_credentials(
    *, adapter_registry=None, token_store=None, organization=None, organization_id=None,
    now=None, limit=100,
):
    if adapter_registry is None or token_store is None:
        default_registry, default_store = _default_dependencies()
        adapter_registry = adapter_registry or default_registry
        token_store = token_store or default_store
    now = now or timezone.now()
    queryset = SocialAccount.objects.filter(
        status=SocialAccount.Status.ACTIVE,
        connector_metadata__connection_kind="official_oauth",
        credential__isnull=False,
        credential__expires_at__lte=now + timedelta(minutes=15),
        credential__expires_at__gt=now,
    ).select_related("platform", "credential").order_by("credential__expires_at", "id")
    if organization is not None:
        queryset = queryset.filter(organization=organization)
    if organization_id is not None:
        queryset = queryset.filter(organization_id=organization_id)
    counters = {"examined": 0, "refreshed": 0, "reauthorization_required": 0, "failed": 0}
    for candidate_id in list(queryset.values_list("id", flat=True)[:max(0, min(limit, 100))]):
        counters["examined"] += 1
        try:
            with transaction.atomic():
                account = SocialAccount.objects.select_for_update().select_related(
                    "platform", "credential"
                ).get(pk=candidate_id)
                if account.credential.expires_at > now + timedelta(minutes=15):
                    continue
                adapter = adapter_registry.resolve(account.platform.code)
                token = token_store.resolve(account.credential.secret_reference)
                refreshed = adapter.refresh(token)
                new_reference = token_store.replace(account.credential.secret_reference, refreshed)
                account.credential.secret_reference = new_reference
                account.credential.expires_at = refreshed.expires_at
                account.credential.save(update_fields=["secret_reference", "expires_at", "updated_at"])
                account.connection_state = SocialAccount.ConnectionState.CONNECTED
                account.last_refresh_at = now
                account.lifecycle_error_code = ""
                account.save(update_fields=[
                    "connection_state", "last_refresh_at", "lifecycle_error_code", "updated_at",
                ])
                counters["refreshed"] += 1
        except ProviderLifecycleError as error:
            account = SocialAccount.objects.get(pk=candidate_id)
            if error.code == "INVALID_GRANT":
                account.connection_state = SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED
                account.reauthorization_required_at = now
                counters["reauthorization_required"] += 1
            else:
                account.connection_state = SocialAccount.ConnectionState.PROVIDER_UNAVAILABLE
                counters["failed"] += 1
            account.lifecycle_error_code = error.code
            account.save(update_fields=[
                "connection_state", "reauthorization_required_at", "lifecycle_error_code", "updated_at",
            ])
        except ConnectorConfigurationRequired:
            account = SocialAccount.objects.get(pk=candidate_id)
            account.connection_state = SocialAccount.ConnectionState.CONFIGURATION_REQUIRED
            account.lifecycle_error_code = "CONFIGURATION_REQUIRED"
            account.save(update_fields=["connection_state", "lifecycle_error_code", "updated_at"])
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
