"""Tests for structured logging via structlog.

Verifies configure_logging() sets up structlog with ProcessorFormatter,
JSON/console modes, idempotency, and stdlib interception.
"""

from __future__ import annotations

import json
import logging
import os
from io import StringIO

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_logging():
    """Reset structlog and stdlib logging between tests."""
    # Clear structlog configuration
    structlog.reset_defaults()

    # Save and restore root logger state
    root = logging.getLogger()
    original_level = root.level
    original_handlers = root.handlers[:]

    yield

    # Restore
    root.level = original_level
    root.handlers = original_handlers
    structlog.reset_defaults()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove logging env vars to avoid interference."""
    monkeypatch.delenv("KICAD_LOG_LEVEL", raising=False)
    monkeypatch.delenv("KICAD_LOG_FORMAT", raising=False)


def test_configure_sets_level():
    """configure_logging(level='DEBUG') sets root logger level to DEBUG."""
    from kicad_agent.logging_config import configure_logging

    configure_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG


def test_configure_sets_level_from_env(monkeypatch):
    """KICAD_LOG_LEVEL env var controls root log level."""
    from kicad_agent.logging_config import configure_logging

    monkeypatch.setenv("KICAD_LOG_LEVEL", "WARNING")
    configure_logging()
    assert logging.getLogger().level == logging.WARNING


def test_json_output_valid_json():
    """configure_logging(json_output=True) produces valid JSON log lines."""
    from kicad_agent.logging_config import configure_logging

    configure_logging(level="INFO", json_output=True)

    # Capture stderr where logging outputs
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    # Remove existing handlers, add our capture handler
    root.handlers = [handler]

    logger = logging.getLogger("test.json.module")
    logger.info("test event message")

    output = stream.getvalue().strip()
    # Should be valid JSON
    parsed = json.loads(output)
    assert isinstance(parsed, dict)
    # Should contain the event or message
    assert "event" in parsed or "message" in parsed


def test_console_output_not_json():
    """configure_logging(json_output=False) produces console-formatted output."""
    from kicad_agent.logging_config import configure_logging

    configure_logging(level="INFO", json_output=False)

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]

    logger = logging.getLogger("test.console.module")
    logger.info("console test message")

    output = stream.getvalue().strip()
    # Console output should NOT be valid JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(output)
    # Should contain the message text
    assert "console test message" in output


def test_idempotent():
    """Calling configure_logging twice produces exactly 1 handler, no errors."""
    from kicad_agent.logging_config import configure_logging

    configure_logging(level="INFO")
    handler_count_1 = len(logging.getLogger().handlers)

    configure_logging(level="DEBUG")
    handler_count_2 = len(logging.getLogger().handlers)

    assert handler_count_1 == 1
    assert handler_count_2 == 1


def test_stdlib_interception():
    """A module-level logging.getLogger call produces structured JSON after configure."""
    from kicad_agent.logging_config import configure_logging

    configure_logging(level="INFO", json_output=True)

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]

    # Use a stdlib logger like existing code does
    module_logger = logging.getLogger("kicad_agent.ops.executor")
    module_logger.info("operation completed")

    output = stream.getvalue().strip()
    parsed = json.loads(output)

    # Should have structured fields
    assert isinstance(parsed, dict)
    # Should contain the log message
    assert "operation completed" in str(parsed.get("event", ""))
    # Should contain logger name
    assert parsed.get("_record", {}).get("name") == "kicad_agent.ops.executor" or \
           parsed.get("logger_name") == "kicad_agent.ops.executor" or \
           "kicad_agent.ops.executor" in str(parsed)


def test_env_var_json_format(monkeypatch):
    """KICAD_LOG_FORMAT=json enables JSON output."""
    from kicad_agent.logging_config import configure_logging

    monkeypatch.setenv("KICAD_LOG_FORMAT", "json")
    configure_logging()

    # Capture output
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]

    logger = logging.getLogger("test.env.json")
    logger.info("env var test")

    output = stream.getvalue().strip()
    parsed = json.loads(output)
    assert isinstance(parsed, dict)


def test_invalid_level_defaults_to_info():
    """Invalid KICAD_LOG_LEVEL value defaults to INFO."""
    from kicad_agent.logging_config import configure_logging

    # Invalid level string should not crash, default to INFO
    configure_logging(level="INVALID_LEVEL")
    assert logging.getLogger().level == logging.INFO
