from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.ai.models import AIProviderConfiguration
from apps.ai.provider_configuration import (
    ProviderConfigurationError,
    delete_deepseek_credential,
    test_and_save_deepseek_configuration as save_configuration,
    test_deepseek_configuration as check_configuration,
)
from apps.identity.models import Organization
from integrations.ai.providers import ProviderAuthenticationError, ProviderResult
from integrations.credentials import CredentialStoreError


SECRET = "sk-test-secret-1234567890"


class Store:
    def __init__(self, value=None, *, fail_write=False):
        self.value = value
        self.fail_write = fail_write
        self.events = []

    def read(self, target):
        self.events.append(("read", target))
        return self.value

    def write(self, target, secret):
        self.events.append(("write", target))
        if self.fail_write:
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
    assert configuration.key_suffix == "old1"
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
