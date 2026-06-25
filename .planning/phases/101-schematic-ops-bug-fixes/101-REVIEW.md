---
phase: 101-schematic-ops-bug-fixes
reviewed: 2026-06-25T15:48:35Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - src/kicad_agent/ops/erc_auto_fix.py
  - src/kicad_agent/ops/registry.py
  - src/kicad_agent/ops/repair_components.py
  - src/kicad_agent/ops/repair_erc.py
  - src/kicad_agent/ops/repair_wires.py
  - src/kicad_agent/ops/_schema_repair.py
  - src/kicad_agent/ops/handlers/schematic.py
  - src/kicad_agent/validation/symbol_mismatch.py
  - tests/test_erc_auto_fix.py
  - tests/test_place_no_connects_power_aware.py
  - tests/test_schematic_repair.py
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 101: Code Review Report

**Reviewed:** 2026-06-25T15:48:35Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Phase 101 closes 5 P0/P1 schematic ops bugs (R-1 through R-5). All five fixes
correctly target the verified root cause rather than the symptom, and each fix
has grep-verifiable test coverage. The bug-fix logic itself is sound:

- **R-1 (P0-001)**: `sym.name` → `sym.entryName` applied at both callsites
  (`repair_components.py:152`, `symbol_mismatch.py:141`), with an OR-expanded
  match against `sym.libId` for qualified IDs. Root cause addressed in both the
  op and its validation sibling.
- **R-2 (P0-002)**: Dedup loop moved outside the fallback branch in
  `repair_components.py:658-675`, so it applies to ALL position sources.
  Dry-run mode also correctly populates `_occupied_positions`.
- **R-3 (P0-003)**: Deprecation-only approach. `DeprecationWarning` emitted at
  both `erc_auto_fix` and `erc_auto_fix_hierarchical` entry points
  (`erc_auto_fix.py:216-223, 672-679`); registry marks both as
  `deprecated: True` (`registry.py:1154, 1164`).
- **R-4 (P0-004)**: Tolerance-based `_lookup_pin_type_with_tolerance` helper
  (`repair_erc.py:27-58`) replaces exact dict-key lookup; uses per-axis
  `SNAP_TOLERANCE` comparison to handle sub-micron precision drift.
- **R-5 (P0-005)**: `trust_erc` parameter added with default `True`
  (`repair_wires.py:410`, `_schema_repair.py:184-192`). Dispatcher at
  `handlers/schematic.py:411` correctly passes `trust_erc=op.trust_erc`.

No new mutability violations. Test coverage is thorough for each fix,
including sub-micron rounding-boundary cases (R-4) and 4-instance collision
scenarios (R-2).

The 4 warnings below are all secondary issues — none undermine the bug fixes
themselves, but each represents a path that should be tracked for follow-up
 per the bureaucracy engine's "no silent deferral" rule (§7/§10).

## Critical Issues

None. All five bug fixes target verified root cause and introduce no
security, crash, or data-loss regressions.

## Warnings

### WR-01: Deprecated `erc_auto_fix` ops still mutate files after warning fires

**File:** `src/kicad_agent/ops/erc_auto_fix.py:216-223`
**Issue:**
R-3 is "deprecate only" per the plan, and the `DeprecationWarning` is
correctly emitted on entry. However, the warning fires and then execution
**continues** into the full mutation path (`ir.schematic.to_file(...)` at
lines 350, 397, 418, 535). This leaves the data-loss path (P0-003:
kiutils re-serialization corrupts KiCad 10 schematics) fully active — the
warning informs callers but does not protect them.

The prompt's focus bullet says "R-3 is DEPRECATE ONLY — no half-measures
that leave data-loss paths open." A warning that fires and then allows the
data-loss operation to proceed is arguably a half-measure. Two stricter
options exist:
1. Raise `DeprecationWarning` as an error (turn the warning into a hard
   refusal), preserving the op only for explicit opt-in via a future
   `force=True` parameter.
2. Keep the warning but document the follow-up bead that will actually
   remove the code path (the comment references "Full raw S-expr rewrite
   tracked as follow-up" — a bead ID should be attached).

If the choice is intentionally "warn but proceed" (e.g. for migration
window), this should be documented as a deferred bead per bureaucracy §7.7.

**Fix:**
```python
# Option A: hard refusal (recommended for P0 data-loss)
warnings.warn(
    "erc_auto_fix is DEPRECATED (P0-003) and disabled. ...",
    DeprecationWarning,
    stacklevel=2,
)
return {
    "fixes_applied": [],
    "iterations": 0,
    "remaining_violations": 0,
    "unhandled_violations": [],
    "verification_rollback": [],
    "disabled_reason": "P0-003: disabled to prevent kiutils re-serialization "
                       "corruption. Use targeted individual ops instead.",
}
```
At minimum, create a deferred bead labeled `council-deferred,p0-data-loss`
with a concrete resolution plan for the raw S-expr rewrite.

---

### WR-02: Test patches `kicad_agent.ops.repair.NetPositionIndex` but `repair_erc.py` binds the class at module top

**File:** `tests/test_place_no_connects_power_aware.py:314, 359, 419, 467`
**Issue:**
Multiple tests use `patch("kicad_agent.ops.repair.NetPositionIndex")` to
neutralize net-index lookups. But `repair_erc.py:17` imports the class
directly (`from kicad_agent.schematic_routing.net_extractor import NetPositionIndex`),
which means the binding inside `repair_erc.py` is
`kicad_agent.ops.repair_erc.NetPositionIndex`, **not**
`kicad_agent.ops.repair.NetPositionIndex`. The `patch` call replaces the
re-export binding in the `repair` shim, not the one actually used by the
function under test.

The tests happen to pass anyway because the tiny test schematics cause
`NetPositionIndex.from_file()` to raise an exception, falling into the
`except: net_index = None` branch (see `repair_erc.py:278-280`). So the
patch is currently load-bearing only by accident — if a future change makes
`NetPositionIndex.from_file()` succeed on the minimal test schematic, the
patch would silently fail to take effect and the test would still "pass"
while exercising a different code path than intended.

This is a test-reliability issue, not a production bug.

**Fix:**
Patch where the name is actually looked up:
```python
# Before (incorrect target):
with patch("kicad_agent.ops.repair.NetPositionIndex") as mock_idx:
    ...

# After (correct target — matches repair_erc.py:17 import):
with patch("kicad_agent.ops.repair_erc.NetPositionIndex") as mock_idx:
    ...
```
Note: this file is NOT in the Phase 101 modified list (it's pre-existing),
so tracking this as an out-of-scope finding per bureaucracy §7.

---

### WR-03: `remove_dangling_wires` ERC-passthrough can double-count wires in `removed_count`

**File:** `src/kicad_agent/ops/repair_wires.py:512-552`
**Issue:**
The R-5 ERC-passthrough branch guards against re-flagging wires already in
`wires_to_remove` (line 521: `already_flagged = set(wires_to_remove)`), which
is correct. However, in `dry_run=True` mode the geometric path does NOT
populate `wires_to_remove` (line 499: `wires_to_remove.append(wire_idx)` is
inside the `else` branch). So in dry_run, `already_flagged` is empty and a
wire that geometric criteria *would* remove AND that matches an ERC
violation position gets reported twice — once in `removed` (geometric) and
once in `erc_removed` (with `"source": "erc_passthrough"`).

These two entries have different schemas (geometric has no `source` key;
ERC has no `dry_run` key), so downstream consumers that deduplicate by
position will see the same wire twice with inconsistent fields.

**Fix:**
Track flagged wire indices in both branches so dry_run also deduplicates:
```python
# Around line 465 — keep a set of indices flagged for removal
flagged_indices: set[int] = set()

# Geometric path (line 499):
else:
    wires_to_remove.append(wire_idx)
    flagged_indices.add(wire_idx)
    removed.append({...})

# ERC passthrough (line 521):
already_flagged = flagged_indices  # was: set(wires_to_remove)
for wire_info in wire_endpoints:
    wire_idx = wire_info["wire_index"]
    if wire_idx in already_flagged:
        continue
    ...
```

---

### WR-04: ERC passthrough swallows all exceptions at DEBUG level — silent degradation

**File:** `src/kicad_agent/ops/repair_wires.py:547-548`
**Issue:**
The `trust_erc` lookup wraps `extract_violation_positions` in a broad
`except Exception` with only a `logger.debug` call. ERC parsing failures
(which can happen if `kicad-cli` is missing or the schematic fails ERC) are
silently swallowed and the op falls back to geometric-only mode.

For a P0 fix whose entire purpose is "trust ERC when it says a wire
dangles", silent fallback to geometric-only is a meaningful behavior change
that callers cannot detect from the return value. A user who sets
`trust_erc=True` and gets `removed_count=0` cannot tell whether ERC found
nothing or ERC failed to run.

**Fix:**
Elevate to `WARNING` and surface in the result dict:
```python
except Exception as exc:
    logger.warning(
        "trust_erc lookup failed for %s, using geometric only: %s",
        file_path, exc,
    )
    # Optional: surface in result so callers can detect the fallback
    erc_lookup_failed = True
```
Then include `"erc_lookup_failed": erc_lookup_failed` in the return dict
when `trust_erc=True`, so downstream callers can distinguish "ERC clean"
from "ERC broken".

## Info

### IN-01: `registry.py:581-587` — `delete_copper_zone` description is accurate but duplicate of `remove_copper_zone`

**File:** `src/kicad_agent/ops/registry.py:581-587`
**Issue:** `delete_copper_zone` is registered as an alias of `remove_copper_zone`
(per the description "Phase 101-06 alias of remove_copper_zone"). This is
correct and intentional, but the Phase 101 scope is "schematic ops bug
fixes" — PCB zone aliases appear unrelated. Verify this is in scope or
track as out-of-scope per bureaucracy §7.
**Fix:** No code change. Confirm scope or create out-of-scope bead if needed.

---

### IN-02: `registry.py:615-623` — `add_zone_keepout` appears unrelated to schematic bug fixes

**File:** `src/kicad_agent/ops/registry.py:615-623`
**Issue:** `add_zone_keepout` registration is tagged "Phase 101-06" but the
phase name is "schematic-ops-bug-fixes". This looks like it belongs to a
different phase (PCB zone ops). Same scope concern as IN-01.
**Fix:** No code change. Verify phase attribution.

---

### IN-03: `repair_components.py:263-293` — `_get_unit_pin_map` uses `getattr(sub_sym, "libId", "")` but inline callers use `sub_sym.libId` directly

**File:** `src/kicad_agent/ops/repair_components.py:276, 306, 577`
**Issue:** Defensive `getattr(..., "")` is used in `_get_unit_pin_map` but
the inline loops at lines 306 (`_get_unit_pin_offsets`) and 577 (power-pin
scan inside `place_missing_units`) use bare `sub_sym.libId`. If `libId`
were ever missing on a sub-symbol, the bare access would raise
AttributeError just like the P0-001 bug being fixed in this same file.
The kiutils API guarantees `libId` so this is currently safe, but the
inconsistency is a minor smell given the file's recent brush with exactly
this class of bug.
**Fix:** Standardize on `getattr(sub_sym, "libId", "") or ""` for all
sub-symbol name lookups, or drop the defensive form entirely and rely on
the kiutils contract.

---

### IN-04: `repair_wires.py:550-552` — `erc_removed` entries merged via `list.extend()` mix schemas

**File:** `src/kicad_agent/ops/repair_wires.py:550-552`
**Issue:** The final `removed.extend(erc_removed)` produces a list whose
first N entries have one schema (no `source` key) and remaining entries
have another (`source: "erc_passthrough"`, no `dry_run` key when
`dry_run=True`). Consumers that iterate `details` and read `d["source"]`
will KeyError on the geometric entries.
**Fix:** Normalize the geometric entries to also include `"source":
"geometric"` (and include `"dry_run": dry_run` on the ERC entries), so the
two schemas match.

---

_Reviewed: 2026-06-25T15:48:35Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
