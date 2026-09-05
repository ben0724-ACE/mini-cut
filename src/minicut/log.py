"""Structured logging primitives for MiniCut."""

import json
import logging
from dataclasses import dataclass
from typing import TextIO
from uuid import uuid4


@dataclass(slots=True)
class LogContext:
    """Identifiers shared by log events from one request or job."""

    request_id: str
    job_id: str | None = None


def new_request_id() -> str:
    """Create an identifier for one user request."""
    return uuid4().hex


def new_job_id() -> str:
    """Create an identifier for one background or processing job."""
    return uuid4().hex


class JsonFormatter(logging.Formatter):
    """Format a log record as one JSON object."""

    def __init__(self, context: LogContext) -> None:
        super().__init__()
        self._context = context

    def format(self, record: logging.LogRecord) -> str:
        event: object = record.__dict__.get("event")
        payload: dict[str, object] = {
            "level": record.levelname,
            "event": event if isinstance(event, str) else "log",
            "message": record.getMessage(),
            "request_id": self._context.request_id,
        }
        if self._context.job_id is not None:
            payload["job_id"] = self._context.job_id
        return json.dumps(payload, ensure_ascii=False)


def create_logger(
    context: LogContext,
    *,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Create an isolated structured logger for one context."""
    logger = logging.Logger("minicut", level=logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(context))
    logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, event: str, message: str) -> None:
    """Write one informational event."""
    logger.info(message, extra={"event": event})
