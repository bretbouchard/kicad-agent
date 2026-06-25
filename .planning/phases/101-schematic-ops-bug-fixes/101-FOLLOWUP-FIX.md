---
phase: 101-schematic-ops-bug-fixes
fixed_at: 2026-06-25T20:30:00Z
review_path: .planning/phases/101-schematic-ops-bug-fixes/101-COUNCIL-EXEC-REVIEW.md
iteration: followup
findings_in_scope: 5
fixed: 4
skipped: 1
status: partial
---

# Phase 101: Code Review Follow-up Fix Report

**Fixed at:** 2026-06-25T20:30:00Z
**Source review:** `.planning/phases/101-schematic-ops-bug-fixes/101-COUNCIL-EXEC-REVIEW.md`
**Iteration:** followup

**Summary:**
- Findings in scope: 5 (MD-01, MD-02, LO-01, LO-02, LO-03) + 1 pre-existing dispatch gap
- Fixed: 4 (MD-01, LO-01, LO-02, LO-03) + 1 pre-existing (generate_bom dispatch)
- Skipped: 1 (MD-02 — out-of-scope, Bead filed in STATE.md)

## Fixed Issues

### MD-01: Raw S-expr rewrite for erc_auto_fix (P0-003 data-loss fix)

**Files modified:**
- `src/kicad_agent/ops/erc_auto_fix.py` (new `_persist_ir_raw` helper, all 6 `to_file()` calls replaced)
- `src/kicad_agent/ops/schematic_raw_writer.py` (NEW — SchematicRawWriter class)
- `tests/test_erc_auto_fix.py` (10 new acceptance + unit tests)

**Commit:** `9f42272`

**Applied fix:**
Rewrote `erc_auto_fix` and `erc_auto_fix_hierarchical` to use raw S-expression manipulation instead of kiutils `to_file()` re-serialization, eliminating the P0-003 data-loss path that corrupted KiCad 10 schematics.

Key changes:
- New `SchematicRawWriter` module with static methods for surgical S-expr edits: `insert_no_connect`, `insert_junction`, `insert_power_flag`, `apply_mutation`/`apply_mutations`
- `_ensure_lib_symbol_exists` correctly places PWR_FLAG lib_symbols in the TOP-LEVEL `(lib_symbols ...)` container — fixes the P0-003 root cause where lib_symbols were nested inside other lib_symbol blocks
- New `_persist_ir_raw(ir, file_path)` helper in `erc_auto_fix.py`: reads raw file text, replays IR's `mutation_log` via `SchematicRawWriter.apply_mutations`, writes atomically via `atomic_write`
- All 6 `ir.schematic.to_file(str(file_path))` calls in `erc_auto_fix.py` replaced with `_persist_ir_raw(ir, file_path)`
- Graceful fallback when file doesn't exist (test/mock scenario) — skips write, mutations remain in IR audit log

**Acceptance criteria verified:**
- `grep 'to_file' src/kicad_agent/ops/erc_auto_fix.py` returns 0 code calls (comments only)
- `atomic_write` imported from `kicad_agent.io.atomic_write`
- `test_erc_auto_fix_preserves_kicad_10_formatting` — verifies `generator_version`, `uuid`, original formatting preserved + output re-parseable by kiutils
- `test_erc_auto_fix_hierarchical_no_corruption` — verifies PWR_FLAG lib_symbol placed at correct nesting level (sibling of Device:R, not child)
- 10 new tests pass, 140 total tests pass (0 regressions)

---

### LO-01: Normalize removed list schema

**Files modified:** `src/kicad_agent/ops/repair_wires.py`
**Commit:** `873b3c5`

**Applied fix:**
Normalized geometric `removed` entries to include `"source": "geometric"` key. ERC entries now include `dry_run` key for consistency. Consumers can now safely read `d["source"]` without `KeyError` on geometric entries.

---

### LO-02: Fix dry_run double-count in remove_dangling_wires

**Files modified:** `src/kicad_agent/ops/repair_wires.py`
**Commit:** `873b3c5`

**Applied fix:**
Added `flagged_indices: set[int]` populated in BOTH dry_run and mutate branches. The ERC passthrough now checks `flagged_indices` instead of `set(wires_to_remove)` (which was empty in dry_run mode). Wires matching both geometric AND ERC criteria are now reported once, not twice.

---

### LO-03: Surface ERC fallback in return dict

**Files modified:** `src/kicad_agent/ops/repair_wires.py`
**Commit:** `873b3c5`

**Applied fix:**
- Elevated `trust_erc` lookup failure log from DEBUG to WARNING
- Added `erc_fallback_used: bool` to return dict when `trust_erc=True` and lookup failed
- Callers can now distinguish "ERC found nothing" from "ERC failed to run"

---

### Pre-existing: generate_bom dispatch gap

**Files modified:** `src/kicad_agent/ops/handlers/schematic_query.py`
**Commit:** `e9113fe`

**Applied fix:**
Added `_handle_generate_bom` wrapper in `schematic_query.py` that delegates to the existing handler in `pcb_bom.py`. The op now routes through `execute_schematic_query` (no Transaction, no serialization). Test `test_schematic_readonly_ops_have_query_handler` passes (was failing on master).

## Skipped Issues

### MD-02: NetPositionIndex patch target mismatch

**File:** `tests/test_place_no_connects_power_aware.py:314, 359, 419, 467`
**Reason:** out-of-scope per bureaucracy §7 — pre-existing issue, not introduced by Phase 101
**Original issue:** Tests patch `kicad_agent.ops.repair.NetPositionIndex` but `repair_erc.py:17` binds the class directly. Patch targets wrong namespace; tests pass only because `NetPositionIndex.from_file()` raises on minimal test schematics.

**Out-of-scope Bead filed:** Documented in `.planning/STATE.md` under Deferred Items with label `out-of-scope,test-reliability`, priority 2. Resolution plan: change patch target to `kicad_agent.ops.repair_erc.NetPositionIndex` at lines 314, 359, 419, 467.

---

_Fixed: 2026-06-25T20:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: followup_
