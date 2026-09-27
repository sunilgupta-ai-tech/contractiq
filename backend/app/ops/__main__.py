"""
Operations command line (Phase 23).

    python -m app.ops status                     # jobs, queue, worker, vectors, snapshots
    python -m app.ops recover [--dry-run] [--org ID]  # requeue interrupted jobs now
    python -m app.ops reindex (--org ID | --all) # rebuild vectors from stored chunks
    python -m app.ops snapshot [--keep 3]        # Qdrant snapshot → backups/qdrant/
    python -m app.ops restore-snapshot KEY --yes # replace the collection from a snapshot

Uses the same configuration as the API and worker. Locally:
`docker compose exec backend python -m app.ops status`. On ECS, run it as a
one-off task with the backend task definition. Runbooks for each failure are
in docs/reliability.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.resources import Resources
from app.db.models import Organization, OrganizationStatus, ProcessingJob
from app.ops.snapshots import restore_snapshot, save_snapshot
from app.services.health_service import WORKER_HEALTH_KEY
from app.services.job_recovery import recover, stale_jobs_filter

REEMBED_TENANT = "reembed_tenant"  # workers/app/tasks/embedding.py


async def _status(resources: Resources) -> dict[str, Any]:
    settings = resources.settings
    async with resources.db.session_factory() as session:
        by_status = dict(
            (
                await session.execute(
                    select(ProcessingJob.status, func.count()).group_by(ProcessingJob.status)
                )
            ).all()
        )
        stale = await session.scalar(
            select(func.count()).select_from(ProcessingJob).where(stale_jobs_filter(settings))
        )
        deleting = await session.scalar(
            select(func.count())
            .select_from(Organization)
            .where(Organization.status == OrganizationStatus.DELETING)
        )
    collection = await resources.qdrant.get_collection(settings.qdrant_collection)
    snapshots = await resources.qdrant.list_snapshots(settings.qdrant_collection)
    return {
        "jobs": {status.value: count for status, count in by_status.items()},
        "jobs_stale": stale,
        "organizations_deleting": deleting,
        "queue_length": await resources.queue.zcard(resources.queue.default_queue_name),
        "worker_alive": bool(await resources.redis.exists(WORKER_HEALTH_KEY)),
        "vectors": collection.points_count,
        "server_snapshots": sorted(s.name for s in snapshots),
    }


async def _reindex(resources: Resources, org: str | None) -> dict[str, Any]:
    """Queue `reembed_tenant` per organization. It rebuilds every processed
    version's vectors from its stored chunks. Nothing is parsed or OCR'd
    again, and texts still in the embedding cache cost nothing."""
    await resources.bootstrap()  # recreates the collection if it is gone
    async with resources.db.session_factory() as session:
        query = select(Organization.id).where(Organization.status != OrganizationStatus.DELETING)
        if org is not None:
            query = query.where(Organization.id == uuid.UUID(org))
        org_ids = [str(i) for i in (await session.scalars(query)).all()]
    stamp = int(time.time())
    for org_id in org_ids:
        await resources.queue.enqueue_job(
            REEMBED_TENANT, org_id, _job_id=f"reindex:{org_id}:{stamp}"
        )
    return {"queued": org_ids}


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    resources = Resources.create(settings)
    try:
        if args.command == "status":
            result: Any = await _status(resources)
        elif args.command == "recover":
            report = await recover(
                resources.db.session_factory,
                resources.queue,
                settings,
                dry_run=args.dry_run,
                organization_id=uuid.UUID(args.org) if args.org else None,
            )
            result = report.as_dict()
        elif args.command == "reindex":
            result = await _reindex(resources, None if args.all else args.org)
        elif args.command == "snapshot":
            saved = await save_snapshot(
                resources.qdrant, resources.storage, settings, keep=args.keep
            )
            result = {"name": saved.name, "key": saved.storage_key, "size_bytes": saved.size_bytes}
        else:  # restore-snapshot
            await restore_snapshot(resources.storage, settings, args.key)
            result = {"restored": args.key, "collection": settings.qdrant_collection}
    finally:
        await resources.close()
    print(json.dumps(result, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ops")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="jobs, queue, worker, vectors and snapshots")
    recover_cmd = commands.add_parser("recover", help="requeue interrupted jobs now")
    recover_cmd.add_argument("--dry-run", action="store_true", help="report, change nothing")
    recover_cmd.add_argument("--org", help="only this organization id")
    reindex = commands.add_parser("reindex", help="rebuild vectors from stored chunks")
    target = reindex.add_mutually_exclusive_group(required=True)
    target.add_argument("--org", help="one organization id")
    target.add_argument("--all", action="store_true", help="every organization")
    snapshot = commands.add_parser("snapshot", help="Qdrant snapshot copied to storage")
    snapshot.add_argument("--keep", type=int, default=3, help="snapshots kept on the server")
    restore = commands.add_parser("restore-snapshot", help="replace the collection's contents")
    restore.add_argument("key", help="storage key printed by `snapshot`")
    restore.add_argument("--yes", action="store_true", help="confirm replacing the collection")
    args = parser.parse_args(argv)
    if args.command == "restore-snapshot" and not args.yes:
        print("Refusing to replace the collection without --yes.", file=sys.stderr)
        return 2

    configure_logging(get_settings().log_level, get_settings().log_json)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
