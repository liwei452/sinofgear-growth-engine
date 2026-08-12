from __future__ import annotations

import ctypes

import pytest

from integrations.credentials.windows import (
    CRED_PERSIST_LOCAL_MACHINE,
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
        self.raise_write_os_error = False
        self.raise_read_os_error = False
        self.raise_delete_os_error = False
        self.raw_error_text = "raw operating-system failure text"

    def CredWriteW(self, credential, flags: int) -> bool:  # noqa: N802
        self.write_calls += 1
        assert flags == 0
        value = credential.contents
        assert value.Type == CRED_TYPE_GENERIC
        assert value.Persist == CRED_PERSIST_LOCAL_MACHINE
        assert value.CredentialBlobSize % 2 == 0
        blob = ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize)
        assert value.CredentialBlobSize == len(blob)
        if self.raise_write_os_error:
            raise OSError(self.raw_error_text)
        if self.fail_write:
            self.last_error = 5
            return False
        self.entries[value.TargetName] = blob
        return True

    def CredReadW(self, target: str, credential_type: int, flags: int, result) -> bool:  # noqa: N802
        assert credential_type == CRED_TYPE_GENERIC
        assert flags == 0
        if self.raise_read_os_error:
            raise OSError(self.raw_error_text)
        blob = self.entries.get(target)
        if blob is None:
            self.last_error = ERROR_NOT_FOUND
            return False

        buffer = ctypes.create_string_buffer(blob, len(blob))
        credential = CREDENTIALW()
        credential.Type = CRED_TYPE_GENERIC
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        self.allocated.append((credential, buffer))
        result_pointer = ctypes.cast(result, ctypes.POINTER(ctypes.POINTER(CREDENTIALW)))
        result_pointer[0] = ctypes.pointer(credential)
        return True

    def CredDeleteW(self, target: str, credential_type: int, flags: int) -> bool:  # noqa: N802
        assert credential_type == CRED_TYPE_GENERIC
        assert flags == 0
        if self.raise_delete_os_error:
            raise OSError(self.raw_error_text)
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
    fake_wincred.raise_write_os_error = True
    target = "SinofGear/DeepSeek/target-not-for-errors"
    secret = "sk-not-for-errors"

    with pytest.raises(CredentialStoreError) as captured:
        store.write(target, secret)

    _assert_exception_chain_excludes(
        captured.value,
        fake_wincred.raw_error_text,
        target,
        secret,
    )


@pytest.mark.parametrize("operation", ["read", "delete"])
def test_windows_store_drops_read_and_delete_os_errors_from_exception_chain(
    fake_wincred: FakeWincred,
    operation: str,
) -> None:
    store = WindowsCredentialStore(api=fake_wincred)
    target = "SinofGear/DeepSeek/target-not-for-errors"
    secret = "sk-not-for-errors"
    fake_wincred.entries[target] = secret.encode("utf-16-le")
    setattr(fake_wincred, f"raise_{operation}_os_error", True)

    with pytest.raises(CredentialStoreError) as captured:
        getattr(store, operation)(target)

    _assert_exception_chain_excludes(
        captured.value,
        fake_wincred.raw_error_text,
        target,
        secret,
    )


def test_windows_store_drops_unencodable_secret_from_exception_chain(
    fake_wincred: FakeWincred,
) -> None:
    store = WindowsCredentialStore(api=fake_wincred)
    secret = "sk-\ud800-not-for-exceptions"

    with pytest.raises(CredentialStoreError) as captured:
        store.write("SinofGear/DeepSeek/org-1", secret)

    _assert_exception_chain_excludes(captured.value, secret)


def test_windows_store_drops_malformed_credential_blob_from_exception_chain(
    fake_wincred: FakeWincred,
) -> None:
    store = WindowsCredentialStore(api=fake_wincred)
    target = "SinofGear/DeepSeek/org-1"
    malformed_blob = b"\x00"
    fake_wincred.entries[target] = malformed_blob

    with pytest.raises(CredentialStoreError) as captured:
        store.read(target)

    _assert_exception_chain_excludes(captured.value, malformed_blob)


def _assert_exception_chain_excludes(error: BaseException, *forbidden: object) -> None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        values = (str(current), repr(current), current.args, getattr(current, "object", None))
        for value in values:
            for sensitive_value in forbidden:
                assert not _contains_sensitive_value(value, sensitive_value)
        current = current.__cause__ or current.__context__


def _contains_sensitive_value(value: object, sensitive_value: object) -> bool:
    if isinstance(value, tuple):
        return any(_contains_sensitive_value(item, sensitive_value) for item in value)
    if isinstance(value, str) and isinstance(sensitive_value, str):
        return sensitive_value in value
    if isinstance(value, bytes) and isinstance(sensitive_value, bytes):
        return sensitive_value in value
    return value == sensitive_value
