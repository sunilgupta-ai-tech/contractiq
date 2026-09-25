"""
Sign-up, sign-in and token refresh.

Security properties this service is responsible for:

* Login failures are indistinguishable. Unknown email, wrong password and a
  disabled account all return the same error, and an unknown email still
  pays for a bcrypt comparison so response time does not reveal which
  emails have accounts.
* Refresh tokens are single-use. Each token's `jti` is claimed in Redis on
  first use; replaying it is rejected. A stolen refresh token therefore
  stops working as soon as either party refreshes.
* Refresh re-reads the user. Role changes and deactivation take effect at
  the next refresh (at most one access-token lifetime), not at token expiry.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime
from functools import cache

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictError, ServiceUnavailableError, UnauthorizedError
from app.core.logging import get_logger
from app.core.security import Role, create_token, decode_token, hash_password, verify_password
from app.db.models import Organization, User
from app.db.repositories.user_repository import (
    find_user_by_email,
    find_user_in_tenant,
    get_organization,
)
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair
from app.services.audit_service import RequestMeta, record_audit

logger = get_logger(__name__)

INVALID_CREDENTIALS = "Invalid email or password."
EMAIL_TAKEN = "An account with this email already exists."


@cache
def _dummy_hash() -> str:
    # Computed lazily (bcrypt is deliberately slow) and reused for every
    # unknown-email login so those take as long as a real comparison.
    return hash_password(secrets.token_urlsafe(16))


def slugify(name: str) -> str:
    """URL-safe organization slug with a random suffix, so two organizations
    with the same name never collide on the unique index."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{base}-{secrets.token_hex(3)}"


async def claim_refresh_token(redis: Redis, jti: str, expires_at: int) -> bool:
    """Atomically mark a refresh token as used. Returns False if it already was.

    The key expires with the token itself, after which the JWT's own `exp`
    check rejects it, so the set of claimed IDs never grows unbounded.
    """
    ttl = max(expires_at - int(datetime.now(UTC).timestamp()), 1)
    try:
        return bool(await redis.set(f"ciq:auth:refresh-used:{jti}", "1", nx=True, ex=ttl))
    except RedisError as exc:
        # Fail closed: without the replay check, refresh is not safe to serve.
        raise ServiceUnavailableError(internal_detail=f"redis: {exc}") from exc


class AuthService:
    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings

    async def register(self, data: RegisterRequest, meta: RequestMeta) -> TokenPair:
        """Create an organization and its first user, who becomes its ADMIN."""
        if await find_user_by_email(self.session, data.email):
            raise ConflictError(EMAIL_TAKEN)

        org = Organization(name=data.organization_name, slug=slugify(data.organization_name))
        self.session.add(org)
        await self.session.flush()
        user = User(
            organization_id=org.id,
            email=data.email,
            full_name=data.full_name,
            password_hash=hash_password(data.password),
            role=Role.ADMIN,
            last_login_at=datetime.now(UTC),
        )
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # concurrent sign-up with the same email
            await self.session.rollback()
            raise ConflictError(EMAIL_TAKEN) from exc

        record_audit(
            self.session,
            tenant_id=org.id,
            actor_user_id=user.id,
            action="auth.register",
            resource_type="organization",
            resource_id=org.id,
            meta=meta,
        )
        await self.session.commit()
        return self._issue_tokens(user)

    async def login(self, data: LoginRequest, meta: RequestMeta) -> TokenPair:
        user = await find_user_by_email(self.session, data.email)
        if user is None:
            verify_password(data.password, _dummy_hash())
            raise UnauthorizedError(INVALID_CREDENTIALS)

        if not verify_password(data.password, user.password_hash):
            record_audit(
                self.session,
                tenant_id=user.organization_id,
                actor_user_id=user.id,
                action="auth.login_failed",
                resource_type="user",
                resource_id=user.id,
                meta=meta,
            )
            await self.session.commit()
            raise UnauthorizedError(INVALID_CREDENTIALS)

        # Checked only after the password, so the response for a disabled
        # account does not tell a guesser that the password was right.
        if not await self._is_enabled(user):
            raise UnauthorizedError(INVALID_CREDENTIALS)

        user.last_login_at = datetime.now(UTC)
        record_audit(
            self.session,
            tenant_id=user.organization_id,
            actor_user_id=user.id,
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
            meta=meta,
        )
        await self.session.commit()
        return self._issue_tokens(user)

    async def refresh(self, refresh_token: str) -> TokenPair:
        claims = decode_token(self.settings, refresh_token, expected_type="refresh")
        jti = claims.get("jti")
        if not jti:
            raise UnauthorizedError("Invalid or expired token.")
        if not await claim_refresh_token(self.redis, jti, int(claims["exp"])):
            logger.warning("refresh_token_replay", extra={"user_id": claims["sub"]})
            raise UnauthorizedError("This session has expired. Please sign in again.")

        try:
            user_id, tenant_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["tid"])
        except ValueError as exc:
            raise UnauthorizedError("Invalid or expired token.") from exc
        user = await find_user_in_tenant(self.session, user_id, tenant_id)
        if user is None or not await self._is_enabled(user):
            raise UnauthorizedError("This session has expired. Please sign in again.")
        return self._issue_tokens(user)

    async def _is_enabled(self, user: User) -> bool:
        if not user.is_active:
            return False
        org = await get_organization(self.session, user.organization_id)
        return org is not None and org.is_active

    def _issue_tokens(self, user: User) -> TokenPair:
        subject, tenant_id = str(user.id), str(user.organization_id)
        return TokenPair(
            access_token=create_token(
                self.settings, subject=subject, tenant_id=tenant_id, role=user.role
            ),
            refresh_token=create_token(
                self.settings,
                subject=subject,
                tenant_id=tenant_id,
                role=user.role,
                token_type="refresh",  # noqa: S106
            ),
            expires_in=self.settings.access_token_expire_minutes * 60,
        )
