async def test_liveness_returns_envelope_and_headers(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["request_id"] == response.headers["x-request-id"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


async def test_upstream_request_id_is_propagated(client):
    response = await client.get("/api/v1/health", headers={"X-Request-ID": "lb-abc-123"})
    assert response.headers["x-request-id"] == "lb-abc-123"
    assert response.json()["request_id"] == "lb-abc-123"


async def test_ready_when_all_dependencies_up(client, use_probes):
    use_probes(postgres=(True, True), redis=(True, True), qdrant=(True, True))
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ready"
    assert {d["name"] for d in data["dependencies"]} == {"postgres", "redis", "qdrant"}


async def test_not_ready_when_critical_dependency_down(client, use_probes):
    use_probes(postgres=(False, True), redis=(True, True))
    response = await client.get("/api/v1/ready")
    assert response.status_code == 503
    postgres = next(d for d in response.json()["data"]["dependencies"] if d["name"] == "postgres")
    assert postgres["status"] == "down"
    # The raw exception text contained credentials; only the class name is exposed.
    assert postgres["error"] == "ConnectionError"
    assert "secret" not in response.text


async def test_degraded_when_only_noncritical_down(client, use_probes):
    use_probes(postgres=(True, True), langfuse=(False, False))
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "degraded"
