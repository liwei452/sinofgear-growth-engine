from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.identity.models import Organization
from apps.platforms.lifecycle import (
    LifecycleAdapterRegistry,
    ProviderLifecycleError,
    disconnect_social_account,
    probe_social_account,
    refresh_due_credentials,
)
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount
from integrations.platforms.token_store import OAuthTokenSet
from integrations.platforms.base import ConnectorConfigurationRequired


class TokenStore:
    def __init__(self):
        self.deleted = []
        self.replaced = []

    def resolve(self, reference):
        return OAuthTokenSet(
            access_token="fixture-access",
            refresh_token="fixture-refresh",
            expires_at=timezone.now() + timedelta(minutes=5),
        )

    def replace(self, reference, token):
        self.replaced.append((reference, token))
        return f"vault://rotated/{len(self.replaced)}"

    def delete(self, reference):
        self.deleted.append(reference)


class Adapter:
    def __init__(self, *, error=None):
        self.error = error
        self.calls = []

    def probe(self, token, external_id):
        self.calls.append(("probe", external_id))
        if self.error:
            raise self.error

    def refresh(self, token):
        self.calls.append(("refresh", token.refresh_token))
        if self.error:
            raise self.error
        return OAuthTokenSet(
            access_token="fixture-new-access",
            refresh_token="fixture-new-refresh",
            expires_at=timezone.now() + timedelta(hours=2),
        )

    def revoke(self, token):
        self.calls.append(("revoke", token.access_token))
        if self.error:
            raise self.error


@pytest.fixture
def lifecycle_account(db):
    organization = Organization.objects.create(name="Lifecycle", slug=f"life-{uuid4()}")
    actor = get_user_model().objects.create_user(username=f"life-{uuid4()}")
    platform = Platform.objects.create(code="LINKEDIN", name="LinkedIn")
    credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://fixture/original",
        granted_scopes=["PUBLISH"],
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=credential,
        external_id="company-1",
        display_name="Factory Page",
        publish_mode=SocialAccount.PublishMode.API_CONFIRM,
        connector_metadata={"connection_kind": "official_oauth"},
        connection_state=SocialAccount.ConnectionState.CONNECTED,
    )
    return organization, actor, credential, account


@pytest.mark.django_db
def test_probe_updates_only_safe_health_metadata(lifecycle_account) -> None:
    _organization, actor, _credential, account = lifecycle_account
    adapter, store = Adapter(), TokenStore()

    result = probe_social_account(
        account=account, adapter=adapter, token_store=store, actor=actor
    )

    assert result.connection_state == SocialAccount.ConnectionState.CONNECTED
    assert result.last_probe_at is not None
    assert "fixture-access" not in repr(result)


@pytest.mark.django_db(transaction=True)
def test_probe_and_revoke_provider_calls_run_outside_transactions(
    lifecycle_account,
) -> None:
    _organization, actor, _credential, account = lifecycle_account

    class BoundaryAdapter(Adapter):
        def probe(self, token, external_id):
            assert connection.in_atomic_block is False
            return super().probe(token, external_id)

        def revoke(self, token):
            assert connection.in_atomic_block is False
            return super().revoke(token)

    adapter = BoundaryAdapter()
    store = TokenStore()
    probe_social_account(
        account=account, adapter=adapter, token_store=store, actor=actor
    )
    disconnect_social_account(
        account=account,
        adapter=adapter,
        token_store=store,
        actor=actor,
        confirmed=True,
    )


@pytest.mark.django_db
def test_refresh_due_is_locked_idempotent_and_rotates_refresh_token(lifecycle_account) -> None:
    organization, _actor, credential, account = lifecycle_account
    adapter, store = Adapter(), TokenStore()
    registry = LifecycleAdapterRegistry({"LINKEDIN": adapter})

    first = refresh_due_credentials(
        adapter_registry=registry,
        token_store=store,
        organization=organization,
        now=timezone.now(),
    )
    second = refresh_due_credentials(
        adapter_registry=registry,
        token_store=store,
        organization=organization,
        now=timezone.now(),
    )

    credential.refresh_from_db()
    account.refresh_from_db()
    assert first == {"examined": 1, "refreshed": 1, "reauthorization_required": 0, "failed": 0}
    assert second["examined"] == 0
    assert credential.secret_reference == "vault://rotated/1"
    assert credential.expires_at > timezone.now() + timedelta(hours=1)
    assert account.last_refresh_at is not None
    assert len(store.replaced) == 1


@pytest.mark.django_db
def test_invalid_grant_marks_reauthorization_without_overwriting_credential(lifecycle_account) -> None:
    organization, _actor, credential, account = lifecycle_account
    registry = LifecycleAdapterRegistry({
        "LINKEDIN": Adapter(error=ProviderLifecycleError("INVALID_GRANT"))
    })

    result = refresh_due_credentials(
        adapter_registry=registry,
        token_store=TokenStore(),
        organization=organization,
        now=timezone.now(),
    )

    account.refresh_from_db()
    credential.refresh_from_db()
    assert result["reauthorization_required"] == 1
    assert account.connection_state == SocialAccount.ConnectionState.REAUTHORIZATION_REQUIRED
    assert credential.secret_reference == "vault://fixture/original"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "outcome",
    ["success", "invalid_grant", "configuration_required"],
)
def test_stale_refresh_result_never_overwrites_concurrent_credential_rotation(
    lifecycle_account, outcome
) -> None:
    organization, _actor, credential, account = lifecycle_account

    class RotatingAdapter:
        def refresh(self, token):
            assert connection.in_atomic_block is False
            ConnectorCredential.objects.filter(pk=credential.id).update(
                secret_reference="vault://fixture/concurrent",
                updated_at=timezone.now() + timedelta(seconds=1),
            )
            SocialAccount.objects.filter(pk=account.id).update(
                connection_state=SocialAccount.ConnectionState.DISCONNECTED,
                lifecycle_error_code="CONCURRENT_STATE",
                reauthorization_required_at=None,
            )
            if outcome == "invalid_grant":
                raise ProviderLifecycleError("INVALID_GRANT")
            if outcome == "configuration_required":
                raise ConnectorConfigurationRequired("configuration unavailable")
            return OAuthTokenSet(
                access_token="stale-access",
                refresh_token="stale-refresh",
                expires_at=timezone.now() + timedelta(hours=2),
            )

    store = TokenStore()
    result = refresh_due_credentials(
        adapter_registry=LifecycleAdapterRegistry({"LINKEDIN": RotatingAdapter()}),
        token_store=store,
        organization=organization,
        now=timezone.now(),
    )

    credential.refresh_from_db()
    account.refresh_from_db()
    assert result == {
        "examined": 1,
        "refreshed": 0,
        "reauthorization_required": 0,
        "failed": 0,
    }
    assert credential.secret_reference == "vault://fixture/concurrent"
    assert account.connection_state == SocialAccount.ConnectionState.DISCONNECTED
    assert account.lifecycle_error_code == "CONCURRENT_STATE"
    assert account.reauthorization_required_at is None
    assert store.replaced == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "outcome",
    ["success", "invalid_grant", "configuration_required"],
)
def test_stale_refresh_result_never_overwrites_disconnected_account(
    lifecycle_account, outcome
) -> None:
    organization, actor, credential, account = lifecycle_account
    store = TokenStore()

    class DisconnectingAdapter:
        def refresh(self, token):
            assert connection.in_atomic_block is False
            disconnect_social_account(
                account=account,
                adapter=Adapter(),
                token_store=store,
                actor=actor,
                confirmed=True,
            )
            if outcome == "invalid_grant":
                raise ProviderLifecycleError("INVALID_GRANT")
            if outcome == "configuration_required":
                raise ConnectorConfigurationRequired("configuration unavailable")
            return OAuthTokenSet(
                access_token="stale-access",
                refresh_token="stale-refresh",
                expires_at=timezone.now() + timedelta(hours=2),
            )

    result = refresh_due_credentials(
        adapter_registry=LifecycleAdapterRegistry({"LINKEDIN": DisconnectingAdapter()}),
        token_store=store,
        organization=organization,
        now=timezone.now(),
    )

    credential.refresh_from_db()
    account.refresh_from_db()
    assert result == {
        "examined": 1,
        "refreshed": 0,
        "reauthorization_required": 0,
        "failed": 0,
    }
    assert account.status == SocialAccount.Status.INACTIVE
    assert account.connection_state == SocialAccount.ConnectionState.DISCONNECTED
    assert account.lifecycle_error_code == ""
    assert credential.secret_reference == "vault://fixture/original"
    assert store.replaced == []


@pytest.mark.django_db(transaction=True)
def test_replace_configuration_failure_does_not_stop_later_candidate(
    lifecycle_account,
) -> None:
    organization, _actor, first_credential, first_account = lifecycle_account
    platform = first_account.platform
    now = timezone.now()
    ConnectorCredential.objects.filter(pk=first_credential.id).update(
        expires_at=now + timedelta(minutes=1)
    )
    second_credential = ConnectorCredential.objects.create(
        organization=organization,
        platform=platform,
        secret_reference="vault://fixture/second",
        granted_scopes=["PUBLISH"],
        expires_at=now + timedelta(minutes=2),
    )
    second_account = SocialAccount.objects.create(
        organization=organization,
        platform=platform,
        credential=second_credential,
        external_id="company-2",
        display_name="Second Page",
        publish_mode=SocialAccount.PublishMode.API_CONFIRM,
        connector_metadata={"connection_kind": "official_oauth"},
        connection_state=SocialAccount.ConnectionState.CONNECTED,
    )

    class FailingFirstReplaceStore(TokenStore):
        def replace(self, reference, token):
            if reference == "vault://fixture/original":
                raise ConnectorConfigurationRequired("secure store unavailable")
            return super().replace(reference, token)

    store = FailingFirstReplaceStore()
    result = refresh_due_credentials(
        adapter_registry=LifecycleAdapterRegistry({"LINKEDIN": Adapter()}),
        token_store=store,
        organization=organization,
        now=now,
        limit=2,
    )

    first_account.refresh_from_db()
    second_account.refresh_from_db()
    first_credential.refresh_from_db()
    second_credential.refresh_from_db()
    assert result == {
        "examined": 2,
        "refreshed": 1,
        "reauthorization_required": 0,
        "failed": 1,
    }
    assert first_account.connection_state == (
        SocialAccount.ConnectionState.CONFIGURATION_REQUIRED
    )
    assert first_account.lifecycle_error_code == "CONFIGURATION_REQUIRED"
    assert first_credential.secret_reference == "vault://fixture/original"
    assert second_account.connection_state == SocialAccount.ConnectionState.CONNECTED
    assert second_credential.secret_reference == "vault://rotated/1"


@pytest.mark.django_db
def test_disconnect_preserves_account_and_history_even_if_revoke_fails(lifecycle_account) -> None:
    _organization, actor, credential, account = lifecycle_account
    store = TokenStore()

    result = disconnect_social_account(
        account=account,
        adapter=Adapter(error=ProviderLifecycleError("PROVIDER_UNAVAILABLE")),
        token_store=store,
        actor=actor,
        confirmed=True,
    )

    assert SocialAccount.objects.filter(pk=account.pk).exists()
    assert ConnectorCredential.objects.filter(pk=credential.pk).exists()
    assert result.connection_state == SocialAccount.ConnectionState.DISCONNECTED
    assert result.status == SocialAccount.Status.INACTIVE
    assert store.deleted == ["vault://fixture/original"]
    assert result.lifecycle_error_code == "PROVIDER_UNAVAILABLE"
