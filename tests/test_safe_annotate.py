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
    """2 sheets each with R1 + whole_project + reset -> one renamed, paren balance preserved.

    H-03 (Council Gate 1): proven on minimal multi-sheet fixtures (2 sheets, 2 duplicate
    refs). Full real-world validation (47+ cross-sheet duplicates across 16 sub-sheets)
    is deferred to Phase 145 manual verification per VALIDATION.md line 69.
    """
    # Copy the 3-file multi-sheet project to tmpdir
    for fname in [
        "multi_sheet_root.kicad_sch",
        "multi_sheet_child_a.kicad_sch",
        "multi_sheet_child_b.kicad_sch",
    ]:
        shutil.copy(FIXTURES / fname, tmp_path / fname)

    root_file = tmp_path / "multi_sheet_root.kicad_sch"
    original_root = root_file.read_text()
    original_child_a = (tmp_path / "multi_sheet_child_a.kicad_sch").read_text()
    original_child_b = (tmp_path / "multi_sheet_child_b.kicad_sch").read_text()

    result = _execute_op(
        {
            "op_type": "safe_annotate",
            "target_file": "multi_sheet_root.kicad_sch",
            "scope": "whole_project",
            "reset": True,
        },
        base_dir=tmp_path,
    )

    details = result.get("details", {})
    stats = details.get("stats", {})
    annotated = details.get("annotated", [])

    # (a) At least one duplicate resolved (one of the two R1 symbols renamed)
    assert stats.get("duplicates_resolved", 0) >= 1, (
        f"Expected duplicates_resolved >= 1, got stats={stats}"
    )

    # (b) At least one annotated entry with old_ref="R1" and new_ref != "R1"
    renamed_r1 = [
        r for r in annotated if r["old_ref"] == "R1" and r["new_ref"] != "R1"
    ]
    assert len(renamed_r1) >= 1, (
        f"Expected at least 1 R1 rename, got annotated={annotated}"
    )

    # (c) Both child files still exist and are paren-balanced
    for child in [
        "multi_sheet_child_a.kicad_sch",
        "multi_sheet_child_b.kicad_sch",
    ]:
        content = (tmp_path / child).read_text()
        assert content.count("(") == content.count(")"), (
            f"{child}: paren imbalance after dedup"
        )

    # (d) Root file is NOT mutated (it has no components — only sheet blocks)
    assert root_file.read_text() == original_root, (
        "Root file mutated by whole_project annotate (should be unchanged — root has no components)"
    )

    # (e) If kicad-cli is available, confirm the children still parse cleanly.
    # Exit code 0 or 1 (ERC violations) is fine; we just need the file to PARSE.
    # Exit code > 1 indicates a parse failure (the P0-006 corruption pattern).
    if shutil.which("kicad-cli"):
        import subprocess

        for child in [
            "multi_sheet_child_a.kicad_sch",
            "multi_sheet_child_b.kicad_sch",
        ]:
            proc = subprocess.run(
                ["kicad-cli", "sch", "erc", str(tmp_path / child)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert proc.returncode <= 1, (
                f"kicad-cli sch erc failed to parse {child}: rc={proc.returncode}, "
                f"stderr={proc.stderr[:500]}"
            )


# ---- TC-4: P0-006 regression (LOCKED) ----
def test_p0_006_regression_no_reserialization(tmp_path):
    """Diff line count approx= refs renamed, NOT approx= file size (the P0-006 regression).

    P0-006 reproduction on mcu.kicad_sch: 1183 ins / 1131 del = 2314 changed lines
    while reporting annotated:[]. safe_annotate should produce ~2 lines per renamed
    ref (1 deletion + 1 addition per ref), bounded by refs_renamed * 4 + 4.

    T-102-03-01 (mitigate): if kiutils re-serialization sneaks back in (e.g.,
    SELF_SERIALIZING_OPS membership accidentally removed), this bound explodes.
    """
    # Copy the 3-file multi-sheet project to tmpdir
    files = [
        "multi_sheet_root.kicad_sch",
        "multi_sheet_child_a.kicad_sch",
        "multi_sheet_child_b.kicad_sch",
    ]
    for fname in files:
        shutil.copy(FIXTURES / fname, tmp_path / fname)

    snapshots = {f: (tmp_path / f).read_text() for f in files}

    root_file = tmp_path / "multi_sheet_root.kicad_sch"
    result = _execute_op(
        {
            "op_type": "safe_annotate",
            "target_file": "multi_sheet_root.kicad_sch",
            "scope": "whole_project",
            "reset": True,
        },
        base_dir=tmp_path,
    )

    details = result.get("details", {})
    stats = details.get("stats", {})
    refs_renamed = stats.get("refs_renamed", 0)
    assert refs_renamed >= 1, (
        f"Expected refs_renamed >= 1, got stats={stats}"
    )

    # For each file, count changed lines in the diff
    total_changed_lines = 0
    per_file_changed = {}
    for fname in files:
        old = snapshots[fname].splitlines(keepends=True)
        new = (tmp_path / fname).read_text().splitlines(keepends=True)
        diff = list(difflib.unified_diff(old, new, n=0, lineterm=""))
        # Count + and - lines (excluding +++/--- headers)
        changed = [
            line
            for line in diff
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        ]
        per_file_changed[fname] = len(changed)
        total_changed_lines += len(changed)

    # P0-006 produced 1183 ins / 1131 del = 2314 changed lines on a similar file.
    # safe_annotate should produce ~2 lines per renamed ref (+ the old line, + the new line).
    # For our fixtures with 2 refs renamed, expect <= ~10 changed lines total.
    # Allow generous upper bound: refs_renamed * 4 + 4 (safety margin per SI Rick's analysis).
    upper_bound = refs_renamed * 4 + 4
    assert total_changed_lines <= upper_bound, (
        f"P0-006 REGRESSION: diff has {total_changed_lines} changed lines "
        f"({per_file_changed}), expected <= {upper_bound} "
        f"(refs_renamed={refs_renamed}). "
        f"This suggests kiutils re-serialization occurred. "
        f"Check SELF_SERIALIZING_OPS membership and AST grep for to_file calls."
    )


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
