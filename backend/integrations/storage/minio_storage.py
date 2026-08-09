import hashlib
from datetime import timedelta
from typing import BinaryIO
from urllib.parse import urlunsplit

from django.conf import settings
from minio import Minio
from minio import time as minio_time
from minio.error import S3Error
from minio.signer import sign_v4_s3

from .base import ObjectStorage


def _remaining_length(stream: BinaryIO) -> int:
    start = stream.tell()
    stream.seek(0, 2)
    end = stream.tell()
    stream.seek(start)
    return end - start


def _sha256_stream(stream: BinaryIO) -> str:
    start = stream.tell()
    digest = hashlib.sha256()
    while chunk := stream.read(64 * 1024):
        digest.update(chunk)
    stream.seek(start)
    return digest.hexdigest()


def _conditional_put_object(client, bucket: str, key: str, stream: BinaryIO) -> bool:
    """Issue streaming S3 PutObject with If-None-Match instead of overwriting."""
    length = _remaining_length(stream)
    content_sha256 = _sha256_stream(stream)
    region = client._get_region(bucket)
    url = client._base_url.build(
        method="PUT",
        region=region,
        bucket_name=bucket,
        object_name=key,
    )
    credentials = client._provider.retrieve() if client._provider else None
    date = minio_time.utcnow()
    headers = {
        "Host": url.netloc,
        "User-Agent": client._user_agent,
        "Content-Length": str(length),
        "If-None-Match": "*",
        "x-amz-content-sha256": content_sha256,
        "x-amz-date": minio_time.to_amz_date(date),
    }
    if credentials:
        if credentials.session_token:
            headers["X-Amz-Security-Token"] = credentials.session_token
        headers = sign_v4_s3(
            method="PUT",
            url=url,
            region=region,
            headers=headers,
            credentials=credentials,
            content_sha256=content_sha256,
            date=date,
        )
    response = client._http.urlopen(
        "PUT",
        urlunsplit(url),
        body=stream,
        headers=headers,
        preload_content=True,
    )
    try:
        if response.status in {200, 204}:
            return True
        if response.status in {409, 412}:
            return False
        response.read(cache_content=True)
        if response.data:
            raise S3Error.fromxml(response)
        raise S3Error(
            response=response,
            code="ConditionalPutFailed",
            message=f"Conditional PutObject failed with HTTP {response.status}",
            resource=key,
            request_id=response.headers.get("x-amz-request-id"),
            host_id=response.headers.get("x-amz-id-2"),
            bucket_name=bucket,
            object_name=key,
        )
    finally:
        response.release_conn()


class MinioResponseStream:
    """File-like response that always closes and releases its HTTP connection."""

    def __init__(self, response) -> None:
        self._response = response
        self._closed = False

    def read(self, *args, **kwargs):
        return self._response.read(*args, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._response.close()
        finally:
            self._response.release_conn()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def __getattr__(self, name):
        return getattr(self._response, name)


class MinioObjectStorage(ObjectStorage):
    def __init__(self, *, client=None, public_client=None, bucket: str | None = None) -> None:
        self.bucket = bucket or settings.MINIO_BUCKET
        self.client = client or Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.public_client = public_client or (
            self.client
            if client is not None
            else Minio(
                settings.MINIO_PUBLIC_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_PUBLIC_SECURE,
            )
        )
        if not self.client.bucket_exists(self.bucket):
            try:
                self.client.make_bucket(self.bucket)
            except S3Error as error:
                if error.code != "BucketAlreadyOwnedByYou":
                    raise
                if not self.client.bucket_exists(self.bucket):
                    raise

    def put(self, stream: BinaryIO, key: str) -> bool:
        conditional_put = getattr(self.client, "put_object_if_absent", None)
        if conditional_put is not None:
            return conditional_put(
                self.bucket,
                key,
                stream,
                _remaining_length(stream),
            )
        return _conditional_put_object(self.client, self.bucket, key, stream)

    def open(self, key: str) -> BinaryIO:
        try:
            return MinioResponseStream(self.client.get_object(self.bucket, key))
        except S3Error as error:
            if error.code in {"NoSuchKey", "NoSuchObject"}:
                raise FileNotFoundError(key) from error
            raise

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def presigned_download_url(self, key: str, expires_seconds: int) -> str:
        return self.public_client.presigned_get_object(
            self.bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
        )
