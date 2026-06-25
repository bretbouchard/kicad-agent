---
phase: 100-routingorchestrator-and-human-approval-loop
fixed_at: 2026-06-25T08:05:52Z
review_path: .planning/phases/100-routingorchestrator-and-human-approval-loop/100-COUNCIL-EXEC-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 9
deferred: 2
status: partial
---

# Phase 100: Code Review Fix Report

**Fixed at:** 2026-06-25T08:05:52Z
**Source review:** `.planning/phases/100-routingorchestrator-and-human-approval-loop/100-COUNCIL-EXEC-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (2 CRITICAL + 4 MEDIUM + 5 LOW)
- Fixed inline: 9
- Deferred with tracking: 2 (LO-04, LO-05 — concrete resolution plans below)
- Skipped: 0

**Test results (final):**
- Phase 100 suite: **76/76 pass** (was 74; +2 new CR-01 regression tests)
- Broader regression (routing + parser + adapter): **338/338 pass**
- Combined: **414 tests green, zero regressions**

## Per-Finding Status Table

| ID | Severity | Title | Status | Commit |
|----|----------|-------|--------|--------|
| CR-01 | CRITICAL | rollback_net UUID parent_index divergence | **fixed** | `ab7035d` |
| CR-02 | CRITICAL | 3 non-atomic write paths in orchestrator | **fixed** | `4134904` |
| MD-01 | MEDIUM | Audit hardcodes `drc_clean=True` | **fixed** | `c5748d6` |
| MD-02 | MEDIUM | Orchestrator synthesizes fake `Pin.footprint_ref` | **fixed** | `4fbe7f8` |
| MD-03 | MEDIUM | `NativeBoard.general` None-patched via `__post_init__` | **fixed** | `adcd73d` |
| MD-04 | MEDIUM | `MappingProxyType` rebuilt on every access | **fixed** | `2203e0a` |
| LO-01 | LOW | `rollback_full` PRE/POST duality undocumented | **fixed** | `7657ecf` |
| LO-02 | LOW | `rollback_net` stale-IR warning missing | **fixed** | `7657ecf` |
| LO-03 | LOW | Silent net drop in InteractiveRoutingSession | **fixed** | `d563f6c` |
| LO-04 | LOW | Double SES parse in `_dispatch_freerouting` | **deferred** | — |
| LO-05 | LOW | Noisy unsupported-element warnings | **deferred** | — |

## Fixed Issues

### CR-01: rollback_net assumes UUID parent_index == NativeBoard segment index — they diverge

**Files modified:** `src/kicad_agent/parser/pcb_native_types.py`, `src/kicad_agent/parser/pcb_native_parser.py`, `src/kicad_agent/routing/orchestrator.py`, `tests/test_phase100_rollback.py`
**Commit:** `ab7035d`
**Applied fix:** Added `uuid: str = ""` field to `NativeSegment` and `NativeVia`. Populated during parse in `_extract_segments` and `_extract_vias` via `_find_string_child(block, "uuid")`. Rewrote `rollback_net` to collect target UUIDs directly from the parsed `board.segments` / `board.vias` (filtered by `net_name`) and join on UUID value — drops the `extract_uuids` call entirely. Added 2 regression tests: `test_rollback_with_nested_segment_in_group` (board with segment nested inside `(group ...)`, verifies rollback targets only the correct net) and `test_segment_uuid_field_populated_by_parser`.

### CR-02: Three non-atomic write paths in orchestrator.py

**Files modified:** `src/kicad_agent/routing/orchestrator.py`
**Commit:** `4134904`
**Applied fix:** Added `from kicad_agent.io.atomic_write import atomic_write` at top of orchestrator.py. Replaced all 3 bare `pcb_path.write_text(...)` calls with `atomic_write(pcb_path, ...)` at: `_dispatch_freerouting` (line ~485), `rollback_net` (line ~616), `rollback_full` (line ~636). `atomic_write` uses tempfile + fsync + os.replace for crash safety, matching the pattern already used by `PcbIR.commit_raw_content`.

### MD-01: Audit hardcodes `drc_clean=True`

**Files modified:** `src/kicad_agent/routing/orchestrator.py`
**Commit:** `c5748d6`
**Applied fix:** Changed `drc_clean=True` to `drc_clean=False` in the audit entry construction and appended `[drc_deferred_to_board_level]` marker to notes. No per-net DRC is run during `route_board` dispatch, so `False` is distinguishable from a real PASS. The marker makes the deferral reason greppable in the JSONL trail. Phase 98 can later add a board-level DRC pass that sets `drc_clean=True` only when verified.

### MD-02: Orchestrator synthesizes fake `Pin.footprint_ref=f"net_{net_name}"`

**Files modified:** `src/kicad_agent/ir/pcb_ir.py`, `src/kicad_agent/routing/orchestrator.py`
**Commit:** `4fbe7f8`
**Applied fix:** Added `PcbIR.extract_netlist_with_refs()` returning `dict[str, list[(footprint_ref, pad_number, x, y)]]`. The reference designator (e.g., "R1") is preferred when available via `fp.properties.get("Reference")`; `lib_id` (e.g., "Device:R") is the fallback. Updated the orchestrator to use this method instead of synthesizing the fake `f"net_{net_name}"`. `extract_netlist()` (returning `dict[str, list[(x, y)]]`) is preserved unchanged for backward compatibility — many callers depend on its existing signature.

### MD-03: `NativeBoard.general` uses `None  # type: ignore` + `__post_init__` patch

**Files modified:** `src/kicad_agent/parser/pcb_native_types.py`
**Commit:** `adcd73d`
**Applied fix:** Replaced `general: NativeGeneral = None  # type: ignore[assignment]` + `__post_init__` patch with `general: NativeGeneral = field(default_factory=NativeGeneral)`. Deleted `__post_init__`. The `field` import was already added. Cleanly type-safe, no `# type: ignore`, works on frozen dataclasses. Verified no code passes `general=None` explicitly.

### MD-04: `MappingProxyType(dict(self._properties_tuple))` rebuilt on every access

**Files modified:** `src/kicad_agent/parser/pcb_native_types.py`
**Commit:** `2203e0a`
**Applied fix:** Added `_properties_view` field to `NativeFootprint` (default `MappingProxyType({})`). Added `__post_init__` that materializes the view once via `object.__setattr__(self, "_properties_view", MappingProxyType(dict(self._properties_tuple)))`. The `properties` property returns the cached view directly. `dataclasses.replace` correctness preserved: `__post_init__` runs after every replace, rebuilding the view from the (possibly updated) `_properties_tuple`.

### LO-01: `rollback_full` PRE/POST duality undocumented

**Files modified:** `src/kicad_agent/routing/orchestrator.py`
**Commit:** `7657ecf`
**Applied fix:** Added explicit documentation to `rollback_full` docstring explaining that `route_board` pushes two undo entries (PRE and POST), `pop_undo` returns the POST entry first, and a second `rollback_full` call pops the PRE entry restoring the same pre-route state (a no-op masked as success).

### LO-02: `rollback_net` does not invalidate cached `PcbIR` state

**Files modified:** `src/kicad_agent/routing/orchestrator.py`
**Commit:** `7657ecf`
**Applied fix:** Added stale-IR warning to `rollback_net` docstring: any in-memory `PcbIR` held by the caller becomes stale after rollback; callers must re-parse via `NativeParser.parse_pcb` / `PcbIR.from_native` before reading board state again.

### LO-03: `InteractiveRoutingSession._generate_suggestions` silently drops nets with <2 pins

**Files modified:** `src/kicad_agent/routing/interactive.py`
**Commit:** `d563f6c`
**Applied fix:** Nets with 0 or 1 pins are now surfaced as PENDING `RoutingSuggestion` objects with `clearance_violations=["insufficient pins (N)"]` and a warning log, instead of being silently filtered out. `summary()["total_nets"]` now reflects the true net count on the board. Added `logging` import and module-level `logger`.

## Deferred Issues (Bead-tracking per bureaucracy §7.7)

These two findings are structural improvements that touch the Freerouting dispatch path or parser warning aggregation. They are not trivial one-liners and risk regressions if rushed. Per §7.7, they are deferred with concrete resolution plans. **The orchestrator workflow should create `council-deferred` Beads for these from this report.**

### LO-04: Double SES parse in `_dispatch_freerouting`

**File:** `src/kicad_agent/routing/orchestrator.py:491-492`
**Original issue:** `import_ses_into_pcb` already parses the SES internally to extract wires/vias. Then the orchestrator re-reads `fr_result.ses_path` and calls `parse_ses` again at line 491-492 to get per-net attribution. Doubles parse cost and adds an extra file read.
**Resolution plan:**
1. Change `import_ses_into_pcb` signature to return `(content: str, stats: dict, ses_parse: SesParseResult)` — OR add a new variant `import_ses_into_pcb_with_parse(ses_path, pcb_content) -> tuple[str, dict, SesParseResult]`.
2. Update orchestrator to use the returned `SesParseResult` directly instead of calling `parse_ses` again.
3. Update any other callers of `import_ses_into_pcb` (check `src/kicad_agent/routing/freerouting.py` and tests).
4. Add a test verifying `import_ses_into_pcb` is called exactly once per Freerouting dispatch.
**Priority:** LOW (performance — only matters on large boards with many Freerouting-dispatched nets).
**Suggested Bead:** `title="Council deferred: eliminate double SES parse in _dispatch_freerouting"`, `labels="council-deferred,low,performance"`, `priority="3"`.

### LO-05: Noisy unsupported-element warnings

**File:** `src/kicad_agent/parser/pcb_native_parser.py:180-194`
**Original issue:** `_check_unsupported` logs a warning per occurrence. A board with 500 `(thermal_relief_pads ...)` entries logs 500 warnings.
**Resolution plan:**
1. Add a module-level `_unsupported_counts: dict[str, int] = defaultdict(int)` (or thread it through `_build_board` as a local).
2. In `_check_unsupported`, increment `_unsupported_counts[block_name]` instead of logging immediately.
3. At the end of `_build_board`, emit a single aggregated warning per unsupported element type: `logger.warning("Unsupported element '%s' appeared %d times (data preserved in raw_content)", name, count)`.
4. Ensure the aggregation is cleared per-parse (thread-safety: `_build_board` is a classmethod, so use a local dict passed through, or reset at start of `parse_pcb_content`).
5. Update any test that asserts on unsupported-element warning counts.
**Priority:** LOW (noise — only matters on large boards with many unsupported elements).
**Suggested Bead:** `title="Council deferred: aggregate noisy unsupported-element parser warnings"`, `labels="council-deferred,low,noise"`, `priority="3"`.

## Verification Summary

### CR-01 regression tests (new)

```
$ .venv/bin/python -m pytest tests/test_phase100_rollback.py::TestRollbackNetUuidJoin -q
..                                                                       [100%]
2 passed
```

- `test_rollback_with_nested_segment_in_group`: board with top-level + nested-in-group segments; rollback targets ONLY the correct net's segment.
- `test_segment_uuid_field_populated_by_parser`: verifies `NativeSegment.uuid` and `NativeVia.uuid` are populated by the parser.

### Phase 100 suite (76/76 pass — was 74, +2 new CR-01 tests)

```
$ .venv/bin/python -m pytest tests/test_phase100_*.py -q
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 74.91s
```

### Broader regression (338/338 pass)

```
$ .venv/bin/python -m pytest tests/test_pcb_native_parser.py tests/test_pcb_native_types.py \
    tests/test_pcb_native_adapter.py tests/test_routing.py tests/test_routing_submodules.py \
    tests/test_multi_pass_router.py tests/test_routing_geometry.py tests/test_routing_gate.py \
    tests/test_phase62_routing.py tests/test_auto_route_freerouting.py -q
........................................................................ [ 42%]
........................................................................ [ 63%]
........................................................................ [ 85%]
..................................................                       [100%]
338 passed in 17.35s
```

**Combined: 414 tests green, zero regressions.**

### Grep acceptance criteria

- `grep -c "write_text" src/kicad_agent/routing/orchestrator.py` → **0** (only comments mention it; CR-02 closed)
- `grep -c "atomic_write" src/kicad_agent/routing/orchestrator.py` → **5** (1 import + 3 call sites + 1 comment)
- `grep -c "extract_uuids" src/kicad_agent/routing/orchestrator.py` → **0** (CR-01: dropped entirely, join on UUID value)
- `grep -c "f\"net_{net_name}\"" src/kicad_agent/routing/orchestrator.py` → **0** (MD-02: fake footprint_ref removed)
- `grep -c "drc_clean=True" src/kicad_agent/routing/orchestrator.py` → **0** (MD-01: changed to False)
- `grep -c "type: ignore" src/kicad_agent/parser/pcb_native_types.py` → **0** directives (MD-03: only a comment describing the fix remains)
- `grep -c "field(default_factory=NativeGeneral)" src/kicad_agent/parser/pcb_native_types.py` → **1** (MD-03)
- `grep -c "_properties_view" src/kicad_agent/parser/pcb_native_types.py` → **3** (MD-04: field + post_init + property)

---

_Fixed: 2026-06-25T08:05:52Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
