"""Credential storage interfaces for secrets that must not enter application data."""

from .base import CredentialStore, CredentialStoreError, CredentialTargetError, credential_target
from .registry import (
    CredentialStoreUnavailableError,
    credential_store_override,
    get_credential_store,
)

__all__ = [
    "CredentialStore",
    "CredentialStoreError",
    "CredentialStoreUnavailableError",
    "CredentialTargetError",
    "credential_store_override",
    "credential_target",
    "get_credential_store",
]
