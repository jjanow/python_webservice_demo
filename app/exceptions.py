"""Centralized exception handlers producing a consistent JSON error envelope."""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.middleware import REQUEST_ID_HEADER, get_request_id

logger = logging.getLogger(__name__)


def _envelope(code: int, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _request_id(request: Request) -> str | None:
    """Prefer the contextvar; fall back to request.state for the 500 path,
    where the contextvar has already been reset by RequestIDMiddleware's
    `finally` block before this handler runs (it lives outside that middleware)."""
    return get_request_id() or getattr(request.state, "request_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers so HTTPException (including routing-layer 404/405),
    validation errors, and unhandled errors all return the same
    `{"error": {"code", "message"}}` shape."""

    # Registering on Starlette's HTTPException (FastAPI's HTTPException is a
    # subclass) also catches 404/405s raised by routing itself, before a route
    # is even matched -- those would otherwise bypass this envelope entirely.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        headers = dict(exc.headers) if exc.headers else {}
        request_id = _request_id(request)
        if request_id:
            headers.setdefault(REQUEST_ID_HEADER, request_id)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.status_code, str(exc.detail)),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(status.HTTP_422_UNPROCESSABLE_ENTITY, "Validation error"),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Full traceback goes to the logs, tagged with request_id pulled from
        # request.state since the contextvar is already gone by this point;
        # the client only ever sees a generic message, never internal details.
        request_id = _request_id(request)
        logger.error(
            "Unhandled exception while processing request",
            exc_info=exc,
            extra={"request_id": request_id} if request_id else None,
        )
        headers = {REQUEST_ID_HEADER: request_id} if request_id else None
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error"),
            headers=headers,
        )
