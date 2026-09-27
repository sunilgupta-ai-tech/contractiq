"""
ContractIQ worker (arq on Redis).

Scaled independently of the API: in AWS, the worker runs as its own ECS
service with autoscaling on queue depth. Swapping Redis/arq for SQS later
only changes this entrypoint and the enqueue call — task functions stay.

Run: `arq worker.main.WorkerSettings`
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings
from prometheus_client import start_http_server

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.resources import Resources
from app.observability.tracing import configure_langsmith
from app.queue import QUEUE_NAME

from .tasks.analysis import analyze_version
from .tasks.document_processing import process_document
from .tasks.embedding import reembed_tenant
from .tasks.indexing import delete_document_vectors
from .tasks.organization import delete_organization
from .tasks.recovery import recover_jobs

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
configure_langsmith(settings)
logger = get_logger("contractiq.worker")


async def startup(ctx: dict[str, Any]) -> None:
    if settings.metrics_enabled and settings.worker_metrics_port:
        # Prometheus scrapes the worker here (Phase 13); one server per process.
        start_http_server(settings.worker_metrics_port)
    ctx["resources"] = Resources.create(settings)
    await ctx["resources"].bootstrap()
    logger.info("worker_started", extra={"queue": QUEUE_NAME})


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["resources"].close()
    logger.info("worker_stopped")


class WorkerSettings:
    functions: ClassVar = [
        process_document,
        reembed_tenant,
        delete_document_vectors,
        analyze_version,
        delete_organization,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = QUEUE_NAME
    max_jobs = 4  # OCR/embedding are CPU/IO heavy; scale out with replicas
    job_timeout = 60 * 30  # large scanned contracts can take a while
    max_tries = 3
    keep_result = 60 * 60 * 24
    health_check_interval = 30
    # Phase 23: requeue work a crash or a Redis loss interrupted. Scheduled
    # runs happen on one worker at a time; the extra sweep at startup (so a
    # restarted worker picks up lost jobs at once) may overlap another, which
    # is safe because the sweep locks its rows with SKIP LOCKED.
    cron_jobs: ClassVar = (
        [
            cron(
                recover_jobs,
                minute=set(range(0, 60, max(1, settings.job_recovery_interval_min))),
                run_at_startup=True,
                timeout=5 * 60,
            )
        ]
        if settings.job_recovery_enabled
        else []
    )
