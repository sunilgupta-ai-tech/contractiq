async def test_planned_endpoint_returns_501_envelope(client):
    response = await client.post("/api/v1/contracts/compare")
    assert response.status_code == 501
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_IMPLEMENTED"
    assert body["error"]["details"]["phase"] == 10
    assert body["request_id"]


async def test_unknown_route_uses_error_envelope(client):
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_unhandled_exception_hides_internals(app, client):
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        response = await c.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text


def test_full_api_surface_is_registered(app):
    paths = set(app.openapi()["paths"])
    for expected in [
        "/api/v1/auth/login",
        "/api/v1/documents/upload",
        "/api/v1/documents/{document_id}/status",
        "/api/v1/query",
        "/api/v1/contracts/compare",
        "/api/v1/contracts/risk-analysis",
        "/api/v1/contracts/extract-clauses",
        "/api/v1/contracts/summarize",
        "/api/v1/jobs/{job_id}",
        "/api/v1/health",
        "/api/v1/ready",
    ]:
        assert expected in paths
