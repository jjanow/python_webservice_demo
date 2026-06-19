"""Shared pytest fixtures.

IMPORTANT: env vars for settings must be set *before* `app.config` (and
anything importing it, e.g. `app.database`, `app.main`) is imported anywhere
in the test session. `app.config.settings` is a module-level singleton built
via an `lru_cache`d `get_settings()`, and `app.database` builds its engine
from `settings.DATABASE_URL` at import time. Setting env vars in a fixture
(which runs after collection-time imports) would be too late. So this happens
at module level, at the very top of conftest, before any `app.*` import.
"""
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-not-for-prod-use")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "admin-test-password")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORS_ORIGINS", "")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User, UserRole  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402

ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
STAFF_EMAIL = "staff@example.com"
STAFF_PASSWORD = "staff-test-password"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A fresh in-memory SQLite DB (single shared connection) per test.

    StaticPool forces every checkout to reuse the same underlying connection,
    so tables created by `create_all` are visible to every session in this
    test instead of vanishing when a different pooled connection is used.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    async with session_factory() as session:
        yield session

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def seed_users(db_session: AsyncSession) -> dict[str, User]:
    """Insert an admin and a staff user directly into the test DB."""
    admin = User(
        email=ADMIN_EMAIL,
        hashed_password=hash_password(ADMIN_PASSWORD),
        role=UserRole.ADMIN,
    )
    staff = User(
        email=STAFF_EMAIL,
        hashed_password=hash_password(STAFF_PASSWORD),
        role=UserRole.STAFF,
    )
    db_session.add_all([admin, staff])
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(staff)
    return {"admin": admin, "staff": staff}


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Unauthenticated client. Depends on db_session so overrides are wired."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_client(
    db_session: AsyncSession, seed_users: dict[str, User]
) -> AsyncGenerator[AsyncClient, None]:
    """Own AsyncClient instance (not shared with `client`/`staff_client`) so
    setting an Authorization header here can never leak onto another
    fixture's client when both are requested by the same test."""
    token = create_access_token(subject=seed_users["admin"].email)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def staff_client(
    db_session: AsyncSession, seed_users: dict[str, User]
) -> AsyncGenerator[AsyncClient, None]:
    token = create_access_token(subject=seed_users["staff"].email)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {token}"}
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """Disable slowapi rate limiting for every test except the dedicated one.

    The /auth/login limiter shares in-memory state across requests within a
    test process; leaving it enabled would make unrelated tests flaky/order
    dependent. The one test that exercises the limiter explicitly re-enables
    it for its own duration.
    """
    app.state.limiter.enabled = False
    yield
    app.state.limiter.enabled = False


@pytest.fixture
def enable_rate_limiting():
    app.state.limiter.enabled = True
    yield
    app.state.limiter.enabled = False
