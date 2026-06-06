"""Tests for execute_batch() batch operation mode.

Validates single-parse single-write optimization: groups ops by target file,
parses each file once, validates all operations upfront, applies all mutations,
and writes once per file.

Uses Arduino_Mega fixture which has references J1-J7.
"""

import shutil
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ops.executor import OperationExecutor
from kicad_agent.ops.ir_cache import IRCache
from kicad_agent.ops.schema import Operation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_modify_property_op(
    target_file: str, reference: str, property_name: str, new_value: str
) -> Operation:
    """Create a modify_property operation."""
    return Operation.model_validate({
        "root": {
            "op_type": "modify_property",
            "target_file": target_file,
            "reference": reference,
            "property_name": property_name,
            "new_value": new_value,
        }
    })


def _make_validate_refs_op(target_file: str) -> Operation:
    """Create a validate_refs operation (read-only, always succeeds)."""
    return Operation.model_validate({
        "root": {
            "op_type": "validate_refs",
            "target_file": target_file,
        }
    })


def _copy_arduino_fixture(tmp_path: Path, name: str = "test.kicad_sch") -> Path:
    """Copy Arduino_Mega schematic fixture to tmp_path and return the path."""
    fixture = Path(__file__).parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
    dest = tmp_path / name
    shutil.copy2(fixture, dest)
    return dest


# ---------------------------------------------------------------------------
# TestBatchExecutor
# ---------------------------------------------------------------------------


class TestBatchExecutor:
    """Tests for execute_batch() correctness and optimization guarantees."""

    def test_empty_batch_returns_success(self, tmp_path: Path) -> None:
        """Empty ops list returns success with empty results."""
        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch([])
        assert result["success"] is True
        assert result["results"] == []

    def test_three_ops_same_file_parses_once(self, tmp_path: Path) -> None:
        """Three ops on same file triggers one parse."""
        _copy_arduino_fixture(tmp_path)

        # Use validate_refs (read-only) to confirm single-parse behavior
        ops = [
            _make_validate_refs_op("test.kicad_sch"),
            _make_validate_refs_op("test.kicad_sch"),
            _make_validate_refs_op("test.kicad_sch"),
        ]

        executor = OperationExecutor(base_dir=tmp_path)

        with patch(
            "kicad_agent.ops.batch_executor.parse_schematic",
            side_effect=lambda p: __import__(
                "kicad_agent.parser", fromlist=["parse_schematic"]
            ).parse_schematic(p),
        ) as mock_parse:
            result = executor.execute_batch(ops)

        assert result["success"] is True
        assert mock_parse.call_count == 1

    def test_writes_file_once(self, tmp_path: Path) -> None:
        """Three modify_property ops on same file triggers one serialization."""
        _copy_arduino_fixture(tmp_path)

        # Use J1, J2, J3 which exist in the Arduino_Mega fixture
        ops = [
            _make_modify_property_op("test.kicad_sch", "J1", "Value", "val1"),
            _make_modify_property_op("test.kicad_sch", "J2", "Value", "val2"),
            _make_modify_property_op("test.kicad_sch", "J3", "Value", "val3"),
        ]

        executor = OperationExecutor(base_dir=tmp_path)

        with patch(
            "kicad_agent.ops.batch_executor.serialize_schematic",
            side_effect=lambda pr, fp, **kwargs: __import__(
                "kicad_agent.serializer", fromlist=["serialize_schematic"]
            ).serialize_schematic(pr, fp, **kwargs),
        ) as mock_serialize:
            result = executor.execute_batch(ops)

        assert result["success"] is True
        assert mock_serialize.call_count == 1

    def test_returns_results_for_all_operations(self, tmp_path: Path) -> None:
        """Batch result contains one result dict per operation."""
        _copy_arduino_fixture(tmp_path)

        ops = [
            _make_modify_property_op("test.kicad_sch", "J1", "Value", "val1"),
            _make_modify_property_op("test.kicad_sch", "J2", "Value", "val2"),
            _make_modify_property_op("test.kicad_sch", "J3", "Value", "val3"),
        ]

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch(ops)

        assert result["success"] is True
        assert len(result["results"]) == 3
        for r in result["results"]:
            assert r["success"] is True
            assert r["operation"] == "modify_property"

    def test_rejects_batch_with_nonexistent_target(self, tmp_path: Path) -> None:
        """Batch with an op targeting a nonexistent file is rejected."""
        ops = [
            _make_modify_property_op("nonexistent.kicad_sch", "J1", "Value", "val"),
        ]

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch(ops)

        assert result["success"] is False
        assert "validation_errors" in result

    def test_reports_all_validation_errors(self, tmp_path: Path) -> None:
        """Reports ALL validation errors, not just the first one."""
        ops = [
            _make_modify_property_op("missing_a.kicad_sch", "J1", "Value", "a"),
            _make_modify_property_op("missing_b.kicad_sch", "J2", "Value", "b"),
        ]

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch(ops)

        assert result["success"] is False
        errors = result["validation_errors"]
        assert len(errors) >= 2

    def test_rejects_batch_containing_create_ops(self, tmp_path: Path) -> None:
        """Batch rejects create operations."""
        create_op = Operation.model_validate({
            "root": {
                "op_type": "create_schematic",
                "target_file": "new.kicad_sch",
            }
        })
        ops = [create_op]

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch(ops)

        assert result["success"] is False
        assert "create_schematic" in result["error"]

    def test_rejects_batch_containing_cross_file_ops(self, tmp_path: Path) -> None:
        """Batch rejects cross-file operations."""
        cross_op = Operation.model_validate({
            "root": {
                "op_type": "propagate_symbol_change",
                "target_file": "test.kicad_sch",
                "target_files": ["test.kicad_sch"],
                "old_lib_id": "Old:Sym",
                "new_lib_id": "New:Sym",
            }
        })
        ops = [cross_op]

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch(ops)

        assert result["success"] is False
        assert "propagate_symbol_change" in result["error"]

    def test_groups_ops_by_target_file(self, tmp_path: Path) -> None:
        """Ops targeting different files are grouped correctly."""
        fixture = Path(__file__).parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
        file_a = tmp_path / "a.kicad_sch"
        file_b = tmp_path / "b.kicad_sch"
        shutil.copy2(fixture, file_a)
        shutil.copy2(fixture, file_b)

        ops = [
            _make_validate_refs_op("a.kicad_sch"),
            _make_validate_refs_op("a.kicad_sch"),
            _make_validate_refs_op("b.kicad_sch"),
        ]

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch(ops)

        assert result["success"] is True
        assert len(result["results"]) == 3

    def test_uses_cache_if_executor_has_cache(self, tmp_path: Path) -> None:
        """Batch uses cached parse result when executor has a cache."""
        _copy_arduino_fixture(tmp_path)

        cache = IRCache()
        executor = OperationExecutor(base_dir=tmp_path, cache=cache)

        ops = [
            _make_validate_refs_op("test.kicad_sch"),
            _make_validate_refs_op("test.kicad_sch"),
        ]

        with patch(
            "kicad_agent.ops.batch_executor.parse_schematic",
            side_effect=lambda p: __import__(
                "kicad_agent.parser", fromlist=["parse_schematic"]
            ).parse_schematic(p),
        ) as mock_parse:
            result = executor.execute_batch(ops)

        assert result["success"] is True
        # Should parse once (cache miss on first access, cache was empty)
        assert mock_parse.call_count == 1

    def test_rolls_back_all_mutations_if_serialization_fails(
        self, tmp_path: Path
    ) -> None:
        """If serialization fails, all mutations on that file are rolled back."""
        _copy_arduino_fixture(tmp_path)

        # Read original content to verify rollback
        original = (tmp_path / "test.kicad_sch").read_text(encoding="utf-8")

        ops = [
            _make_modify_property_op("test.kicad_sch", "J1", "Value", "val1"),
            _make_modify_property_op("test.kicad_sch", "J2", "Value", "val2"),
        ]

        executor = OperationExecutor(base_dir=tmp_path)

        with patch(
            "kicad_agent.ops.batch_executor.serialize_schematic",
            side_effect=RuntimeError("serialization failed"),
        ):
            with pytest.raises(RuntimeError, match="serialization failed"):
                executor.execute_batch(ops)

        # File content should be restored to original (Transaction rollback)
        current = (tmp_path / "test.kicad_sch").read_text(encoding="utf-8")
        assert current == original


# ---------------------------------------------------------------------------
# TestBatchPerformance
# ---------------------------------------------------------------------------


class TestBatchPerformance:
    """Performance benchmarks for execute_batch()."""

    def test_100_modify_property_ops_completes_under_10s(
        self, tmp_path: Path
    ) -> None:
        """100 modify_property ops on Arduino_Mega.kicad_sch completes in <10s."""
        _copy_arduino_fixture(tmp_path)

        # Build 100 modify_property operations targeting existing refs J1-J7
        # Cycle through the available references
        valid_refs = ["J1", "J2", "J3", "J4", "J5", "J6", "J7"]
        ops = []
        for i in range(100):
            ops.append(
                _make_modify_property_op(
                    "test.kicad_sch",
                    valid_refs[i % len(valid_refs)],
                    "Value",
                    f"component_{i}",
                )
            )

        executor = OperationExecutor(base_dir=tmp_path)
        start = time.perf_counter()
        result = executor.execute_batch(ops)
        elapsed = time.perf_counter() - start

        assert result["success"] is True
        assert len(result["results"]) == 100
        assert elapsed < 10.0, f"Batch took {elapsed:.2f}s, expected <10s"


# ---------------------------------------------------------------------------
# TestBatchDependencyValidation
# ---------------------------------------------------------------------------


class TestBatchDependencyValidation:
    """Tests for dependency validation in execute_batch()."""

    def test_batch_rejects_missing_prerequisite(self, tmp_path: Path) -> None:
        """Batch with connect_pins but no resolve_pin_positions is rejected."""
        _copy_arduino_fixture(tmp_path)

        connect_op = Operation.model_validate({
            "root": {
                "op_type": "connect_pins",
                "target_file": "test.kicad_sch",
                "net_name": "GND",
                "pins": [{"ref": "J1", "pin": "1"}],
            }
        })

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch([connect_op])

        assert result["success"] is False
        assert "missing_prerequisites" in result
        assert "resolve_pin_positions" in result["missing_prerequisites"]

    def test_batch_accepts_satisfied_prerequisite(self, tmp_path: Path) -> None:
        """Batch with prerequisite before dependent op succeeds."""
        _copy_arduino_fixture(tmp_path)

        resolve_op = Operation.model_validate({
            "root": {
                "op_type": "resolve_pin_positions",
                "target_file": "test.kicad_sch",
            }
        })
        connect_op = Operation.model_validate({
            "root": {
                "op_type": "connect_pins",
                "target_file": "test.kicad_sch",
                "net_name": "GND",
                "pins": [{"ref": "J1", "pin": "1"}],
            }
        })

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch([resolve_op, connect_op])

        # Should not be rejected for dependency reasons
        # (may fail for other reasons like missing connections, but not deps)
        assert "missing_prerequisites" not in result

    def test_batch_rejects_conflict_pair(self, tmp_path: Path) -> None:
        """Batch with repair_schematic after remove_component is rejected."""
        _copy_arduino_fixture(tmp_path)

        # repair_schematic requires parse_erc, so include it first
        parse_op = Operation.model_validate({
            "root": {
                "op_type": "parse_erc",
                "target_file": "test.kicad_sch",
            }
        })
        remove_op = Operation.model_validate({
            "root": {
                "op_type": "remove_component",
                "target_file": "test.kicad_sch",
                "reference": "J1",
            }
        })
        repair_op = Operation.model_validate({
            "root": {
                "op_type": "repair_schematic",
                "target_file": "test.kicad_sch",
            }
        })

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch([parse_op, remove_op, repair_op])

        assert result["success"] is False
        # Conflict detected because repair_schematic conflicts with remove_component
        assert "conflict" in str(result.get("validation_errors", result.get("error", ""))).lower() or "conflict" in result.get("error", "").lower()

    def test_batch_rejects_multi_file_scope_ops(self, tmp_path: Path) -> None:
        """Batch rejects ops with multi_file scope."""
        # array_replicate has multi_file scope
        array_op = Operation.model_validate({
            "root": {
                "op_type": "array_replicate",
                "target_file": "test.kicad_sch",
                "source_reference": "J1",
                "pattern": "linear",
                "count": 2,
                "spacing": {"x": 5.0, "y": 0.0},
            }
        })

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch([array_op])

        assert result["success"] is False
        assert "array_replicate" in result["error"]

    def test_batch_rejects_erc_auto_fix_without_parse_erc(self, tmp_path: Path) -> None:
        """Batch with erc_auto_fix but no parse_erc is rejected."""
        _copy_arduino_fixture(tmp_path)

        erc_fix_op = Operation.model_validate({
            "root": {
                "op_type": "erc_auto_fix",
                "target_file": "test.kicad_sch",
            }
        })

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch([erc_fix_op])

        assert result["success"] is False
        assert "parse_erc" in result["missing_prerequisites"]

    def test_dependency_error_includes_prerequisite_names(self, tmp_path: Path) -> None:
        """Dependency error message names the specific missing prerequisites."""
        _copy_arduino_fixture(tmp_path)

        connect_op = Operation.model_validate({
            "root": {
                "op_type": "connect_pins",
                "target_file": "test.kicad_sch",
                "net_name": "GND",
                "pins": [{"ref": "J1", "pin": "1"}],
            }
        })

        executor = OperationExecutor(base_dir=tmp_path)
        result = executor.execute_batch([connect_op])

        assert "resolve_pin_positions" in str(result["error"])
