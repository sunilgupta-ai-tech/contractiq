"""
Authentication: register, login, refresh (JWT + bcrypt).

Route handlers stay thin: validation in schemas, logic in AuthService.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.dependencies import AuthServiceDep, LoginThrottleDep, RequestMetaDep
from app.core.exceptions import UnauthorizedError
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenPair
from app.schemas.common import ApiResponse

router = APIRouter(tags=["auth"])


@router.post(
    "/auth/register",
    summary="Register a user and organization",
    response_model=ApiResponse[TokenPair],
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest, service: AuthServiceDep, meta: RequestMetaDep
) -> ApiResponse[TokenPair]:
    """Create a new organization with the caller as its ADMIN."""
    return ApiResponse(data=await service.register(body, meta))


@router.post(
    "/auth/login",
    summary="Exchange credentials for access/refresh tokens",
    response_model=ApiResponse[TokenPair],
)
async def login(
    body: LoginRequest, service: AuthServiceDep, meta: RequestMetaDep, throttle: LoginThrottleDep
) -> ApiResponse[TokenPair]:
    """Too many failed attempts for this email from this IP (or from this IP
    overall) returns 429 with Retry-After, before the password is checked."""
    await throttle.check(body.email)
    try:
        tokens = await service.login(body, meta)
    except UnauthorizedError:
        await throttle.failed(body.email)
        raise
    await throttle.succeeded(body.email)
    return ApiResponse(data=tokens)


@router.post(
    "/auth/logout",
    summary="Sign out: revoke the session's refresh token",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def logout(body: RefreshRequest, service: AuthServiceDep) -> Response:
    """Always 204. The refresh token can no longer renew the session; the
    client discards its access token (which expires on its own shortly)."""
    await service.logout(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/auth/refresh",
    summary="Rotate an access token using a refresh token",
    response_model=ApiResponse[TokenPair],
)
async def refresh(body: RefreshRequest, service: AuthServiceDep) -> ApiResponse[TokenPair]:
    """Each refresh token is single-use; the response carries a new pair."""
    return ApiResponse(data=await service.refresh(body.refresh_token))
