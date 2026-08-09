from datetime import timedelta
from typing import BinaryIO

from django.conf import settings
from minio import Minio
from minio.error import S3Error

from .base import ObjectStorage


def _remaining_length(stream: BinaryIO) -> int:
    start = stream.tell()
    stream.seek(0, 2)
    end = stream.tell()
    stream.seek(start)
    return end - start


class MinioObjectStorage(ObjectStorage):
    def __init__(self, *, client=None, bucket: str | None = None) -> None:
        self.bucket = bucket or settings.MINIO_BUCKET
        self.client = client or Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        if not self.client.bucket_exists(self.bucket):
            try:
                self.client.make_bucket(self.bucket)
            except S3Error as error:
                if error.code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
                    raise

    def put(self, stream: BinaryIO, key: str) -> None:
        self.client.put_object(
            self.bucket,
            key,
            stream,
            _remaining_length(stream),
        )

    def open(self, key: str) -> BinaryIO:
        try:
            return self.client.get_object(self.bucket, key)
        except S3Error as error:
            if error.code in {"NoSuchKey", "NoSuchObject"}:
                raise FileNotFoundError(key) from error
            raise

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def presigned_download_url(self, key: str, expires_seconds: int) -> str:
        return self.client.presigned_get_object(
            self.bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
        )
