from __future__ import annotations

from typing import Protocol
from uuid import UUID


class CredentialStoreError(RuntimeError):
    """A controlled credential-store error that contains no sensitive values."""


class CredentialTargetError(ValueError):
    """Raised when an organization id cannot form a credential target."""


class CredentialStore(Protocol):
    def read(self, target: str) -> str | None: ...

    def write(self, target: str, secret: str) -> None: ...

    def delete(self, target: str) -> bool: ...


def credential_target(organization_id: object) -> str:
    """Return the fixed credential-vault target for an organization UUID."""
    try:
        value = UUID(str(organization_id))
    except (TypeError, ValueError, AttributeError) as error:
        raise CredentialTargetError("Organization id must be a UUID.") from error
    return f"SinofGear/DeepSeek/{value}"
