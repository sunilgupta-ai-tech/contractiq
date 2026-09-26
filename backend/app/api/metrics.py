"""
GET /metrics — Prometheus scrape endpoint (Phase 13).

Outside /api/v1 and hidden from OpenAPI: it is for the monitoring system,
not API clients. Metrics carry no tenant data (see observability/metrics.py),
but they do reveal traffic and cost patterns, so in production either keep
the path off the public load balancer or set METRICS_TOKEN and scrape with
`Authorization: Bearer <token>`.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Request, Response

from app.core.exceptions import UnauthorizedError
from app.observability.metrics import render_latest

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    settings = request.app.state.settings
    if settings.metrics_token is not None:
        expected = f"Bearer {settings.metrics_token.get_secret_value()}"
        given = request.headers.get("authorization", "")
        if not hmac.compare_digest(given.encode(), expected.encode()):
            raise UnauthorizedError()
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
