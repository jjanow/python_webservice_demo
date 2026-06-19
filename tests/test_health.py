"""Liveness/readiness probes, and a smoke check for global middleware."""
from httpx import AsyncClient

from app.middleware import REQUEST_ID_HEADER


async def test_liveness_always_ok(client: AsyncClient):
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readiness_ok_when_db_reachable(client: AsyncClient):
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_security_headers_and_request_id_present(client: AsyncClient):
    resp = await client.get("/health/live")
    assert resp.headers.get(REQUEST_ID_HEADER)
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert "Strict-Transport-Security" in resp.headers


async def test_request_id_is_echoed_back_when_supplied(client: AsyncClient):
    resp = await client.get("/health/live", headers={REQUEST_ID_HEADER: "test-rid-123"})
    assert resp.headers.get(REQUEST_ID_HEADER) == "test-rid-123"
