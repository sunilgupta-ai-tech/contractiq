"""
Structured logging.

Every log line carries the request ID and tenant ID from context variables,
so one request can be followed across API, retrieval, LLM and worker logs.
In staging/production logs are emitted as JSON for CloudWatch / Loki.

Security: values under keys that look like secrets are redacted before
formatting. Contract text should never be logged; log IDs instead.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_ctx: ContextVar[str | None] = ContextVar("tenant_id", default=None)

_SENSITIVE_KEYS = ("password", "secret", "token", "api_key", "authorization", "access_key")
_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def _redact(key: str, value: Any) -> Any:
    return "***REDACTED***" if any(s in key.lower() for s in _SENSITIVE_KEYS) else value


class ContextFilter(logging.Filter):
    """Injects request/tenant IDs into each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.tenant_id = tenant_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "tenant_id": getattr(record, "tenant_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and key not in payload:
                payload[key] = _redact(key, value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure the root logger once at process start (API and worker)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if json_logs else ConsoleFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn's access log duplicates our request log middleware.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
