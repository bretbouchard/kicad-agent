"""Operation schema validation tests.

Requirements covered:
  OPS-01: JSON operation schema for all edit intents (Pydantic v2 models).
  OPS-02: Reject structurally invalid intents before mutation.

Security tests:
  Council H-01: target_file path traversal, absolute path, null byte, extension defense.
  Council M-04: String field length constraints.
"""

import pytest
from pydantic import ValidationError

from volta.ops.schema import (
    AddComponentOp,
    ModifyPropertyOp,
    MoveComponentOp,
    Operation,
    PositionSpec,
    RemoveComponentOp,
    ReviewSchematicOp,
    get_operation_schema,
)


# ======================================================================
# TestValidOperations (OPS-01)
# ======================================================================


class TestValidOperations:
    """Verify that structurally valid operation intents are accepted."""

    def test_add_component_valid(self) -> None:
        """A complete add_component intent validates and fields are accessible."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "add_component",
                    "target_file": "test.kicad_sch",
                    "library_id": "Device:R_Small_US",
                    "reference": "R1",
                    "value": "10k",
                    "position": {"x": 10.0, "y": 20.0, "angle": 90.0},
                }
            }
        )
        assert op.root.op_type == "add_component"
        assert op.root.target_file == "test.kicad_sch"
        assert op.root.library_id == "Device:R_Small_US"
        assert op.root.reference == "R1"
        assert op.root.value == "10k"
        assert op.root.position.x == 10.0
        assert op.root.position.y == 20.0
        assert op.root.position.angle == 90.0

    def test_add_component_defaults(self) -> None:
        """add_component with only required fields uses default reference and value."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "add_component",
                    "target_file": "motor.kicad_sch",
                    "library_id": "Device:R",
                    "position": {"x": 5.0, "y": 10.0},
                }
            }
        )
        assert op.root.reference == "R?"
        assert op.root.value == ""
        assert op.root.position.angle == 0.0

    def test_remove_component_valid(self) -> None:
        """A remove_component intent validates correctly."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "remove_component",
                    "target_file": "board.kicad_pcb",
                    "reference": "C1",
                }
            }
        )
        assert op.root.op_type == "remove_component"
        assert op.root.reference == "C1"

    def test_move_component_valid(self) -> None:
        """A move_component intent with position validates correctly."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "move_component",
                    "target_file": "main.kicad_sch",
                    "reference": "U1",
                    "position": {"x": 100.0, "y": 200.0, "angle": 45.0},
                }
            }
        )
        assert op.root.op_type == "move_component"
        assert op.root.position.x == 100.0
        assert op.root.position.angle == 45.0

    def test_modify_property_valid(self) -> None:
        """A modify_property intent with property_name and new_value validates."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "modify_property",
                    "target_file": "power.kicad_sch",
                    "reference": "R2",
                    "property_name": "Value",
                    "new_value": "4.7k",
                }
            }
        )
        assert op.root.op_type == "modify_property"
        assert op.root.property_name == "Value"
        assert op.root.new_value == "4.7k"


# ======================================================================
# TestInvalidOperations (OPS-02)
# ======================================================================


class TestUpdatePcbFromSchematicOp:
    """Verify update_pcb_from_schematic schema validation."""

    def test_valid_minimal(self) -> None:
        """Minimal valid intent with required fields only."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "update_pcb_from_schematic",
                    "target_file": "board.kicad_pcb",
                    "target_files": ["board.kicad_pcb", "root.kicad_sch"],
                }
            }
        )
        assert op.root.op_type == "update_pcb_from_schematic"
        assert op.root.target_file == "board.kicad_pcb"
        assert len(op.root.target_files) == 2
        assert op.root.sync_netlist is True  # default
        assert op.root.sync_footprints is True  # default
        assert op.root.add_new_components is True  # default
        assert op.root.remove_orphans is False  # default

    def test_valid_all_flags(self) -> None:
        """All optional flags set explicitly."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "update_pcb_from_schematic",
                    "target_file": "board.kicad_pcb",
                    "target_files": ["board.kicad_pcb", "root.kicad_sch"],
                    "sync_netlist": False,
                    "sync_footprints": False,
                    "add_new_components": False,
                    "remove_orphans": True,
                }
            }
        )
        assert op.root.sync_netlist is False
        assert op.root.remove_orphans is True

    def test_rejects_missing_schematic(self) -> None:
        """Rejects target_files without a .kicad_sch."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "update_pcb_from_schematic",
                        "target_file": "board.kicad_pcb",
                        "target_files": ["board.kicad_pcb", "other.kicad_pcb"],
                    }
                }
            )

    def test_rejects_missing_pcb(self) -> None:
        """Rejects target_files without a .kicad_pcb."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "update_pcb_from_schematic",
                        "target_file": "board.kicad_pcb",
                        "target_files": ["root.kicad_sch", "other.kicad_sch"],
                    }
                }
            )

    def test_rejects_single_file(self) -> None:
        """Rejects target_files with only one entry."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "update_pcb_from_schematic",
                        "target_file": "board.kicad_pcb",
                        "target_files": ["board.kicad_pcb"],
                    }
                }
            )

    def test_rejects_path_traversal(self) -> None:
        """Rejects path traversal in target_files (Council H-01)."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "update_pcb_from_schematic",
                        "target_file": "board.kicad_pcb",
                        "target_files": ["board.kicad_pcb", "../evil.kicad_sch"],
                    }
                }
            )


class TestInvalidOperations:
    """Verify that structurally invalid intents raise ValidationError."""

    def test_missing_target_file(self) -> None:
        """An intent without target_file is rejected."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "add_component",
                        "library_id": "Device:R",
                        "position": {"x": 1.0, "y": 2.0},
                    }
                }
            )

    def test_missing_required_field(self) -> None:
        """add_component without library_id is rejected."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "add_component",
                        "target_file": "test.kicad_sch",
                        "position": {"x": 1.0, "y": 2.0},
                    }
                }
            )

    def test_invalid_op_type(self) -> None:
        """An unknown op_type value is rejected."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "invalid_type",
                        "target_file": "test.kicad_sch",
                    }
                }
            )

    def test_empty_intent(self) -> None:
        """An empty root dict is rejected."""
        with pytest.raises(ValidationError):
            Operation.model_validate({"root": {}})

    def test_path_traversal_rejected(self) -> None:
        """target_file with '..' path traversal is rejected (Council H-01)."""
        with pytest.raises(ValidationError, match="traversal"):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "add_component",
                        "target_file": "../../etc/passwd",
                        "library_id": "Device:R",
                        "position": {"x": 1.0, "y": 2.0},
                    }
                }
            )

    def test_absolute_path_rejected(self) -> None:
        """target_file with absolute path is rejected (Council H-01)."""
        with pytest.raises(ValidationError, match="relative"):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "add_component",
                        "target_file": "/tmp/test.kicad_sch",
                        "library_id": "Device:R",
                        "position": {"x": 1.0, "y": 2.0},
                    }
                }
            )

    def test_null_byte_rejected(self) -> None:
        """target_file with null byte is rejected (Council H-01)."""
        with pytest.raises(ValidationError, match="null"):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "add_component",
                        "target_file": "test\x00.kicad_sch",
                        "library_id": "Device:R",
                        "position": {"x": 1.0, "y": 2.0},
                    }
                }
            )

    def test_non_kicad_extension_rejected(self) -> None:
        """target_file with non-KiCad extension is rejected (Council H-01)."""
        with pytest.raises(ValidationError, match="KiCad file type"):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "add_component",
                        "target_file": "test.txt",
                        "library_id": "Device:R",
                        "position": {"x": 1.0, "y": 2.0},
                    }
                }
            )

    def test_oversized_field_rejected(self) -> None:
        """An oversized reference field (1000 chars) exceeds max_length (Council M-04)."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "add_component",
                        "target_file": "test.kicad_sch",
                        "library_id": "Device:R",
                        "reference": "R" * 1000,
                        "position": {"x": 1.0, "y": 2.0},
                    }
                }
            )

    def test_empty_library_id_rejected(self) -> None:
        """An empty library_id violates min_length=1 constraint (Council M-04)."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "add_component",
                        "target_file": "test.kicad_sch",
                        "library_id": "",
                        "position": {"x": 1.0, "y": 2.0},
                    }
                }
            )


# ======================================================================
# TestSchemaExport (OPS-01, D-04)
# ======================================================================


class TestSchemaExport:
    """Verify JSON Schema export for LLM consumption (D-04)."""

    def test_json_schema_export(self) -> None:
        """get_operation_schema() returns a dict with schema structure."""
        schema = get_operation_schema()
        assert isinstance(schema, dict)
        assert "$defs" in schema or "properties" in schema

    def test_schema_contains_all_op_types(self) -> None:
        """The exported schema references all four operation type literals."""
        schema = get_operation_schema()
        schema_str = str(schema)
        for op_type in (
            "add_component",
            "remove_component",
            "move_component",
            "modify_property",
        ):
            assert op_type in schema_str, f"op_type '{op_type}' not found in schema"

    def test_schema_has_field_descriptions(self) -> None:
        """At least one field in the schema has a description (Pydantic Field descriptions)."""
        schema = get_operation_schema()
        schema_str = str(schema)
        assert "description" in schema_str, "No field descriptions found in schema"


# ======================================================================
# TestPositionSpec
# ======================================================================


class TestPositionSpec:
    """Verify PositionSpec defaults and construction."""

    def test_position_defaults(self) -> None:
        """PositionSpec defaults angle to 0.0 when omitted."""
        pos = PositionSpec(x=1.0, y=2.0)
        assert pos.x == 1.0
        assert pos.y == 2.0
        assert pos.angle == 0.0

    def test_position_with_angle(self) -> None:
        """PositionSpec accepts an explicit angle."""
        pos = PositionSpec(x=1.0, y=2.0, angle=90.0)
        assert pos.angle == 90.0


# ======================================================================
# TestReviewSchematicOp (schema fix: op_type + target_file)
# ======================================================================


class TestReviewSchematicOp:
    """Verify ReviewSchematicOp validates through Operation union."""

    def test_valid_minimal(self) -> None:
        """review_schematic with only target_file validates and uses defaults."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "review_schematic",
                    "target_file": "test.kicad_sch",
                }
            }
        )
        assert op.root.op_type == "review_schematic"
        assert op.root.target_file == "test.kicad_sch"
        assert op.root.vision is False
        assert op.root.output_format == "markdown"
        assert op.root.config_path is None

    def test_valid_all_fields(self) -> None:
        """review_schematic with all fields validates correctly."""
        op = Operation.model_validate(
            {
                "root": {
                    "op_type": "review_schematic",
                    "target_file": "board.kicad_sch",
                    "vision": True,
                    "output_format": "json",
                    "config_path": "/tmp/rules.yaml",
                }
            }
        )
        assert op.root.vision is True
        assert op.root.output_format == "json"
        assert op.root.config_path == "/tmp/rules.yaml"

    def test_direct_class_instantiation(self) -> None:
        """ReviewSchematicOp can be instantiated directly."""
        op = ReviewSchematicOp(target_file="sch.kicad_sch")
        assert op.op_type == "review_schematic"
        assert op.target_file == "sch.kicad_sch"

    def test_old_field_names_rejected(self) -> None:
        """Old field names (operation_type, file_path) are rejected."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "operation_type": "review_schematic",
                        "file_path": "test.kicad_sch",
                    }
                }
            )

    def test_target_file_validation_applies(self) -> None:
        """Path traversal in target_file is rejected (Council H-01)."""
        with pytest.raises(ValidationError, match="traversal"):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "review_schematic",
                        "target_file": "../../etc/passwd",
                    }
                }
            )

    def test_missing_target_file_rejected(self) -> None:
        """Missing target_file is rejected."""
        with pytest.raises(ValidationError):
            Operation.model_validate(
                {
                    "root": {
                        "op_type": "review_schematic",
                    }
                }
            )

    def test_schema_export_includes_review_schematic(self) -> None:
        """review_schematic appears in exported JSON schema."""
        schema = get_operation_schema()
        assert "review_schematic" in str(schema)
