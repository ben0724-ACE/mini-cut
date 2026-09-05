"""Structured logging primitives for MiniCut."""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TextIO, cast
from uuid import uuid4

REDACTED = "[REDACTED]"
SENSITIVE_FIELD_NAMES = {"api_key", "apikey", "authorization", "prompt"}


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
        fields: object = record.__dict__.get("fields")
        if isinstance(fields, dict):
            payload["fields"] = _redact_value(cast(dict[object, object], fields))
        return json.dumps(payload, ensure_ascii=False)


def _redact_value(value: object) -> object:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        redacted: dict[str, object] = {}
        for raw_key, nested_value in mapping.items():
            key = str(raw_key)
            normalized_key = key.casefold().replace("-", "_")
            if normalized_key in SENSITIVE_FIELD_NAMES or normalized_key.endswith(
                "_prompt"
            ):
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact_value(nested_value)
        return redacted
    if isinstance(value, list):
        values = cast(list[object], value)
        return [_redact_value(item) for item in values]
    return value


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


def log_event(
    logger: logging.Logger,
    event: str,
    message: str,
    *,
    fields: Mapping[str, object] | None = None,
) -> None:
    """Write one informational event."""
    extra: dict[str, object] = {"event": event}
    if fields is not None:
        extra["fields"] = dict(fields)
    logger.info(message, extra=extra)
