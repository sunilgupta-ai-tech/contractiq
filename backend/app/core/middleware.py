"""
HTTP middleware: request IDs, access logging and security headers.

Implemented as pure ASGI middleware (not BaseHTTPMiddleware) so it does not
buffer streaming responses — the query endpoint will stream tokens later.
"""

from __future__ import annotations

import json
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger, request_id_ctx

logger = get_logger("contractiq.http")

REQUEST_ID_HEADER = "x-request-id"

_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


class BodySizeLimitMiddleware:
    """Reject requests whose declared Content-Length exceeds `max_bytes`
    before the body is read.

    FastAPI parses multipart forms before the route runs, so without this an
    oversized upload would be received in full just to be rejected. Requests
    without a Content-Length (chunked) are still capped by the route's own
    streaming size check, and the load balancer should enforce a limit too.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            declared = dict(scope["headers"]).get(b"content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                body = json.dumps(
                    {
                        "success": False,
                        "error": {
                            "code": "FILE_TOO_LARGE",
                            "message": "The request body exceeds the maximum allowed size.",
                            "details": {"max_bytes": self.max_bytes},
                        },
                        "request_id": request_id_ctx.get(),
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                            (b"connection", b"close"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


class RequestContextMiddleware:
    """Assigns a request ID, logs latency and adds security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(REQUEST_ID_HEADER.encode())
        # Accept an upstream ID (from the load balancer) only if it is short
        # and printable, so clients can't inject arbitrary data into logs.
        request_id = (
            incoming.decode()
            if incoming and len(incoming) <= 64 and incoming.isascii()
            else uuid.uuid4().hex
        )
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                for key, value in _SECURITY_HEADERS.items():
                    headers.setdefault(key, value)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            if scope["path"] not in ("/api/v1/health",):
                logger.info(
                    "%s %s %s %.2fms",
                    scope["method"],
                    scope["path"],
                    status_code,
                    duration_ms,
                    extra={"status": status_code, "duration_ms": duration_ms},
                )
            request_id_ctx.reset(token)
