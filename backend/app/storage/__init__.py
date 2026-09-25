from app.core.config import Settings, StorageBackend
from app.storage.base import ObjectStorage, build_object_key, document_prefix


def create_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend is StorageBackend.S3:
        from app.storage.s3 import S3ObjectStorage

        return S3ObjectStorage(settings)
    from app.storage.local import LocalObjectStorage

    return LocalObjectStorage(settings.local_storage_path)


__all__ = ["ObjectStorage", "build_object_key", "create_storage", "document_prefix"]
