"""Background contract analysis (Phase 10).

Queued by the API when a risk or portfolio request spans more un-analysed
documents than it analyses inline (ANALYSIS_SYNC_DOCUMENTS). The result is
the same cached analysis the API would have produced, so the next request
finds it ready.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.db.models import DocumentStatus
from app.db.repositories.document_repository import (
    DocumentAccess,
    DocumentRepository,
    DocumentVersionRepository,
)
from app.db.tenancy import bind_tenant
from app.services.contract_service import ContractAnalyzer, VersionRef

logger = get_logger("contractiq.worker.analysis")


async def analyze_version(
    ctx: dict[str, Any], tenant_id: str, document_id: str, version_id: str
) -> dict[str, Any]:
    """Extract and cache the clauses of one version. The ids are re-checked
    against the database inside the tenant, so a stale or foreign job does
    nothing; a version that is not (or no longer) processed is skipped."""
    resources = ctx["resources"]
    tenant = uuid.UUID(tenant_id)
    try:
        async with resources.db.session_factory() as session:
            await bind_tenant(session, tenant)
            # The worker serves no user: it sees every document of the tenant.
            access = DocumentAccess.system()
            document = await DocumentRepository(session, tenant, access=access).get(
                uuid.UUID(document_id)
            )
            version = await DocumentVersionRepository(session, tenant, access=access).get(
                uuid.UUID(version_id)
            )
    except NotFoundError:  # deleted since the job was queued: nothing to do, don't retry
        return {"status": "skipped", "version_id": version_id}
    if version.document_id != document.id or version.status is not DocumentStatus.COMPLETED:
        return {"status": "skipped", "version_id": version_id}

    analysis = await ContractAnalyzer.from_resources(resources).clauses(
        VersionRef.of(document, version)
    )
    found = sum(1 for c in analysis.clauses if c.found)
    logger.info(
        "analysis_completed",
        extra={"version_id": version_id, "found": found, "cached": analysis.complete},
    )
    return {"status": "completed", "version_id": version_id, "clauses_found": found}
