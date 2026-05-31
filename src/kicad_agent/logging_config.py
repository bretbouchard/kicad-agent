"""Structured logging configuration via structlog.

Provides configure_logging() which sets up structlog with stdlib
ProcessorFormatter so all existing logging.getLogger(__name__) calls
automatically produce structured output -- JSON for machines,
colored console output for humans.

Environment variables:
    KICAD_LOG_LEVEL:   Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                       Defaults to INFO.
    KICAD_LOG_FORMAT:  Output format -- "json" or "console".
                       Defaults to "console".

Usage::

    from kicad_agent.logging_config import configure_logging
    configure_logging()  # reads env vars

    # Or override explicitly:
    configure_logging(level="DEBUG", json_output=True)

After calling configure_logging(), any module using
``logging.getLogger(__name__)`` will emit structured log lines.
"""

from __future__ import annotations

import logging
import os

import structlog
from structlog.stdlib import ProcessorFormatter


def _resolve_level(level: str | None) -> int:
    """Resolve a log level string to its integer constant.

    Args:
        level: Level name (e.g. "DEBUG", "INFO"). Case-insensitive.
            Falls back to KICAD_LOG_LEVEL env var if None.
            Defaults to INFO if neither is valid.

    Returns:
        Integer log level from the logging module.
    """
    if level is None:
        level = os.environ.get("KICAD_LOG_LEVEL", "INFO")
    # Map level name to int, defaulting to INFO for invalid values
    return getattr(logging, level.upper(), logging.INFO)


def _resolve_json_output(json_output: bool | None) -> bool:
    """Determine whether JSON output should be used.

    Args:
        json_output: Explicit override. Falls back to KICAD_LOG_FORMAT
            env var if None. Defaults to False (console mode).

    Returns:
        True for JSON output, False for console output.
    """
    if json_output is not None:
        return json_output
    return os.environ.get("KICAD_LOG_FORMAT", "console").lower() == "json"


def configure_logging(
    level: str | None = None,
    json_output: bool | None = None,
) -> None:
    """Configure structured logging for the entire application.

    Sets up structlog with stdlib ProcessorFormatter so all existing
    ``logging.getLogger(__name__)`` call sites produce structured output
    without any per-file changes.

    Idempotent: calling multiple times will not duplicate handlers.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            Overrides KICAD_LOG_LEVEL env var. Defaults to env var or INFO.
        json_output: If True, emit JSON log lines. If False, emit colored
            console output. If None, reads KICAD_LOG_FORMAT env var
            (defaults to console).
    """
    log_level = _resolve_level(level)
    use_json = _resolve_json_output(json_output)

    # Shared processors that run for both stdlib and structlog loggers.
    # NOTE: filter_by_level is intentionally excluded from foreign_pre_chain
    # because it requires a structlog logger object which is None for stdlib
    # records. Level filtering is handled by the root logger's setLevel()
    # and the handler's level, which is sufficient for stdlib loggers.
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Configure structlog to use stdlib integration
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Choose renderer based on output mode
    renderer = (
        structlog.processors.JSONRenderer()
        if use_json
        else structlog.dev.ConsoleRenderer()
    )

    # Create the ProcessorFormatter that bridges structlog and stdlib
    formatter = ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    # Configure root logger -- use force=True for basicConfig to override
    # any prior configuration, then ensure exactly one handler with our formatter
    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove existing handlers to ensure idempotency
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
