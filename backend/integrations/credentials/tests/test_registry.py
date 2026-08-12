from __future__ import annotations

from uuid import UUID

import pytest
from django.test import override_settings

from integrations.credentials.base import CredentialTargetError, credential_target
from integrations.credentials.registry import (
    CredentialStoreUnavailableError,
    credential_store_override,
    get_credential_store,
)


class FakeCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, target: str) -> str | None:
        return self.values.get(target)

    def write(self, target: str, secret: str) -> None:
        self.values[target] = secret

    def delete(self, target: str) -> bool:
        return self.values.pop(target, None) is not None


def test_target_formats_uuid_organization_id() -> None:
    organization_id = UUID("12345678-1234-5678-1234-567812345678")

    assert credential_target(organization_id) == "SinofGear/DeepSeek/12345678-1234-5678-1234-567812345678"


def test_target_rejects_non_uuid_organization_ids() -> None:
    with pytest.raises(CredentialTargetError):
        credential_target("../other-user")


def test_registry_uses_explicit_dependency_override_for_fake() -> None:
    fake = FakeCredentialStore()

    with credential_store_override(fake):
        store = get_credential_store()
        store.write("SinofGear/DeepSeek/org-1", "test-secret")
        assert store.read("SinofGear/DeepSeek/org-1") == "test-secret"


def test_registry_allows_memory_store_only_with_test_setting() -> None:
    with override_settings(
        AI_CREDENTIAL_STORE="memory",
        AI_CREDENTIAL_STORE_TEST_FAKE_ALLOWED=True,
    ):
        store = get_credential_store()
        store.write("SinofGear/DeepSeek/org-1", "test-secret")
        assert store.read("SinofGear/DeepSeek/org-1") == "test-secret"
        assert store.delete("SinofGear/DeepSeek/org-1") is True


def test_registry_fails_closed_when_memory_store_is_not_test_enabled() -> None:
    with override_settings(
        AI_CREDENTIAL_STORE="memory",
        AI_CREDENTIAL_STORE_TEST_FAKE_ALLOWED=False,
    ):
        with pytest.raises(CredentialStoreUnavailableError) as captured:
            get_credential_store()

    assert "memory" not in str(captured.value).lower()


def test_registry_fails_closed_when_e2e_gate_does_not_match_owned_run() -> None:
    with override_settings(
        AI_CREDENTIAL_STORE="memory",
        AI_CREDENTIAL_STORE_TEST_FAKE_ALLOWED=True,
        PHASE_A_E2E_RUN_ID="owned-run",
        PHASE_A_E2E_OWNERSHIP_SECRET="a" * 64,
        DEEPSEEK_E2E_GATE="b" * 64,
    ):
        with pytest.raises(CredentialStoreUnavailableError):
            get_credential_store()


def test_owned_e2e_store_can_start_with_deterministic_nonsecret_placeholder() -> None:
    gate = "a" * 64
    with override_settings(
        AI_CREDENTIAL_STORE="memory", AI_CREDENTIAL_STORE_TEST_FAKE_ALLOWED=True,
        PHASE_A_E2E_RUN_ID="owned-run", PHASE_A_E2E_OWNERSHIP_SECRET=gate,
        DEEPSEEK_E2E_GATE=gate, DEEPSEEK_E2E_DEFAULT_CREDENTIAL=True,
    ):
        store = get_credential_store()
        target = credential_target(UUID("12345678-1234-5678-1234-567812345678"))
        assert store.read(target) == "".join(("s", "k-", "valid-placeholder"))
        assert store.delete(target) is True
        assert store.read(target) is None
        store.write(target, "restored-test-value")
        assert store.read(target) == "restored-test-value"


def test_registry_fails_closed_for_windows_store_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("integrations.credentials.registry.platform.system", lambda: "Linux")

    with override_settings(AI_CREDENTIAL_STORE="windows"):
        with pytest.raises(CredentialStoreUnavailableError):
            get_credential_store()


def test_registry_rejects_unknown_store_without_echoing_its_name() -> None:
    with override_settings(AI_CREDENTIAL_STORE="unapproved-store"):
        with pytest.raises(CredentialStoreUnavailableError) as captured:
            get_credential_store()

    assert "unapproved-store" not in str(captured.value)
