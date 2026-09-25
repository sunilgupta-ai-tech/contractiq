"""
Authentication: register, login, refresh (JWT + bcrypt).

Route handlers stay thin: validation in schemas, logic in AuthService.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.core.dependencies import AuthServiceDep, RequestMetaDep
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
    body: LoginRequest, service: AuthServiceDep, meta: RequestMetaDep
) -> ApiResponse[TokenPair]:
    return ApiResponse(data=await service.login(body, meta))


@router.post(
    "/auth/refresh",
    summary="Rotate an access token using a refresh token",
    response_model=ApiResponse[TokenPair],
)
async def refresh(body: RefreshRequest, service: AuthServiceDep) -> ApiResponse[TokenPair]:
    """Each refresh token is single-use; the response carries a new pair."""
    return ApiResponse(data=await service.refresh(body.refresh_token))
