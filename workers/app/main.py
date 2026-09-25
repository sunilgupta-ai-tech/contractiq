"""
ContractIQ worker (arq on Redis).

Scaled independently of the API: in AWS, the worker runs as its own ECS
service with autoscaling on queue depth. Swapping Redis/arq for SQS later
only changes this entrypoint and the enqueue call — task functions stay.

Run: `arq worker.main.WorkerSettings`
"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.resources import Resources

from .tasks.document_processing import process_document
from .tasks.embedding import reembed_tenant
from .tasks.indexing import delete_document_vectors

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
logger = get_logger("contractiq.worker")

QUEUE_NAME = "contractiq:documents"


async def startup(ctx: dict[str, Any]) -> None:
    ctx["resources"] = Resources.create(settings)
    await ctx["resources"].bootstrap()
    logger.info("worker_started", extra={"queue": QUEUE_NAME})


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["resources"].close()
    logger.info("worker_stopped")


class WorkerSettings:
    functions: ClassVar = [process_document, reembed_tenant, delete_document_vectors]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = QUEUE_NAME
    max_jobs = 4  # OCR/embedding are CPU/IO heavy; scale out with replicas
    job_timeout = 60 * 30  # large scanned contracts can take a while
    max_tries = 3
    keep_result = 60 * 60 * 24
    health_check_interval = 30
