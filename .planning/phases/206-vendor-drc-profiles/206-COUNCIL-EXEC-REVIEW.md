---
phase: 206
plan: 01
review_type: execution
date: 2026-07-10
decision: REJECT
severity_counts:
  critical: 0
  high: 1
  medium: 1
  low: 4
specialists:
  - Architecture Rick
  - Security Rick
  - Quality Rick
  - SLC Rick
  - KiCad Rick
---

# Council of Ricks — Phase 206 Execution Review

**Phase:** 206 — Vendor DRC Profiles
**Execution reviewed:** 21 source/test files across 6 tasks (commit `f9c613a` → `e4fec40`)
**Prior gates:** Plan review REJECTED (ARCH-1 critical) → plan revised → executed → code review (HIGH-1 oshpark, MEDIUM-1 same-net clearance) → fix commit `e4fec40`.
**Phase tests:** 86 passed (`test_vendor_drc`, `test_drc_vendor_ops`, `test_drc_profiles`, `test_registry`).
**Cross-referenced against:** `206-01-PLAN.md`, `206-REVIEW.md`, `206-COUNCIL-PLAN-REVIEW.md`, `REQUIREMENTS.md` (DRC-01..08), `AGENTS.md`.

---

## Executive Summary

The execution is **architecturally sound and the core deliverable works**. The critical plan-review defect (ARCH-1 — evaluator reading kiutils `Board` instead of `NativeBoard`) is correctly fixed: the handler re-parses via `NativeParser.parse_pcb(file_path)` and passes a `NativeBoard` to `run_vendor_drc`, with an explicit CRITICAL docstring citing the Phase 205 precedent. The internal evaluator's geometry math is correct (segment-gap, annular-ring formula, clearance corridor, `_EPS` tolerance), the `NativeVia.diameter` field name is right, and the evaluator empirically detects violations on a deliberately-violating board through the handler path. Both code-review findings (HIGH-1 oshpark alias, MEDIUM-1 same-net clearance) are genuinely applied and verified working end-to-end. The threat model is well-defended at both layers, package-data is wired, and SLC compliance is clean across all new/modified source files.

**However, the HIGH-1 fix introduced a regression that breaks an existing test.** Adding the `"oshpark": _OSH_PARK` alias to `_PROFILES` brought the built-in profile count from 10 to 11 and added an `oshpark` key, but `tests/test_dfm_checker.py::test_builtin_profiles_exist` (which asserts an *exact* set of keys and an exact count `== 10`) was not updated. This test now fails. It is a direct, demonstrable consequence of the HIGH-1 fix commit `e4fec40`, and it is *not* a pre-existing failure (it passed at the Task 6 summary commit `8c88253` immediately before the fix). This is a one-line fix (add `"oshpark"` to the expected set and bump the count to 11), but it is a real red test in the suite, so the verdict is REJECT until the regression is closed.

The code-review findings that remain open (LOW-1 through LOW-3, NIT-1, NIT-2) are acceptable as follow-ups and do not block approval. The pre-existing full-suite failures (92 failures in unrelated modules, including the `SKILL.md` "149 operations" drift in `test_slc_compliance`) predate Phase 206 and are correctly out of scope.

Decision: **REJECT** — fix the one broken test (`test_dfm_checker.py::test_builtin_profiles_exist`) introduced by the HIGH-1 alias. Everything else is approvable.

---

## Specialist Findings

### Architecture Rick — Dual-path correctness, evaluator data source

**Verdict: CORRECT. The ARCH-1 critical defect from the plan review is properly fixed.**

Verified against the codebase:

- **`_handle_drc_vendor` (`query.py:88-127`) re-parses via `NativeParser.parse_pcb(file_path)`.** Line 107: `board = NativeParser.parse_pcb(file_path)`. Line 108: `result = run_vendor_drc(board, profile)`. The evaluator receives a `NativeBoard`, NOT the kiutils-path `ir.board`. This is exactly the fix the plan review required. The handler carries an explicit `CRITICAL:` docstring (lines 95-99) documenting the `_native_board is None` issue and citing the Phase 205 `read_board_metadata` precedent. This is exemplary — the lesson was carried forward.
- **`run_vendor_drc(board: Any, profile)` is decoupled from `PcbIR.board`.** The signature takes a board object (duck-typed via `getattr`), not a `PcbIR`. This matches the plan-review recommendation to decouple the evaluator from the kiutils-vs-native ambiguity. The `Any` type hint is pragmatic: the evaluator uses `getattr(board, "segments", ())` etc., so any object exposing `segments`/`vias`/`footprints` works, including test doubles.
- **`ir` is not used in the drc_vendor handler** beyond the signature (it is a positional argument `execute_query` passes). The handler does not touch `ir.board` or `ir.native_board`. Confirmed by reading the full handler body (lines 100-127).
- **`list_vendor_drc_profiles` handler ignores `ir`/`file_path` entirely** (lines 130-143) — correct, it returns static registry data.

**No new architecture findings.** The dual-path issue that was the plan review's CRITICAL is resolved at the code level.

### Security Rick — Path traversal, malformed board handling

**Verdict: SOUND. Dual-layer defense verified empirically. Both threat-model scenarios mitigated.**

**Scenario 1 — path traversal via vendor name (verified end-to-end):**
- Schema layer: `DrcVendorOp.vendor` carries `pattern=r"^[a-z0-9_]+$"` (`_schema_pcb.py:1260`). Empirically confirmed: `Operation.model_validate` with `vendor="../../etc/passwd"` raises `ValidationError`.
- Resolver layer: `get_drc_profile_path` re-validates `^[a-z0-9_]+$` AND checks `path.is_file()` (`drc_profiles/__init__.py:187-196`). Empirically confirmed: blocked `../../etc/passwd`, `../x`, `a/b`, `a.b`, `OSH`, `osh park` — all raise `ValueError`.
- No injection vectors: the DRU files are static package data (no `eval`, no template interpolation); `run_drc(file_path)` passes args as a list (no `shell=True`). Clean.

**Scenario 2 — malformed board crashes evaluator (verified by code + test):**
- Every geometry access uses `getattr(obj, field, default)` with safe defaults (`vendor_drc.py:114-116, 181, 186-187, 214, 241, 275-277, 309-311, 346`).
- Each of the 5 checks is wrapped in its own `try/except` (`vendor_drc.py:119-161`) — one bad feature never aborts the run.
- `width 0.0` and missing-width cases degrade to a default (`vendor_drc.py:181-184`).
- `test_evaluator_does_not_crash_on_malformed_geometry` and `test_evaluator_does_not_crash_on_empty_board` both pass.

**[SEC-2, LOW (pre-existing, not a regression)] `NativeParser.parse_pcb` can raise on a malformed PCB file.** The handler (`query.py:107`) calls `NativeParser.parse_pcb(file_path)` with no try/except. If the PCB is malformed enough that the native parser raises (rather than returning a partially-populated board), the exception propagates out of the handler. This is consistent with how other query handlers behave (they generally do not wrap parser calls) and the executor layer handles unexpected exceptions, so it is not a new vulnerability — but worth noting that the evaluator's "never re-raises" contract does not extend to the parse step that feeds it. Non-blocking; consistent with the codebase pattern.

### Quality Rick — Test coverage, evaluator correctness, regression

**Verdict: STRONG evaluator coverage, but the HIGH-1 fix left one existing test red.**

**Strengths (verified):**
- **The silent-pass guard holds.** The evaluator empirically detects violations: track width 0.1mm < 0.2mm generic → `vendor_trace_width` violation; same-net clearance produces 0 false positives (MEDIUM-1 fix verified); different-net clearance at 0.1mm gap → `vendor_clearance` violation. This is the highest-risk failure mode and it is guarded.
- **Handler-path resolution covered for all 9 vendors.** Empirically confirmed: every key in `list_drc_profiles()` resolves via `load_profile()` (the handler path). The HIGH-1 oshpark mismatch is fixed — `load_profile("oshpark")` returns the profile.
- **Read-only behavior verified.** `test_drc_vendor_file_mtime_unchanged` confirms the op does not mutate the PCB.
- **Path-traversal tested at both layers** (schema + resolver).
- **Per-check coverage** for all 5 constraint classes with violating and passing variants.

**[QUAL-EXEC-1, HIGH — REGRESSION] `tests/test_dfm_checker.py::test_builtin_profiles_exist` is broken by the HIGH-1 fix.** This is the blocking finding. The fix commit `e4fec40` added `"oshpark": _OSH_PARK` to `_PROFILES` (one line) but did not update this test, which asserts an *exact* set of keys and `len(profiles) == 10`. The alias makes the count 11 and adds `oshpark` to the keys. Reproduced:

```
tests/test_dfm_checker.py:67: AssertionError: assert {...} == {...}
  Extra items in the left set:
  'oshpark'
FAILED tests/test_dfm_checker.py::TestManufacturerProfile::test_builtin_profiles_exist
```

Git bisect confirms: the test passed at commit `8c88253` (Task 6 summary, immediately before the fix) and fails at `e4fec40` (the fix). This is not a pre-existing failure — it is a direct consequence of the HIGH-1 fix. The Task 2 commit `ed3235f` had correctly updated this same test to expect 10 profiles; the fix invalidated that update.

**Fix (one-line, mechanical):** in `tests/test_dfm_checker.py:67-72`, add `"oshpark"` to the expected set and change the count to `11`:
```python
assert set(profiles.keys()) == {
    "jlcpcb", "jlcpcb-4layer", "pcbway", "osh_park", "oshpark", "generic",
    "advanced_circuits", "aisler_2layer", "aisler_4layer",
    "aisler_6layer", "aisler_8layer",
}
assert len(profiles) == 11
```

**Why this blocks approval:** the council's standing rule is that the suite must be green for the changed surface. `test_dfm_checker.py` is in the modified-files set (Task 2 touched it) and was green before the fix; the fix made it red. This is the kind of regression a full-suite run is meant to catch, and the summary's claim of "no regressions in this plan's changes" is inaccurate for this one test.

**[QUAL-EXEC-2, LOW — pre-existing, correctly out of scope] 92 full-suite failures unrelated to Phase 206.** The summary correctly identifies these as pre-existing (in `test_schematic_repair`, `test_undo_stack`, `test_training_eval`, etc.) with zero file overlap. The `test_slc_compliance::test_skill_md_operation_count_matches` failure (SKILL.md says "149", schema now has 156) is documentation drift that predates Phase 206 (it was already stale at 154 from Phase 205). Not a regression introduced here.

### SLC Rick — No workarounds, no stubs, complete solutions

**Verdict: COMPLIANT across all new/modified source files.**

- **No stubs, TODOs, FIXMEs, NotImplemented, HACK, or placeholder markers** in any of the new/modified source files (`vendor_drc.py`, `drc_profiles/__init__.py`, `query.py`, `profiles.py`, `_schema_pcb.py`, `schema.py`, `registry.py`). Grep returned exit 1 (no matches).
- **Every check is fully implemented**, not stubbed: all 5 checks (`_check_track_width`, `_check_drill_size`, `_check_annular_ring`, `_check_via_diameter`, `_check_clearance`) have complete logic with real geometry math, not `pass` bodies.
- **The `run_kicad_drc` optional branch degrades gracefully** (`except Exception → {"error": str(exc)}`) — this is a documented design decision for an external binary that may be absent in test/dev, not a stub. Appropriate.
- **Frozen dataclasses** (`VendorDrcResult`, `VendorDrcProfileInfo`) and tuple collections are consistent with the project's CR-01 immutability rule.
- **Deferred items are correctly out of scope** (CLI subcommands, MCP exposure, vendor APIs) per ROADMAP/CONTEXT. No scope creep.

The one open SLC item from the plan review (SLC-1: authoritative `passed` semantics when `run_kicad_drc=True`) is resolved by clear documentation: the handler comment (`query.py:125-126`) explicitly states `passed` reflects VENDOR DRC only and `kicad_drc` is separate. The `must_haves`/RESEARCH framing treats vendor DRC as the gate, with KiCad DRC as supplementary — this is a defensible contract and it is documented at the point of ambiguity.

### KiCad Rick — DRU files, vendor specs, source-of-truth consistency

**Verdict: ACCURATE. DRU files are correct and the OSH Park value-drift flagged at plan review (KCAD-1) was resolved in the right direction.**

- **9 DRU files ship with attribution headers** (Source/License/Last-verified/Vendor/Capabilities) — verified, 1 attribution per file.
- **PCBWay/JLCPCB annular ring = 0.15mm** in both DRU files and `_PROFILES` (DRC-07, not stale 0.25mm/0.1mm).
- **AISLER 0.2mm annular hard limit** present and larger than JLC/PCBWay.
- **No `--custom-rules` invocation** — grep confirms the only occurrence is the docstring explaining the pivot. The evaluator is pure-Python.
- **KCAD-1 (OSH Park value-drift) was resolved by making the DRU file match the conservative profile, not vice-versa.** The shipped `oshpark.kicad_dru` uses 0.3556mm drill / 0.1524mm annular (the existing `_OSH_PARK` values), which is *more conservative* than OSH Park's actual published limits (0.254mm / 0.127mm). This is the safe direction — the evaluator will reject some boards OSH Park would accept, but will never pass a board OSH Park rejects. This satisfies the "source of truth" consistency requirement (DRU file and `ManufacturerProfile` now agree) even though both are slightly tighter than the vendor's real spec. Acceptable.
- **`via_diameter` constraint name** is used consistently in the DRU files (KCAD-2 from plan review, LOW, non-blocking).

**[KCAD-EXEC-1, LOW — pre-existing, documented by code review] `_JLCPCB_4LAYER` still has `min_annular_ring_mm=0.1`** and is keyed `jlcpcb-4layer` (hyphen, unreachable via the op schema pattern). This predates Phase 206 and is out of DRC-07's stated scope (which targeted 2-layer profiles). The code review (LOW-1, LOW-2) correctly flagged it as a follow-up. Non-blocking.

**[KCAD-EXEC-2, LOW — documented v1 limitation] Top-level `(arc ...)` tracks are not evaluated.** The evaluator checks `board.segments` only. This is consistent with the "v1 track-to-track" framing and is noted in the code review (LOW-3). Non-blocking.

---

## Code-Review Fix Verification

The two findings from `206-REVIEW.md` were the focus of this gate. Both are verified applied AND working:

| Finding | Status | Evidence |
|---------|--------|----------|
| **HIGH-1** `oshpark` key unreachable (`_PROFILES` had `osh_park`, registry had `oshpark`) | **APPLIED** | `profiles.py:261` adds `"oshpark": _OSH_PARK` alias. Empirically verified: `load_profile("oshpark")` resolves to OSH Park profile; all 9 advertised keys now resolve via the handler path. **HOWEVER** the fix introduced QUAL-EXEC-1 (regression in `test_dfm_checker.py`). |
| **MEDIUM-1** same-net clearance false positives | **APPLIED** | `vendor_drc.py:413` adds `if net1 and net2 and net1 == net2: continue`. Empirically verified: two same-net (GND) segments 0.1mm apart produce 0 clearance violations; two different-net segments at the same gap produce 1 violation. The `net1 and net2` guard correctly preserves checking of unnamed nets. |

MEDIUM-2 (test gap that allowed HIGH-1 to ship) was addressed: `test_drc_vendor_all_vendor_keys_valid` and the per-vendor handler tests now exist. The fix commit's scope was the two findings; the missed test update (QUAL-EXEC-1) is the gap.

---

## Requirement Coverage Check (DRC-01 through DRC-08)

All 8 requirements are implemented in code. (Note: the REQUIREMENTS.md checkboxes remain unchecked `[ ]` — that is the orchestrator's bookkeeping, not a coverage gap.)

| REQ | Implemented? | Evidence | Notes |
|-----|--------------|----------|-------|
| DRC-01 (run vendor DRC) | YES | `drc_vendor` op + `run_vendor_drc` evaluator + handler; silent-pass guard test passes; detects violations end-to-end | Core deliverable works. |
| DRC-02 (DRU files: PCBWay, JLCPCB, AISLER 2/4/6/8L) | YES | 9 DRU files exist with attribution | Verified by `ls` + grep. |
| DRC-03 (OSH Park + Advanced Circuits) | YES | `oshpark.kicad_dru`, `advanced_circuits.kicad_dru`, both profiles resolvable | OSH Park now reachable via `oshpark` key (HIGH-1 fix). |
| DRC-04 (generic conservative) | YES | `generic.kicad_dru` + `_GENERIC_CONSERVATIVE`; `drc_vendor(vendor="generic")` works | Generic min_drill=0.4mm (corrected from stale 0.3mm). |
| DRC-05 (drc_rules_path field) | YES | `ManufacturerProfile.drc_rules_path` (`profiles.py:57`); wired on all 10 profiles | |
| DRC-06 (attribution headers) | YES | Every DRU file has Source/License/Last-verified/Vendor/Capabilities | `test_all_dru_files_have_attribution` passes. |
| DRC-07 (PCBWay annular 0.15mm) | YES | `pcbway.kicad_dru` annular_width 0.15mm; `_PCBWAY_STANDARD.min_annular_ring_mm=0.15`; same for JLCPCB | Not the stale 0.1mm/0.25mm. |
| DRC-08 (list profiles query) | YES | `list_vendor_drc_profiles` returns 9 profiles with all capability fields | `test_list_vendor_drc_profiles_returns_9` passes. |

No orphan requirements. No partial implementations.

---

## Pytest Result

```
$ pytest tests/test_vendor_drc.py tests/test_drc_vendor_ops.py tests/test_drc_profiles.py tests/test_registry.py
86 passed in 1.95s

$ pytest tests/test_dfm_checker.py
1 failed (test_builtin_profiles_exist), 37 passed
```

The 4 Phase-206 test files are green (86 passed). The regression is in `test_dfm_checker.py`, which is in the modified-files set and was green before the HIGH-1 fix.

---

## Severity Summary

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 0 | — |
| High | 1 | QUAL-EXEC-1 (test_dfm_checker regression from HIGH-1 fix) |
| Medium | 0 | — (MEDIUM-1 same-net clearance is fixed) |
| Low | 4 | SEC-2, QUAL-EXEC-2, KCAD-EXEC-1, KCAD-EXEC-2 (all pre-existing or documented v1 limitations) |
| Nit | 0 | (NIT-1/NIT-2 from code review are unchanged, acceptable) |

---

## Recommendations (ordered by priority)

1. **(HIGH, must fix before merge) [QUAL-EXEC-1]** Update `tests/test_dfm_checker.py::test_builtin_profiles_exist` to account for the `oshpark` alias: add `"oshpark"` to the expected key set and bump the count assertion `10 → 11`. One-line fix. This closes the only red test in the changed surface.

2. **(LOW, follow-up) [KCAD-EXEC-1]** Align or document `_JLCPCB_4LAYER` (0.1mm annular, hyphenated key) — either add a DRU companion + underscore alias, or comment that it is intentionally a pre-existing entry without a DRU.

3. **(LOW, follow-up) [KCAD-EXEC-2]** Add a docstring note that top-level `(arc ...)` tracks are out of scope for v1 (currently a silent skip); ideally track a follow-up to parse arcs.

4. **(LOW, opportunistic) [SEC-2]** Consider wrapping `NativeParser.parse_pcb(file_path)` in the handler so a malformed board returns a `VendorDrcResult` with `error_message` rather than raising — consistent with the evaluator's "never re-raises" contract. Not a regression; matches codebase pattern.

5. **(NIT, follow-up)** Rename `test_registry_has_98_operations` (code review NIT-1) and update `skills/SKILL.md` line 31 ("149 operations" → current count) to clear the stale `test_slc_compliance` failure. Both predate Phase 206.

---

## Decision

# REJECT

**Rationale:** The execution is high-quality. The ARCH-1 critical defect from the plan review is correctly fixed (handler re-parses to `NativeBoard`; evaluator decoupled from `PcbIR.board`). Both code-review findings (HIGH-1 oshpark alias, MEDIUM-1 same-net clearance) are genuinely applied and verified working end-to-end. All 8 DRC requirements are implemented and covered by tests. The threat-model defenses hold at both layers. SLC compliance is clean.

The sole reason for REJECT is **QUAL-EXEC-1**: the HIGH-1 fix commit (`e4fec40`) added the `oshpark` alias to `_PROFILES` but did not update `tests/test_dfm_checker.py::test_builtin_profiles_exist`, which asserts an exact key set and an exact count. That test was green before the fix and is red after it — a direct, demonstrable regression in the changed surface. The fix is one line (add `"oshpark"` to the expected set, bump `10 → 11`).

**Required for approval:**
- QUAL-EXEC-1 resolved (`test_dfm_checker.py::test_builtin_profiles_exist` updated for the `oshpark` alias; `pytest tests/test_dfm_checker.py` green).

No other changes are required. Once that single test is updated, the phase is APPROVE-eligible.
