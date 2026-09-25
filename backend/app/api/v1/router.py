from fastapi import APIRouter

from app.api.v1 import (
    auth,
    comparison,
    contracts,
    documents,
    health,
    jobs,
    query,
    risk,
    summaries,
    users,
)

api_router = APIRouter()
for module in (health, auth, users, documents, jobs, query, contracts, comparison, risk, summaries):
    api_router.include_router(module.router)
