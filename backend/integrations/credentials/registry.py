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


_override: ContextVar[CredentialStore | None] = ContextVar(
    "credential_store_override", default=None
)
_test_store = _InMemoryCredentialStore()


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
        return _test_store
    if backend == "windows" and platform.system() == "Windows":
        from .windows import WindowsCredentialStore

        return WindowsCredentialStore()
    raise CredentialStoreUnavailableError("No approved credential store is available.")
