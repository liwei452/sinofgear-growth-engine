from io import BytesIO
from pathlib import Path

import pytest
import yaml
from minio import Minio
from minio.error import S3Error

from apps.identity.models import Role
from integrations.storage.minio_storage import MinioObjectStorage

from .conftest import create_member_client, upload_payload
from .test_storage import RawMinioClient, RawResponse


def test_real_minio_sdk_presigns_public_url_without_region_network_lookup(
    settings, monkeypatch
) -> None:
    settings.MINIO_ENDPOINT = "minio:9000"
    settings.MINIO_PUBLIC_ENDPOINT = "localhost:9000"
    settings.MINIO_ACCESS_KEY = "access"
    settings.MINIO_SECRET_KEY = "secret"
    settings.MINIO_BUCKET = "assets"
    settings.MINIO_SECURE = False
    settings.MINIO_PUBLIC_SECURE = False
    settings.MINIO_REGION = "us-east-1"
    monkeypatch.setattr(Minio, "bucket_exists", lambda self, bucket: True)
    storage = MinioObjectStorage()

    def reject_network_lookup(*args, **kwargs):
        raise AssertionError("public signer attempted a network region lookup")

    monkeypatch.setattr(storage.public_client, "_url_open", reject_network_lookup)

    url = storage.presigned_download_url("organizations/o/assets/a/original", 300)

    assert url.startswith("http://localhost:9000/assets/organizations/o/assets/a/original?")


@pytest.mark.django_db
def test_deep_multipart_json_returns_documented_json_400(organizations, roles) -> None:
    own, _ = organizations
    _, client = create_member_client(
        organization=own,
        role=roles[Role.Code.OPERATOR],
        username="deep-multipart-json",
    )
    payload = upload_payload()
    payload["metadata_json"] = "[" * 5_000 + "0" + "]" * 5_000
    client.raise_request_exception = False

    response = client.post("/api/v1/assets", payload, format="multipart")

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert "metadata_json" in response.json()["errors"]


class ConflictHTTP:
    def urlopen(self, method, url, *, body, headers, preload_content):
        body.read()
        response = RawResponse(409)
        response.data = (
            b"<Error><Code>OperationAborted</Code>"
            b"<Message>another operation is in progress</Message></Error>"
        )
        return response


def test_minio_conditional_put_propagates_unrelated_http_409() -> None:
    client = RawMinioClient()
    client._http = ConflictHTTP()
    storage = MinioObjectStorage(client=client, bucket="assets")

    with pytest.raises(S3Error) as captured:
        storage.put(BytesIO(b"new object"), "organizations/o/assets/a/original")

    assert captured.value.code == "OperationAborted"


def test_compose_binds_minio_api_to_loopback_only() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    compose = yaml.safe_load((repository_root / "docker-compose.yml").read_text(encoding="utf-8"))

    assert compose["services"]["minio"]["ports"] == ["127.0.0.1:9000:9000"]
