from decimal import Decimal
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.ai.models import AIProviderConfiguration
from apps.ai.provider_configuration import (
    ProviderConfigurationError,
    delete_deepseek_credential,
    test_and_save_deepseek_configuration as save_configuration,
    test_deepseek_configuration as check_configuration,
    _begin_configuration_mutation,
    _complete_configuration_mutation,
)
from apps.identity.models import Organization
from integrations.ai.providers import ProviderAuthenticationError, ProviderResult
from integrations.ai.providers import (
    ProviderBalanceError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from integrations.credentials import CredentialStoreError


SECRET = "sk-test-secret-1234567890"


class Store:
    def __init__(self, value=None, *, fail_write=False, fail_restore=False):
        self.value = value
        self.fail_write = fail_write
        self.fail_restore = fail_restore
        self.events = []

    def read(self, target):
        self.events.append(("read", target))
        return self.value

    def write(self, target, secret):
        self.events.append(("write", target))
        if self.fail_write or (self.fail_restore and secret != SECRET):
            raise CredentialStoreError("safe")
        self.value = secret

    def delete(self, target):
        self.events.append(("delete", target))
        existed = self.value is not None
        self.value = None
        return existed


class Provider:
    def __init__(self, credential_store, *, error=None):
        self.store = credential_store
        self.error = error

    def generate(self, **kwargs):
        assert self.store.read(self.store.target) == SECRET
        if self.error:
            raise self.error
        return ProviderResult(output={"connected": True}, metadata={})


@pytest.fixture
def context(db):
    organization = Organization.objects.create(name="AI Own", slug="ai-own")
    actor = get_user_model().objects.create_user(username="ai-admin")
    return organization, actor


def limits(**overrides):
    values = {
        "daily_budget_usd": Decimal("10.00"),
        "flash_max_output_tokens": 1200,
        "pro_max_output_tokens": 2400,
        "timeout_seconds": 30,
    }
    values.update(overrides)
    return values


def test_test_and_save_tests_before_write_and_never_persists_secret(context):
    organization, actor = context
    vault = Store()

    configuration = save_configuration(
        organization=organization,
        actor=actor,
        api_key=SECRET,
        limits=limits(),
        credential_store=vault,
        provider_factory=Provider,
    )

    assert vault.value == SECRET
    assert vault.events[0][0] == "read"
    assert vault.events[-1][0] == "write"
    assert configuration.connection_state == "CONNECTED"
    assert configuration.key_suffix == SECRET[-4:]
    assert configuration.credential_revision == 1
    assert SECRET not in str(AIProviderConfiguration.objects.values())


def test_failed_test_does_not_write_or_create_configuration(context):
    organization, actor = context
    vault = Store()

    with pytest.raises(ProviderConfigurationError) as caught:
        save_configuration(
            organization=organization,
            actor=actor,
            api_key=SECRET,
            limits=limits(),
            credential_store=vault,
            provider_factory=lambda credential_store: Provider(
                credential_store, error=ProviderAuthenticationError("must not leak")
            ),
        )

    assert caught.value.code == "deepseek_invalid_key"
    assert vault.value is None
    assert not AIProviderConfiguration.objects.exists()


@pytest.mark.parametrize(
    ("provider_error", "code"),
    [
        (ProviderBalanceError("safe"), "deepseek_balance_required"),
        (ProviderRateLimitError(), "deepseek_rate_limited"),
        (ProviderUnavailableError("safe"), "deepseek_unavailable"),
    ],
)
def test_provider_failures_map_to_fixed_codes_without_logging_secret(
    context, caplog, provider_error, code
):
    organization, _ = context
    with pytest.raises(ProviderConfigurationError) as caught:
        check_configuration(
            organization=organization,
            api_key=SECRET,
            credential_store=Store(),
            provider_factory=lambda credential_store: Provider(
                credential_store, error=provider_error
            ),
        )
    assert caught.value.code == code
    assert SECRET not in caplog.text


def test_vault_mutations_happen_after_organization_lock(context, monkeypatch):
    organization, actor = context
    lock_acquired = False
    original = Organization.objects.select_for_update

    def select_for_update(*args, **kwargs):
        nonlocal lock_acquired
        lock_acquired = True
        return original(*args, **kwargs)

    monkeypatch.setattr(Organization.objects, "select_for_update", select_for_update)

    class LockCheckingStore(Store):
        def write(self, target, secret):
            assert lock_acquired
            super().write(target, secret)

        def delete(self, target):
            assert lock_acquired
            return super().delete(target)

    vault = LockCheckingStore()
    save_configuration(
        organization=organization, actor=actor, api_key=SECRET,
        limits=limits(), credential_store=vault, provider_factory=Provider,
    )
    lock_acquired = False
    delete_deepseek_credential(
        organization=organization, actor=actor, credential_store=vault
    )


@pytest.mark.parametrize("operation", ["put", "delete"])
def test_failed_database_and_failed_compensation_marks_state_uncertain(
    context, monkeypatch, operation
):
    organization, actor = context
    AIProviderConfiguration.objects.create(
        organization=organization, connection_state="CONNECTED", key_suffix="old1",
        credential_revision=2, **limits(),
    )
    vault = Store("sk-old-key", fail_restore=True)
    original_save = AIProviderConfiguration.save

    def fail_requested_state(self, *args, **kwargs):
        target_state = "CONNECTED" if operation == "put" else "NOT_CONFIGURED"
        if self.connection_state == target_state:
            raise RuntimeError(f"database failed {SECRET}")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(AIProviderConfiguration, "save", fail_requested_state)
    with pytest.raises(ProviderConfigurationError) as caught:
        if operation == "put":
            save_configuration(
                organization=organization, actor=actor, api_key=SECRET,
                limits=limits(), credential_store=vault, provider_factory=Provider,
            )
        else:
            delete_deepseek_credential(
                organization=organization, actor=actor, credential_store=vault
            )
    assert caught.value.code == "deepseek_credential_state_uncertain"
    configuration = AIProviderConfiguration.objects.get(organization=organization)
    assert configuration.connection_state == "NEEDS_RECONNECT"
    assert configuration.key_suffix == ""
    assert SECRET not in repr(caught.value)


def test_premark_is_persistent_fail_closed_without_process_memory(context):
    organization, actor = context
    AIProviderConfiguration.objects.create(
        organization=organization, connection_state="CONNECTED", key_suffix="old1",
        credential_revision=3, **limits(),
    )
    operation = _begin_configuration_mutation(
        organization=organization, actor=actor
    )
    configuration = AIProviderConfiguration.objects.get(organization=organization)
    assert configuration.connection_state == "CONFIGURING"
    assert configuration.key_suffix == ""
    assert configuration.operation_revision == operation.revision
    assert str(configuration.operation_token) == str(operation.token)


def test_active_operation_is_busy_but_stale_premark_can_be_taken_over(context):
    organization, actor = context
    first = _begin_configuration_mutation(organization=organization, actor=actor)
    with pytest.raises(ProviderConfigurationError) as caught:
        _begin_configuration_mutation(organization=organization, actor=actor)
    assert caught.value.code == "deepseek_configuration_busy"
    configuration = AIProviderConfiguration.objects.get(organization=organization)
    assert configuration.operation_revision == first.revision

    AIProviderConfiguration.objects.filter(organization=organization).update(
        operation_started_at=timezone.now() - timedelta(minutes=10)
    )
    takeover = _begin_configuration_mutation(organization=organization, actor=actor)
    assert takeover.revision == first.revision + 1


def test_stale_operation_cannot_overwrite_newer_success(context):
    organization, actor = context
    vault = Store("sk-old-key")
    old = _begin_configuration_mutation(organization=organization, actor=actor)
    AIProviderConfiguration.objects.filter(organization=organization).update(
        operation_started_at=timezone.now() - timedelta(minutes=10)
    )
    new = _begin_configuration_mutation(organization=organization, actor=actor)
    result = _complete_configuration_mutation(
        operation=new, organization=organization, actor=actor, store=vault,
        replacement_secret=SECRET, limits=limits(), delete=False,
    )
    assert result.connection_state == "CONNECTED"

    with pytest.raises(ProviderConfigurationError) as caught:
        _complete_configuration_mutation(
            operation=old, organization=organization, actor=actor, store=vault,
            replacement_secret="sk-stale-secret-123456", limits=limits(), delete=False,
        )
    assert caught.value.code == "deepseek_configuration_superseded"
    configuration = AIProviderConfiguration.objects.get(organization=organization)
    assert configuration.connection_state == "CONNECTED"
    assert configuration.key_suffix == SECRET[-4:]


def test_stale_success_cannot_clear_newer_failed_operation(context):
    organization, actor = context
    vault = Store("sk-old-key")
    old = _begin_configuration_mutation(organization=organization, actor=actor)
    AIProviderConfiguration.objects.filter(organization=organization).update(
        operation_started_at=timezone.now() - timedelta(minutes=10)
    )
    new = _begin_configuration_mutation(organization=organization, actor=actor)
    vault.fail_write = True
    with pytest.raises(ProviderConfigurationError):
        _complete_configuration_mutation(
            operation=new, organization=organization, actor=actor, store=vault,
            replacement_secret=SECRET, limits=limits(), delete=False,
        )
    with pytest.raises(ProviderConfigurationError) as caught:
        _complete_configuration_mutation(
            operation=old, organization=organization, actor=actor, store=vault,
            replacement_secret=SECRET, limits=limits(), delete=False,
        )
    assert caught.value.code == "deepseek_configuration_superseded"
    configuration = AIProviderConfiguration.objects.get(organization=organization)
    assert configuration.connection_state in {"CONFIGURING", "NEEDS_RECONNECT"}
    assert configuration.key_suffix == ""


def test_invalid_direct_service_limits_are_rejected_before_provider_or_vault(context):
    organization, actor = context
    vault = Store()

    with pytest.raises(ProviderConfigurationError) as caught:
        save_configuration(
            organization=organization,
            actor=actor,
            api_key=SECRET,
            limits=limits(timeout_seconds=0) | {"key_suffix": "evil"},
            credential_store=vault,
            provider_factory=lambda **kwargs: pytest.fail("provider must not be called"),
        )

    assert caught.value.code == "deepseek_invalid_configuration"
    assert vault.events == []


def test_vault_failure_keeps_previous_database_configuration(context):
    organization, actor = context
    configuration = AIProviderConfiguration.objects.create(
        organization=organization,
        connection_state="CONNECTED",
        key_suffix="old1",
        credential_revision=4,
        **limits(),
    )
    vault = Store("sk-old-key", fail_write=True)

    with pytest.raises(ProviderConfigurationError) as caught:
        save_configuration(
            organization=organization,
            actor=actor,
            api_key=SECRET,
            limits=limits(daily_budget_usd=Decimal("20.00")),
            credential_store=vault,
            provider_factory=Provider,
        )

    assert caught.value.code == "deepseek_credential_store_unavailable"
    configuration.refresh_from_db()
    assert configuration.key_suffix == ""
    assert configuration.connection_state == "NEEDS_RECONNECT"
    assert configuration.credential_revision == 4
    assert configuration.daily_budget_usd == Decimal("10.00")


def test_test_replacement_does_not_persist_and_delete_is_idempotent(context):
    organization, actor = context
    configuration = AIProviderConfiguration.objects.create(
        organization=organization,
        connection_state="CONNECTED",
        key_suffix="old1",
        credential_revision=1,
        **limits(),
    )
    vault = Store("sk-old-key")

    check_configuration(
        organization=organization,
        api_key=SECRET,
        credential_store=vault,
        provider_factory=Provider,
    )
    assert vault.value == "sk-old-key"
    configuration.refresh_from_db()
    assert configuration.key_suffix == "old1"

    deleted = delete_deepseek_credential(
        organization=organization, actor=actor, credential_store=vault
    )
    again = delete_deepseek_credential(
        organization=organization, actor=actor, credential_store=vault
    )
    assert deleted.connection_state == again.connection_state == "NOT_CONFIGURED"
    assert deleted.key_suffix == again.key_suffix == ""
