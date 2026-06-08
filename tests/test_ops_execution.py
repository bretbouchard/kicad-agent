"""Tests for ops/execution module: standalone execution functions."""

import pytest


class TestExecutionModule:
    """Tests for execution module imports."""

    def test_import(self):
        """Execution module is importable."""
        from kicad_agent.ops import execution
        assert hasattr(execution, "execute_single_operation")

    def test_execute_single_callable(self):
        """execute_single_operation is callable."""
        from kicad_agent.ops.execution import execute_single_operation
        assert callable(execute_single_operation)


class TestBatchExecutor:
    """Tests for batch executor module."""

    def test_import(self):
        """Batch executor module is importable."""
        from kicad_agent.ops import batch_executor
        assert hasattr(batch_executor, "execute_batch")

    def test_execute_batch_callable(self):
        """execute_batch is callable."""
        from kicad_agent.ops.batch_executor import execute_batch
        assert callable(execute_batch)


class TestOpsHandler:
    """Tests for operation handler registry."""

    def test_import(self):
        """Handler module is importable."""
        from kicad_agent.ops import executor
        assert hasattr(executor, "OperationExecutor")


class TestConflictDetector:
    """Tests for conflict detector module."""

    def test_import(self):
        """Conflict detector module is importable."""
        from kicad_agent.ops import conflict_detector
        assert hasattr(conflict_detector, "validate_conflicts")
