from __future__ import annotations

import ctypes

import pytest

from integrations.credentials.windows import (
    CRED_PERSIST_SESSION,
    CRED_TYPE_GENERIC,
    ERROR_NOT_FOUND,
    CREDENTIALW,
    CredentialStoreError,
    WindowsCredentialStore,
)


class FakeWincred:
    """A test double for the Windows API; it never reaches the OS vault."""

    def __init__(self) -> None:
        self.entries: dict[str, bytes] = {}
        self.last_error = ERROR_NOT_FOUND
        self.allocated: list[tuple[CREDENTIALW, ctypes.Array[ctypes.c_char]]] = []
        self.freed = 0
        self.write_calls = 0
        self.fail_write = False
        self.raw_error_text = "raw operating-system failure text"

    def CredWriteW(self, credential, flags: int) -> bool:  # noqa: N802
        self.write_calls += 1
        assert flags == 0
        value = credential.contents
        assert value.Type == CRED_TYPE_GENERIC
        assert value.Persist == CRED_PERSIST_SESSION
        assert value.CredentialBlobSize % 2 == 0
        blob = ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize)
        assert value.CredentialBlobSize == len(blob)
        if self.fail_write:
            self.last_error = 5
            return False
        self.entries[value.TargetName] = blob
        return True

    def CredReadW(self, target: str, credential_type: int, flags: int, result) -> bool:  # noqa: N802
        assert credential_type == CRED_TYPE_GENERIC
        assert flags == 0
        blob = self.entries.get(target)
        if blob is None:
            self.last_error = ERROR_NOT_FOUND
            return False

        buffer = ctypes.create_string_buffer(blob, len(blob))
        credential = CREDENTIALW()
        credential.Type = CRED_TYPE_GENERIC
        credential.Persist = CRED_PERSIST_SESSION
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        self.allocated.append((credential, buffer))
        result_pointer = ctypes.cast(result, ctypes.POINTER(ctypes.POINTER(CREDENTIALW)))
        result_pointer[0] = ctypes.pointer(credential)
        return True

    def CredDeleteW(self, target: str, credential_type: int, flags: int) -> bool:  # noqa: N802
        assert credential_type == CRED_TYPE_GENERIC
        assert flags == 0
        if target not in self.entries:
            self.last_error = ERROR_NOT_FOUND
            return False
        del self.entries[target]
        return True

    def CredFree(self, credential) -> None:  # noqa: N802
        assert credential
        self.freed += 1

    def get_last_error(self) -> int:
        return self.last_error


@pytest.fixture
def fake_wincred() -> FakeWincred:
    return FakeWincred()


def test_windows_store_round_trips_unicode_secret(fake_wincred: FakeWincred) -> None:
    store = WindowsCredentialStore(api=fake_wincred)
    target = "SinofGear/DeepSeek/org-1"
    secret = "sk-瀵嗛挜-value"

    store.write(target, secret)

    assert fake_wincred.entries[target] == secret.encode("utf-16-le")
    assert store.read(target) == secret
    assert fake_wincred.freed == 1
    assert store.delete(target) is True
    assert store.read(target) is None


def test_windows_store_rejects_empty_secret_without_calling_os(
    fake_wincred: FakeWincred,
) -> None:
    store = WindowsCredentialStore(api=fake_wincred)

    with pytest.raises(CredentialStoreError, match="empty"):
        store.write("SinofGear/DeepSeek/org-1", "")

    assert fake_wincred.write_calls == 0


def test_windows_store_returns_not_found_without_freeing_unallocated_credential(
    fake_wincred: FakeWincred,
) -> None:
    store = WindowsCredentialStore(api=fake_wincred)

    assert store.read("SinofGear/DeepSeek/missing") is None
    assert store.delete("SinofGear/DeepSeek/missing") is False
    assert fake_wincred.freed == 0


def test_windows_store_replaces_raw_os_errors_without_exposing_target_or_secret(
    fake_wincred: FakeWincred,
) -> None:
    store = WindowsCredentialStore(api=fake_wincred)
    fake_wincred.fail_write = True
    target = "SinofGear/DeepSeek/target-not-for-errors"
    secret = "sk-not-for-errors"

    with pytest.raises(CredentialStoreError) as captured:
        store.write(target, secret)

    message = str(captured.value)
    assert fake_wincred.raw_error_text not in message
    assert target not in message
    assert secret not in message
