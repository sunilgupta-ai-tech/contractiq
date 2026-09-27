"""
`recover_jobs` — periodic recovery sweep (Phase 23).

Finds document jobs and organization deletions that a worker crash or a
Redis loss interrupted, and queues them again (see
app/services/job_recovery.py). Scheduled as an arq cron job, which arq runs
on one worker at a time however many replicas are up.
"""

from __future__ import annotations

from typing import Any

from app.services.job_recovery import recover


async def recover_jobs(ctx: dict[str, Any]) -> dict[str, Any]:
    resources = ctx["resources"]
    report = await recover(resources.db.session_factory, resources.queue, resources.settings)
    return report.as_dict()
