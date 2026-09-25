"""Request/response schemas for authentication."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# bcrypt only reads the first 72 bytes of a password. Longer inputs are
# rejected here rather than silently truncated by the hasher.
PASSWORD_MIN_CHARS = 12
PASSWORD_MAX_BYTES = 72


def _normalize_email(value: str) -> str:
    """Emails are unique across the platform, so they are compared lower-cased."""
    value = value.strip().lower()
    if len(value) > 320 or not _EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address.")
    return value


def _check_password(value: str) -> str:
    if len(value) < PASSWORD_MIN_CHARS:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_CHARS} characters.")
    if len(value.encode()) > PASSWORD_MAX_BYTES:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_BYTES} bytes.")
    return value


Email = Annotated[str, AfterValidator(_normalize_email)]
NewPassword = Annotated[str, AfterValidator(_check_password)]
FullName = Annotated[str, Field(min_length=1, max_length=200)]


class RegisterRequest(BaseModel):
    """Self-service sign-up: creates an organization and its first ADMIN."""

    organization_name: Annotated[str, Field(min_length=2, max_length=200)]
    full_name: FullName
    email: Email
    password: NewPassword


class LoginRequest(BaseModel):
    email: Email
    # Not validated against the password policy: a policy change must not
    # lock out users whose existing passwords predate it.
    password: Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_BYTES)]


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=4096)]


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int = Field(description="Access token lifetime in seconds.")
