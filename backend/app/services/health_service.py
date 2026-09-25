"""
Dependency health checks for the readiness probe.

Liveness (`/health`) answers "is the process up?" and never touches
dependencies — otherwise a Postgres blip would make the orchestrator kill
healthy API containers. Readiness (`/ready`) checks each dependency with a
timeout, concurrently, and tells the load balancer whether to route traffic.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.core.logging import get_logger
from app.core.resources import Resources
from app.schemas.health import DependencyHealth, ReadinessReport

logger = get_logger(__name__)

ProbeFn = Callable[[], Awaitable[object]]


@dataclass(frozen=True)
class Probe:
    name: str
    check: ProbeFn
    critical: bool = True  # non-critical failures degrade, not fail, readiness


WORKER_HEALTH_KEY = "contractiq:documents:health-check"  # written by arq every 30s


async def _worker_heartbeat(resources: Resources) -> None:
    """arq refreshes this key on each health-check interval; if it has
    expired, no worker is consuming the document queue."""
    if not await resources.redis.exists(WORKER_HEALTH_KEY):
        raise LookupError("no worker heartbeat")


class HealthService:
    def __init__(self, probes: list[Probe], timeout_s: float = 3.0) -> None:
        self.probes = probes
        self.timeout_s = timeout_s

    @classmethod
    def from_resources(cls, resources: Resources) -> HealthService:
        return cls(
            [
                Probe("postgres", resources.db.ping),
                Probe("redis", resources.redis.ping),
                Probe("qdrant", resources.qdrant.get_collections),
                # Non-critical: the API can serve queries while ingestion is down.
                Probe("worker", lambda: _worker_heartbeat(resources), critical=False),
            ]
        )

    async def _run(self, probe: Probe) -> DependencyHealth:
        started = time.perf_counter()
        try:
            await asyncio.wait_for(probe.check(), timeout=self.timeout_s)
            status, error = "up", None
        except TimeoutError:
            status, error = "down", "timeout"
        except Exception as exc:  # noqa: BLE001
            # Class name only: exception text can contain hostnames/credentials.
            status, error = "down", type(exc).__name__
            logger.warning("probe_failed", extra={"probe": probe.name, "error": repr(exc)})
        latency = round((time.perf_counter() - started) * 1000, 2)
        return DependencyHealth(
            name=probe.name, status=status, latency_ms=latency, critical=probe.critical, error=error
        )

    async def readiness(self) -> ReadinessReport:
        results = await asyncio.gather(*(self._run(p) for p in self.probes))
        critical_down = any(r.status == "down" and r.critical for r in results)
        any_down = any(r.status == "down" for r in results)
        overall = "not_ready" if critical_down else ("degraded" if any_down else "ready")
        return ReadinessReport(status=overall, dependencies=list(results))
