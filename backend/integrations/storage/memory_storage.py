from io import BytesIO
from threading import RLock
from typing import BinaryIO
from urllib.parse import quote

from .base import ObjectStorage


class MemoryObjectStorage(ObjectStorage):
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = RLock()

    def put(self, stream: BinaryIO, key: str) -> None:
        payload = bytes(stream.read())
        with self._lock:
            self._objects[key] = payload

    def open(self, key: str) -> BytesIO:
        with self._lock:
            try:
                payload = self._objects[key]
            except KeyError as error:
                raise FileNotFoundError(key) from error
        return BytesIO(bytes(payload))

    def delete(self, key: str) -> None:
        with self._lock:
            self._objects.pop(key, None)

    def presigned_download_url(self, key: str, expires_seconds: int) -> str:
        return f"memory://download/{quote(key, safe='/')}?expires={expires_seconds}"
