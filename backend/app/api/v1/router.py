from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    comparison,
    contracts,
    documents,
    health,
    invitations,
    jobs,
    platform,
    query,
    risk,
    roles,
    summaries,
    usage,
    users,
)

api_router = APIRouter()
for module in (
    health,
    auth,
    users,
    roles,
    invitations,
    audit,
    documents,
    jobs,
    platform,
    query,
    contracts,
    comparison,
    risk,
    summaries,
    usage,
):
    api_router.include_router(module.router)
