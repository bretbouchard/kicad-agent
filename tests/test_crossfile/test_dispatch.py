"""Integration tests for cross-file dispatch through the OperationExecutor.

Covers:
- PropagateSymbolChangeOp dispatches through _execute_cross_file
- Happy path updates schematic + PCB atomically
- No-match and identical old/new return zero updates
- Missing file raises FileNotFoundError
- Path traversal raises ValueError
- Partial failure triggers rollback on both files
- Path confinement rejects escape attempts
- Empty target_files raises ValueError
"""

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from volta.ir.base import _clear_registry
from volta.ops.executor import OperationExecutor
from volta.ops.schema import Operation
from volta.ops._schema_crossfile import PropagateSymbolChangeOp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the IR UUID registry between tests to avoid cross-contamination."""
    _clear_registry()
    yield
    _clear_registry()


@pytest.fixture
def project_dir(
    tmp_path: Path,
    arduino_mega_sch: Path,
    arduino_mega_pcb: Path,
) -> Path:
    """Copy Arduino Mega sch + pcb into tmp_path for isolated testing.

    Returns:
        tmp_path containing both KiCad files.
    """
    shutil.copy2(arduino_mega_sch, tmp_path / "Arduino_Mega.kicad_sch")
    shutil.copy2(arduino_mega_pcb, tmp_path / "Arduino_Mega.kicad_pcb")
    return tmp_path


def _make_propagate_op(
    target_files: list[str],
    old_lib_id: str = "power:+5V",
    new_lib_id: str = "MyPower:+5V",
) -> Operation:
    """Construct a PropagateSymbolChangeOp wrapped in Operation."""
    return Operation(
        root=PropagateSymbolChangeOp(
            target_file=target_files[0],
            target_files=target_files,
            old_lib_id=old_lib_id,
            new_lib_id=new_lib_id,
        )
    )


# ---------------------------------------------------------------------------
# TestPropagateSymbolChangeDispatch
# ---------------------------------------------------------------------------


class TestPropagateSymbolChangeDispatch:
    """Happy-path and edge-case tests for propagate_symbol_change dispatch."""

    def test_propagate_symbol_change_updates_schematic_and_pcb(
        self, project_dir: Path
    ) -> None:
        """Happy path: propagate a symbol change across sch + pcb atomically."""
        op = _make_propagate_op(
            target_files=[
                "Arduino_Mega.kicad_sch",
                "Arduino_Mega.kicad_pcb",
            ],
            old_lib_id="power:+5V",
            new_lib_id="MyPower:+5V",
        )
        executor = OperationExecutor(base_dir=project_dir)
        result = executor.execute(op)

        assert result["success"] is True
        assert result["operation"] == "propagate_symbol_change"
        details = result["details"]
        assert details["total_updated"] > 0
        # Should have results for both files
        assert len(details["files_modified"]) == 2

    def test_propagate_symbol_change_no_match_returns_zero(
        self, project_dir: Path
    ) -> None:
        """Non-matching old_lib_id returns zero updates."""
        op = _make_propagate_op(
            target_files=[
                "Arduino_Mega.kicad_sch",
                "Arduino_Mega.kicad_pcb",
            ],
            old_lib_id="NonExistent:Component",
            new_lib_id="MyLib:Component",
        )
        executor = OperationExecutor(base_dir=project_dir)
        result = executor.execute(op)

        assert result["success"] is True
        assert result["details"]["total_updated"] == 0

    def test_propagate_symbol_change_identical_old_new_returns_zero(
        self, project_dir: Path
    ) -> None:
        """Same old/new lib_id returns zero updates (no-op)."""
        op = _make_propagate_op(
            target_files=[
                "Arduino_Mega.kicad_sch",
                "Arduino_Mega.kicad_pcb",
            ],
            old_lib_id="power:+5V",
            new_lib_id="power:+5V",
        )
        executor = OperationExecutor(base_dir=project_dir)
        result = executor.execute(op)

        assert result["success"] is True
        assert result["details"]["total_updated"] == 0

    def test_propagate_symbol_change_missing_file_raises(
        self, project_dir: Path
    ) -> None:
        """FileNotFoundError when a target file does not exist."""
        op = _make_propagate_op(
            target_files=[
                "Arduino_Mega.kicad_sch",
                "NonExistent.kicad_pcb",
            ],
        )
        executor = OperationExecutor(base_dir=project_dir)

        with pytest.raises(FileNotFoundError, match="Cross-file target not found"):
            executor.execute(op)

    def test_propagate_symbol_change_path_traversal_raises(
        self, project_dir: Path
    ) -> None:
        """ValueError when target_file contains path traversal."""
        # The TargetFile validator catches '..' so this should fail at validation
        with pytest.raises(Exception):
            PropagateSymbolChangeOp(
                target_file="../../etc/passwd",
                target_files=["../../etc/passwd"],
                old_lib_id="power:+5V",
                new_lib_id="MyPower:+5V",
            )


# ---------------------------------------------------------------------------
# TestCrossFilePartialFailure
# ---------------------------------------------------------------------------


class TestCrossFilePartialFailure:
    """Verify rollback behavior when partial failure occurs."""

    def test_partial_failure_rollback_both_files(
        self, project_dir: Path
    ) -> None:
        """When propagation fails on one file, both files remain unchanged."""
        sch_path = project_dir / "Arduino_Mega.kicad_sch"
        pcb_path = project_dir / "Arduino_Mega.kicad_pcb"

        # Snapshot original file contents
        original_sch = sch_path.read_text(encoding="utf-8")
        original_pcb = pcb_path.read_text(encoding="utf-8")

        op = _make_propagate_op(
            target_files=[
                "Arduino_Mega.kicad_sch",
                "Arduino_Mega.kicad_pcb",
            ],
            old_lib_id="power:+5V",
            new_lib_id="MyPower:+5V",
        )

        # Make propagate_footprint_ref raise to simulate PCB-side failure
        with patch(
            "volta.crossfile.propagation.propagate_footprint_ref",
            side_effect=RuntimeError("Simulated PCB failure"),
        ):
            executor = OperationExecutor(base_dir=project_dir)

            with pytest.raises(RuntimeError, match="Simulated PCB failure"):
                executor.execute(op)

        # Both files should be unchanged (AtomicOperation rolled back)
        assert sch_path.read_text(encoding="utf-8") == original_sch
        assert pcb_path.read_text(encoding="utf-8") == original_pcb


# ---------------------------------------------------------------------------
# TestCrossFilePathConfinement
# ---------------------------------------------------------------------------


class TestCrossFilePathConfinement:
    """Security: cross-file operations must enforce path confinement."""

    def test_path_confinement_rejects_escape(
        self, tmp_path: Path, arduino_mega_sch: Path
    ) -> None:
        """Path traversal in target_files is rejected by TargetFile validator."""
        # The TargetFile validator catches '..' at schema validation time
        with pytest.raises(Exception, match="path traversal"):
            PropagateSymbolChangeOp(
                target_file="Arduino_Mega.kicad_sch",
                target_files=[
                    "Arduino_Mega.kicad_sch",
                    "../outside/escape.kicad_sch",
                ],
                old_lib_id="power:+5V",
                new_lib_id="MyPower:+5V",
            )

    def test_cross_file_with_empty_target_files_raises(
        self, project_dir: Path
    ) -> None:
        """ValueError when target_files list is empty (validation should catch this)."""
        # Pydantic min_length=1 on target_files should reject empty list
        with pytest.raises(Exception):
            PropagateSymbolChangeOp(
                target_file="Arduino_Mega.kicad_sch",
                target_files=[],
                old_lib_id="power:+5V",
                new_lib_id="MyPower:+5V",
            )
