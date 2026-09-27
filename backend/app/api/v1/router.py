from fastapi import APIRouter

from app.api.v1 import (
    auth,
    comparison,
    contracts,
    documents,
    health,
    jobs,
    platform,
    query,
    risk,
    roles,
    summaries,
    users,
)

api_router = APIRouter()
for module in (
    health,
    auth,
    users,
    roles,
    documents,
    jobs,
    platform,
    query,
    contracts,
    comparison,
    risk,
    summaries,
):
    api_router.include_router(module.router)
