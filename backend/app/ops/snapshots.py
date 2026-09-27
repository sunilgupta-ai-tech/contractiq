"""
Qdrant snapshots (Phase 23).

A snapshot is a point-in-time copy of the vector collection, taken by the
Qdrant server itself. `save_snapshot` creates one and copies it into object
storage under backups/qdrant/, so it survives the loss of the Qdrant
volume. `restore_snapshot` uploads such a copy back into Qdrant, replacing
the collection's contents.

Vectors can always be rebuilt from PostgreSQL and each version's stored
chunks (`python -m app.ops reindex`). A snapshot is the faster route back,
and it costs no embedding calls. See docs/reliability.md for which to use.

Files move through a temporary file on disk, never whole in memory: a
collection for 10,000+ documents is several GB.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from qdrant_client import AsyncQdrantClient

from app.core.config import Settings
from app.storage.base import ObjectStorage

BACKUP_PREFIX = "backups/qdrant"
SNAPSHOT_CONTENT_TYPE = "application/octet-stream"
_CHUNK = 1024 * 1024
_TRANSFER_TIMEOUT = httpx.Timeout(30.0, read=30 * 60.0, write=30 * 60.0)


@dataclass(frozen=True)
class SavedSnapshot:
    name: str
    storage_key: str
    size_bytes: int


def backup_key(collection: str, name: str) -> str:
    return f"{BACKUP_PREFIX}/{collection}/{name}"


def _headers(settings: Settings) -> dict[str, str]:
    if settings.qdrant_api_key is None:
        return {}
    return {"api-key": settings.qdrant_api_key.get_secret_value()}


async def save_snapshot(
    qdrant: AsyncQdrantClient, storage: ObjectStorage, settings: Settings, *, keep: int = 3
) -> SavedSnapshot:
    """Create a snapshot, copy it to storage, keep the newest `keep` on the
    Qdrant server (snapshots there take disk space next to the data)."""
    collection = settings.qdrant_collection
    description = await qdrant.create_snapshot(collection_name=collection, wait=True)
    if description is None:
        raise RuntimeError("Qdrant did not return a snapshot description")
    url = f"{settings.qdrant_url.rstrip('/')}/collections/{collection}/snapshots/{description.name}"
    key = backup_key(collection, description.name)
    with tempfile.TemporaryDirectory(prefix="qdrant-snapshot-") as tmp:
        path = os.path.join(tmp, description.name)
        async with (
            httpx.AsyncClient(timeout=_TRANSFER_TIMEOUT, headers=_headers(settings)) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            await _write_chunks(path, response.aiter_bytes(_CHUNK))
        size = os.path.getsize(path)
        await storage.put_file(key, path, SNAPSHOT_CONTENT_TYPE)
    await prune_server_snapshots(qdrant, collection, keep=keep)
    return SavedSnapshot(name=description.name, storage_key=key, size_bytes=size)


async def prune_server_snapshots(qdrant: AsyncQdrantClient, collection: str, *, keep: int) -> int:
    snapshots = await qdrant.list_snapshots(collection_name=collection)
    snapshots.sort(key=lambda s: s.creation_time or "", reverse=True)
    stale = snapshots[max(keep, 1) :]
    for snapshot in stale:
        await qdrant.delete_snapshot(collection_name=collection, snapshot_name=snapshot.name)
    return len(stale)


async def restore_snapshot(storage: ObjectStorage, settings: Settings, storage_key: str) -> None:
    """Replace the collection's contents with a stored snapshot. The
    collection is recreated from the snapshot; points written since it was
    taken are lost (reindex the documents processed after it)."""
    collection = settings.qdrant_collection
    url = f"{settings.qdrant_url.rstrip('/')}/collections/{collection}/snapshots/upload"
    with tempfile.TemporaryDirectory(prefix="qdrant-restore-") as tmp:
        path = os.path.join(tmp, "snapshot")
        await _write_chunks(path, storage.stream(storage_key))
        snapshot = await asyncio.to_thread(open, path, "rb")
        try:
            async with httpx.AsyncClient(
                timeout=_TRANSFER_TIMEOUT, headers=_headers(settings)
            ) as client:
                response = await client.post(
                    url,
                    params={"priority": "snapshot", "wait": "true"},
                    files={"snapshot": (os.path.basename(storage_key), snapshot)},
                )
            response.raise_for_status()
        finally:
            snapshot.close()


async def _write_chunks(path: str, chunks: AsyncIterator[bytes]) -> None:
    handle = await asyncio.to_thread(open, path, "wb")
    try:
        async for chunk in chunks:
            await asyncio.to_thread(handle.write, chunk)
    finally:
        handle.close()
