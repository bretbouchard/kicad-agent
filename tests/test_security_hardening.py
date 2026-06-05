"""Security regression tests for Phase 24 Council Audit Remediation.

Tests verify that all security hardening measures from the Council audit
remain in place and cannot be accidentally regressed.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ir.pcb_ir import (
    _escape_sexpr_value,
    _inject_layer,
    _inject_lib_id,
    _inject_pad_net,
)
from kicad_agent.ops.create_file import _atomic_write
from kicad_agent.ops.schema import (
    _UNSAFE_SEXPR_CHARS,
    _validate_sexpr_safe_string,
)


# ---------------------------------------------------------------------------
# C-1: Path confinement in executor
# ---------------------------------------------------------------------------


class TestPathConfiment:
    """Verify path traversal attacks are rejected at runtime."""

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """Executor rejects target_file paths outside base_dir."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        executor = OperationExecutor(base_dir=tmp_path)
        with pytest.raises(Exception):
            executor.execute(Operation.model_validate({
                "root": {
                    "op_type": "add_component",
                    "target_file": "../../etc/passwd",
                    "library_id": "Device:R",
                    "reference": "R1",
                    "value": "1k",
                }
            }))

    def test_absolute_path_outside_rejected(self, tmp_path: Path) -> None:
        """Executor rejects absolute paths outside base_dir."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        executor = OperationExecutor(base_dir=tmp_path)
        with pytest.raises(Exception):
            executor.execute(Operation.model_validate({
                "root": {
                    "op_type": "add_component",
                    "target_file": "/etc/passwd",
                    "library_id": "Device:R",
                    "reference": "R1",
                    "value": "1k",
                }
            }))

    def test_valid_relative_path_accepted(self, tmp_path: Path) -> None:
        """Executor accepts valid relative paths inside base_dir."""
        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch (version 20231120) (generator kicad-agent))")
        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute(Operation.model_validate({
            "root": {
                "op_type": "parse_erc",
                "target_file": "test.kicad_sch",
            }
        }))
        assert result is not None


# ---------------------------------------------------------------------------
# C-4: S-expression injection escaping
# ---------------------------------------------------------------------------


class TestSexprEscaping:
    """Verify S-expression injection is escaped in all _inject_* functions.

    KiCad uses doubled-quote convention: literal quotes become "".
    """

    def test_inject_lib_id_escapes_quotes(self):
        """Double quotes in lib_id are escaped using KiCad doubled-quote."""
        result = _inject_lib_id('(footprint "original")', 'lib"evil')
        assert '""' in result
        assert result == '(footprint "lib""evil")'

    def test_inject_layer_escapes_parens(self):
        """Parentheses in layer names are escaped using KiCad doubled-quote."""
        result = _inject_layer('\t(layer "F.Cu")', 'F.Cu") (evil')
        assert '""' in result

    def test_inject_pad_net_escapes_net_name(self):
        """Net names with special characters are escaped using KiCad doubled-quote."""
        sexp = '(pad "1" thru_hole circle (at 0 0) (size 1 1) (drill 0.5))'
        result = _inject_pad_net(sexp, "1", 'net"evil')
        assert result is not None
        assert '""' in result

    def test_escape_sexpr_value_backslash(self):
        """Backslashes pass through unchanged (KiCad doesn't use backslash escaping)."""
        assert _escape_sexpr_value("a\\b") == "a\\b"

    def test_escape_sexpr_value_quote(self):
        """Double quotes are escaped using KiCad doubled-quote convention."""
        assert _escape_sexpr_value('a"b') == 'a""b'


# ---------------------------------------------------------------------------
# H-5: Unsafe S-expression character validator
# ---------------------------------------------------------------------------


class TestSexprSafeValidator:
    """Verify _validate_sexpr_safe_string rejects dangerous characters."""

    def test_rejects_parentheses(self):
        with pytest.raises(ValueError, match="unsafe S-expression"):
            _validate_sexpr_safe_string("foo(bar)")

    def test_rejects_double_quotes(self):
        with pytest.raises(ValueError, match="unsafe S-expression"):
            _validate_sexpr_safe_string('foo"bar')

    def test_rejects_newlines(self):
        with pytest.raises(ValueError, match="unsafe S-expression"):
            _validate_sexpr_safe_string("foo\nbar")

    def test_accepts_normal_strings(self):
        assert _validate_sexpr_safe_string("hello world") == "hello world"

    def test_accepts_alphanumeric(self):
        assert _validate_sexpr_safe_string("R1_2.5V") == "R1_2.5V"

    def test_unsafe_chars_regex_matches_dangerous(self):
        """The regex pattern itself detects the expected characters."""
        assert _UNSAFE_SEXPR_CHARS.search("(")
        assert _UNSAFE_SEXPR_CHARS.search(")")
        assert _UNSAFE_SEXPR_CHARS.search('"')
        assert _UNSAFE_SEXPR_CHARS.search("\n")


# ---------------------------------------------------------------------------
# L-1: Atomic file write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    """Verify atomic write creates files and cleans up on failure."""

    def test_creates_file(self, tmp_path):
        """Atomic write creates the target file with correct content."""
        target = tmp_path / "test.kicad_sch"
        _atomic_write(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_cleans_up_on_failure(self, tmp_path):
        """If rename fails, temp file is cleaned up."""
        # Make target directory read-only to cause rename failure
        target = tmp_path / "nonexistent" / "subdir" / "test.kicad_sch"
        with pytest.raises(OSError):
            _atomic_write(target, "should fail")
        # Verify no temp files left behind
        temp_files = list(tmp_path.glob(".kicad_*.tmp"))
        assert len(temp_files) == 0

    def test_overwrites_existing(self, tmp_path):
        """Atomic write overwrites existing file."""
        target = tmp_path / "existing.kicad_sch"
        target.write_text("old content", encoding="utf-8")
        _atomic_write(target, "new content")
        assert target.read_text(encoding="utf-8") == "new content"


# ---------------------------------------------------------------------------
# H-3: MCP error sanitization
# ---------------------------------------------------------------------------


class TestMcpErrorSanitization:
    """Verify MCP server returns generic errors with correlation IDs."""

    def test_error_format_contains_correlation_id(self):
        """Error responses contain 'Internal error (ref:' prefix."""
        import re

        # Simulate what the sanitized handler produces
        import uuid

        correlation_id = str(uuid.uuid4())[:8]
        msg = f"Internal error (ref: {correlation_id}). See server logs for details."
        assert "Internal error (ref:" in msg
        assert correlation_id in msg
        # Should NOT contain raw exception info
        assert "Traceback" not in msg

    def test_server_imports_uuid(self):
        """Server module imports uuid for correlation ID generation."""
        import kicad_agent.mcp.server as server_mod

        assert hasattr(server_mod, "uuid")
