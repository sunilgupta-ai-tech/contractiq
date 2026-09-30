"""
Production preflight (Phase 14): is this configuration safe and complete
enough to serve real contracts?

    python -m app.core.preflight              # configuration checks only
    python -m app.core.preflight --connect    # + reach Postgres, Redis, Qdrant, storage

Exit code 0 = no errors (warnings allowed), 1 = at least one error. The
deploy workflow runs it against the new image and environment before any
service is rolled, so a misconfiguration stops the release instead of
reaching users. The API also logs these findings at startup outside
development.

Settings' own validator (core/config.py) already *refuses to start* on the
worst mistakes (default JWT secret, wildcard CORS, S3 without a bucket,
Gemini without a key). Preflight adds the checks that are wrong for
production but legitimate elsewhere (local storage, no TLS to Redis, demo
thresholds), so they are reported rather than hard-coded into startup.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from app.core.config import Environment, LLMProviderName, Settings, StorageBackend, get_settings


class Level(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    level: Level
    check: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.value.upper()}] {self.check}: {self.message}"


def check_settings(settings: Settings) -> list[Finding]:
    """Configuration checks. Errors apply to production; in staging they are
    reported as warnings (staging may legitimately run on one host)."""
    findings: list[Finding] = []
    strict = settings.app_env is Environment.PRODUCTION

    def problem(check: str, message: str) -> None:
        findings.append(Finding(Level.ERROR if strict else Level.WARNING, check, message))

    def warn(check: str, message: str) -> None:
        findings.append(Finding(Level.WARNING, check, message))

    if settings.app_env is Environment.DEVELOPMENT:
        warn("environment", "APP_ENV=development: production safety checks are not enforced.")

    # Secrets and sessions
    if len(settings.jwt_secret_key.get_secret_value()) < 32:
        problem("jwt_secret", "JWT_SECRET_KEY should be at least 32 random characters.")

    # Storage: the API and worker run as separate tasks and must share files.
    if settings.storage_backend is StorageBackend.LOCAL:
        problem(
            "storage",
            "STORAGE_BACKEND=local keeps files on one machine; API and worker tasks can't "
            "share them. Use s3.",
        )

    # Transport security to managed services
    if urlparse(settings.redis_url).scheme != "rediss":
        problem("redis_tls", "REDIS_URL should use rediss:// (TLS) outside a private dev host.")
    qdrant = urlparse(settings.qdrant_url)
    if qdrant.hostname not in ("localhost", "127.0.0.1", "qdrant"):
        if qdrant.scheme != "https":
            problem("qdrant_tls", "QDRANT_URL to a remote cluster should use https://.")
        if settings.qdrant_api_key is None:
            problem("qdrant_auth", "QDRANT_API_KEY is required for a remote Qdrant cluster.")
    if "sslmode" not in settings.database_url and "ssl=" not in settings.database_url:
        warn(
            "database_tls",
            "DATABASE_URL has no ssl parameter; ensure TLS is enforced (e.g. RDS "
            "rds.force_ssl=1 or '?ssl=require').",
        )

    # Operations
    if not settings.log_json:
        problem("log_json", "LOG_JSON=true is needed for CloudWatch/Loki queries by request_id.")
    if settings.log_level.upper() == "DEBUG":
        warn("log_level", "LOG_LEVEL=DEBUG is noisy and may log more than intended.")
    if settings.metrics_enabled and settings.metrics_token is None:
        warn(
            "metrics_token",
            "/metrics has no METRICS_TOKEN; keep the path off the public load balancer.",
        )
    if not settings.rate_limit_enabled:
        problem("rate_limits", "RATE_LIMIT_ENABLED=false removes brute-force and cost protection.")

    # Models and answer quality
    if LLMProviderName.OLLAMA in (settings.llm_provider, settings.embedding_provider):
        warn(
            "ollama",
            "An Ollama provider is configured; make sure OLLAMA_BASE_URL points at a sized, "
            "monitored model server, not a laptop.",
        )
    if settings.grounding_mode == "flag":
        warn(
            "grounding_mode",
            "GROUNDING_MODE=flag shows weakly grounded answers; switch to enforce once the "
            "evaluation calibration supports it (docs/evaluation.md).",
        )
    if settings.langfuse_capture_content:
        warn(
            "trace_content",
            "LANGFUSE_CAPTURE_CONTENT=true sends contract text to the tracing backend; confirm "
            "the data-processing terms allow it.",
        )
    return findings


async def check_connectivity(settings: Settings) -> list[Finding]:
    """Reach each dependency the way the app does (read-only except one
    throwaway storage object, which is deleted again)."""
    from app.core.resources import Resources
    from app.vectorstore.collections import check_dimension

    findings: list[Finding] = []
    resources = Resources.create(settings)

    async def attempt(check: str, action: object) -> None:
        try:
            await action  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 — every failure is a finding
            findings.append(Finding(Level.ERROR, check, f"{type(exc).__name__}: {exc}"[:300]))

    try:
        await attempt("postgres", resources.db.ping())
        await attempt("redis", resources.redis.ping())
        await attempt(
            "qdrant",
            check_dimension(
                resources.qdrant, settings.qdrant_collection, settings.embedding_dimension
            ),
        )
        key = f"preflight/{uuid.uuid4().hex}.txt"

        async def storage_roundtrip() -> None:
            await resources.storage.put(key, b"ok", "text/plain")
            if await resources.storage.get(key) != b"ok":
                raise RuntimeError("read back different bytes")
            await resources.storage.delete(key)

        await attempt("storage", storage_roundtrip())
        for check, factory in (("llm", resources.llm), ("embeddings", resources.embeddings)):
            try:
                factory()
            except Exception as exc:  # noqa: BLE001
                findings.append(Finding(Level.ERROR, check, f"{type(exc).__name__}: {exc}"))
    finally:
        await resources.close()
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.core.preflight")
    parser.add_argument("--connect", action="store_true", help="also reach every dependency")
    args = parser.parse_args(argv)

    settings = get_settings()
    findings = check_settings(settings)
    if args.connect:
        findings += asyncio.run(check_connectivity(settings))
    for finding in sorted(findings, key=lambda f: f.level != Level.ERROR):
        print(finding)
    errors = sum(f.level is Level.ERROR for f in findings)
    print(f"preflight: {errors} error(s), {len(findings) - errors} warning(s) [{settings.app_env}]")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
