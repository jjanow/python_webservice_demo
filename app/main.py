"""FastAPI application factory: the only module that wires everything together."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

# Logging must be configured before any other module logs anything, so this
# import/call happens first, ahead of every other app import.
from app.logging_config import configure_logging
from app.config import settings

configure_logging(settings.LOG_LEVEL)

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.exceptions import register_exception_handlers  # noqa: E402
from app.middleware import (  # noqa: E402
    MetricsMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from app.models import User, UserRole  # noqa: E402
from app.routers import auth, customers, health, orders, products  # noqa: E402
from app.routers.auth import limiter  # noqa: E402
from app.security import hash_password  # noqa: E402

logger = logging.getLogger(__name__)


async def _seed_admin_user() -> None:
    """Create the single admin account from settings if it doesn't already exist.

    There is intentionally no API endpoint that can create an admin account;
    this startup seed is the only path, which avoids a privilege-escalation hole.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == settings.ADMIN_EMAIL))
        if result.scalar_one_or_none() is not None:
            return
        admin = User(
            email=settings.ADMIN_EMAIL,
            hashed_password=hash_password(settings.ADMIN_PASSWORD),
            role=UserRole.ADMIN,
        )
        session.add(admin)
        await session.commit()
        logger.info("Seeded admin user %s", settings.ADMIN_EMAIL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # create-on-startup instead of Alembic migrations: a deliberate simplification
    # for this demo, not an oversight — fine for a single-instance SQLite demo app.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_admin_user()
    logger.info("Application startup complete")
    yield
    await engine.dispose()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(title="Inventory & Orders API", version="1.0.0", lifespan=lifespan)

    # Rate limiter wiring (used by the /auth/login endpoint).
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    # Middleware order matters: Starlette applies middleware in reverse of
    # registration order to the request, so the last one added runs first.
    # We want request-id assigned first (so logs during this request have it),
    # then security headers, then metrics, then CORS innermost.
    # This API authenticates with bearer tokens in the Authorization header,
    # not cookies, so allow_credentials stays False. Keeping it False also
    # avoids the well-known browser rejection of `allow_credentials=True`
    # combined with a wildcard origin, should one ever be configured.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(products.router)
    app.include_router(customers.router)
    app.include_router(orders.router)

    return app


async def _rate_limit_handler(request, exc):
    from fastapi.responses import JSONResponse
    from starlette import status

    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": {"code": status.HTTP_429_TOO_MANY_REQUESTS, "message": "Too many requests"}
        },
    )


app = create_app()
