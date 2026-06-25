---
phase: 100-routingorchestrator-and-human-approval-loop
fixed_at: 2026-06-25T18:39:39Z
review_path: .planning/phases/100-routingorchestrator-and-human-approval-loop/100-COUNCIL-EXEC-REVIEW.md
iteration: followup
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---

# Phase 100: Follow-up Code Review Fix Report

**Fixed at:** 2026-06-25T18:39:39Z
**Source review:** `.planning/phases/100-routingorchestrator-and-human-approval-loop/100-COUNCIL-EXEC-REVIEW.md` (Round 2 APPROVE — LO-04, LO-05 deferred)
**Source review (cross-phase):** `.planning/phases/98-ai-routing-strategy-advisor/98-COUNCIL-EXEC-REVIEW.md` (ME-05 / H-1 out-of-scope Bead)
**Iteration:** followup

**Summary:**
- Findings in scope: 3 (2 LOW deferred from Round 2 + 1 MEDIUM cross-phase H-1)
- Fixed: 3
- Skipped: 0

**Test results (final):**
- Phase 100 + routing regression suite: **420/420 pass** (was 414 at Round 2 APPROVE; +6 new tests)
- Zero regressions

## Per-Finding Status Table

| ID | Severity | Title | Status | Commit |
|----|----------|-------|--------|--------|
| LO-04 | LOW | Double SES parse / double file read in rollback_net | **fixed** | `558b497` |
| LO-05 | LOW | Noisy warnings from DeterministicStrategy population | **fixed (invariant locked)** | `628349d` |
| H-1 / ME-05 | MEDIUM | routing_notes not in durable JSONL audit trail | **fixed** | `127c908` |

## Fixed Issues

### LO-04: Double parse + double file read in rollback_net

**Files modified:** `src/kicad_agent/routing/orchestrator.py`, `tests/test_phase100_rollback.py`
**Commit:** `558b497`
**Applied fix:** `rollback_net` previously called `NativeParser.parse_pcb(pcb_path)` (which reads the file internally) then separately `pcb_path.read_text()` for the raw string `PcbRawWriter` needs — doubling file I/O on every rollback. The fix reads raw content once via `pcb_path.read_text()`, then calls `NativeParser.parse_pcb_content(raw, ...)` to parse the cached string. The post-rollback undo snapshot also no longer re-reads the file (post content == `raw` just written). Net result: 1 read + 1 parse-from-content (was 2 reads + 1 parse-from-path).

**Acceptance verification (AST-confirmed):**
- `rollback_net` body contains exactly 1 parse call (`parse_pcb_content`) and 1 `read_text` call
- Regression test `test_rollback_net_parses_pcb_once` patches `NativeParser.parse_pcb_content` and asserts call count == 1

### LO-05: Noisy warnings from DeterministicStrategy population

**Files modified:** `tests/test_phase100_strategy.py`
**Commit:** `628349d`
**Applied fix:** The grep acceptance criterion ("No `logger.warning` in `DeterministicStrategy` populating net_class_map/differential_pairs") was already satisfied — `strategy.py` has zero `logger.warning` calls and zero `logging` imports. The fix adds a regression test (`test_deterministic_strategy_no_warnings_on_normal_population`) that locks in the invariant: `caplog` captures zero WARNING-or-higher records from the strategy module during `strategize()` with a fully-populated `net_class_map` (6 entries) and `differential_pairs` (2 pairs). Protects against future regressions where diagnostic warnings fire on every populated entry.

**Acceptance verification:**
- `grep -c "logger.warning" src/kicad_agent/routing/strategy.py` → **0**
- New test asserts zero WARNING records in caplog during population

### H-1 / ME-05: routing_notes not in durable JSONL audit trail

**Files modified:** `src/kicad_agent/routing/audit.py`, `src/kicad_agent/routing/orchestrator.py`, `tests/test_phase100_audit.py`
**Commit:** `127c908`
**Applied fix:**
1. Added `strategy_notes: str = ""` field to `RoutingAuditEntry` (defaults to empty for backward compatibility with pre-H-1 audit lines)
2. Updated `_entry_to_dict` to serialize `strategy_notes` to JSONL
3. Updated `_dict_to_entry` to deserialize `strategy_notes` (missing key → `""`)
4. Populated `strategy_notes=strategy_result.routing_notes` in the audit entry construction in `route_board` (orchestrator.py ~line 307)

For `DeterministicStrategy` this persists a static descriptor. For `AiRoutingStrategy` it carries the `ai_fallback:` prefix when the model failed and the deterministic fallback handled dispatch — closing the gap where the durable trail could not distinguish a real AI win from a silent fallback.

**Tests added (4):**
- `test_audit_entry_includes_strategy_notes`: verifies notes flow through to JSONL on append
- `test_strategy_notes_round_trips_through_query_by_net`: verifies serialize → deserialize → query round-trip preserves the `ai_fallback:` prefix
- `test_strategy_notes_defaults_to_empty_string`: backward compat — pre-H-1 audit lines missing the key deserialize to `""`
- `test_ai_fallback_marker_persists_to_audit`: end-to-end test with a stub strategy mimicking AiRoutingStrategy's R-6 fallback; verifies the `ai_fallback:` prefix reaches the durable JSONL file via the orchestrator on a real board fixture

**Acceptance verification:**
- `grep -c "strategy_notes" src/kicad_agent/routing/audit.py` → **5** (field, docstring, serialize, deserialize, +1 in docstring body)
- `grep -c "strategy_notes=strategy_result.routing_notes" src/kicad_agent/routing/orchestrator.py` → **1**

## Verification Summary

### LO-04 regression test (new)

```
$ .venv/bin/python -m pytest tests/test_phase100_rollback.py::TestRollbackNetParsesPcbOnce -q
.                                                                        [100%]
1 passed
```

### LO-05 regression test (new)

```
$ .venv/bin/python -m pytest tests/test_phase100_strategy.py::TestDeterministicStrategyNoWarningsOnPopulation -q
.                                                                        [100%]
1 passed
```

### H-1 regression tests (new)

```
$ .venv/bin/python -m pytest tests/test_phase100_audit.py::TestStrategyNotesPersistsToAudit tests/test_phase100_audit.py::TestAiFallbackMarkerPersistsToAudit -q
....                                                                     [100%]
4 passed
```

### Full Phase 100 + routing regression suite (420/420 pass)

```
$ .venv/bin/python -m pytest tests/test_phase100_*.py tests/test_pcb_native_parser.py \
    tests/test_pcb_native_types.py tests/test_pcb_native_adapter.py \
    tests/test_routing.py tests/test_routing_submodules.py \
    tests/test_multi_pass_router.py tests/test_routing_geometry.py \
    tests/test_routing_gate.py tests/test_phase62_routing.py \
    tests/test_auto_route_freerouting.py -q
........................................................................ [ 17%]
........................................................................ [ 34%]
........................................................................ [ 51%]
........................................................................ [ 68%]
........................................................................ [ 85%]
............................................................             [100%]
420 passed in 111.23s
```

**Combined: 420 tests green, zero regressions.** (Was 414 at Round 2 APPROVE; +6 new tests: 1 LO-04, 1 LO-05, 4 H-1.)

### Grep Acceptance Criteria

| Criterion | Expected | Actual | Status |
|---|---|---|---|
| `rollback_net` parse calls (AST) | 1 | 1 (`parse_pcb_content`) | PASS |
| `rollback_net` read_text calls (AST) | 1 | 1 | PASS |
| `grep -c "logger.warning" strategy.py` | 0 | 0 | PASS |
| `grep -c "strategy_notes" audit.py` | >=3 | 5 | PASS |
| `grep -c "strategy_notes=strategy_result.routing_notes" orchestrator.py` | 1 | 1 | PASS |

## Notes

- The LO-05 finding was originally deferred as "aggregate noisy unsupported-element parser warnings" (`pcb_native_parser.py:180-194`). The follow-up task refocused it on `DeterministicStrategy` population warnings. Inspection confirmed `strategy.py` already has zero `logger.warning` calls — the grep criterion was met by inspection. The regression test was added to lock in the invariant.
- The H-1 / ME-05 finding was carried as an out-of-scope Bead from Phase 98 Plan 02 (`98-02-SUMMARY.md:97`). It is now fully resolved in Phase 100 source. The Phase 98 Bead can be closed.

---

_Fixed: 2026-06-25T18:39:39Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: followup_
