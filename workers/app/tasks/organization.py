"""
Organization deletion (Phase 22).

The platform console marks the organization DELETING (its users are already
signed out and locked out) and queues this job, which erases vectors, files
and cache entries, then the organization row — every tenant table cascades
from it. A record of the deletion stays in the platform audit log.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete

from app.core.logging import get_logger
from app.db.models import Organization, OrganizationStatus, PlatformAuditLog
from app.services.erasure import erase_tenant_data

logger = get_logger("contractiq.worker.organization")


async def delete_organization(ctx: dict[str, Any], organization_id: str) -> dict[str, Any]:
    resources = ctx["resources"]
    org_uuid = uuid.UUID(organization_id)
    async with resources.db.session_factory() as session:
        org = await session.get(Organization, org_uuid)
        if org is None:
            return {"status": "already_deleted"}
        if org.status is not OrganizationStatus.DELETING:
            # Reactivated (or never confirmed) since the job was queued.
            logger.warning(
                "organization_delete_skipped", extra={"organization_id": organization_id}
            )
            return {"status": "skipped", "reason": org.status.value}
        name = org.name

    erased = await erase_tenant_data(resources, organization_id)

    async with resources.db.session_factory() as session:
        # A SQL DELETE, so PostgreSQL's ON DELETE CASCADE removes every tenant
        # table's rows (the ORM would try to detach them instead).
        await session.execute(delete(Organization).where(Organization.id == org_uuid))
        session.add(
            PlatformAuditLog(
                actor_id=None,
                action="organization.erased",
                target_type="organization",
                target_id=org_uuid,
                organization_id=None,  # the row is gone; keep its id in the details
                details={"organization_id": organization_id, "name": name, **erased},
            )
        )
        await session.commit()
    logger.info("organization_deleted", extra={"organization_id": organization_id})
    return {"status": "deleted", **erased}
