"""Phase 102 — safe_annotate op test suite (5 LOCKED + 3 supporting tests).

Tests TC-1 through TC-5 are LOCKED by CONTEXT.md. TC-6 through TC-8 are
supporting tests (kiutils avoidance, paren balance, registration).

All tests are RED in Plan 01. Plans 02 and 03 turn them GREEN.
"""
import ast
import shutil
import difflib
from pathlib import Path

import pytest

# Fixtures directory
FIXTURES = Path(__file__).parent / "fixtures" / "safe_annotate"


def _execute_op(op_json: dict) -> dict:
    """Execute a safe_annotate op via the operation executor.

    RED in Plan 01 (op not registered yet). GREEN after Plan 02.
    """
    from kicad_agent.ops.executor import execute
    return execute(op_json)


# ---- TC-1: Idempotency (LOCKED) ----
def test_idempotency_clean_schematic(tmp_path):
    """Clean schematic + dry_run:true -> annotated:[], file byte-identical."""
    # RED: stub — implement properly in Plan 02
    raise NotImplementedError("Plan 02: wire to safe_annotate op")


# ---- TC-2: Single rename (LOCKED) ----
def test_single_rename_current_sheet(tmp_path):
    """R? + scope:current_sheet -> R1, only one line changes."""
    raise NotImplementedError("Plan 02: wire to safe_annotate op")


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
    raise NotImplementedError("Plan 02: wire to safe_annotate op")


# ---- TC-6: kiutils avoidance (supporting) ----
def test_handler_does_not_use_kiutils_to_file():
    """Function-scoped AST grep (H-01): _handle_safe_annotate source has NO to_file Call nodes.

    Uses inspect.getsource(_handle_safe_annotate) — NOT a whole-module walk of
    handlers/schematic.py. Mirrors test_safe_sync_pcb_from_schematic.py:74-88.
    Implemented in Plan 02 (RED here because _handle_safe_annotate doesn't exist yet).
    """
    raise NotImplementedError("Plan 02: function-scoped AST grep test via inspect.getsource")


# ---- TC-7: Paren balance (supporting) ----
def test_paren_balance_preserved(tmp_path):
    """After every edit, validate_paren_balance passes."""
    raise NotImplementedError("Plan 02: paren balance test")


# ---- TC-8: Registration (supporting) ----
def test_safe_annotate_registered():
    """Op in SELF_SERIALIZING_OPS, registry, schema imports cleanly."""
    raise NotImplementedError("Plan 02: registration test")
