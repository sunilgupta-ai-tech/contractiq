"""
The platform console (Phase 18): every organization, its status, plan,
limits and usage, and the platform's own admins.

Privacy by design: the console works with counts and account metadata
(names, emails, roles, sign-in times). It has no endpoint that returns a
document, a chunk, a question or an answer, so a platform admin cannot read
an organization's content — the standard a customer expects of a SaaS
operator.

Sessions here are never bound to a tenant (row-level security would hide
every other organization); isolation from tenants comes from the separate
token audience, and tenant sessions have no grant on the platform tables.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from arq.connections import ArqRedis
from redis.asyncio import Redis
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.core.security import hash_password
from app.core.sessions import revoke_org_sessions, revoke_platform_sessions, revoke_user_sessions
from app.db.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    FileType,
    Organization,
    OrganizationStatus,
    Plan,
    PlatformAdmin,
    PlatformAuditLog,
    Role,
    User,
)
from app.queue import enqueue_organization_deletion
from app.schemas.common import Page
from app.schemas.platform import (
    LIMIT_FIELDS,
    CreatePlatformAdminRequest,
    LimitsOut,
    OrganizationDetail,
    OrganizationMember,
    OrganizationSummary,
    PlanOut,
    PlatformAdminOut,
    PlatformAuditOut,
    PlatformOverview,
    UpdateOrganizationRequest,
    UpdatePlatformAdminRequest,
    UsageOut,
)
from app.schemas.usage import UsagePeriodOut
from app.services.audit_service import RequestMeta
from app.services.plans import PLAN_LIMITS, apply_plan
from app.services.platform_auth_service import platform_audit
from app.services.usage import current_period, month_usage


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _limits(org: Organization) -> LimitsOut:
    return LimitsOut(**{field: getattr(org, field) for field in LIMIT_FIELDS})


class PlatformService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        redis: Redis | None,
        revoke_ttl_s: int,
        queue: ArqRedis | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.revoke_ttl_s = revoke_ttl_s
        self.queue = queue

    # --- Overview ---------------------------------------------------------------

    async def overview(self) -> PlatformOverview:
        s = self.session
        by_status = dict(
            (
                await s.execute(
                    select(Organization.status, func.count()).group_by(Organization.status)
                )
            )
            .tuples()
            .all()
        )
        by_plan = dict(
            (await s.execute(select(Organization.plan, func.count()).group_by(Organization.plan)))
            .tuples()
            .all()
        )
        users, active_users = (
            await s.execute(
                select(func.count(), func.count().filter(User.is_active.is_(True))).select_from(
                    User
                )
            )
        ).one()
        documents = await s.scalar(select(func.count()).select_from(Document))
        storage = await s.scalar(select(func.coalesce(func.sum(DocumentVersion.size_bytes), 0)))
        day_ago = datetime.now(UTC) - timedelta(days=1)
        failed = await s.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(
                DocumentVersion.status == DocumentStatus.FAILED,
                DocumentVersion.updated_at >= day_ago,
            )
        )
        new_orgs = await s.scalar(
            select(func.count())
            .select_from(Organization)
            .where(Organization.created_at >= datetime.now(UTC) - timedelta(days=30))
        )
        return PlatformOverview(
            organizations=sum(by_status.values()),
            active_organizations=by_status.get(OrganizationStatus.ACTIVE, 0),
            suspended_organizations=by_status.get(OrganizationStatus.SUSPENDED, 0),
            users=int(users),
            active_users=int(active_users),
            documents=int(documents or 0),
            storage_bytes=int(storage or 0),
            failed_documents_24h=int(failed or 0),
            organizations_by_plan={plan: by_plan.get(plan, 0) for plan in Plan},
            new_organizations_30d=int(new_orgs or 0),
        )

    @staticmethod
    def plans() -> list[PlanOut]:
        return [
            PlanOut(
                plan=plan,
                limits=LimitsOut(**{field: getattr(limits, field) for field in LIMIT_FIELDS}),
            )
            for plan, limits in PLAN_LIMITS.items()
        ]

    # --- Organizations ----------------------------------------------------------

    def _summaries(self) -> Select:  # type: ignore[type-arg]
        """Organizations with usage, as one query of grouped subqueries (not
        one query per organization), so the list stays fast with thousands."""
        users = (
            select(
                User.organization_id.label("org_id"),
                func.count().label("total"),
                func.count().filter(User.is_active.is_(True)).label("active"),
                func.max(User.last_login_at).label("last_login"),
            )
            .group_by(User.organization_id)
            .subquery()
        )
        docs = (
            select(Document.organization_id.label("org_id"), func.count().label("n"))
            .group_by(Document.organization_id)
            .subquery()
        )
        storage = (
            select(
                DocumentVersion.organization_id.label("org_id"),
                func.sum(DocumentVersion.size_bytes).label("bytes"),
            )
            .group_by(DocumentVersion.organization_id)
            .subquery()
        )
        return (
            select(
                Organization,
                func.coalesce(users.c.total, 0),
                func.coalesce(users.c.active, 0),
                users.c.last_login,
                func.coalesce(docs.c.n, 0),
                func.coalesce(storage.c.bytes, 0),
            )
            .outerjoin(users, users.c.org_id == Organization.id)
            .outerjoin(docs, docs.c.org_id == Organization.id)
            .outerjoin(storage, storage.c.org_id == Organization.id)
        )

    @staticmethod
    def _summary(row: tuple) -> OrganizationSummary:  # type: ignore[type-arg]
        org, total, active, last_login, documents, storage = row
        return OrganizationSummary(
            id=org.id,
            name=org.name,
            slug=org.slug,
            status=org.status,
            plan=org.plan,
            limits=_limits(org),
            usage=UsageOut(
                active_users=int(active),
                total_users=int(total),
                documents=int(documents),
                storage_bytes=int(storage),
            ),
            last_active_at=last_login,
            created_at=org.created_at,
        )

    async def list_organizations(
        self,
        *,
        q: str | None,
        status: OrganizationStatus | None,
        plan: Plan | None,
        offset: int,
        limit: int,
    ) -> Page[OrganizationSummary]:
        filters = []
        if q:
            pattern = f"%{_escape_like(q.strip())}%"
            # An organization is also found by one of its members' emails.
            member = select(User.id).where(
                User.organization_id == Organization.id,
                User.email.ilike(pattern, escape="\\"),
            )
            filters.append(
                or_(
                    Organization.name.ilike(pattern, escape="\\"),
                    Organization.slug.ilike(pattern, escape="\\"),
                    member.exists(),
                )
            )
        if status is not None:
            filters.append(Organization.status == status)
        if plan is not None:
            filters.append(Organization.plan == plan)
        total = await self.session.scalar(
            select(func.count()).select_from(Organization).where(*filters)
        )
        rows = (
            await self.session.execute(
                self._summaries()
                .where(*filters)
                .order_by(Organization.created_at.desc(), Organization.id)
                .offset(offset)
                .limit(min(limit, 200))
            )
        ).all()
        return Page(
            items=[self._summary(tuple(r)) for r in rows],
            total=int(total or 0),
            offset=offset,
            limit=limit,
        )

    async def get_organization(self, org_id: uuid.UUID) -> OrganizationDetail:
        row = (
            await self.session.execute(self._summaries().where(Organization.id == org_id))
        ).first()
        if row is None:
            raise NotFoundError("Organization not found.")
        summary = self._summary(tuple(row))
        org: Organization = row[0]
        by_type = dict(
            (
                await self.session.execute(
                    select(Document.file_type, func.count())
                    .where(Document.organization_id == org_id)
                    .group_by(Document.file_type)
                )
            )
            .tuples()
            .all()
        )
        failed = await self.session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.organization_id == org_id, Document.status == DocumentStatus.FAILED)
        )
        members = (
            await self.session.execute(
                select(User, Role.name)
                .join(Role, Role.id == User.role_id)
                .where(User.organization_id == org_id)
                .order_by(User.created_at)
            )
        ).all()
        return OrganizationDetail(
            **summary.model_dump(),
            suspended_reason=org.suspended_reason,
            suspended_at=org.suspended_at,
            documents_by_type={t: by_type.get(t, 0) for t in FileType},
            failed_documents=int(failed or 0),
            ai_usage_this_month=UsagePeriodOut.model_validate(used)
            if (used := await month_usage(self.session, org_id))
            else UsagePeriodOut(period=current_period()),
            members=[
                OrganizationMember(
                    id=u.id,
                    email=u.email,
                    full_name=u.full_name,
                    role_name=role_name,
                    is_active=u.is_active,
                    last_login_at=u.last_login_at,
                )
                for u, role_name in members
            ],
        )

    async def update_organization(
        self,
        org_id: uuid.UUID,
        data: UpdateOrganizationRequest,
        *,
        actor_id: uuid.UUID,
        meta: RequestMeta,
    ) -> OrganizationDetail:
        org = await self.session.get(Organization, org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        before = {
            "status": org.status.value,
            "plan": org.plan.value,
            **_limits(org).model_dump(),
        }
        suspended_now = False
        if data.status is not None and data.status is not org.status:
            org.status = data.status
            if data.status is OrganizationStatus.SUSPENDED:
                org.suspended_reason = (data.suspended_reason or "").strip()
                org.suspended_at = datetime.now(UTC)
                suspended_now = True
            else:
                org.suspended_reason, org.suspended_at = None, None
        elif data.status is OrganizationStatus.SUSPENDED and data.suspended_reason:
            org.suspended_reason = data.suspended_reason.strip()
        if data.plan is not None:
            apply_plan(org, data.plan)
        for field in LIMIT_FIELDS:
            value = getattr(data, field)
            if value is not None:
                setattr(org, field, value)
        for field in data.unlimited:
            setattr(org, field, None)
        after = {"status": org.status.value, "plan": org.plan.value, **_limits(org).model_dump()}
        platform_audit(
            self.session,
            actor_id=actor_id,
            action="organization.update",
            meta=meta,
            target_type="organization",
            target_id=org.id,
            organization_id=org.id,
            details={
                "changes": {k: [before[k], after[k]] for k in after if before[k] != after[k]},
                **({"reason": org.suspended_reason} if suspended_now else {}),
            },
        )
        await self.session.commit()
        if suspended_now:
            # Everyone in the organization is signed out at once.
            await revoke_org_sessions(self.redis, org.id, ttl_s=self.revoke_ttl_s)
        return await self.get_organization(org.id)

    async def delete_organization(
        self, org_id: uuid.UUID, *, confirm_name: str, actor_id: uuid.UUID, meta: RequestMeta
    ) -> None:
        """Phase 22: end all access now and erase everything in the background
        (vectors, files, caches, then every row). Irreversible."""
        org = await self.session.get(Organization, org_id)
        if org is None:
            raise NotFoundError("Organization not found.")
        if confirm_name.strip() != org.name:
            raise ConflictError("Type the organization's exact name to confirm deletion.")
        org.status = OrganizationStatus.DELETING
        org.suspended_reason = "Deletion requested"
        org.suspended_at = datetime.now(UTC)
        platform_audit(
            self.session,
            actor_id=actor_id,
            action="organization.delete_requested",
            meta=meta,
            target_type="organization",
            target_id=org.id,
            organization_id=org.id,
            details={"name": org.name},
        )
        await self.session.commit()
        await revoke_org_sessions(self.redis, org.id, ttl_s=self.revoke_ttl_s)
        if self.queue is None:
            raise ServiceUnavailableError("The deletion could not be queued. Try again.")
        await enqueue_organization_deletion(self.queue, str(org.id))

    async def set_member_active(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        active: bool,
        *,
        actor_id: uuid.UUID,
        meta: RequestMeta,
    ) -> OrganizationDetail:
        """Support tool: re-enable a locked-out admin, or stop a compromised
        account. Plan limits do not apply to the platform."""
        user = (
            await self.session.execute(
                select(User).where(User.id == user_id, User.organization_id == org_id)
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError("User not found.")
        user.is_active = active
        platform_audit(
            self.session,
            actor_id=actor_id,
            action="organization.member_update",
            meta=meta,
            target_type="user",
            target_id=user.id,
            organization_id=org_id,
            details={"is_active": active},
        )
        await self.session.commit()
        if not active:
            await revoke_user_sessions(self.redis, user.id, ttl_s=self.revoke_ttl_s)
        return await self.get_organization(org_id)

    # --- Platform admins ----------------------------------------------------------

    async def list_admins(self) -> list[PlatformAdminOut]:
        rows = (
            await self.session.execute(select(PlatformAdmin).order_by(PlatformAdmin.created_at))
        ).scalars()
        return [PlatformAdminOut.model_validate(a) for a in rows]

    async def create_admin(
        self, data: CreatePlatformAdminRequest, *, actor_id: uuid.UUID, meta: RequestMeta
    ) -> PlatformAdminOut:
        admin = PlatformAdmin(
            email=data.email,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
            role=data.role,
        )
        self.session.add(admin)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A platform admin with this email already exists.") from exc
        platform_audit(
            self.session,
            actor_id=actor_id,
            action="platform_admin.create",
            meta=meta,
            target_type="platform_admin",
            target_id=admin.id,
            details={"role": data.role.value},
        )
        await self.session.commit()
        await self.session.refresh(admin)
        return PlatformAdminOut.model_validate(admin)

    async def update_admin(
        self,
        admin_id: uuid.UUID,
        data: UpdatePlatformAdminRequest,
        *,
        actor_id: uuid.UUID,
        meta: RequestMeta,
    ) -> PlatformAdminOut:
        if admin_id == actor_id:
            raise ForbiddenError("You cannot change your own role or status.")
        admin = await self.session.get(PlatformAdmin, admin_id)
        if admin is None:
            raise NotFoundError("Platform admin not found.")
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in changes.items():
            setattr(admin, field, value)
        platform_audit(
            self.session,
            actor_id=actor_id,
            action="platform_admin.update",
            meta=meta,
            target_type="platform_admin",
            target_id=admin.id,
            details={k: str(v) for k, v in changes.items()},
        )
        await self.session.commit()
        if changes:
            await revoke_platform_sessions(self.redis, admin.id, ttl_s=self.revoke_ttl_s)
        await self.session.refresh(admin)
        return PlatformAdminOut.model_validate(admin)

    # --- Audit ------------------------------------------------------------------

    async def audit(
        self, *, organization_id: uuid.UUID | None, offset: int, limit: int
    ) -> Page[PlatformAuditOut]:
        filters = []
        if organization_id is not None:
            filters.append(PlatformAuditLog.organization_id == organization_id)
        total = await self.session.scalar(
            select(func.count()).select_from(PlatformAuditLog).where(*filters)
        )
        rows = (
            await self.session.execute(
                select(PlatformAuditLog, PlatformAdmin.email)
                .outerjoin(PlatformAdmin, PlatformAdmin.id == PlatformAuditLog.actor_id)
                .where(*filters)
                .order_by(PlatformAuditLog.created_at.desc(), PlatformAuditLog.id)
                .offset(offset)
                .limit(min(limit, 200))
            )
        ).all()
        items = []
        for entry, email in rows:
            out = PlatformAuditOut.model_validate(entry)
            out.actor_email = email
            items.append(out)
        return Page(items=items, total=int(total or 0), offset=offset, limit=limit)
