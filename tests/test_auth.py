"""Auth endpoint tests: register, login, /auth/me, and rate limiting."""
import pytest
from httpx import AsyncClient

from app.config import settings


async def test_register_staff_success(client: AsyncClient, db_session):
    resp = await client.post(
        "/auth/register", json={"email": "new.staff@example.com", "password": "longenough123"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "new.staff@example.com"
    assert body["role"] == "staff"
    assert "hashed_password" not in body


async def test_register_duplicate_email_returns_409(client: AsyncClient, db_session):
    payload = {"email": "dupe@example.com", "password": "longenough123"}
    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == 409


async def test_register_password_too_short_returns_422(client: AsyncClient, db_session):
    resp = await client.post(
        "/auth/register", json={"email": "shortpw@example.com", "password": "short"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == 422


async def test_register_password_over_72_bytes_returns_422(client: AsyncClient, db_session):
    # bcrypt silently truncates input past 72 bytes rather than erroring, which
    # would otherwise weaken long/multi-byte passwords invisibly. A 4-byte emoji
    # repeated 20 times is 80 bytes (>72) but only 20 chars (well under max_length).
    resp = await client.post(
        "/auth/register", json={"email": "longpw@example.com", "password": "\U0001f600" * 20}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == 422


async def test_register_role_field_is_ignored_and_forced_to_staff(
    client: AsyncClient, db_session
):
    """Client-supplied `role: admin` must never be honored; UserCreate has no
    role field at all, so FastAPI/Pydantic silently drops the extra key and
    the server always creates a STAFF account."""
    resp = await client.post(
        "/auth/register",
        json={"email": "wannabe.admin@example.com", "password": "longenough123", "role": "admin"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "staff"


async def test_login_success_returns_valid_jwt(client: AsyncClient, db_session):
    await client.post(
        "/auth/register", json={"email": "login.user@example.com", "password": "longenough123"}
    )
    resp = await client.post(
        "/auth/login",
        data={"username": "login.user@example.com", "password": "longenough123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    # The token decodes and authorizes against /auth/me.
    me = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "login.user@example.com"


async def test_login_wrong_password_returns_generic_401(client: AsyncClient, db_session):
    await client.post(
        "/auth/register", json={"email": "wrongpw@example.com", "password": "longenough123"}
    )
    resp = await client.post(
        "/auth/login", data={"username": "wrongpw@example.com", "password": "incorrect-pass"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Incorrect email or password"


async def test_login_nonexistent_email_returns_same_generic_401(client: AsyncClient, db_session):
    """Message must be identical to the wrong-password case so the API never
    reveals whether an email is registered."""
    resp = await client.post(
        "/auth/login", data={"username": "nobody@example.com", "password": "whatever123"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Incorrect email or password"


async def test_me_requires_auth(client: AsyncClient, db_session):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_returns_correct_profile_for_admin(admin_client: AsyncClient):
    resp = await admin_client.get("/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == settings.ADMIN_EMAIL
    assert body["role"] == "admin"


@pytest.mark.usefixtures("enable_rate_limiting")
async def test_login_rate_limit_trips_after_five_attempts(client: AsyncClient, db_session):
    """Isolated from the rest of the suite: the autouse fixture disables the
    limiter everywhere else, and this test re-enables it just for itself."""
    creds = {"username": "ratelimited@example.com", "password": "whatever-wrong"}
    statuses = []
    for _ in range(6):
        resp = await client.post("/auth/login", data=creds)
        statuses.append(resp.status_code)

    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
    assert resp.json()["error"]["message"] == "Too many requests"


@pytest.mark.usefixtures("enable_rate_limiting")
async def test_register_rate_limit_trips_after_five_attempts(client: AsyncClient, db_session):
    statuses = []
    for i in range(6):
        resp = await client.post(
            "/auth/register",
            json={"email": f"ratelimited{i}@example.com", "password": "whatever123"},
        )
        statuses.append(resp.status_code)

    assert statuses[:5] == [201] * 5
    assert statuses[5] == 429
    assert resp.json()["error"]["message"] == "Too many requests"
