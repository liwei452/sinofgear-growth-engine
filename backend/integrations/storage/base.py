from abc import ABC, abstractmethod
from typing import BinaryIO


class ObjectStorage(ABC):
    @abstractmethod
    def put(self, stream: BinaryIO, key: str) -> bool:
        """Create key from stream, returning False without overwriting on collision."""
        raise NotImplementedError

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def presigned_download_url(self, key: str, expires_seconds: int) -> str:
        raise NotImplementedError
