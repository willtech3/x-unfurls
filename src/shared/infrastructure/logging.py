"""Structured logging utilities for Cloud Logging compatibility."""

import contextvars
import json
import logging
import sys
from typing import Any

# Context variable for trace IDs
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging compatible with Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record, self.datefmt),
            "logger": record.name,
        }

        # Add trace ID if available
        trace_id = trace_id_var.get()
        if trace_id:
            log_data["logging.googleapis.com/trace"] = trace_id

        # Add any extra fields from the record
        if hasattr(record, "event"):
            log_data["event"] = record.event
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def ensure_trace_id() -> str:
    """Ensure a trace ID exists in context, creating one if needed.

    Returns:
        The current trace ID
    """
    import uuid

    trace_id = trace_id_var.get()
    if not trace_id:
        trace_id = str(uuid.uuid4())
        trace_id_var.set(trace_id)
    return trace_id


def log_event(
    logger: logging.Logger, level: int, message: str, event: str = "", **kwargs: Any
) -> None:
    """Log a structured event with additional metadata.

    Args:
        logger: Logger instance
        level: Log level
        message: Log message
        event: Event name/type
        **kwargs: Additional fields to include in the log
    """
    extra = {"event": event, "extra_data": kwargs}
    logger.log(level, message, extra=extra)
