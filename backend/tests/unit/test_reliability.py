"""Phase 23: recovery decisions, requeue ids, the ops CLI and snapshot pruning."""

from types import SimpleNamespace

import pytest
from arq.jobs import JobStatus as ArqJobStatus
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.ops.__main__ import main as ops_main
from app.ops.snapshots import backup_key, prune_server_snapshots
from app.queue import (
    DELETE_ORGANIZATION,
    PROCESS_DOCUMENT,
    enqueue_document_processing,
    enqueue_organization_deletion,
)
from app.services.job_recovery import Action, RecoveryReport, decide, stale_jobs_filter


@pytest.mark.parametrize(
    ("arq_status", "attempts", "expected"),
    [
        # arq still owns the job: a backlog or a slow run, never "lost".
        (ArqJobStatus.queued, 0, Action.LEAVE),
        (ArqJobStatus.deferred, 9, Action.LEAVE),
        (ArqJobStatus.in_progress, 9, Action.LEAVE),
        # Redis lost it, or arq gave up after a crash: run it again...
        (ArqJobStatus.not_found, 0, Action.REQUEUE),
        (ArqJobStatus.complete, 2, Action.REQUEUE),
        # ...until it has been started too often.
        (ArqJobStatus.not_found, 5, Action.FAIL),
        (ArqJobStatus.complete, 7, Action.FAIL),
    ],
)
def test_decide(arq_status, attempts, expected):
    assert decide(arq_status, attempts, max_attempts=5) is expected


def test_stale_filter_uses_both_limits_and_the_database_clock():
    settings = Settings(job_stale_pending_s=600, job_stale_running_s=2400)
    sql = str(
        stale_jobs_filter(settings).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "now()" in sql
    assert "PENDING" in sql and "RUNNING" in sql
    assert "DOCUMENT_PROCESSING" in sql


def test_stale_running_limit_outlasts_the_worker_job_timeout():
    # A job arq is still allowed to run must never look lost.
    assert Settings().job_stale_running_s > 30 * 60


class _Queue:
    def __init__(self):
        self.calls = []

    async def enqueue_job(self, function, *args, _job_id=None):
        self.calls.append((function, args, _job_id))


async def test_requeue_uses_a_fresh_arq_id_but_first_enqueue_keeps_the_job_id():
    queue = _Queue()
    await enqueue_document_processing(queue, "job-1")
    await enqueue_document_processing(queue, "job-1", arq_job_id="job-1:recovery-ab")
    await enqueue_organization_deletion(queue, "org-1")
    await enqueue_organization_deletion(queue, "org-1", arq_job_id="delete-org:org-1:recovery-cd")
    assert queue.calls == [
        (PROCESS_DOCUMENT, ("job-1",), "job-1"),
        (PROCESS_DOCUMENT, ("job-1",), "job-1:recovery-ab"),
        (DELETE_ORGANIZATION, ("org-1",), "delete-org:org-1"),
        (DELETE_ORGANIZATION, ("org-1",), "delete-org:org-1:recovery-cd"),
    ]


def test_report_changed_and_serialisable():
    report = RecoveryReport()
    assert not report.changed
    report.requeued.append("a")
    assert report.changed
    assert report.as_dict()["requeued"] == ["a"]


def test_restore_refuses_without_confirmation(capsys):
    # Checked before any connection is opened.
    assert ops_main(["restore-snapshot", "backups/qdrant/c/x.snapshot"]) == 2
    assert "--yes" in capsys.readouterr().err


def test_reindex_needs_a_target():
    with pytest.raises(SystemExit):
        ops_main(["reindex"])


def test_backup_key():
    assert (
        backup_key("contract_chunks", "s1.snapshot") == "backups/qdrant/contract_chunks/s1.snapshot"
    )


class _Qdrant:
    def __init__(self, names_by_time):
        self.snapshots = [
            SimpleNamespace(name=name, creation_time=time) for name, time in names_by_time
        ]
        self.deleted = []

    async def list_snapshots(self, collection_name):
        return list(self.snapshots)

    async def delete_snapshot(self, collection_name, snapshot_name):
        self.deleted.append(snapshot_name)


async def test_prune_keeps_the_newest_snapshots():
    qdrant = _Qdrant(
        [("b", "2026-09-02T00:00:00"), ("c", "2026-09-03T00:00:00"), ("a", "2026-09-01T00:00:00")]
    )
    assert await prune_server_snapshots(qdrant, "c1", keep=2) == 1
    assert qdrant.deleted == ["a"]


async def test_prune_never_deletes_the_last_snapshot():
    qdrant = _Qdrant([("a", "2026-09-01T00:00:00")])
    assert await prune_server_snapshots(qdrant, "c1", keep=0) == 0
