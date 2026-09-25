from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.dependencies import get_health_service
from app.main import create_app
from app.services.health_service import HealthService, Probe


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionError("connection refused to postgres://user:secret@db")


@pytest.fixture
def settings() -> Settings:
    return Settings(app_env="development", cors_origins=["http://localhost:3000"])


@pytest.fixture
def app(settings: Settings):  # type: ignore[no-untyped-def]
    return create_app(settings)


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    # ASGITransport does not run the lifespan, so no real infrastructure is
    # touched; dependencies that need it are overridden per test.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def use_probes(app):  # type: ignore[no-untyped-def]
    def _set(**states: tuple[bool, bool]) -> None:
        probes = [
            Probe(name, _ok if healthy else _fail, critical=critical)
            for name, (healthy, critical) in states.items()
        ]
        app.dependency_overrides[get_health_service] = lambda: HealthService(probes, timeout_s=1)

    return _set
