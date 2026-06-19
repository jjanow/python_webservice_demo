"""Error envelope consistency for routing-layer errors (404/405) that bypass
route handlers entirely, plus the /metrics endpoint smoke check.

A genuine unhandled-exception (500) path isn't reachable here without
injecting a fault into the running app, which the task instructions say not
to manufacture -- so that case is intentionally not covered.
"""
from httpx import AsyncClient


async def test_unknown_route_returns_404_envelope(client: AsyncClient):
    resp = await client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == 404
    assert "message" in body["error"]


async def test_wrong_method_on_existing_route_returns_405_envelope(client: AsyncClient):
    # /health/live only supports GET.
    resp = await client.post("/health/live")
    assert resp.status_code == 405
    body = resp.json()
    assert body["error"]["code"] == 405


async def test_validation_error_envelope_shape(client: AsyncClient, db_session):
    resp = await client.post("/auth/register", json={"email": "not-an-email", "password": "x"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == 422
    assert body["error"]["message"] == "Validation error"


async def test_metrics_endpoint_exposes_prometheus_text(client: AsyncClient):
    # Issue a prior request so MetricsMiddleware has recorded at least one
    # sample before we scrape.
    await client.get("/health/live")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "http_requests_total" in resp.text
