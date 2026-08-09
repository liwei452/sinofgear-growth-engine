from datetime import timedelta
from io import BytesIO

import pytest
from minio.error import S3Error

from integrations.storage.memory_storage import MemoryObjectStorage
from integrations.storage.minio_storage import MinioObjectStorage


def test_memory_storage_copies_put_bytes_and_returns_independent_streams() -> None:
    storage = MemoryObjectStorage()
    source = BytesIO(b"original")

    storage.put(source, "key")
    source.getbuffer()[0] = ord("X")
    first = storage.open("key")
    first.getbuffer()[0] = ord("Y")

    assert storage.open("key").read() == b"original"


def test_memory_storage_delete_and_missing_key_contract() -> None:
    storage = MemoryObjectStorage()
    storage.put(BytesIO(b"stored"), "key")

    storage.delete("key")
    storage.delete("key")

    with pytest.raises(FileNotFoundError):
        storage.open("key")


def test_memory_storage_signed_url_has_exact_expiry_and_no_credentials() -> None:
    storage = MemoryObjectStorage()

    url = storage.presigned_download_url("organizations/o/assets/a/original", 300)

    assert "expires=300" in url
    assert "secret" not in url.lower()
    assert "credential" not in url.lower()


class FakeMinioClient:
    def __init__(
        self,
        *,
        bucket_exists: bool = True,
        make_error: Exception | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.exists = bucket_exists
        self.make_error = make_error
        self.get_error = get_error
        self.calls: list[tuple[object, ...]] = []
        self.response = BytesIO(b"remote")

    def bucket_exists(self, bucket: str) -> bool:
        self.calls.append(("bucket_exists", bucket))
        return self.exists

    def make_bucket(self, bucket: str) -> None:
        self.calls.append(("make_bucket", bucket))
        if self.make_error is not None:
            raise self.make_error

    def put_object(self, bucket: str, key: str, stream, length: int) -> None:
        self.calls.append(("put_object", bucket, key, stream.read(), length))

    def get_object(self, bucket: str, key: str):
        self.calls.append(("get_object", bucket, key))
        if self.get_error is not None:
            raise self.get_error
        return self.response

    def remove_object(self, bucket: str, key: str) -> None:
        self.calls.append(("remove_object", bucket, key))

    def presigned_get_object(self, bucket: str, key: str, *, expires: timedelta) -> str:
        self.calls.append(("presigned_get_object", bucket, key, expires))
        return "https://objects.example/download?signature=opaque"


def test_minio_adapter_validates_bucket_and_delegates_contract() -> None:
    client = FakeMinioClient(bucket_exists=False)
    storage = MinioObjectStorage(client=client, bucket="assets")

    storage.put(BytesIO(b"abc"), "key")
    opened = storage.open("key")
    storage.delete("key")
    url = storage.presigned_download_url("key", 300)

    assert opened.read() == b"remote"
    assert url == "https://objects.example/download?signature=opaque"
    assert client.calls == [
        ("bucket_exists", "assets"),
        ("make_bucket", "assets"),
        ("put_object", "assets", "key", b"abc", 3),
        ("get_object", "assets", "key"),
        ("remove_object", "assets", "key"),
        ("presigned_get_object", "assets", "key", timedelta(seconds=300)),
    ]


def _s3_error(code: str) -> S3Error:
    return S3Error(None, code, code, None, None, None)


def test_minio_adapter_tolerates_bucket_creation_race() -> None:
    client = FakeMinioClient(
        bucket_exists=False,
        make_error=_s3_error("BucketAlreadyOwnedByYou"),
    )

    storage = MinioObjectStorage(client=client, bucket="assets")

    assert storage.bucket == "assets"
    assert client.calls == [("bucket_exists", "assets"), ("make_bucket", "assets")]


def test_minio_adapter_translates_missing_object() -> None:
    client = FakeMinioClient(get_error=_s3_error("NoSuchKey"))
    storage = MinioObjectStorage(client=client, bucket="assets")

    with pytest.raises(FileNotFoundError, match="missing"):
        storage.open("missing")
