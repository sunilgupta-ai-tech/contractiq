"""
Job queue shared by the API (producer) and the worker (consumer).

Only job IDs cross the queue — never file contents or tenant data. The
ProcessingJob row in PostgreSQL is the source of truth; the queue is
transport. Swapping arq/Redis for SQS later changes only this module and
the worker entrypoint.
"""

from __future__ import annotations

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from app.core.config import Settings

QUEUE_NAME = "contractiq:documents"
PROCESS_DOCUMENT = "process_document"
DELETE_ORGANIZATION = "delete_organization"


def create_queue(settings: Settings) -> ArqRedis:
    # A dedicated pool: arq stores pickled bytes, while the app's shared
    # Redis client decodes responses to str.
    return ArqRedis(ConnectionPool.from_url(settings.redis_url), default_queue_name=QUEUE_NAME)


async def enqueue_document_processing(queue: ArqRedis, job_id: str) -> None:
    """Enqueue `process_document` using the ProcessingJob ID as arq's job ID,
    so a retried enqueue for the same job is a no-op rather than a duplicate."""
    await queue.enqueue_job(PROCESS_DOCUMENT, job_id, _job_id=job_id)


async def enqueue_organization_deletion(queue: ArqRedis, organization_id: str) -> None:
    """Phase 22: erase an organization in the background. The fixed job id
    makes a repeated request a no-op while one is pending."""
    await queue.enqueue_job(
        DELETE_ORGANIZATION, organization_id, _job_id=f"delete-org:{organization_id}"
    )
