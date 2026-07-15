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
    from volta.ops.executor import OperationExecutor
    from volta.ops.schema import Operation

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
    from volta.ops.handlers.schematic import _handle_safe_annotate

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
    from volta.ops.execution import SELF_SERIALIZING_OPS
    from volta.ops.registry import OPERATION_REGISTRY
    from volta.ops._schema_reference import SafeAnnotateOp

    assert "safe_annotate" in SELF_SERIALIZING_OPS
    assert "safe_annotate" in OPERATION_REGISTRY
    # Schema constructs with defaults
    op = SafeAnnotateOp(target_file="test.kicad_sch")
    assert op.op_type == "safe_annotate"
    assert op.scope == "whole_project"


# ---- EXEC-01: Power symbols skipped (Council Gate 2) ----
def test_power_symbols_are_skipped(tmp_path):
    """Power symbols (#PWR?, #PWR01, #GND01) must not be renamed.

    EXEC-01: the _POWER_SYMBOL_PREFIX filter at extraction time is load-bearing.
    A schematic with a #PWR? symbol and an R? component should only annotate R?,
    never touch the power symbol.
    """
    dst = tmp_path / "test.kicad_sch"
    fixture = FIXTURES / "single_sheet_unannotated.kicad_sch"
    shutil.copy(fixture, dst)
    content = dst.read_text()

    # Inject a power symbol block before the closing (sheet) paren
    power_block = '''  (symbol (lib_id "power:GND") (at 50 50 0)
    (in_bom yes) (on_board yes)
    (property "Reference" "#PWR01") (property "Value" "GND")
    (property "Footprint" "")
    (uuid "power-uuid-1234")
  )
'''
    injected = content.replace("  (symbol_instances", power_block + "  (symbol_instances")
    dst.write_text(injected)

    result = _execute_op({
        "op_type": "safe_annotate",
        "target_file": "test.kicad_sch",
        "scope": "current_sheet",
    }, base_dir=tmp_path)

    annotated = result.get("details", {}).get("annotated", [])
    power_renamed = [r for r in annotated if r["old_ref"].startswith("#")]
    assert not power_renamed, (
        f"Power symbol was renamed (should be skipped): {power_renamed}"
    )


# ---- EXEC-04: _extract_number defensive fallback (Council Gate 2) ----
def test_extract_number_fallback_returns_zero_on_garbage():
    """_extract_number returns 0 for unparseable suffixes (defensive, normally unreachable).

    EXEC-04: the fallback is unreachable in practice (upstream _REF_PATTERN
    filters garbage), but the defensive return-0 path must be covered.
    """
    from volta.ops.handlers.schematic import _extract_number

    assert _extract_number("R42", "R") == 42
    assert _extract_number("C7", "C") == 7
    # Defensive: garbage suffix returns 0 (not a crash)
    assert _extract_number("R???", "R") == 0
    assert _extract_number("R", "R") == 0


# ---- EXEC-05: reset=False resolves existing duplicates (Council Gate 2) ----
def test_reset_false_resolves_duplicates(tmp_path):
    """Dedup must work even when reset=False (don't renumber everything).

    EXEC-05: the realistic case is a schematic that ALREADY has duplicates
    (R1 on two sheets) where the user wants to resolve the conflict WITHOUT
    resetting all refs to ?. The op should rename the duplicate, not skip it.
    """
    for fname in [
        "multi_sheet_root.kicad_sch",
        "multi_sheet_child_a.kicad_sch",
        "multi_sheet_child_b.kicad_sch",
    ]:
        shutil.copy(FIXTURES / fname, tmp_path / fname)

    result = _execute_op(
        {
            "op_type": "safe_annotate",
            "target_file": "multi_sheet_root.kicad_sch",
            "scope": "whole_project",
            "reset": False,  # the key difference from TC-3
        },
        base_dir=tmp_path,
    )

    stats = result.get("details", {}).get("stats", {})
    annotated = result.get("details", {}).get("annotated", [])

    # Duplicate resolution must still fire when reset=False
    renamed_r1 = [
        r for r in annotated if r["old_ref"] == "R1" and r["new_ref"] != "R1"
    ]
    assert len(renamed_r1) >= 1, (
        f"reset=False should still resolve R1 duplicates, got annotated={annotated}"
    )
    assert stats.get("duplicates_resolved", 0) >= 1


# ---- EXEC-03: Sort tie-break uses sheet UUID (Phase 102.1) ----
def test_sort_tie_break_uses_sheet_uuid(tmp_path):
    """Same project run from two different base dirs produces identical refdes.

    EXEC-03 (Phase 102.1): before this fix, the sort tie-break used the
    absolute sheet path string, so the same project at /tmp/aaa/ vs /tmp/zzz/
    produced different refdes owners for duplicate R1 components. The fix
    uses the sheet UUID (KiCad-embedded, stable across machines).

    This test creates TWO copies of the multi-sheet project under different
    parent directories (aaa vs zzz — alphabetically distinct) and asserts
    that safe_annotate produces byte-identical refdes assignments on both.
    """
    # Create two sibling directories with alphabetically distinct names.
    # tmp_path is already created by pytest; we create two subdirs under it.
    dir_a = tmp_path / "aaa_test_project"
    dir_z = tmp_path / "zzz_test_project"
    dir_a.mkdir()
    dir_z.mkdir()

    fixtures = [
        "multi_sheet_root.kicad_sch",
        "multi_sheet_child_a.kicad_sch",
        "multi_sheet_child_b.kicad_sch",
    ]

    # Copy the multi-sheet project to BOTH directories.
    for d in (dir_a, dir_z):
        for fname in fixtures:
            shutil.copy(FIXTURES / fname, d / fname)

    # Run safe_annotate on both with identical params.
    result_a = _execute_op(
        {
            "op_type": "safe_annotate",
            "target_file": "multi_sheet_root.kicad_sch",
            "scope": "whole_project",
            "reset": True,
        },
        base_dir=dir_a,
    )
    result_z = _execute_op(
        {
            "op_type": "safe_annotate",
            "target_file": "multi_sheet_root.kicad_sch",
            "scope": "whole_project",
            "reset": True,
        },
        base_dir=dir_z,
    )

    details_a = result_a.get("details", {})
    details_z = result_z.get("details", {})

    # Normalize the "sheet" field (which is an absolute path) out of the
    # annotated entries — only the (old_ref, new_ref, uuid) tuples matter
    # for cross-machine determinism. The UUIDs are file-embedded and stable.
    def _normalize(details):
        return sorted(
            (r["uuid"], r["old_ref"], r["new_ref"]) for r in details.get("annotated", [])
        )

    normalized_a = _normalize(details_a)
    normalized_z = _normalize(details_z)

    # EXEC-03 PASS CONDITION: identical refdes assignments across both dirs.
    assert normalized_a == normalized_z, (
        f"EXEC-03 FAIL: refdes assignments differ across base directories.\n"
        f"  dir_a annotated (normalized): {normalized_a}\n"
        f"  dir_z annotated (normalized): {normalized_z}\n"
        f"With the OLD sheet_path tie-break, these would differ because "
        f"aaa_test_project sorts before zzz_test_project alphabetically."
    )

    # Sanity: stats must also match (deterministic ref count, dedup count).
    stats_a = details_a.get("stats", {})
    stats_z = details_z.get("stats", {})
    assert stats_a == stats_z, (
        f"EXEC-03 FAIL: stats differ across base directories.\n"
        f"  dir_a stats: {stats_a}\n"
        f"  dir_z stats: {stats_z}"
    )

    # Sanity: at least one rename happened (otherwise test is vacuous).
    assert stats_a.get("refs_renamed", 0) >= 1, (
        f"EXEC-03 vacuous: no renames occurred. stats={stats_a}"
    )


def test_sort_tie_break_uses_sheet_uuid_not_path():
    """DIRECT test: sort tie-break uses sheet_uuid, not sheet_path.

    WR-02 fix (Phase 102.1 code review): the integration test above is
    vacuous because the fixture filenames sort in the same order as their
    UUIDs (child_a < child_b by both path AND uuid). This unit test
    constructs components where PATH ORDER IS INVERTED from UUID order,
    proving the sort picks by UUID (stable across machines) not path
    (varies by machine/layout).

    With the OLD sheet_path tie-break, the winner would be the component
    on sheet_path "/zzz_first.kicad_sch" (wait — no: "/aaa_..." sorts first).
    Let me be precise:
      - Component P has sheet="/aaa_path.kicad_sch", uuid="zzz-uuid"
      - Component Q has sheet="/zzz_path.kicad_sch", uuid="aaa-uuid"
      - Both at identical (x, y)
    OLD code (path tie-break): P wins ("/aaa_..." < "/zzz_...")
    NEW code (uuid tie-break): Q wins ("aaa-uuid" < "zzz-uuid")
    """
    from volta.ops.handlers.schematic import _build_rename_plan

    components = [
        {
            "uuid": "sym-p-uuid",
            "ref": "R?",
            "x": 50.0,
            "y": 50.0,
            "sheet": "/aaa_path.kicad_sch",   # sorts FIRST by path
            "sheet_uuid": "zzzz-p-sheet-uuid",  # but LAST by uuid
        },
        {
            "uuid": "sym-q-uuid",
            "ref": "R?",
            "x": 50.0,
            "y": 50.0,
            "sheet": "/zzz_path.kicad_sch",   # sorts LAST by path
            "sheet_uuid": "aaaa-q-sheet-uuid",  # but FIRST by uuid
        },
    ]

    plan = _build_rename_plan(components, reset=True, order="by_x_position")

    # Both get renamed (R? -> R1, R? -> R2). The question is WHO gets R1.
    r1_entry = next(r for r in plan if r["new_ref"] == "R1")
    r2_entry = next(r for r in plan if r["new_ref"] == "R2")

    # EXEC-03 PASS: the component with the alphabetically-first UUID wins R1.
    # That's Q (uuid "aaaa-q-sheet-uuid"), NOT P (uuid "zzzz-p-sheet-uuid").
    # If the sort used sheet_path, P would win ("/aaa_..." < "/zzz_...").
    assert r1_entry["uuid"] == "sym-q-uuid", (
        f"EXEC-03 FAIL: R1 assigned to {r1_entry['uuid']} (expected sym-q-uuid "
        f"with first-UUID). Sort may be using sheet_path instead of sheet_uuid. "
        f"Plan: {[(r['uuid'], r['new_ref']) for r in plan]}"
    )
    assert r2_entry["uuid"] == "sym-p-uuid", (
        f"EXEC-03 FAIL: R2 assigned to {r2_entry['uuid']} (expected sym-p-uuid). "
        f"Plan: {[(r['uuid'], r['new_ref']) for r in plan]}"
    )


# ---- H-02 Option B: instances block co-edit (Phase 102.1) ----
def test_instances_block_co_edited(tmp_path):
    """safe_annotate updates BOTH (property "Reference") AND (instances reference).

    H-02 Option B (Phase 102.1): real-world KiCad 10 schematics contain
    (instances (project "..." (path "/" (reference "OLD") (unit N)))) blocks.
    The netlist exporter reads the refdes from here. Without co-editing,
    safe_annotate renames the property but the netlist still shows the old
    ref → silent partial annotation.

    Fixture with_instances.kicad_sch has ONE R1 symbol with an instances block.
    With reset:true, safe_annotate renumbers R1 → R1 (same) but the test also
    forces a rename by having TWO R1's — no, simpler: reset:true alone renames
    R1 -> R1 (counter starts at 1). To force an actual rename we use a fixture
    whose ref starts higher. Actually the simplest: reset:true on a single R1
    produces R1 (no change). So we add a second component with R5 to force
    renumbering via reset.

    Simpler approach: the fixture has R1. We run reset:true. The single
    resistor gets renumbered R1 -> R1 (no change). That doesn't test the edit.
    So instead we craft the test to verify the instances block is updated
    WHEN a rename happens. We achieve a rename by copying the fixture, then
    manually running reset which renumbers the single R1 to R1 (stable).
    That's a no-op rename. To force a real rename we need 2+ components.

    Final approach: load fixture (1 R1), pre-edit it to R5, then run
    reset:true -> R5 becomes R1 (real rename). Verify both property AND
    instances reference updated to R1.
    """
    src = FIXTURES / "with_instances.kicad_sch"
    dst = tmp_path / "test.kicad_sch"
    shutil.copy(src, dst)

    # Pre-edit: change both the property AND instances reference from R1 to R5
    # so that reset:true produces a real rename (R5 -> R1), exercising the
    # co-edit path.
    content = dst.read_text()
    content = content.replace('(property "Reference" "R1"', '(property "Reference" "R5"')
    content = content.replace('(reference "R1")', '(reference "R5")')
    dst.write_text(content)

    # Sanity: the pre-edit took effect.
    pre = dst.read_text()
    assert '(property "Reference" "R5"' in pre, "Pre-edit property failed"
    assert '(reference "R5")' in pre, "Pre-edit instances reference failed"

    # Run safe_annotate with reset:true. R5 -> R1 (the counter starts at 1
    # for the R prefix under reset, and this is the only R in the schematic).
    result = _execute_op(
        {
            "op_type": "safe_annotate",
            "target_file": "test.kicad_sch",
            "scope": "current_sheet",
            "reset": True,
        },
        base_dir=tmp_path,
    )

    annotated = result.get("details", {}).get("annotated", [])
    stats = result.get("details", {}).get("stats", {})

    # A rename must have occurred (R5 -> R1).
    assert stats.get("refs_renamed", 0) >= 1, (
        f"H-02 vacuous: no rename occurred. stats={stats}, annotated={annotated}"
    )

    # The annotated entry should show old_ref=R5, new_ref=R1.
    renamed = [r for r in annotated if r["old_ref"] == "R5" and r["new_ref"] == "R1"]
    assert len(renamed) == 1, (
        f"Expected R5->R1 rename, got annotated={annotated}"
    )

    # H-02 CORE ASSERTION: read the output file and verify BOTH locations
    # reflect the new ref (R1), and the old ref (R5) is gone from both.
    out = dst.read_text()

    # (property "Reference" "R1") must be present
    assert '(property "Reference" "R1"' in out, (
        f"H-02 FAIL: (property \"Reference\" \"R1\") not found in output"
    )
    # (reference "R1") inside instances must be present
    assert '(reference "R1")' in out, (
        f"H-02 FAIL: (reference \"R1\") not found in instances block"
    )

    # The OLD ref R5 must be GONE from both locations.
    assert '(property "Reference" "R5"' not in out, (
        f"H-02 FAIL: stale (property \"Reference\" \"R5\") still present "
        f"— property edit did not apply"
    )
    assert '(reference "R5")' not in out, (
        f"H-02 FAIL: stale (reference \"R5\") still present in instances "
        f"— instances co-edit did not apply (the H-02 bug)"
    )

    # Paren balance must be preserved.
    assert out.count("(") == out.count(")"), (
        f"H-02 FAIL: paren imbalance after instances co-edit"
    )


