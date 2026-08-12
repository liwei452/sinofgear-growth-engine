from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from integrations.ai.deepseek import DeepSeekProvider
from integrations.ai.providers import (
    ProviderAuthenticationError,
    ProviderBalanceError,
    ProviderCallError,
    ProviderRateLimitError,
)
from integrations.credentials import (
    CredentialStoreError,
    CredentialStoreUnavailableError,
    credential_target,
    get_credential_store,
)

from .models import AIProviderConfiguration


class ProviderConfigurationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _TemporaryCredentialStore:
    def __init__(self, target: str, secret: str) -> None:
        self.target = target
        self.secret = secret

    def read(self, target: str) -> str | None:
        return self.secret if target == self.target else None

    def write(self, target: str, secret: str) -> None:
        raise CredentialStoreError("Temporary credential store is read-only.")

    def delete(self, target: str) -> bool:
        raise CredentialStoreError("Temporary credential store is read-only.")


@dataclass(frozen=True)
class _TestExecution:
    organization_id: object
    model: str = "deepseek-v4-flash"
    thinking_enabled: bool = False
    max_output_tokens: int = 64
    timeout_seconds: float = 15


_TEST_SCHEMA = {
    "type": "object",
    "required": ["connected"],
    "properties": {"connected": {"type": "boolean", "const": True}},
    "additionalProperties": False,
}
_API_KEY = re.compile(r"^sk-[A-Za-z0-9_-]{8,508}$")
_LIMIT_FIELDS = frozenset(
    {
        "daily_budget_usd",
        "flash_max_output_tokens",
        "pro_max_output_tokens",
        "timeout_seconds",
    }
)


def _store_or_error(credential_store):
    if credential_store is not None:
        return credential_store
    try:
        return get_credential_store()
    except CredentialStoreUnavailableError:
        raise ProviderConfigurationError("deepseek_credential_store_unavailable") from None


def _validated_limits(*, organization, limits: dict) -> dict:
    if set(limits) != _LIMIT_FIELDS:
        raise ProviderConfigurationError("deepseek_invalid_configuration")
    candidate = AIProviderConfiguration(organization=organization, **limits)
    try:
        candidate.full_clean(validate_unique=False, validate_constraints=False)
    except (ValidationError, TypeError, ValueError):
        raise ProviderConfigurationError("deepseek_invalid_configuration") from None
    return {field: getattr(candidate, field) for field in _LIMIT_FIELDS}


def _map_provider_error(error: ProviderCallError) -> ProviderConfigurationError:
    if isinstance(error, ProviderAuthenticationError):
        code = "deepseek_invalid_key"
    elif isinstance(error, ProviderBalanceError):
        code = "deepseek_balance_required"
    elif isinstance(error, ProviderRateLimitError):
        code = "deepseek_rate_limited"
    else:
        code = "deepseek_unavailable"
    return ProviderConfigurationError(code)


def _run_test(*, organization, api_key: str, provider_factory) -> None:
    target = credential_target(organization.id)
    temporary_store = _TemporaryCredentialStore(target, api_key)
    provider = provider_factory(credential_store=temporary_store)
    try:
        provider.generate(
            prompt='Return {"connected": true}.',
            schema=_TEST_SCHEMA,
            execution=_TestExecution(organization_id=organization.id),
        )
    except ProviderCallError as error:
        raise _map_provider_error(error) from None


def test_deepseek_configuration(
    *, organization, api_key: str | None = None, credential_store=None,
    provider_factory=None,
) -> None:
    store = _store_or_error(credential_store)
    target = credential_target(organization.id)
    if api_key is None:
        try:
            api_key = store.read(target)
        except CredentialStoreError:
            raise ProviderConfigurationError("deepseek_credential_store_unavailable") from None
    if not isinstance(api_key, str) or _API_KEY.fullmatch(api_key) is None:
        raise ProviderConfigurationError("deepseek_invalid_key")
    _run_test(
        organization=organization,
        api_key=api_key,
        provider_factory=provider_factory or DeepSeekProvider,
    )


def test_and_save_deepseek_configuration(
    *, organization, actor, api_key: str, limits: dict,
    credential_store=None, provider_factory=None,
) -> AIProviderConfiguration:
    store = _store_or_error(credential_store)
    limits = _validated_limits(organization=organization, limits=limits)
    test_deepseek_configuration(
        organization=organization,
        api_key=api_key,
        credential_store=store,
        provider_factory=provider_factory,
    )
    target = credential_target(organization.id)
    try:
        previous_secret = store.read(target)
        store.write(target, api_key)
    except CredentialStoreError:
        try:
            if "previous_secret" in locals():
                if previous_secret is None:
                    store.delete(target)
                else:
                    store.write(target, previous_secret)
        except CredentialStoreError:
            pass
        raise ProviderConfigurationError("deepseek_credential_store_unavailable") from None
    try:
        with transaction.atomic():
            configuration, _ = AIProviderConfiguration.objects.select_for_update().get_or_create(
                organization=organization
            )
            configuration.connection_state = AIProviderConfiguration.ConnectionState.CONNECTED
            configuration.key_suffix = api_key[-4:]
            configuration.credential_revision += 1
            configuration.last_tested_at = timezone.now()
            configuration.last_tested_by = actor
            for field, value in limits.items():
                setattr(configuration, field, value)
            configuration.full_clean()
            configuration.save()
            return configuration
    except Exception:
        try:
            if previous_secret is None:
                store.delete(target)
            else:
                store.write(target, previous_secret)
        except CredentialStoreError:
            pass
        raise


def delete_deepseek_credential(
    *, organization, actor, credential_store=None
) -> AIProviderConfiguration:
    store = _store_or_error(credential_store)
    target = credential_target(organization.id)
    try:
        previous_secret = store.read(target)
        store.delete(target)
    except CredentialStoreError:
        raise ProviderConfigurationError("deepseek_credential_store_unavailable") from None
    try:
        with transaction.atomic():
            configuration, _ = AIProviderConfiguration.objects.select_for_update().get_or_create(
                organization=organization
            )
            configuration.connection_state = AIProviderConfiguration.ConnectionState.NOT_CONFIGURED
            configuration.key_suffix = ""
            configuration.last_tested_at = None
            configuration.last_tested_by = actor
            configuration.full_clean()
            configuration.save()
            return configuration
    except Exception:
        if previous_secret is not None:
            try:
                store.write(target, previous_secret)
            except CredentialStoreError:
                pass
        raise
