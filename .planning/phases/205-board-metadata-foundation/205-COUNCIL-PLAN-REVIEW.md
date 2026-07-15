---
phase: 205
plan: 01
review_type: plan
date: 2026-07-10
decision: APPROVE
severity_counts:
  critical: 0
  high: 1
  medium: 4
  low: 3
specialists:
  - Architecture Rick
  - Security Rick
  - Quality Rick
  - SLC Rick
  - KiCad Rick
---

# Council of Ricks — Phase 205 Plan Review

**Phase:** 205 — Board Metadata Foundation
**Plan reviewed:** `205-01-PLAN.md` (6 tasks, wave 1, autonomous)
**Supporting docs:** `205-CONTEXT.md`, `205-RESEARCH.md`, `205-VALIDATION.md`
**Cross-referenced against:** `ROADMAP.md` (phase 205), `REQUIREMENTS.md` (META-01..07), `PITFALLS.md` (Pitfall 2), `AGENTS.md`

**Prior gate status:** Plan-checker passed with 0 BLOCKERs, 3 WARNINGs (all reported fixed).

---

## Executive Summary

This is a well-researched, well-structured plan. The two CRITICAL architectural decisions — (1) mutation path via raw-writer + `commit_raw_content` because the serializer does not emit typed `title_block`, and (2) query path reading from `ir.raw_content` because `execute_query` uses the kiutils path, not the native parser — are correct, verified against the codebase, and correctly propagated through every task. The research file (RQ1, RQ2) did the hard work of proving these constraints; the plan honors them.

Requirement coverage is complete: all 7 META requirements map to specific tasks and acceptance criteria. The `must_haves` list is concrete and falsifiable.

The findings below are execution hazards (one import path error that will break Task 6 tests, one enum typo that will persist to sidecar JSON) and a few robustness gaps in the raw-writer insertion/replace logic. None are architectural. Decision: **APPROVE** with the high-severity finding fixed before or during Task 6 execution.

---

## Specialist Findings

### Architecture Rick — Pattern consistency, mutation path correctness

**Verdict: SOUND.** The plan demonstrates strong architectural discipline.

**Strengths verified against codebase:**
- Mutation path is correct. Confirmed `serialize_pcb` (`pcb_ser.py:65`) calls `kiutils_obj.to_file()` and does NOT emit `NativeBoard` fields. The plan's decision to use the raw-writer + `commit_raw_content` path (Task 3 → Task 5b) is the only viable approach. This matches the `move_footprint` / `assign_net_class` handler precedent.
- Query path is correct. Confirmed `execute_query` (`execution.py:193-230`) builds PcbIR via `parse_pcb` (kiutils), not native parser. The plan's `read_board_metadata` handler (Task 5a) correctly parses from `ir.raw_content` via `sexpdata.loads` + native helpers, NOT `ir.board.title_block`. This would have been a silent no-op bug if gotten wrong.
- The `raw_written` skip logic is real. Confirmed `execution.py:533` (`if not ir.raw_written and parse_result is not None`). After `commit_raw_content` sets `_raw_written = True`, the executor skips serialization. The mutation will land on disk. Verified `commit_raw_content` (`pcb_ir.py:1109`) does atomic_write + hash verification (D-14).
- Handler placement follows precedent: read-only in `handlers/query.py` (`@register_query`), mutating in `handlers/pcb.py` (`@register_pcb`). No new handler module, so Integration Pitfall IP-3 (merge) does not apply. Correctly noted in the plan.
- Task 4 is correctly atomic (schema + registry + union together). This avoids IP-2 (schema union drift / `validate_registry_completeness` failure).

**MEDIUM — [ARCH-1] `read_board_metadata` mutates a frozen dataclass path that the query path doesn't use, so the typed `NativeTitleBlock` (Task 1) is structurally coupled to the mutating `execute_pcb` path but NOT the query path.** The plan handles this correctly (query handler re-parses raw content), but this dual-path asymmetry is worth a code comment in the query handler so future maintainers don't "helpfully" switch it to `ir.board.title_block`. The plan's Task 5a docstring does say "CRITICAL: execute_query uses kiutils path" — good. Recommend the implementing agent keep that comment.

**LOW — [ARCH-2] `_handle_set_board_metadata` return value is inconsistent with `read_board_metadata` return value.** The set handler returns `{"title": op.title, ...}` which yields `None` for unspecified fields, while read returns actual stored strings. The plan's `test_set_board_metadata_partial_update` sidesteps this by re-reading via the query handler. Not a bug (the tests pass), but the return contract is muddy. Minor.

### Security Rick — Path traversal, file corruption vectors

**Verdict: ACCEPTABLE.** Threat model is present, specific, and traces to real mitigations.

**Verified threat model claims:**
- `TargetFile` path validation exists and is robust. Confirmed `_validate_target_file` (`schema.py:143-159`) rejects null bytes, absolute paths, `..` traversal, and non-KiCad extensions. The `target_file` field on all 3 new Op classes flows through this validator.
- `atomic_write` (`io/atomic_write.py:15`) uses tempfile in `file_path.parent` + `os.fsync` + `os.replace`. Crash-safe. The sidecar write via `save_board_spec` reuses this canonical function (not a hand-rolled tempfile). Correct.
- Block-level rebuild strategy for `set_title_block_fields` eliminates partial-update corruption: the method reads existing values, rebuilds the entire `(title_block ...)` from typed Python strings, and replaces the whole block. Field values are double-quoted; embedded quotes doubled per KiCad convention. No string interpolation into existing content = no injection vector. Sound.

**MEDIUM — [SEC-1] Threat Model Scenario 1 slightly overstates the protection for the sidecar write path.** The sidecar path is derived from `pcb_path` via `Path.with_suffix()`, which is safe (suffix replacement only). The threat model claims "existing path validation suffices." This is true *only because* `pcb_path` arrives as the already-resolved `file_path` from the executor (which resolved it from a `TargetFile`-validated `target_file`). If a future caller invokes `save_board_spec` or `load_board_spec` with an arbitrary path (not via an Op), the `TargetFile` validator is not in the chain. Since both functions are public (`manufacturing/__init__.py` exports them), recommend either (a) documenting that callers must supply a validated path, or (b) the executing agent confirm the only call sites are the 2 handlers. Not a blocker — the MCP/CLI surface is auto-generated from Ops, so external callers go through `TargetFile`. Note for the execution reviewer to verify no direct `save_board_spec` exposure lands in Phase 209 without path validation.

**LOW — [SEC-2] `kicad-cli` subprocess call in `test_modified_pcb_loads_in_kicad_cli` does not use shell=True and passes args as a list — correct.** The `pcb_path` is `tmp_path`-scoped. No injection. Fine.

### Quality Rick — Test coverage, round-trip fidelity, edge cases

**Verdict: STRONG coverage, one concrete test bug.**

**Strengths:**
- Round-trip fidelity is thoroughly tested: `test_set_board_revision_round_trip`, `test_set_board_metadata_partial_update`, `test_title_block_special_chars_round_trip`, plus `kicad-cli pcb export stats` structural validation (Task 6c). This directly addresses META-06 and Pitfall 2.
- Non-sequential comments (1, 3, 9 with gaps) are explicitly tested in both the parser (Task 6a `test_title_block_non_sequential_comments`) and operation (Task 6b `test_set_board_metadata_comments`). Good — this is the trickiest title_block edge case.
- Empty-string fields vs. absent fields distinction is tested (`test_title_block_empty_string_fields`). Correct — these must round-trip differently.
- BoardSpec JSON round-trip + impedance tuple serialization tested. Defaults tested.

**HIGH — [QUAL-1] Task 6b test helper `_build_ir` imports `extract_uuids` from the wrong module, and references a non-existent `SMD_TEST_BOARD` constant. This will cause test collection failures, not logic failures.**
The `_build_ir` helper in Task 6b uses:
```python
from volta.ops.pcb_ops import extract_uuids
```
`extract_uuids` actually lives in `volta.parser.uuid_extractor` (verified: `tests/test_pcb_ops.py:23` imports `from volta.parser.uuid_extractor import extract_uuids`). The Task 6b import will raise `ImportError` at test collection time, failing the entire `test_board_metadata_ops.py` file. Separately, Task 1 acceptance criteria and Task 6a reference `SMD_TEST_BOARD` and `NativeParser.parse_pcb(SMD_TEST_BOARD)`, but no `SMD_TEST_BOARD` constant exists in `tests/test_pcb_native_parser.py` (verified by grep — zero matches). The plan even hedges ("Ensure `SMD_TEST_BOARD` path constant exists (if not, use `tests/fixtures/smd_test_board.kicad_pcb` directly)") but the acceptance criterion `b.title_block is None` on `smd_test_board.kicad_pcb` still needs that fixture to actually lack a title_block (verified in RESEARCH.md line 29: it has no title_block — good).
**Action:** Before executing Task 6, fix the import to `from volta.parser.uuid_extractor import extract_uuids`. Resolve the `SMD_TEST_BOARD` reference to a concrete path literal or add the module constant. This is a one-line fix but must happen or Task 6 acceptance criteria cannot pass.

**MEDIUM — [QUAL-2] No test for the "insert when absent, but also no `(paper ...)`" fallback chain in `set_title_block_fields`.** The method has a 3-tier fallback: existing block → after `(paper ...)` → after `(kicad_pcb ...)` → no-op. The plan tests "inserts when absent" (Task 6b `test_set_board_metadata_inserts_when_absent`) but that fixture includes `(paper "A4")`, so it only exercises tier 2. Tiers 3 and 4 (no paper line; total fallback) are untested. Since the `(kicad_pcb ...)` regex `r"^[ \t]*\(kicad_pcb[^\n]*\n"` is also fragile (what if the first line is `(kicad_pcb (version ...))` with the close paren on a later line?), recommend adding one test with a paper-less board. Not a blocker — tier 2 covers the common case.

**MEDIUM — [QUAL-3] No test verifies that a board WITHOUT a title_block that gets one inserted still passes `kicad-cli pcb export stats`.** Task 6c validates modification of an *existing* title_block. The insertion path (which synthesizes a whole new block including the closing paren placement) is the higher-risk write path and should get the same structural validation. Recommend extending Task 6c or adding a second `kicad-cli` test for the insert case.

### SLC Rick — No workarounds, no stubs, complete solutions

**Verdict: COMPLIANT.** No stubs, no `TODO`s, no "implement later" deferrals within scope.

- Every task has real implementation code, not pseudocode placeholders. The `set_title_block_fields` body is fully specified including the escape function and all 3 fallback tiers.
- Handlers return real dicts, not `{"status": "not implemented"}`.
- The `must_haves` list (10 items) is concrete and each is falsifiable with a specific command.
- Deferred items (DRC profiles, build records, MCP exposure) are correctly out of scope per ROADMAP and explicitly listed in `205-CONTEXT.md` deferred section.

**LOW — [SLC-1] The `except Exception: pass` in `set_title_block_fields` (Task 3a, the existing-value read block) is a broad swallow.** If `sexpdata.loads(content)` fails on malformed input, the method silently uses empty defaults and then *overwrites* the existing title_block with those defaults. This is defensible (the method is called from a handler that already successfully parsed the file upstream), but the breadth of `except Exception` could mask a real regression in the native parser helpers. Recommend narrowing to `except (sexpdata.ExpectNothing, ValueError, TypeError, IndexError):` or at least logging at debug level. Not a blocker — the upstream parse would have failed first.

### KiCad Rick — title_block structure, quoting rules, kicad-cli validation

**Verdict: ACCURATE on KiCad semantics; one nomenclature typo.**

**Verified against RESEARCH.md + fixtures:**
- title_block placement (after `paper`, before `layers`) is correct per the S-expression grammar.
- All string fields always quoted in KiCad 10 — confirmed by RESEARCH RQ1 fixture analysis. The plan's `_escape_kicad_string` (double internal quotes) is the correct KiCad convention.
- Numbered comments 1-9, non-sequential allowed — correct.
- `(title "")` for empty, absent element for missing — correct and distinct, tested.
- `kicad-cli pcb export stats` returns exit 0 even on load failure (must check stdout) — RESEARCH RQ3 verified this non-obvious behavior. The plan's Task 6c test correctly checks both returncode AND stdout content. Good catch by the researcher.

**MEDIUM — [KCAD-1] `SurfaceFinish` enum contains `IMPEG`, which is not a standard PCB surface finish — appears to be a typo conflating `ENEPIG`.** The plan defines:
```python
class SurfaceFinish(str, Enum):
    HASL = "HASL"
    ENIG = "ENIG"
    HASL_LEAD_FREE = "HASL_LEAD_FREE"
    IMPEG = "IMPEG"      # <-- not a real finish
    HARD_GOLD = "HARD_GOLD"
    OSP = "OSP"
    ENIPIG = "ENIPIG"    # <-- also non-standard spelling; standard is ENEPIG
```
Standard industry finishes are: HASL, HASL Lead-Free, ENIG, ENEPIG (Electroless Nickel Electroless Palladium Immersion Gold), OSP, Immersion Silver, Immersion Tin, Hard Gold. `IMPEG` is not a recognized acronym. `ENIPIG` is a common alternate spelling of `ENEPIG` but the canonical form is `ENEPIG`. Since these enum *names* serialize to the sidecar JSON (`str, Enum` serializes as the name), a typo here persists in user-facing `.kicad_build_spec.json` files and becomes a migration concern later. CONTEXT.md repeats the `IMPEG` typo, so this propagated from context.
**Action:** Replace `IMPEG` with nothing (drop it — `ENIPIG`/`ENEPIG` covers the palladium-gold family) or with a real finish (`IMMERSION_SILVER` / `IMMERSION_TIN`). Standardize `ENIPIG` → `ENEPIG`. CONTEXT.md "Claude's Discretion" explicitly allows the enum set to be extended later, so fixing the nomenclature now is in-scope cleanup, not scope creep.

---

## Severity Summary

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 0 | — |
| High | 1 | QUAL-1 |
| Medium | 4 | ARCH-1, SEC-1, QUAL-2, QUAL-3, KCAD-1 (note: 5 items; ARCH-1 is borderline low/medium) |
| Low | 3 | ARCH-2, SEC-2, SLC-1 |

*Recount (5 mediums listed, summary says 4 — see correction below):* ARCH-1, SEC-1, QUAL-2, QUAL-3, KCAD-1 = 5 medium. Adjusted table:

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 0 | — |
| High | 1 | QUAL-1 |
| Medium | 5 | ARCH-1, SEC-1, QUAL-2, QUAL-3, KCAD-1 |
| Low | 3 | ARCH-2, SEC-2, SLC-1 |

---

## Requirement Coverage Check (META-01 through META-07)

| REQ | Covered? | By Task(s) | Acceptance Criterion |
|-----|----------|------------|----------------------|
| META-01 (read metadata) | YES | 4a (schema), 5a (handler), 6b (test) | `test_read_board_metadata_full` |
| META-02 (set revision) | YES | 4a, 5b, 6b | `test_set_board_revision_round_trip` |
| META-03 (set metadata) | YES | 4a, 5b, 6b | `test_set_board_metadata_partial_update`, `..._comments` |
| META-04 (BoardSpec model) | YES | 2a, 2b, 2c | `test_sidecar_load_save`, `test_default_construction` |
| META-05 (impedance reqs) | YES | 2b, 2c | `test_impedance_requirements_round_trip` |
| META-06 (round-trip fidelity) | YES | 3a, 5b, 6b, 6c | `test_set_board_revision_round_trip`, `test_modified_pcb_loads_in_kicad_cli` |
| META-07 (KiCad 10 quoting) | YES | 1e, 6a | `test_title_block_full_fields`, `..._non_sequential_comments`, `..._special_chars_round_trip` |

All 7 requirements have a clear path from schema → handler → test. No orphan requirements.

---

## Success Criteria Check (ROADMAP phase 205)

| SC | Plan coverage |
|----|---------------|
| 1. `read_board_metadata` returns rev/title/date/company | Task 5a handler + Task 6b test |
| 2. `set_board_revision` round-trips with zero data loss | Task 3a raw writer + Task 5b handler + Task 6b round-trip test + Task 6c kicad-cli validation |
| 3. BoardSpec persists to sidecar; reload restores it | Task 2b/2c `save_board_spec`/`load_board_spec` + round-trip tests |
| 4. Quoting variations (empty fields, numbered comments, special chars) round-trip | Task 6a parser tests + Task 6b special-chars test |

All 4 success criteria have explicit verification.

---

## Pitfall 2 (title_block parsing fragility) — Addressed?

**Yes, comprehensively.** The plan:
- Removes `title_block` from `_UNSUPPORTED_ELEMENTS` and adds to `_KNOWN_TOP_LEVEL` (correct two-step to avoid the unsupported-element warning).
- Uses block-level rebuild (not field-level regex surgery) for writes — eliminates partial-update corruption.
- Tests empty fields, absent fields, non-sequential comments, and special characters (parens, ampersands).
- Validates structural correctness via `kicad-cli pcb export stats` (not just re-parse).
- Uses the existing `_find_matching_close` helper which correctly handles KiCad's doubled-quote escaping.

---

## Recommendations (ordered by priority)

1. **(HIGH, before Task 6 execution)** Fix the `extract_uuids` import in Task 6b `_build_ir`: change `from volta.ops.pcb_ops import extract_uuids` to `from volta.parser.uuid_extractor import extract_uuids`. Resolve the `SMD_TEST_BOARD` reference (use the path literal `Path("tests/fixtures/smd_test_board.kicad_pcb")` or add the constant). Without this, Task 6 tests will not collect.

2. **(MEDIUM, during Task 2 execution)** Fix the `SurfaceFinish` enum: drop `IMPEG` (not a real finish), rename `ENIPIG` → `ENEPIG` (canonical spelling). Update CONTEXT.md to match. This prevents typo'd values from persisting in user sidecar JSON.

3. **(MEDIUM, during Task 3 execution)** Add one test for the `set_title_block_fields` fallback tier 3 (board with no `(paper ...)` line) to cover the insertion path's `kicad_pcb`-line fallback. Optionally narrow the `except Exception: pass` to specific parse exceptions.

4. **(MEDIUM, during Task 6 execution)** Add a `kicad-cli pcb export stats` validation test for the *insert* path (board with no title_block gets one inserted), not just the *modify* path. The insert path synthesizes a whole new block and is higher-risk.

5. **(LOW, optional)** Document in `save_board_spec`/`load_board_spec` docstrings that callers must supply a validated path (the functions are public); or have the execution reviewer confirm no direct non-Op call sites are added in Phase 209.

---

## Decision

# APPROVE

**Rationale:** The plan is architecturally sound, fully covers all 7 META requirements, correctly resolves the two critical path decisions (raw-writer mutation, raw-content query), and has a strong test strategy including `kicad-cli` structural validation. The single HIGH finding (QUAL-1, wrong import path) is a one-line execution-time fix that does not reflect an architectural defect — it's a transcription error in the test helper. All other findings are medium/low robustness improvements.

The plan is cleared for execution. The executing agent MUST address QUAL-1 before Task 6 acceptance criteria can pass (the test file will fail to import otherwise). Recommend addressing KCAD-1 (enum typo) during Task 2 since it affects the JSON contract. The remaining findings can be addressed opportunistically during implementation.
