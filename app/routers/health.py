"""Liveness/readiness probes and Prometheus metrics exposition. No auth required."""
from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> Response:
    try:
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return Response(
            content='{"status": "error", "detail": "database unavailable"}',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json",
        )
    return Response(content='{"status": "ok"}', media_type="application/json")


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
