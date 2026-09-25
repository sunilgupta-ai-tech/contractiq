"""
Authentication: register, login, refresh (JWT + bcrypt).

Implementation lands in Phase 2. The routes are registered now so the
API contract is visible in OpenAPI and the frontend can integrate against it.
Route handlers stay thin: validation in schemas, logic in services.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotImplementedYetError

router = APIRouter(tags=["auth"])
PHASE = 2


@router.post("/auth/register", summary="Register a user and organization", status_code=501)
async def post_auth_register() -> None:
    raise NotImplementedYetError("Register a user and organization", PHASE)


@router.post(
    "/auth/login", summary="Exchange credentials for access/refresh tokens", status_code=501
)
async def post_auth_login() -> None:
    raise NotImplementedYetError("Exchange credentials for access/refresh tokens", PHASE)


@router.post(
    "/auth/refresh", summary="Rotate an access token using a refresh token", status_code=501
)
async def post_auth_refresh() -> None:
    raise NotImplementedYetError("Rotate an access token using a refresh token", PHASE)
