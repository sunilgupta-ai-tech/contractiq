from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LivenessReport(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str


class DependencyHealth(BaseModel):
    name: str
    status: Literal["up", "down"]
    latency_ms: float
    critical: bool
    error: str | None = None


class ReadinessReport(BaseModel):
    status: Literal["ready", "degraded", "not_ready"]
    dependencies: list[DependencyHealth]
