"""
Object storage abstraction.

Local filesystem in development, S3 in production — selected by
STORAGE_BACKEND. Services depend on `ObjectStorage`, never on boto3.
"""

from __future__ import annotations

from typing import Protocol


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...


def build_object_key(tenant_id: str, document_id: str, version_id: str, filename: str) -> str:
    """Tenant-prefixed keys let S3 bucket policies and lifecycle rules be
    applied per tenant, and make accidental cross-tenant reads obvious."""
    return f"tenants/{tenant_id}/documents/{document_id}/{version_id}/{filename}"
