from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.dependencies import SettingsDep, get_health_service
from app.schemas.common import ApiResponse
from app.schemas.health import LivenessReport, ReadinessReport
from app.services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[LivenessReport])
async def health(settings: SettingsDep) -> ApiResponse[LivenessReport]:
    """Liveness probe. Never checks dependencies (see HealthService)."""
    return ApiResponse(
        data=LivenessReport(
            service=settings.app_name,
            version=settings.app_version,
            environment=settings.app_env.value,
        )
    )


@router.get(
    "/ready",
    response_model=ApiResponse[ReadinessReport],
    responses={503: {"model": ApiResponse[ReadinessReport]}},
)
async def ready(service: Annotated[HealthService, Depends(get_health_service)]) -> JSONResponse:
    """Readiness probe for the load balancer: 200 when ready/degraded, 503 otherwise."""
    report = await service.readiness()
    body = ApiResponse(success=report.status != "not_ready", data=report)
    return JSONResponse(
        status_code=503 if report.status == "not_ready" else 200,
        content=body.model_dump(mode="json"),
    )
