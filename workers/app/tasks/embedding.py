"""Re-embedding job (Phase 6): re-embed a tenant's chunks after an embedding
model change, writing to a new collection alias so search stays online."""

from __future__ import annotations

from typing import Any


async def reembed_tenant(ctx: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    raise NotImplementedError("Phase 6")
