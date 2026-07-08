"""Tests for add_design_note op (kicad-agent-29).

Design notes annotate schematics with WHY/WHAT/HOW intent. Verifies:
- Op validates against schema
- Op dispatches via handle_operation (matches existing executor patterns)
- Schematic serializes correctly after mutation
- Note text contains prefixed note_type + target_ref for grep-ability

Pattern mirrors tests/test_executor_ops.py::test_add_no_connect_executor.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kicad_agent.ops.schema import Operation
from kicad_agent.result import OperationResult
from kicad_agent.handler import handle_operation


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "Arduino_Mega"
FIXTURE_SCH = "Arduino_Mega.kicad_sch"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project with a copy of the Arduino_Mega fixture."""
    sch_src = FIXTURE_DIR / FIXTURE_SCH
    sch_dst = tmp_path / FIXTURE_SCH
    shutil.copy2(sch_src, sch_dst)
    return tmp_path


class TestAddDesignNoteSchema:
    """Pydantic schema validation."""

    def test_minimal_op_validates(self) -> None:
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_note",
                "target_file": FIXTURE_SCH,
                "text": "10uA/oct",
                "position": {"x": 100.0, "y": 50.0},
            }
        })
        assert op.root.op_type == "add_design_note"
        assert op.root.note_type == "NOTE"  # default
        assert op.root.target_ref is None  # default
        assert op.root.font_size_mm == 1.27  # default

    def test_full_op_validates(self) -> None:
        op = Operation.model_validate({
            "root": {
                "op_type": "add_design_note",
                "target_file": FIXTURE_SCH,
                "text": "2.5/55000=45.5 [uA] + 5/1000000=5 [uA]",
                "position": {"x": 100.0, "y": 50.0, "angle": 0},
                "note_type": "MATH",
                "target_ref": "R7",
                "font_size_mm": 2.0,
            }
        })
        assert op.root.note_type == "MATH"
        assert op.root.target_ref == "R7"
        assert op.root.font_size_mm == 2.0

    def test_rejects_invalid_note_type(self) -> None:
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "add_design_note",
                    "target_file": FIXTURE_SCH,
                    "text": "x",
                    "position": {"x": 0, "y": 0},
                    "note_type": "INVALID",
                }
            })

    def test_rejects_empty_text(self) -> None:
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "add_design_note",
                    "target_file": FIXTURE_SCH,
                    "text": "",
                    "position": {"x": 0, "y": 0},
                }
            })

    def test_rejects_negative_font_size(self) -> None:
        with pytest.raises(Exception):
            Operation.model_validate({
                "root": {
                    "op_type": "add_design_note",
                    "target_file": FIXTURE_SCH,
                    "text": "x",
                    "position": {"x": 0, "y": 0},
                    "font_size_mm": -1.0,
                }
            })


@pytest.mark.integration
class TestAddDesignNoteExecutor:
    """Full executor dispatch via handle_operation — mirrors existing op tests."""

    def test_add_note_executor_dispatches_and_serializes(self, project_dir: Path) -> None:
        """add_design_note dispatches through OperationExecutor and writes note."""
        op_json = json.dumps({
            "op_type": "add_design_note",
            "target_file": FIXTURE_SCH,
            "text": "HF tracking: 2N3904 Rb=1k compensates 1kHz-8kHz droop",
            "position": {"x": 100.0, "y": 60.0},
            "note_type": "REASON",
            "target_ref": "Q3",
        })
        result = handle_operation(op_json, project_dir=project_dir)
        assert isinstance(result, OperationResult)
        assert result.success, f"Executor failed: {result.error}"
        assert result.operation_type == "add_design_note"

        # File written with the note text — verify each prefix appears.
        written = (project_dir / FIXTURE_SCH).read_text()
        assert "[REASON]" in written
        assert "@Q3" in written
        assert "HF tracking" in written

    def test_block_header_dispatches(self, project_dir: Path) -> None:
        """BLOCK_HEADER note type with no target_ref."""
        op_json = json.dumps({
            "op_type": "add_design_note",
            "target_file": FIXTURE_SCH,
            "text": "EXPONENTIAL CONVERTER CVs",
            "position": {"x": 25.0, "y": 75.0},
            "note_type": "BLOCK_HEADER",
        })
        result = handle_operation(op_json, project_dir=project_dir)
        assert result.success
        written = (project_dir / FIXTURE_SCH).read_text()
        assert "[BLOCK_HEADER] EXPONENTIAL CONVERTER CVs" in written

    def test_math_note_with_target_ref(self, project_dir: Path) -> None:
        """MATH note with target_ref — derives a result, ties to specific part."""
        op_json = json.dumps({
            "op_type": "add_design_note",
            "target_file": FIXTURE_SCH,
            "text": "2.5/55000=45.5 [uA] + 5/1000000=5 [uA]",
            "position": {"x": 50.0, "y": 50.0},
            "note_type": "MATH",
            "target_ref": "R7",
            "font_size_mm": 1.5,
        })
        result = handle_operation(op_json, project_dir=project_dir)
        assert result.success
        written = (project_dir / FIXTURE_SCH).read_text()
        assert "[MATH] @R7 2.5/55000=45.5" in written

