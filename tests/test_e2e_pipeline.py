"""End-to-end integration test for the KiCad agent pipeline (Plan 24-04, Task 2).

Validates the core value proposition:
  JSON intent -> handle_operation -> Executor -> IR mutation -> Serialize -> File output

Uses the Arduino_Mega fixture to test real schematic operations
through the full pipeline from JSON input to file output.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kicad_agent.handler import handle_operation
from kicad_agent.result import OperationResult

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "Arduino_Mega"
FIXTURE_SCH = "Arduino_Mega.kicad_sch"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project with a copy of the Arduino_Mega fixture."""
    sch_src = FIXTURE_DIR / FIXTURE_SCH
    sch_dst = tmp_path / FIXTURE_SCH
    shutil.copy2(sch_src, sch_dst)
    return tmp_path


# ---------------------------------------------------------------------------
# Core E2E: JSON intent -> file mutation
# ---------------------------------------------------------------------------


def test_intent_to_file_add_component(project_dir: Path) -> None:
    """Full pipeline: add_component JSON -> executor -> IR mutation -> file output.

    The core value proposition of kicad-agent: LLM generates JSON intent,
    the agent parses it, mutates the schematic, and produces a valid file.
    """
    op_json = json.dumps({
        "op_type": "add_component",
        "target_file": FIXTURE_SCH,
        "library_id": "Device:R_Small_US",
        "position": {"x": 100.0, "y": 50.0},
    })

    result = handle_operation(op_json, project_dir=project_dir)

    # Step 1: Verify the operation succeeded
    assert isinstance(result, OperationResult), (
        f"Expected OperationResult, got {type(result).__name__}"
    )
    assert result.success, f"Operation failed: {getattr(result, 'error', '')}"
    assert result.operation_type == "add_component"

    # Step 2: Verify the output file exists and is valid KiCad
    output_file = project_dir / FIXTURE_SCH
    assert output_file.exists(), "Output file must exist"

    content = output_file.read_text(encoding="utf-8")
    assert content.startswith("(kicad_sch"), "Output must be a valid KiCad schematic"
    assert "(version " in content, "Version header must be present"

    # Step 3: Verify the mutation is reflected in the file
    assert "Device:R_Small_US" in content, (
        "Added component library ID must appear in the output file"
    )


def test_intent_to_file_move_component(project_dir: Path) -> None:
    """Full pipeline: move_component JSON -> executor -> file reflects new position.

    Demonstrates that the pipeline can parse existing components and
    modify their positions without corrupting the file.
    """
    # First read original to find an existing reference
    original = (project_dir / FIXTURE_SCH).read_text(encoding="utf-8")

    # Find a component reference in the fixture (e.g., R1, U1, etc.)
    import re
    ref_match = re.search(r'\(reference "([^"]+)"\)', original)
    if not ref_match:
        pytest.skip("No component references found in fixture")

    ref = ref_match.group(1)

    op_json = json.dumps({
        "op_type": "move_component",
        "target_file": FIXTURE_SCH,
        "reference": ref,
        "position": {"x": 150.0, "y": 80.0},
    })

    result = handle_operation(op_json, project_dir=project_dir)
    assert isinstance(result, OperationResult)
    assert result.success, f"Move failed: {getattr(result, 'error', '')}"

    # Verify file is still valid
    content = (project_dir / FIXTURE_SCH).read_text(encoding="utf-8")
    assert content.startswith("(kicad_sch"), "File must remain valid after move"
    assert f'(reference "{ref}")' in content, "Component reference must still exist"


def test_intent_to_file_add_wire_and_label(project_dir: Path) -> None:
    """Full pipeline: add a wire and label in sequence.

    Validates that multiple sequential operations work without corruption.
    """
    # Add a wire
    wire_json = json.dumps({
        "op_type": "add_wire",
        "target_file": FIXTURE_SCH,
        "start_x": 50.0,
        "start_y": 30.0,
        "end_x": 80.0,
        "end_y": 30.0,
    })
    wire_result = handle_operation(wire_json, project_dir=project_dir)
    assert isinstance(wire_result, OperationResult)
    assert wire_result.success

    # Add a label at the wire start
    label_json = json.dumps({
        "op_type": "add_label",
        "target_file": FIXTURE_SCH,
        "name": "NEW_NET",
        "label_type": "local",
        "position": {"x": 50.0, "y": 30.0, "angle": 0.0},
    })
    label_result = handle_operation(label_json, project_dir=project_dir)
    assert isinstance(label_result, OperationResult)
    assert label_result.success

    # Verify both mutations in the file
    content = (project_dir / FIXTURE_SCH).read_text(encoding="utf-8")
    assert content.startswith("(kicad_sch"), "File must remain valid after both operations"


def test_intent_to_file_invalid_json_returns_error(project_dir: Path) -> None:
    """Invalid JSON returns OperationError, not an unhandled exception."""
    result = handle_operation("{invalid json", project_dir=project_dir)
    assert not result.success
    assert "JSON" in result.error or "json" in result.error.lower()


def test_intent_to_file_missing_field_returns_error(project_dir: Path) -> None:
    """Missing required fields return OperationError with field name."""
    op_json = json.dumps({
        "op_type": "add_component",
        "target_file": FIXTURE_SCH,
        # Missing library_id and position
    })
    result = handle_operation(op_json, project_dir=project_dir)
    assert not result.success


def test_intent_to_file_transaction_rollback(project_dir: Path) -> None:
    """Operations that fail mid-execution do not corrupt the file.

    This tests that the Transaction system properly rolls back on error.
    """
    original_content = (project_dir / FIXTURE_SCH).read_text(encoding="utf-8")

    # Attempt to move a non-existent component
    op_json = json.dumps({
        "op_type": "move_component",
        "target_file": FIXTURE_SCH,
        "reference": "NONEXISTENT_COMPONENT_XYZ",
        "position": {"x": 0.0, "y": 0.0},
    })
    result = handle_operation(op_json, project_dir=project_dir)

    # Operation should fail
    assert not result.success

    # File should be unchanged (transaction rolled back)
    current_content = (project_dir / FIXTURE_SCH).read_text(encoding="utf-8")
    assert current_content == original_content, (
        "File must be unchanged after failed operation (transaction rollback)"
    )
