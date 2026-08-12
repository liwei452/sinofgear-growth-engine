from __future__ import annotations

import ctypes
from ctypes import wintypes

from .base import CredentialStoreError

CRED_TYPE_GENERIC = 1
CRED_PERSIST_SESSION = 1
ERROR_NOT_FOUND = 1168


class CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)


def _windows_credential_api() -> object:
    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    api.CredWriteW.argtypes = (PCREDENTIALW, wintypes.DWORD)
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(PCREDENTIALW),
    )
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = (ctypes.c_void_p,)
    api.CredFree.restype = None
    return api


class WindowsCredentialStore:
    """Windows Credential Manager adapter for generic session credentials."""

    def __init__(self, *, api: object | None = None) -> None:
        self._api = api if api is not None else _windows_credential_api()

    def read(self, target: str) -> str | None:
        credential_pointer = PCREDENTIALW()
        if not self._api.CredReadW(
            target,
            CRED_TYPE_GENERIC,
            0,
            ctypes.byref(credential_pointer),
        ):
            if self._last_error() == ERROR_NOT_FOUND:
                return None
            self._raise_operation_error()

        try:
            return self._decode_secret(credential_pointer.contents)
        finally:
            self._api.CredFree(credential_pointer)

    def write(self, target: str, secret: str) -> None:
        if not secret:
            raise CredentialStoreError("Credential secret must not be empty.")

        secret_blob = secret.encode("utf-16-le")
        blob_buffer = (ctypes.c_ubyte * len(secret_blob)).from_buffer_copy(secret_blob)
        credential = CREDENTIALW(
            Type=CRED_TYPE_GENERIC,
            TargetName=target,
            CredentialBlobSize=len(secret_blob),
            CredentialBlob=ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_ubyte)),
            Persist=CRED_PERSIST_SESSION,
        )
        if not self._api.CredWriteW(ctypes.pointer(credential), 0):
            self._raise_operation_error()

    def delete(self, target: str) -> bool:
        if self._api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            return True
        if self._last_error() == ERROR_NOT_FOUND:
            return False
        self._raise_operation_error()

    def _last_error(self) -> int:
        get_last_error = getattr(self._api, "get_last_error", ctypes.get_last_error)
        return int(get_last_error())

    @staticmethod
    def _decode_secret(credential: CREDENTIALW) -> str:
        try:
            raw_secret = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            return raw_secret.decode("utf-16-le")
        except (UnicodeDecodeError, ValueError, OSError) as error:
            raise CredentialStoreError("Windows credential operation failed.") from error

    @staticmethod
    def _raise_operation_error() -> None:
        raise CredentialStoreError("Windows credential operation failed.")
