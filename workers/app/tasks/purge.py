"""
`purge_document` — erase what a deleted document left outside PostgreSQL
(Phase 24): its vectors and files (again, in case the API's attempt failed
or a job still in flight wrote more after the delete) and the
organization's document-derived caches. See app/services/erasure.py.
"""

from __future__ import annotations

from typing import Any

from app.services.erasure import erase_document_data


async def purge_document(ctx: dict[str, Any], tenant_id: str, document_id: str) -> dict[str, Any]:
    return await erase_document_data(ctx["resources"], tenant_id, document_id)
