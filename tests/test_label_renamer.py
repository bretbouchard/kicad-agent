"""Tests for label_renamer -- rename label text objects across a schematic.

Covers: label finding by name/type, rename logic, safety warnings for
existing names, dry_run behavior, schema validation, and handler dispatch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from volta.ops.label_renamer import (
    _find_labels_by_name,
    rename_net_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_label(text: str, x: float = 10.0, y: float = 20.0, angle: float = 0.0) -> MagicMock:
    """Create a mock label object with text and position."""
    lbl = MagicMock()
    lbl.text = text
    lbl.position = MagicMock()
    lbl.position.X = x
    lbl.position.Y = y
    lbl.position.angle = angle
    return lbl


def _make_mock_ir(
    labels: list | None = None,
    global_labels: list | None = None,
    hierarchical_labels: list | None = None,
) -> MagicMock:
    """Create a mock SchematicIR with label lists."""
    ir = MagicMock()
    ir.schematic.labels = labels or []
    ir.schematic.globalLabels = global_labels or []
    ir.schematic.hierarchicalLabels = hierarchical_labels or []
    ir._record_mutation = MagicMock()
    return ir


# ---------------------------------------------------------------------------
# _find_labels_by_name
# ---------------------------------------------------------------------------

class TestFindLabelsByName:
    """Tests for _find_labels_by_name."""

    def test_finds_local_labels(self) -> None:
        lbl = _make_mock_label("SIG_A")
        ir = _make_mock_ir(labels=[lbl])
        matches = _find_labels_by_name(ir, "SIG_A", "label")
        assert len(matches) == 1
        assert matches[0]["type"] == "label"
        assert matches[0]["position"] == [10.0, 20.0]

    def test_finds_global_labels(self) -> None:
        lbl = _make_mock_label("VCC")
        ir = _make_mock_ir(global_labels=[lbl])
        matches = _find_labels_by_name(ir, "VCC", "global")
        assert len(matches) == 1
        assert matches[0]["type"] == "global"

    def test_finds_hierarchical_labels(self) -> None:
        lbl = _make_mock_label("H_NET")
        ir = _make_mock_ir(hierarchical_labels=[lbl])
        matches = _find_labels_by_name(ir, "H_NET", "hierarchical")
        assert len(matches) == 1
        assert matches[0]["type"] == "hierarchical"

    def test_all_finds_all_types(self) -> None:
        local = _make_mock_label("NET_X")
        glob = _make_mock_label("NET_X", x=50.0)
        hier = _make_mock_label("NET_X", x=100.0)
        ir = _make_mock_ir(labels=[local], global_labels=[glob], hierarchical_labels=[hier])
        matches = _find_labels_by_name(ir, "NET_X", "all")
        assert len(matches) == 3
        types = {m["type"] for m in matches}
        assert types == {"label", "global", "hierarchical"}

    def test_no_match_returns_empty(self) -> None:
        ir = _make_mock_ir(labels=[_make_mock_label("OTHER")])
        matches = _find_labels_by_name(ir, "NONEXIST", "all")
        assert matches == []

    def test_filters_by_name(self) -> None:
        lbl_a = _make_mock_label("SIG_A")
        lbl_b = _make_mock_label("SIG_B")
        ir = _make_mock_ir(labels=[lbl_a, lbl_b])
        matches = _find_labels_by_name(ir, "SIG_A", "all")
        assert len(matches) == 1
        assert matches[0]["label"].text == "SIG_A"

    def test_returns_label_reference(self) -> None:
        lbl = _make_mock_label("REF")
        ir = _make_mock_ir(labels=[lbl])
        matches = _find_labels_by_name(ir, "REF", "label")
        assert matches[0]["label"] is lbl

    def test_specific_type_ignores_others(self) -> None:
        local = _make_mock_label("NET")
        glob = _make_mock_label("NET")
        ir = _make_mock_ir(labels=[local], global_labels=[glob])
        matches = _find_labels_by_name(ir, "NET", "label")
        assert len(matches) == 1
        assert matches[0]["type"] == "label"

    def test_angle_defaults_to_zero(self) -> None:
        lbl = _make_mock_label("NET")
        del lbl.position.angle  # no angle attribute
        ir = _make_mock_ir(labels=[lbl])
        matches = _find_labels_by_name(ir, "NET", "label")
        assert matches[0]["angle"] == 0.0

    def test_captures_angle(self) -> None:
        lbl = _make_mock_label("NET", angle=90.0)
        ir = _make_mock_ir(labels=[lbl])
        matches = _find_labels_by_name(ir, "NET", "label")
        assert matches[0]["angle"] == 90.0


# ---------------------------------------------------------------------------
# rename_net_label
# ---------------------------------------------------------------------------

class TestRenameNetLabel:
    """Tests for rename_net_label."""

    def test_renames_single_label(self) -> None:
        lbl = _make_mock_label("OLD")
        ir = _make_mock_ir(labels=[lbl])
        result = rename_net_label(ir, Path("test.kicad_sch"), old_name="OLD", new_name="NEW")
        assert result["renamed"] == 1
        assert lbl.text == "NEW"

    def test_renames_multiple_labels(self) -> None:
        lbl1 = _make_mock_label("SIG")
        lbl2 = _make_mock_label("SIG", x=30.0)
        lbl3 = _make_mock_label("SIG", x=50.0)
        ir = _make_mock_ir(labels=[lbl1, lbl2, lbl3])
        result = rename_net_label(ir, Path("test.kicad_sch"), old_name="SIG", new_name="SIG_RENAMED")
        assert result["renamed"] == 3
        assert all(lbl.text == "SIG_RENAMED" for lbl in [lbl1, lbl2, lbl3])

    def test_records_mutations(self) -> None:
        lbl = _make_mock_label("A")
        ir = _make_mock_ir(labels=[lbl])
        rename_net_label(ir, Path("test.kicad_sch"), old_name="A", new_name="B")
        ir._record_mutation.assert_called_once()
        call_args = ir._record_mutation.call_args
        assert call_args[0][0] == "rename_net_label"
        mutation_data = call_args[0][1]
        assert mutation_data["old_name"] == "A"
        assert mutation_data["new_name"] == "B"
        assert mutation_data["type"] == "label"

    def test_no_match_returns_zero(self) -> None:
        ir = _make_mock_ir(labels=[])
        result = rename_net_label(ir, Path("test.kicad_sch"), old_name="NONE", new_name="NEW")
        assert result["renamed"] == 0
        assert result["locations"] == []
        assert "No labels found" in result["warnings"][0]

    def test_warns_if_new_name_exists(self) -> None:
        old_lbl = _make_mock_label("SIG_A")
        new_lbl = _make_mock_label("SIG_B")
        ir = _make_mock_ir(labels=[old_lbl, new_lbl])
        result = rename_net_label(ir, Path("test.kicad_sch"), old_name="SIG_A", new_name="SIG_B")
        assert result["renamed"] == 1
        assert len(result["warnings"]) == 1
        assert "SIG_B" in result["warnings"][0]
        assert "already exists" in result["warnings"][0]

    def test_no_warning_when_new_name_unique(self) -> None:
        lbl = _make_mock_label("OLD")
        ir = _make_mock_ir(labels=[lbl])
        result = rename_net_label(ir, Path("test.kicad_sch"), old_name="OLD", new_name="BRAND_NEW")
        assert result["warnings"] == []

    def test_dry_run_reports_without_modifying(self) -> None:
        lbl = _make_mock_label("SIG")
        ir = _make_mock_ir(labels=[lbl])
        result = rename_net_label(
            ir, Path("test.kicad_sch"),
            old_name="SIG", new_name="SIG_NEW", dry_run=True,
        )
        assert result["renamed"] == 0
        assert result["dry_run"] is True
        assert len(result["locations"]) == 1
        assert lbl.text == "SIG"  # unchanged
        ir._record_mutation.assert_not_called()

    def test_dry_run_with_existing_warning(self) -> None:
        old_lbl = _make_mock_label("A")
        existing_lbl = _make_mock_label("B")
        ir = _make_mock_ir(labels=[old_lbl, existing_lbl])
        result = rename_net_label(
            ir, Path("test.kicad_sch"),
            old_name="A", new_name="B", dry_run=True,
        )
        assert len(result["warnings"]) == 1

    def test_location_details(self) -> None:
        lbl = _make_mock_label("X", x=42.0, y=17.5, angle=180.0)
        ir = _make_mock_ir(labels=[lbl])
        result = rename_net_label(ir, Path("test.kicad_sch"), old_name="X", new_name="Y")
        loc = result["locations"][0]
        assert loc["type"] == "label"
        assert loc["position"] == [42.0, 17.5]
        assert loc["angle"] == 180.0
        assert loc["old_name"] == "X"
        assert loc["new_name"] == "Y"

    def test_label_type_filter_local_only(self) -> None:
        local = _make_mock_label("NET")
        glob = _make_mock_label("NET")
        ir = _make_mock_ir(labels=[local], global_labels=[glob])
        result = rename_net_label(
            ir, Path("test.kicad_sch"),
            old_name="NET", new_name="NET2", label_type="label",
        )
        assert result["renamed"] == 1
        assert glob.text == "NET"  # unchanged

    def test_label_type_filter_global_only(self) -> None:
        local = _make_mock_label("NET")
        glob = _make_mock_label("NET")
        ir = _make_mock_ir(labels=[local], global_labels=[glob])
        result = rename_net_label(
            ir, Path("test.kicad_sch"),
            old_name="NET", new_name="NET2", label_type="global",
        )
        assert result["renamed"] == 1
        assert local.text == "NET"  # unchanged

    def test_label_type_filter_hierarchical_only(self) -> None:
        hier = _make_mock_label("NET")
        ir = _make_mock_ir(hierarchical_labels=[hier])
        result = rename_net_label(
            ir, Path("test.kicad_sch"),
            old_name="NET", new_name="NET2", label_type="hierarchical",
        )
        assert result["renamed"] == 1
        assert hier.text == "NET2"

    def test_returns_old_and_new_names(self) -> None:
        lbl = _make_mock_label("SIG_A")
        ir = _make_mock_ir(labels=[lbl])
        result = rename_net_label(ir, Path("test.kicad_sch"), old_name="SIG_A", new_name="SIG_B")
        assert result["old_name"] == "SIG_A"
        assert result["new_name"] == "SIG_B"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestRenameNetLabelOpSchema:
    """Tests for RenameNetLabelOp Pydantic schema."""

    def test_default_fields(self) -> None:
        from volta.ops._schema_wire import RenameNetLabelOp
        op = RenameNetLabelOp(
            target_file="test.kicad_sch",
            old_name="OLD",
            new_name="NEW",
        )
        assert op.op_type == "rename_net_label"
        assert op.label_type == "all"
        assert op.dry_run is False

    def test_all_fields(self) -> None:
        from volta.ops._schema_wire import RenameNetLabelOp
        op = RenameNetLabelOp(
            target_file="test.kicad_sch",
            old_name="A",
            new_name="B",
            label_type="global",
            dry_run=True,
        )
        assert op.label_type == "global"
        assert op.dry_run is True

    @pytest.mark.parametrize("lt", ["label", "global", "hierarchical", "all"])
    def test_valid_label_types(self, lt: str) -> None:
        from volta.ops._schema_wire import RenameNetLabelOp
        op = RenameNetLabelOp(
            target_file="test.kicad_sch",
            old_name="X",
            new_name="Y",
            label_type=lt,
        )
        assert op.label_type == lt

    def test_invalid_label_type_rejected(self) -> None:
        from volta.ops._schema_wire import RenameNetLabelOp
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            RenameNetLabelOp(
                target_file="test.kicad_sch",
                old_name="X",
                new_name="Y",
                label_type="power",
            )

    def test_empty_old_name_rejected(self) -> None:
        from volta.ops._schema_wire import RenameNetLabelOp
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            RenameNetLabelOp(
                target_file="test.kicad_sch",
                old_name="",
                new_name="Y",
            )

    def test_unsafe_chars_rejected(self) -> None:
        from volta.ops._schema_wire import RenameNetLabelOp
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            RenameNetLabelOp(
                target_file="test.kicad_sch",
                old_name='label"with"quotes',
                new_name="valid",
            )


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------

class TestHandlerDispatch:
    """Tests for handler registration and dispatch."""

    def test_handler_registered(self) -> None:
        from volta.ops.handlers.schematic import _SCHEMATIC_HANDLERS
        assert "rename_net_label" in _SCHEMATIC_HANDLERS

    def test_handler_calls_rename_net_label(self) -> None:
        from volta.ops.handlers.schematic import _SCHEMATIC_HANDLERS
        handler = _SCHEMATIC_HANDLERS["rename_net_label"]
        lbl = _make_mock_label("OLD")
        ir = _make_mock_ir(labels=[lbl])
        op = MagicMock()
        op.old_name = "OLD"
        op.new_name = "NEW"
        op.label_type = "all"
        op.dry_run = False
        result = handler(op, ir, Path("test.kicad_sch"))
        assert result["renamed"] == 1
        assert lbl.text == "NEW"
