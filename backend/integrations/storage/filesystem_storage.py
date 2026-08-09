from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.parse import quote

from .base import ObjectStorage


class FileSystemObjectStorage(ObjectStorage):
    """Create-only local storage for child-owned isolated acceptance runs."""

    def __init__(self, *, root) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        logical = PurePosixPath(key)
        if logical.is_absolute() or not logical.parts or any(
            part in {"", ".", ".."} for part in logical.parts
        ):
            raise ValueError("Object key must be a safe relative path.")
        path = self.root.joinpath(*logical.parts).resolve()
        if path == self.root or self.root not in path.parents:
            raise ValueError("Object key must be a safe relative path.")
        return path

    def put(self, stream: BinaryIO, key: str) -> bool:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as target:
                while chunk := stream.read(1024 * 1024):
                    target.write(chunk)
        except FileExistsError:
            return False
        return True

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def presigned_download_url(self, key: str, expires_seconds: int) -> str:
        if not isinstance(expires_seconds, int) or expires_seconds <= 0:
            raise ValueError("Expiry must be a positive integer.")
        path = self._path(key)
        return f"file:///{quote(path.as_posix().lstrip('/'), safe='/')}?expires={expires_seconds}"
