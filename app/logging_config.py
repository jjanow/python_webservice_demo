"""JSON line logging configuration. Must be set up before anything else logs."""
import json
import logging
import sys
from datetime import UTC, datetime

from app.middleware import get_request_id


class JsonFormatter(logging.Formatter):
    """Renders each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Prefer an explicit request_id passed via `extra=` (used by the 500
        # handler, where the contextvar has already been reset); fall back
        # to the contextvar for everything logged during normal request handling.
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger to emit single-line JSON to stdout."""
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove any pre-existing handlers (e.g. uvicorn defaults) to avoid duplicate lines.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Route uvicorn's own loggers through the same JSON formatting.
    for noisy_logger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy_logger).handlers = []
        logging.getLogger(noisy_logger).propagate = True
