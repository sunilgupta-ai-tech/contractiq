"""Request/response schemas for authentication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from app.core import credentials
from app.core.credentials import PASSWORD_MAX_BYTES, PASSWORD_MIN_CHARS, CredentialError

__all__ = ["PASSWORD_MAX_BYTES", "PASSWORD_MIN_CHARS"]


def _rule(check: Callable[[str], str]) -> Callable[[str], str]:
    """Turn a credentials rule into a validator whose message is shown as is
    (no "Value error, " prefix), so the frontend can put it under the field."""

    def validate(value: str) -> str:
        try:
            return check(value)
        except CredentialError as exc:
            raise PydanticCustomError("invalid_input", str(exc)) from exc

    return validate


# Sign-in: normalised only, so accounts from before the stricter rules work.
Email = Annotated[str, AfterValidator(_rule(credentials.normalize_email))]
# New accounts, invitations and platform admins (see app/core/credentials.py).
NewEmail = Annotated[str, AfterValidator(_rule(credentials.validate_new_email))]
NewPassword = Annotated[
    str, Field(max_length=256), AfterValidator(_rule(credentials.validate_new_password))
]
FullName = Annotated[
    str, Field(max_length=400), AfterValidator(_rule(credentials.validate_full_name))
]
OrganizationName = Annotated[
    str, Field(max_length=400), AfterValidator(_rule(credentials.validate_organization_name))
]


class PersonalPasswordCheck(BaseModel):
    """Mixin: the password must not contain the email, name or organization
    given in the same request (fields declared before `password`)."""

    @field_validator("password", check_fields=False)
    @classmethod
    def _not_personal(cls, value: str, info: ValidationInfo) -> str:
        data: dict[str, Any] = info.data
        personal = tuple(
            str(data[k]) for k in ("email", "full_name", "organization_name") if data.get(k)
        )
        return _rule(lambda v: credentials.validate_new_password(v, personal=personal))(value)


class RegisterRequest(PersonalPasswordCheck):
    """Self-service sign-up: creates an organization and its first ADMIN."""

    organization_name: OrganizationName
    full_name: FullName
    email: NewEmail
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
