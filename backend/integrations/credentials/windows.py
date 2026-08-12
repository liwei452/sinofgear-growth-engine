from __future__ import annotations

import ctypes
from ctypes import wintypes

from .base import CredentialStoreError

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
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
    """Store generic credentials for this Windows user on this local machine."""

    def __init__(self, *, api: object | None = None) -> None:
        self._api = api if api is not None else _windows_credential_api()

    def read(self, target: str) -> str | None:
        credential_pointer = PCREDENTIALW()
        try:
            found = self._api.CredReadW(
                target,
                CRED_TYPE_GENERIC,
                0,
                ctypes.byref(credential_pointer),
            )
        except OSError:
            pass
        else:
            if not found:
                if self._last_error() == ERROR_NOT_FOUND:
                    return None
                self._raise_operation_error()
            return self._read_credential(credential_pointer)
        self._raise_operation_error()

    def write(self, target: str, secret: str) -> None:
        if not secret:
            raise CredentialStoreError("Credential secret must not be empty.")

        secret_blob = self._encode_secret(secret)
        blob_buffer = (ctypes.c_ubyte * len(secret_blob)).from_buffer_copy(secret_blob)
        credential = CREDENTIALW(
            Type=CRED_TYPE_GENERIC,
            TargetName=target,
            CredentialBlobSize=len(secret_blob),
            CredentialBlob=ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_ubyte)),
            Persist=CRED_PERSIST_LOCAL_MACHINE,
        )
        try:
            written = self._api.CredWriteW(ctypes.pointer(credential), 0)
        except OSError:
            written = False
        if not written:
            self._raise_operation_error()

    def delete(self, target: str) -> bool:
        try:
            deleted = self._api.CredDeleteW(target, CRED_TYPE_GENERIC, 0)
        except OSError:
            pass
        else:
            if deleted:
                return True
            if self._last_error() == ERROR_NOT_FOUND:
                return False
            self._raise_operation_error()
        self._raise_operation_error()

    def _read_credential(self, credential_pointer: PCREDENTIALW) -> str:
        try:
            return self._decode_secret(credential_pointer.contents)
        finally:
            self._api.CredFree(credential_pointer)

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
        except (UnicodeDecodeError, ValueError, OSError):
            pass
        raise CredentialStoreError("Windows credential operation failed.") from None

    @staticmethod
    def _encode_secret(secret: str) -> bytes:
        try:
            return secret.encode("utf-16-le")
        except UnicodeEncodeError:
            pass
        raise CredentialStoreError("Windows credential operation failed.") from None

    @staticmethod
    def _raise_operation_error() -> None:
        raise CredentialStoreError("Windows credential operation failed.") from None
