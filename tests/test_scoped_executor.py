"""Tests for ScopedExecutor and ScopeViolationError (Phase 92)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_agent.validation.gates.scoped_executor import (
    ScopeViolationError,
    ScopedExecutor,
)


def _make_op(target_file: str) -> MagicMock:
    op = MagicMock()
    op.target_file = target_file
    return op


class TestScopeViolationError:
    def test_message_contains_target_file(self) -> None:
        err = ScopeViolationError(Path("/etc/passwd"), [Path("/tmp/a.sch")])
        assert "/etc/passwd" in str(err)

    def test_message_contains_scope(self) -> None:
        err = ScopeViolationError(Path("/other"), [Path("/tmp/a.sch")])
        assert "a.sch" in str(err)

    def test_attributes_accessible(self) -> None:
        target = Path("/tmp/evil.kicad_pcb")
        scope = [Path("/tmp/good.kicad_pcb")]
        err = ScopeViolationError(target, scope)
        assert err.target_file == target
        assert err.scope_files == scope


class TestScopedExecutor:
    def test_in_scope_executes(self) -> None:
        executor = MagicMock()
        executor.execute.return_value = {"status": "ok"}
        scope = [Path("test.kicad_sch"), Path("other.kicad_pcb")]
        scoped = ScopedExecutor(executor, scope)

        result = scoped.execute(_make_op("test.kicad_sch"))
        assert result == {"status": "ok"}
        executor.execute.assert_called_once()

    def test_out_of_scope_raises(self) -> None:
        executor = MagicMock()
        scope = [Path("allowed.kicad_sch")]
        scoped = ScopedExecutor(executor, scope)

        with pytest.raises(ScopeViolationError):
            scoped.execute(_make_op("/etc/passwd"))
        executor.execute.assert_not_called()

    def test_empty_scope_rejects_all(self) -> None:
        executor = MagicMock()
        scoped = ScopedExecutor(executor, [])

        with pytest.raises(ScopeViolationError):
            scoped.execute(_make_op("anything.sch"))

    def test_scope_files_tuple_immutable(self) -> None:
        scope = [Path("a.sch")]
        scoped = ScopedExecutor(MagicMock(), scope)
        assert isinstance(scoped.scope_files, tuple)
        assert scoped.scope_files == (Path("a.sch"),)

    def test_scope_check_before_parse(self) -> None:
        """Scope check happens before executor is called."""
        executor = MagicMock()
        # Make executor raise if called — proves scope check is first
        executor.execute.side_effect = RuntimeError("should not reach here")
        scope = [Path("allowed.sch")]
        scoped = ScopedExecutor(executor, scope)

        # In-scope would trigger the error, out-of-scope would not
        with pytest.raises(ScopeViolationError):
            scoped.execute(_make_op("forbidden.sch"))
