from datetime import timedelta
from io import BytesIO
from urllib.parse import quote
from urllib.parse import urlsplit

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


def test_memory_storage_put_is_create_only_and_preserves_existing_key() -> None:
    storage = MemoryObjectStorage()

    created = storage.put(BytesIO(b"original"), "key")
    collided = storage.put(BytesIO(b"replacement"), "key")

    assert created is True
    assert collided is False
    assert storage.open("key").read() == b"original"


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
        bucket_exists_values: list[bool] | None = None,
    ) -> None:
        self.exists = bucket_exists
        self.bucket_exists_values = list(bucket_exists_values or [])
        self.make_error = make_error
        self.get_error = get_error
        self.calls: list[tuple[object, ...]] = []
        self.response = BytesIO(b"remote")
        self.objects: dict[str, bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        self.calls.append(("bucket_exists", bucket))
        if self.bucket_exists_values:
            return self.bucket_exists_values.pop(0)
        return self.exists

    def make_bucket(self, bucket: str) -> None:
        self.calls.append(("make_bucket", bucket))
        if self.make_error is not None:
            raise self.make_error

    def put_object(self, bucket: str, key: str, stream, length: int) -> None:
        payload = stream.read()
        self.calls.append(("put_object", bucket, key, payload, length))
        self.objects[key] = payload

    def put_object_if_absent(self, bucket: str, key: str, stream, length: int) -> bool:
        payload = stream.read()
        self.calls.append(("put_object_if_absent", bucket, key, payload, length))
        if key in self.objects:
            return False
        self.objects[key] = payload
        return True

    def get_object(self, bucket: str, key: str):
        self.calls.append(("get_object", bucket, key))
        if self.get_error is not None:
            raise self.get_error
        return self.response

    def remove_object(self, bucket: str, key: str) -> None:
        self.calls.append(("remove_object", bucket, key))

    def presigned_get_object(self, bucket: str, key: str, *, expires: timedelta) -> str:
        self.calls.append(("presigned_get_object", bucket, key, expires))
        return f"https://objects.example/{quote(key, safe='/')}?signature=opaque"


def test_minio_adapter_validates_bucket_and_delegates_contract() -> None:
    client = FakeMinioClient(bucket_exists=False)
    storage = MinioObjectStorage(client=client, bucket="assets")

    assert storage.put(BytesIO(b"abc"), "key") is True
    opened = storage.open("key")
    storage.delete("key")
    url = storage.presigned_download_url("key", 300)

    assert opened.read() == b"remote"
    assert url == "https://objects.example/key?signature=opaque"
    assert client.calls == [
        ("bucket_exists", "assets"),
        ("make_bucket", "assets"),
        ("put_object_if_absent", "assets", "key", b"abc", 3),
        ("get_object", "assets", "key"),
        ("remove_object", "assets", "key"),
        ("presigned_get_object", "assets", "key", timedelta(seconds=300)),
    ]


def test_minio_put_is_create_only_and_preserves_existing_key() -> None:
    client = FakeMinioClient()
    storage = MinioObjectStorage(client=client, bucket="assets")

    assert storage.put(BytesIO(b"original"), "key") is True
    assert storage.put(BytesIO(b"replacement"), "key") is False

    assert client.objects["key"] == b"original"


def _s3_error(code: str) -> S3Error:
    return S3Error(None, code, code, None, None, None)


def test_minio_adapter_tolerates_bucket_creation_race() -> None:
    client = FakeMinioClient(
        bucket_exists_values=[False, True],
        make_error=_s3_error("BucketAlreadyOwnedByYou"),
    )

    storage = MinioObjectStorage(client=client, bucket="assets")

    assert storage.bucket == "assets"
    assert client.calls == [
        ("bucket_exists", "assets"),
        ("make_bucket", "assets"),
        ("bucket_exists", "assets"),
    ]


def test_minio_adapter_does_not_suppress_foreign_bucket_collision() -> None:
    client = FakeMinioClient(
        bucket_exists=False,
        make_error=_s3_error("BucketAlreadyExists"),
    )

    with pytest.raises(S3Error, match="BucketAlreadyExists"):
        MinioObjectStorage(client=client, bucket="assets")


def test_minio_adapter_translates_missing_object() -> None:
    client = FakeMinioClient(get_error=_s3_error("NoSuchKey"))
    storage = MinioObjectStorage(client=client, bucket="assets")

    with pytest.raises(FileNotFoundError, match="missing"):
        storage.open("missing")


class ReleasableResponse(BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.close_calls = 0
        self.release_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        super().close()

    def release_conn(self) -> None:
        self.release_calls += 1


def test_minio_open_context_closes_and_releases_response_connection() -> None:
    client = FakeMinioClient()
    response = ReleasableResponse(b"remote")
    client.response = response
    storage = MinioObjectStorage(client=client, bucket="assets")

    with storage.open("key") as opened:
        assert opened.read() == b"remote"

    assert response.close_calls == 1
    assert response.release_calls == 1


def test_minio_presigning_uses_public_client_and_encoded_key() -> None:
    internal = FakeMinioClient()
    public = FakeMinioClient()
    storage = MinioObjectStorage(
        client=internal,
        public_client=public,
        bucket="assets",
    )
    key = "organizations/组织/assets/asset id/original"

    url = storage.presigned_download_url(key, 300)

    assert "%E7%BB%84%E7%BB%87" in url
    assert "asset%20id" in url
    assert ("presigned_get_object", "assets", key, timedelta(seconds=300)) in public.calls
    assert not any(call[0] == "presigned_get_object" for call in internal.calls)


def test_minio_configures_distinct_internal_and_browser_public_endpoints(
    settings, monkeypatch
) -> None:
    settings.MINIO_ENDPOINT = "minio:9000"
    settings.MINIO_SECURE = False
    settings.MINIO_PUBLIC_ENDPOINT = "localhost:9000"
    settings.MINIO_PUBLIC_SECURE = False
    settings.MINIO_ACCESS_KEY = "access"
    settings.MINIO_SECRET_KEY = "secret"
    settings.MINIO_BUCKET = "assets"
    internal = FakeMinioClient()
    public = FakeMinioClient()
    clients = iter([internal, public])
    calls = []

    def build_client(endpoint, **kwargs):
        calls.append((endpoint, kwargs["secure"]))
        return next(clients)

    monkeypatch.setattr("integrations.storage.minio_storage.Minio", build_client)

    storage = MinioObjectStorage()
    url = storage.presigned_download_url("organizations/o/assets/a/original", 300)

    assert calls == [("minio:9000", False), ("localhost:9000", False)]
    assert url.startswith("https://objects.example/")


class RawResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.headers = {}
        self.data = b""
        self.release_calls = 0

    def read(self, cache_content=True):
        return self.data

    def release_conn(self) -> None:
        self.release_calls += 1


class RawHTTP:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls = []

    def urlopen(self, method, url, *, body, headers, preload_content):
        payload = body.read()
        self.calls.append((method, url, payload, dict(headers), preload_content))
        status = 412 if url in self.objects else 200
        if status == 200:
            self.objects[url] = payload
        return RawResponse(status)


class RawBaseURL:
    def build(self, *, method, region, bucket_name, object_name):
        encoded = quote(object_name, safe="/")
        return urlsplit(f"http://minio:9000/{bucket_name}/{encoded}")


class RawMinioClient:
    _provider = None
    _user_agent = "task-seven-test"

    def __init__(self) -> None:
        self._base_url = RawBaseURL()
        self._http = RawHTTP()

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def _get_region(self, bucket: str) -> str:
        return "us-east-1"

    def presigned_get_object(self, bucket, key, *, expires):
        return "https://public.example/download"


def test_minio_default_conditional_http_put_streams_and_preserves_collision() -> None:
    client = RawMinioClient()
    storage = MinioObjectStorage(client=client, bucket="assets")

    first = storage.put(BytesIO(b"original"), "organizations/o/assets/a/original")
    second = storage.put(BytesIO(b"replacement"), "organizations/o/assets/a/original")

    assert first is True
    assert second is False
    assert next(iter(client._http.objects.values())) == b"original"
    assert all(call[3]["If-None-Match"] == "*" for call in client._http.calls)
    assert all(call[3]["Content-Length"] in {"8", "11"} for call in client._http.calls)
