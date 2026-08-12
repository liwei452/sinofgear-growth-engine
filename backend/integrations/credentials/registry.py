from __future__ import annotations

import platform
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from django.conf import settings

from .base import CredentialStore


class CredentialStoreUnavailableError(RuntimeError):
    """Raised when no approved credential store is available."""


class _InMemoryCredentialStore:
    """Test-only store; production cannot select this implementation."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def read(self, target: str) -> str | None:
        return self._values.get(target)

    def write(self, target: str, secret: str) -> None:
        self._values[target] = secret

    def delete(self, target: str) -> bool:
        return self._values.pop(target, None) is not None


class _OwnedE2ECredentialStore(_InMemoryCredentialStore):
    def __init__(self) -> None:
        super().__init__()
        self._deleted: set[str] = set()

    def read(self, target: str) -> str | None:
        if target in self._deleted:
            return None
        return self._values.get(target, "".join(("s", "k-", "valid-placeholder")))

    def write(self, target: str, secret: str) -> None:
        self._deleted.discard(target)
        super().write(target, secret)

    def delete(self, target: str) -> bool:
        existed = target not in self._deleted
        self._values.pop(target, None)
        self._deleted.add(target)
        return existed


_override: ContextVar[CredentialStore | None] = ContextVar(
    "credential_store_override", default=None
)
_test_store = _InMemoryCredentialStore()
_owned_e2e_store = _OwnedE2ECredentialStore()


@contextmanager
def credential_store_override(store: CredentialStore) -> Iterator[CredentialStore]:
    """Temporarily inject a test double without changing production settings."""
    token = _override.set(store)
    try:
        yield store
    finally:
        _override.reset(token)


def get_credential_store() -> CredentialStore:
    """Return the configured safe store, failing closed for unsupported settings."""
    override = _override.get()
    if override is not None:
        return override

    backend = str(getattr(settings, "AI_CREDENTIAL_STORE", "windows")).lower()
    if backend == "memory" and getattr(
        settings, "AI_CREDENTIAL_STORE_TEST_FAKE_ALLOWED", False
    ):
        run_id = str(getattr(settings, "PHASE_A_E2E_RUN_ID", ""))
        if run_id and (
            str(getattr(settings, "DEEPSEEK_E2E_GATE", ""))
            != str(getattr(settings, "PHASE_A_E2E_OWNERSHIP_SECRET", ""))
        ):
            raise CredentialStoreUnavailableError(
                "No approved credential store is available."
            )
        if run_id and bool(getattr(settings, "DEEPSEEK_E2E_DEFAULT_CREDENTIAL", False)):
            return _owned_e2e_store
        return _test_store
    if backend == "windows" and platform.system() == "Windows":
        from .windows import WindowsCredentialStore

        return WindowsCredentialStore()
    raise CredentialStoreUnavailableError("No approved credential store is available.")
