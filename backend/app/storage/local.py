from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.core.exceptions import NotFoundError


class LocalObjectStorage:
    """Filesystem storage for development. Paths are resolved and checked to
    stay under the root so a crafted key cannot escape it (path traversal)."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise NotFoundError("Stored object not found.")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def delete_prefix(self, prefix: str) -> None:
        # Refuse an empty prefix: it would resolve to the storage root and
        # delete every tenant's files.
        if not prefix.strip("/"):
            raise ValueError("Refusing to delete the storage root")
        path = self._path(prefix)
        if path.is_dir():
            await asyncio.to_thread(shutil.rmtree, path)
