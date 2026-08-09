from functools import lru_cache

from django.conf import settings

from integrations.storage.base import ObjectStorage
from integrations.storage.memory_storage import MemoryObjectStorage
from integrations.storage.minio_storage import MinioObjectStorage


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStorage:
    backend = settings.OBJECT_STORAGE_BACKEND
    if backend == "memory":
        return MemoryObjectStorage()
    if backend == "minio":
        return MinioObjectStorage()
    raise ValueError(f"Unsupported object storage backend: {backend}")


def reset_object_storage() -> None:
    """Drop the configured adapter and all process-local memory-backend state."""
    get_object_storage.cache_clear()
