"""
User management within an organization (ADMIN only).

Implementation lands in Phase 2. The routes are registered now so the
API contract is visible in OpenAPI and the frontend can integrate against it.
Route handlers stay thin: validation in schemas, logic in services.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.exceptions import NotImplementedYetError

router = APIRouter(tags=["users"])
PHASE = 2


@router.get("/users/me", summary="Current user profile", status_code=501)
async def get_users_me() -> None:
    raise NotImplementedYetError("Current user profile", PHASE)


@router.get("/users", summary="List users in the caller's organization", status_code=501)
async def get_users() -> None:
    raise NotImplementedYetError("List users in the caller's organization", PHASE)
