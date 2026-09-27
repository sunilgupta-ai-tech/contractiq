"""Phase 23: the recovery sweep is scheduled on the worker."""

from worker.main import WorkerSettings
from worker.tasks.recovery import recover_jobs


def test_recovery_sweep_is_a_cron_job_that_also_runs_at_startup():
    jobs = [job for job in WorkerSettings.cron_jobs if job.coroutine is recover_jobs]
    assert len(jobs) == 1
    assert jobs[0].run_at_startup
    assert jobs[0].unique  # scheduled runs happen on one worker at a time
