"""Phase 102 — safe_annotate op test suite (5 LOCKED + 3 supporting tests).

Tests TC-1 through TC-5 are LOCKED by CONTEXT.md. TC-6 through TC-8 are
supporting tests (kiutils avoidance, paren balance, registration).

TC-1, TC-2, TC-5, TC-6, TC-7, TC-8 are GREEN after Plan 02.
TC-3 and TC-4 are RED until Plan 03 (multi-sheet integration with kicad-cli).
"""
import ast
import shutil
import inspect
import difflib
from pathlib import Path

import pytest

# Fixtures directory
FIXTURES = Path(__file__).parent / "fixtures" / "safe_annotate"


def _execute_op(op_json: dict, base_dir: Path) -> dict:
    """Execute a safe_annotate op via the operation executor.

    Args:
        op_json: The "root" payload (op_type, target_file, scope, etc.).
        base_dir: Base directory for resolving relative target_file paths.
    """
    from kicad_agent.ops.executor import OperationExecutor
    from kicad_agent.ops.schema import Operation

    executor = OperationExecutor(base_dir=base_dir)
    op = Operation.model_validate({"root": op_json})
    return executor.execute(op)


# ---- TC-1: Idempotency (LOCKED) ----
def test_idempotency_clean_schematic(tmp_path):
    """Clean schematic + dry_run:true -> annotated:[], file byte-identical."""
    src = FIXTURES / "single_sheet_annotated_clean.kicad_sch"
    dst = tmp_path / "test.kicad_sch"
    shutil.copy(src, dst)
    original = dst.read_text()

    result = _execute_op({
        "op_type": "safe_annotate",
        "target_file": "test.kicad_sch",
        "scope": "current_sheet",
        "dry_run": True,
    }, base_dir=tmp_path)

    annotated = result.get("details", {}).get("annotated", [])
    assert annotated == []
    assert dst.read_text() == original  # byte-identical


# ---- TC-2: Single rename (LOCKED) ----
def test_single_rename_current_sheet(tmp_path):
    """R? + scope:current_sheet -> R1, only one line changes."""
    src = FIXTURES / "single_sheet_unannotated.kicad_sch"
    dst = tmp_path / "test.kicad_sch"
    shutil.copy(src, dst)
    original = dst.read_text()

    result = _execute_op({
        "op_type": "safe_annotate",
        "target_file": "test.kicad_sch",
        "scope": "current_sheet",
    }, base_dir=tmp_path)

    annotated = result.get("details", {}).get("annotated", [])
    assert len(annotated) == 1
    entry = annotated[0]
    assert entry["old_ref"] == "R?"
    assert entry["new_ref"] == "R1"
    new_content = dst.read_text()
    assert '(property "Reference" "R1"' in new_content
    assert '(property "Reference" "R?"' not in new_content
    # Surgical edit: exactly one line changed
    diff = list(difflib.unified_diff(original.splitlines(), new_content.splitlines(), n=0))
    changed = [l for l in diff if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
    assert len(changed) == 2, f"Expected 2 diff lines (1 add + 1 del), got {len(changed)}"


# ---- TC-3: Cross-sheet dedup (LOCKED) ----
def test_cross_sheet_dedup_whole_project(tmp_path):
    """2 sheets each with R1 + whole_project + reset -> one renamed, paren balance preserved."""
    raise NotImplementedError("Plan 03: integration test with multi-sheet fixtures")


# ---- TC-4: P0-006 regression (LOCKED) ----
def test_p0_006_regression_no_reserialization(tmp_path):
    """Diff line count approx= refs renamed, NOT approx= file size."""
    raise NotImplementedError("Plan 03: diff assertion test")


# ---- TC-5: Root sheet guard (LOCKED) ----
def test_root_sheet_guard_refuses(tmp_path):
    """Root sheet passed as target -> op refuses with documented error."""
    src = FIXTURES / "multi_sheet_root.kicad_sch"
    dst = tmp_path / "root.kicad_sch"
    shutil.copy(src, dst)

    with pytest.raises(ValueError, match="safe_annotate operates per-sheet; root sheet contains hierarchy only"):
        _execute_op({
            "op_type": "safe_annotate",
            "target_file": "root.kicad_sch",
            "scope": "current_sheet",
        }, base_dir=tmp_path)


# ---- TC-6: kiutils avoidance (supporting) ----
def test_handler_does_not_use_kiutils_to_file():
    """Function-scoped AST grep (H-01): _handle_safe_annotate source has NO to_file Call nodes.

    Uses inspect.getsource(_handle_safe_annotate) — NOT a whole-module walk of
    handlers/schematic.py. Mirrors test_safe_sync_pcb_from_schematic.py:74-88.
    """
    from kicad_agent.ops.handlers.schematic import _handle_safe_annotate

    source = inspect.getsource(_handle_safe_annotate)
    tree = ast.parse(source)
    to_file_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "to_file"
    ]
    assert to_file_calls == [], (
        f"_handle_safe_annotate must NOT call to_file() — use raw S-expr via "
        f"SchematicRawWriter.replace_reference_property. Found: {to_file_calls}"
    )


# ---- TC-7: Paren balance (supporting) ----
def test_paren_balance_preserved(tmp_path):
    """After every edit, validate_paren_balance passes."""
    src = FIXTURES / "single_sheet_unannotated.kicad_sch"
    dst = tmp_path / "test.kicad_sch"
    shutil.copy(src, dst)

    _execute_op({
        "op_type": "safe_annotate",
        "target_file": "test.kicad_sch",
        "scope": "current_sheet",
    }, base_dir=tmp_path)

    content = dst.read_text()
    assert content.count('(') == content.count(')'), "Paren imbalance after edit"


# ---- TC-8: Registration (supporting) ----
def test_safe_annotate_registered():
    """Op in SELF_SERIALIZING_OPS, registry, schema imports cleanly."""
    from kicad_agent.ops.execution import SELF_SERIALIZING_OPS
    from kicad_agent.ops.registry import OPERATION_REGISTRY
    from kicad_agent.ops._schema_reference import SafeAnnotateOp

    assert "safe_annotate" in SELF_SERIALIZING_OPS
    assert "safe_annotate" in OPERATION_REGISTRY
    # Schema constructs with defaults
    op = SafeAnnotateOp(target_file="test.kicad_sch")
    assert op.op_type == "safe_annotate"
    assert op.scope == "whole_project"
