"""
Sign-in for platform admins (Phase 18).

Same guarantees as organization sign-in (app/services/auth_service.py):
indistinguishable failures, constant-time for unknown emails, single-use
refresh tokens. Tokens use the platform audience and carry no tenant, so
they open the console and nothing else. Platform refresh tokens live one
day at most: the console is not a place for week-long sessions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger
from app.core.security import create_platform_token, decode_platform_token, verify_password
from app.db.models import PlatformAdmin, PlatformAuditLog
from app.schemas.auth import LoginRequest, TokenPair
from app.services.audit_service import RequestMeta
from app.services.auth_service import INVALID_CREDENTIALS, _dummy_hash, claim_refresh_token

logger = get_logger(__name__)


def platform_audit(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    meta: RequestMeta,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        PlatformAuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            organization_id=organization_id,
            details=details or {},
            ip_address=meta.ip_address,
        )
    )


class PlatformAuthService:
    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings

    async def login(self, data: LoginRequest, meta: RequestMeta) -> TokenPair:
        admin = await self._by_email(data.email)
        if admin is None:
            verify_password(data.password, _dummy_hash())
            raise UnauthorizedError(INVALID_CREDENTIALS)
        if not verify_password(data.password, admin.password_hash) or not admin.is_active:
            platform_audit(
                self.session,
                actor_id=admin.id,
                action="platform.login_failed",
                meta=meta,
                target_type="platform_admin",
                target_id=admin.id,
            )
            await self.session.commit()
            raise UnauthorizedError(INVALID_CREDENTIALS)
        admin.last_login_at = datetime.now(UTC)
        platform_audit(
            self.session,
            actor_id=admin.id,
            action="platform.login",
            meta=meta,
            target_type="platform_admin",
            target_id=admin.id,
        )
        await self.session.commit()
        return self._issue(admin)

    async def refresh(self, refresh_token: str) -> TokenPair:
        claims = decode_platform_token(self.settings, refresh_token, expected_type="refresh")
        jti = claims.get("jti")
        if not jti or not await claim_refresh_token(self.redis, jti, int(claims["exp"])):
            raise UnauthorizedError("This session has expired. Please sign in again.")
        try:
            admin = await self.session.get(PlatformAdmin, uuid.UUID(claims["sub"]))
        except ValueError as exc:
            raise UnauthorizedError("Invalid or expired token.") from exc
        if admin is None or not admin.is_active:
            raise UnauthorizedError("This session has expired. Please sign in again.")
        return self._issue(admin)

    async def logout(self, refresh_token: str) -> None:
        try:
            claims = decode_platform_token(self.settings, refresh_token, expected_type="refresh")
        except UnauthorizedError:
            return
        if jti := claims.get("jti"):
            await claim_refresh_token(self.redis, jti, int(claims["exp"]))

    async def _by_email(self, email: str) -> PlatformAdmin | None:
        stmt = select(PlatformAdmin).where(func.lower(PlatformAdmin.email) == email.lower())
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _issue(self, admin: PlatformAdmin) -> TokenPair:
        subject, role = str(admin.id), admin.role.value
        return TokenPair(
            access_token=create_platform_token(self.settings, subject=subject, role=role),
            refresh_token=create_platform_token(
                self.settings,
                subject=subject,
                role=role,
                token_type="refresh",  # noqa: S106
            ),
            expires_in=self.settings.access_token_expire_minutes * 60,
        )
