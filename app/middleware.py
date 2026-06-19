"""Request-ID propagation, security headers, and Prometheus metrics middleware."""
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_HEADER = "X-Request-ID"


def get_request_id() -> str | None:
    """Read the current request's ID from context, for use in log formatting."""
    return _request_id_ctx.get()


REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Propagate/generate X-Request-ID and expose it via a contextvar for logging."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        # Also stash on request.state: if an exception propagates past this
        # middleware's `finally`, the contextvar gets reset before Starlette's
        # outer ServerErrorMiddleware invokes our 500 handler, so the handler
        # needs a way to recover the id that survives the unwind.
        request.state.request_id = request_id
        token = _request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            _request_id_ctx.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach standard hardening headers to every response."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # HSTS only has effect once the app is actually served over TLS (e.g. behind a
        # reverse proxy terminating HTTPS); harmless to send over plain HTTP in dev.
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Record request count and latency labeled by method/path-template/status."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        route = request.scope.get("route")
        path_template = route.path if route is not None else request.url.path

        REQUEST_COUNT.labels(
            method=request.method, path=path_template, status_code=response.status_code
        ).inc()
        REQUEST_LATENCY.labels(method=request.method, path=path_template).observe(elapsed)
        return response
