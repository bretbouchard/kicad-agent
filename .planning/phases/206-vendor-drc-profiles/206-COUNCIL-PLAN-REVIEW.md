---
phase: 206
plan: 01
review_type: plan
date: 2026-07-10
decision: REJECT
severity_counts:
  critical: 1
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

# Council of Ricks — Phase 206 Plan Review

**Phase:** 206 — Vendor DRC Profiles
**Plan reviewed:** `206-01-PLAN.md` (6 tasks, wave 1, autonomous)
**Supporting docs:** `206-CONTEXT.md`, `206-RESEARCH.md`, `206-VALIDATION.md`, `206-PATTERNS.md`
**Cross-referenced against:** `ROADMAP.md` (phase 206), `REQUIREMENTS.md` (DRC-01..08), `PITFALLS.md` (Pitfall 1, Pitfall 6), `AGENTS.md`

**Prior gate status:** Plan-checker passed with 0 BLOCKERs, 2 WARNINGs (both reported fixed: clearance test added, generic drill 0.3→0.4mm).

---

## Executive Summary

The plan's central architectural decision — the pivot from `kicad-cli --custom-rules` to an internal Python geometric evaluator — is **correct and necessary**. The RESEARCH file (RQ1) proved empirically with 4 tests that the `--custom-rules` flag does not exist in the installed `kicad-cli 10.0.3`, and that `.kicad_dru` sidecar files are silently ignored by the CLI. Option C (internal evaluation against `ManufacturerProfile` limits using `PcbIR` geometry) is the right call. The plan propagates this decision consistently through the threat model, the evaluator design, and the `must_haves` (which explicitly guards the silent-pass failure mode).

However, the plan contains **one CRITICAL defect** that will prevent the evaluator from working at all. The plan's Task 3 evaluator (`run_vendor_drc`) is designed to access `ir.board.segments`, `ir.board.vias`, and `ir.board.footprints[*].pads` using `NativeBoard` / `NativeSegment` / `NativeVia` field names. But the `drc_vendor` op is registered `is_readonly: True`, which routes it through `execute_query` — and `execute_query` builds the `PcbIR` via the **kiutils path** (`parse_pcb` + `PcbIR(_parse_result=..., _uuid_map=...)`), leaving `_native_board = None`. Consequently `ir.board` returns a **kiutils `Board`**, which has **no `segments` attribute, no `vias` attribute, and uses `traceItems` (a flat list of mixed `Segment`/`Via`/`Arc`)**. The evaluator will raise `AttributeError` on the first geometry access.

This is the exact same class of bug that Phase 205 discovered, documented, and worked around (see the `CRITICAL` comment in `handlers/query.py:33-39`: *"execute_query builds PcbIR via the kiutils path, so ir.board is a kiutils Board"*). Phase 206's research and plan did not carry that lesson forward into the evaluator design. The fix is small and local (re-parse via `NativeParser` inside the handler or evaluator using the `file_path` / `ir.raw_content` that the query path *does* provide), but the plan must be revised before execution because the current Task 3 and Task 5 tests are built on the wrong access pattern.

Decision: **REJECT** — the CRITICAL finding (ARCH-1) must be resolved in the plan before execution. The fix is mechanical (re-parse to `NativeBoard` in the handler), but it changes the evaluator's data source and invalidates the current test helpers, so it cannot be deferred to execution-time.

---

## Specialist Findings

### Architecture Rick — Mutation/query path correctness, evaluator data source

**Verdict: BROKEN at the data-source layer. The evaluator cannot access native geometry through the query path as written.**

**The critical defect — [ARCH-1, CRITICAL]: `run_vendor_drc` accesses `ir.board.segments`/`.vias`, but the query path yields a kiutils `Board` that has neither attribute.**

Verified against the codebase:

- `drc_vendor` is registered `is_readonly: True` (plan Task 4 Edit C, and CONTEXT.md line 132). This routes it through `execute_query`.
- `execute_query` (`execution.py:193-230`) constructs the `PcbIR` as:
  ```python
  parse_result = parse_pcb(file_path)   # kiutils path
  uuid_map = extract_uuids(...)
  ir = PcbIR(_parse_result=parse_result, _uuid_map=uuid_map)
  ```
  It does **not** call `try_native_parse` and does **not** set `_native_board`. (Confirmed: the native-parse path lives only in `execute_pcb` at `execution.py:486-509`, not in `execute_query`.)
- Therefore `_native_board is None`, and `PcbIR.board` (`pcb_ir.py:123-131`) returns `self._parse_result.kiutils_obj` — a kiutils `Board`.
- The kiutils `Board` has attributes: `traceItems`, `footprints`, `nets`, `graphicItems`, `zones`, `setup`, `titleBlock`, etc. It has **no `segments` attribute and no `vias` attribute** (confirmed by loading a fixture: `hasattr(board, 'segments') == False`).
- The plan's Task 3 evaluator iterates `ir.board.segments` and `ir.board.vias` with `NativeSegment`/`NativeVia` field names. On the query path, `ir.board.segments` raises `AttributeError: 'Board' object has no attribute 'segments'`.

This is the same dual-path asymmetry that Phase 205 documented. The `read_board_metadata` query handler (`query.py:33-39`) carries this warning verbatim:
> *"CRITICAL: execute_query builds PcbIR via the kiutils path (RESEARCH RQ1), so `ir.board` is a kiutils Board and `ir.board.title_block` does NOT exist."*

Phase 206's plan even cites the native parser field names from `pcb_native_types.py` (Task 3 read_first) but does not reconcile this with the fact that the query path does not produce a `NativeBoard`. The RESEARCH file's "Validation risk" section warns about the silent-pass failure mode — but this bug is worse than silent-pass: it is a hard crash (`AttributeError`) on every invocation.

**Required fix (must be in the revised plan):** The `_handle_drc_vendor` handler (or `run_vendor_drc` itself) must obtain a `NativeBoard` independently of the query-path `ir.board`. Two viable approaches:

1. **Re-parse from `file_path` (recommended):** In the handler, call `NativeParser.parse_pcb(file_path)` (mirrors `try_native_parse` at `execution.py:162-185`). Pass the `NativeBoard` to `run_vendor_drc`. The handler already receives `file_path`. This is the cleanest: it gives the evaluator the typed native geometry it was designed for, and reuses the same parser the mutating path trusts.
2. **Parse from `ir.raw_content`:** Call `NativeParser.parse_pcb_content(ir.raw_content)` to avoid a second file read. `ir.raw_content` is populated by both paths (the kiutils `parse_pcb` sets it on the `ParseResult`). This saves an I/O but requires the evaluator signature to accept raw content or a `NativeBoard`.

Either way, `run_vendor_drc`'s signature should change from `run_vendor_drc(ir: PcbIR, profile)` to `run_vendor_drc(board: NativeBoard, profile)` (or accept the `NativeBoard` explicitly), so the evaluator is not coupled to the kiutils-vs-native ambiguity of `PcbIR.board`. This also makes the test helpers in Task 5 (`_build_ir`) simpler — they build a `NativeBoard` directly rather than going through `PcbIR`.

**Action:** Revise Task 3 and Task 4 Edit D to parse a `NativeBoard` in the handler and pass it to the evaluator. Revise Task 5 test helpers to construct `NativeBoard` instances (or `NativeSegment`/`NativeVia`/`NativePad` tuples) directly. Add an acceptance criterion that the evaluator works when called through `execute_query` (not just via a direct `run_vendor_drc` unit test with a hand-built `PcbIR.from_native`), so this path is exercised.

**[ARCH-2, MEDIUM] The plan claims `ir.board` "returns `NativeBoard` when `_native_board is not None`" (Task 3 action item 6) — this is true of the property, but misleading in context, because the query path never sets `_native_board`.** The plan's read_first cites `pcb_ir.py:124-161` (the `board` property) but does not cite `execution.py:193-230` (the query path that leaves `_native_board = None`). This omission is the root cause of ARCH-1. The revised plan must explicitly document that the query path produces a kiutils `Board` and that the handler must re-parse.

**[ARCH-3, LOW] Schema union edit (Task 4 Edit B2) misstates the current state.** The plan shows `| SetBoardRevisionOp` without a trailing comma and adds the new ops with the comma. The actual code (`schema.py:562`) is `| SetBoardRevisionOp,` — the trailing comma is already on `SetBoardRevisionOp`. The executing agent will need to move the comma to the new last item. Minor (the edit is obviously resolvable when looking at the file), but it indicates the plan's line-state snapshot is slightly stale.

### Security Rick — Path traversal, malformed board handling

**Verdict: SOUND threat model, well-mitigated, with one documentation gap.**

**Verified mitigations:**

- **Path traversal (scenario 1) — dual-layer defense is correct.** The schema-layer `pattern=r"^[a-z0-9_]+$"` on `DrcVendorOp.vendor` rejects slashes, dots, and path separators at validation time (pydantic raises `ValidationError` before the handler runs). The resolver-layer `_VENDOR_NAME_RE` + file-existence check in `get_drc_profile_path` is defense-in-depth. Confirmed the pattern rejects `../../etc/passwd` (Task 4 acceptance criterion tests this). The `_PROFILE_INFOS` dict acts as an allowlist. This is solid.
- **Malformed board (scenario 2) — robustness design is correct.** The plan specifies `getattr(obj, field, default)` everywhere and per-feature try/except so a single malformed track does not abort the evaluation. The "never re-raises" contract and the `error_message` escape hatch are appropriate. Note: with the ARCH-1 fix, this robustness applies to `NativeBoard` access, which is the correct target.
- **No injection vectors.** The `.kicad_dru` files are static package data (no `eval`, no template interpolation). The handler does not interpolate user input into paths or commands. The `run_drc(file_path)` subprocess call (Task 4 Edit D) passes args as a list (verified: `run_drc` constructs `cmd = [cli_info.path, "pcb", "drc", ...]`), no `shell=True`. Clean.

**[SEC-1, LOW] The threat model does not address the case where `kicad-cli` is invoked by the optional `run_kicad_drc=True` branch on an attacker-supplied board path.** This is not exploitable in practice — `file_path` arrives as a `TargetFile`-validated, executor-resolved path — but the threat model's scenario enumeration should note that `run_drc(file_path)` inherits the executor's path resolution. Non-blocking; recommend a one-line addition to the threat model for completeness.

### Quality Rick — Test coverage, silent-pass guard, edge cases

**Verdict: STRONG test strategy in intent, but the core evaluator tests are built on the wrong data path (consequence of ARCH-1) and must be rewritten.**

**Strengths (intent):**

- **The silent-pass guard is correctly identified as the highest-priority test.** `must_haves` item 1 and `test_track_width_below_limit_violation` directly target the failure mode the RESEARCH "Validation risk" section warns about. Good.
- Coverage of all 5 check types (track width, drill, annular ring, via diameter, clearance) with both violating and passing variants.
- `test_evaluator_does_not_crash_on_empty_board` and `test_evaluator_does_not_crash_on_malformed_geometry` cover threat-model scenario 2.
- Path-traversal rejection tested at both layers (schema pattern + resolver).
- `test_drc_vendor_file_mtime_unchanged` verifies read-only behavior end-to-end — mirrors the established `test_connectivity_query.py` pattern.

**[QUAL-1, HIGH] The Task 5 evaluator tests use `_build_ir` helpers that construct a `PcbIR`, but the evaluator is specified to read from `ir.board` — which (per ARCH-1) is a kiutils `Board` in the real query path.** The tests will either (a) build a `PcbIR.from_native` (which gives a `NativeBoard`, so the tests pass but do NOT match production conditions), or (b) build a kiutils-path `PcbIR` (which makes `ir.board` a kiutils `Board`, and the evaluator crashes). Neither case validates the real path. After the ARCH-1 fix, the tests must build `NativeBoard` geometry directly and the evaluator must accept a `NativeBoard`. As written, the test suite gives false confidence: a green `test_track_width_below_limit_violation` would not prove the op works through `execute_query`. **Action:** add a test that calls the handler (or `execute_query`) on a real violating PCB fixture and asserts a violation is reported — not just a unit test of `run_vendor_drc` with a hand-built IR.

**[QUAL-2, MEDIUM] No test asserts that the evaluator and the `.kicad_dru` file agree on the numeric limits for a given vendor (source-of-truth consistency).** The DRU files are described as the "source of truth for numeric values," but the evaluator reads from `ManufacturerProfile` (dfm/profiles.py), which is a separate set of literals. If someone updates a DRU file but not the profile (or vice versa), the evaluator and the GUI-loaded rules diverge silently. The OSH Park case (see KCAD-1) is a live instance of this. Recommend a test that, for each vendor present in both `_PROFILE_INFOS` and `_PROFILES`, asserts the key limits match. (This may be partially blocked by KCAD-1's existing drift — at minimum, document the intended relationship.)

**[QUAL-3, MEDIUM] The clearance check (Task 3) is the most complex and least-specified part of the evaluator, and has the weakest test.** The plan describes "bounding-box pre-filtering per layer" and "the corridor pattern from `pcb_ir.py:978-986`" but does not specify: (a) whether clearance is checked track-to-track only, or also track-to-pad and pad-to-pad (CONTEXT.md lines 95-100 mention all three; the plan Task 3 says "track-to-track checks"), (b) how arcs in `traceItems` are handled (native segments are straight; but the geometry model should be explicit), (c) the exact distance metric (edge-to-edge vs center-to-center). The test `test_clearance_below_limit_violation` uses "two segments on the same layer closer than min_clearance_mm" but does not pin the metric. Since this is O(n²) and the highest-risk check for both correctness and performance, recommend the plan specify the exact distance function (edge-to-edge Euclidean, consistent with KiCad's `clearance` constraint) and add a track-to-pad clearance test.

### SLC Rick — No workarounds, no stubs, complete solutions

**Verdict: COMPLIANT in spirit; one incomplete specification tied to ARCH-1.**

- Every task has real implementation, not placeholders. The evaluator logic, DRU file contents, schema edits, and handler bodies are fully specified.
- The `must_haves` list (6 items) is concrete and each is falsifiable.
- Deferred items (CLI subcommands, MCP exposure, vendor API adapters, BOM/CPL formatting) are correctly out of scope per ROADMAP and listed in CONTEXT.md deferred section. No scope creep.
- The `run_kicad_drc` optional branch degrades gracefully (`except Exception` → `{"error": str(exc)}`) rather than failing the whole op — appropriate for a feature that depends on an external binary that may be absent in test.

**[SLC-1, MEDIUM] The evaluator's `passed` logic and the `run_kicad_drc` merge are underspecified for the "both run" case.** The plan says `passed = len(errors) == 0` for the vendor result, and the handler separately returns `kicad_drc` results. But the top-level `out["passed"]` is the vendor evaluator's `passed`; the KiCad DRC `passed` is nested under `out["kicad_drc"]["passed"]`. If a user checks only `result["passed"]`, they get the vendor verdict and miss KiCad DRC failures. The plan does not define which `passed` is authoritative for the op. Recommend the plan specify: the op `passed` should be the AND of vendor `passed` and (if run) kicad_drc `passed`, OR explicitly document that consumers must check both. As written, the return contract is ambiguous and a consumer could easily check the wrong field.

### KiCad Rick — DRU format, vendor specs, source-of-truth drift

**Verdict: ACCURATE on the kicad-cli limitation and DRU authoring; one concrete value-drift defect.**

**Verified:**

- **The `--custom-rules` finding is correct and well-evidenced.** RESEARCH RQ1 ran 4 empirical tests (sidecar DRU, DRU+project, invalid syntax, format-upgraded board) — all confirm kicad-cli ignores `.kicad_dru`. The `pcb drc --help` output shows no such flag. (Also confirmed: installed version is `10.0.3`, not the `10.0.1` AGENTS.md states — a pre-existing doc staleness the research correctly flagged.) The internal-evaluator pivot is not a workaround; it is the only viable automated path. This is the strongest part of the plan.
- **DRU file format is correct.** `(version 1)` + `(rule "Name" (constraint <type> (min <val>)))` matches the Cimos reference files (RQ4) and the KiCad DRC rule grammar. Constraint types (`track_width`, `clearance`, `hole_size`, `annular_width`, `via_diameter`) are valid.
- **PCBWay/JLCPCB annular ring correction (DRC-07) is correct.** Both vendors publish 0.15mm (6mil). The existing 0.1mm values (`profiles.py:113,146`) are more permissive than reality. The plan corrects both the DRU files and the `ManufacturerProfile` values.
- **AISLER 0.2mm annular hard limit is correct** and correctly larger than JLC/PCBWay. Good that the plan calls this out explicitly.
- **Generic 0.4mm drill matches the existing `_GENERIC_CONSERVATIVE`** (profiles.py:171) — single source of truth preserved. The CONTEXT.md line 194's "0.3mm" is stale; the plan correctly uses 0.4mm.

**[KCAD-1, MEDIUM] OSH Park DRU file and `_OSH_PARK` profile disagree on drill and annular values — source-of-truth drift.** The plan Task 1 authors `oshpark.kicad_dru` with `hole_size 0.254mm` and `annular_width 0.127mm` (current published OSH Park 2-layer specs per RESEARCH RQ3). But Task 2 wires `_OSH_PARK` (profiles.py:155) to `drc_rules_path=get_drc_profile_path("oshpark")` **without updating its values** — `_OSH_PARK` keeps `min_drill_mm=0.3556` and `min_annular_ring_mm=0.1524`. Result: the evaluator (which reads `ManufacturerProfile`) checks against 0.3556mm drill / 0.1524mm annular, while the DRU file (which a user loads in the GUI) enforces 0.254mm / 0.127mm. The DRU file is more permissive than the evaluator. Since the plan declares the DRU files the "source of truth for numeric values" (Task 1, plan line 41), this is an internal contradiction. The RESEARCH file (RQ3, OSH Park section) even notes the existing profile is "more conservative than OSH Park's actual limits, which is safe but not tight" and says "the DRU file should use the current published values" — but never reconciles the two. **Action:** either (a) update `_OSH_PARK` to match the DRU file (0.254mm drill, 0.127mm annular), making both authoritative, or (b) document that the `ManufacturerProfile` values are intentionally conservative overrides and the DRU file is the vendor-published reference. Option (a) is cleaner and eliminates the drift. Note: the same drift risk applies to `_JLCPCB_4LAYER` (profiles.py:122-140) which is NOT updated by the plan and has no corresponding DRU file — the plan adds `aisler_*` but not `jlcpcb-4layer` DRU. Recommend documenting this as intentional (the 4-layer profile is a pre-existing entry without a DRU companion) or adding the file.

**[KCAD-2, LOW] The plan cites the constraint `via_diameter` in DRU files, but the Cimos reference files (RQ4) and KiCad's rule grammar use `min_via_diameter` for the constraint name in some contexts.** The plan uses `(constraint via_diameter (min 0.4mm))`. This appears valid per RQ6's constraint table (`via_diameter` listed), but worth a quick GUI load-test (the VALIDATION.md "Manual-Only" table already plans this). Non-blocking.

---

## Severity Summary

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 1 | ARCH-1 |
| High | 1 | QUAL-1 |
| Medium | 4 | ARCH-2, QUAL-2, QUAL-3, SLC-1, KCAD-1 (5 items; see note) |
| Low | 3 | ARCH-3, SEC-1, KCAD-2 |

*Note on medium recount:* ARCH-2, QUAL-2, QUAL-3, SLC-1, KCAD-1 = 5 medium items. Adjusted table:

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 1 | ARCH-1 |
| High | 1 | QUAL-1 |
| Medium | 5 | ARCH-2, QUAL-2, QUAL-3, SLC-1, KCAD-1 |
| Low | 3 | ARCH-3, SEC-1, KCAD-2 |

---

## Requirement Coverage Check (DRC-01 through DRC-08)

| REQ | Covered? | By Task(s) | Acceptance Criterion | Notes |
|-----|----------|------------|----------------------|-------|
| DRC-01 (run vendor DRC) | YES (by design) | 3 (evaluator), 4 (op), 5 (test) | `test_track_width_below_limit_violation` | **Blocked by ARCH-1** — evaluator cannot read geometry via query path as written. Coverage is correct in intent but not executable until the data-source defect is fixed. |
| DRC-02 (DRU files: PCBWay, JLCPCB, AISLER 2/4/6/8L) | YES | 1 | `ls *.kicad_dru` == 9, `test_all_dru_files_have_attribution` | Sound. |
| DRC-03 (OSH Park + Advanced Circuits) | YES | 1, 2 | `load_profile('advanced_circuits')`, oshpark.kicad_dru exists | Sound. See KCAD-1 on OSH Park value drift. |
| DRC-04 (generic conservative) | YES | 1, 4, 5 | `test_drc_vendor_clean_board_passes_via_handler`, generic.kicad_dru | Sound. |
| DRC-05 (drc_rules_path field) | YES | 2 | `'drc_rules_path' in ManufacturerProfile.model_fields` | Sound. |
| DRC-06 (attribution headers) | YES | 1 | `test_all_dru_files_have_attribution` (Source/License/Last-verified/Vendor/Capabilities) | Sound. |
| DRC-07 (PCBWay annular 0.15mm) | YES | 1, 2 | `grep "0.15mm" pcbway.kicad_dru`, `p.min_annular_ring_mm == 0.15` | Sound. |
| DRC-08 (list profiles query) | YES | 1, 4, 5 | `test_list_vendor_drc_profiles_returns_9`, all fields present | Sound. |

All 8 requirements have a clear schema → handler → test path. DRC-01's path is architecturally correct in intent but blocked by ARCH-1 at the execution layer. No orphan requirements.

---

## Success Criteria Check (ROADMAP phase 206)

| SC | Plan coverage | Status |
|----|---------------|--------|
| 1. `drc_vendor(vendor="pcbway")` returns vendor-specific violations | Task 3 evaluator + Task 5 `test_track_width_below_limit_violation` | **At risk** — blocked by ARCH-1 (evaluator cannot read geometry through query path). Fix unblocks this. |
| 2. Ships 5+ verified vendor profiles with attribution | Task 1 (9 DRU files) + Task 5 `test_all_dru_files_have_attribution` | Covered. |
| 3. `drc_vendor(vendor="generic")` gives conservative results | Task 4 (generic wired) + Task 5 `test_drc_vendor_clean_board_passes_via_handler` | **At risk** — same ARCH-1 blocker. |
| 4. List profiles + capabilities | Task 4 `list_vendor_drc_profiles` + Task 5 `test_list_vendor_drc_profiles_returns_9` | Covered. |

2 of 4 success criteria are directly blocked by ARCH-1 until the evaluator data-source defect is fixed.

---

## Pitfall Coverage

**Pitfall 1 (Stale DRC values) — Addressed, comprehensively.** PCBWay + JLCPCB annular ring corrected to 0.15mm (DRC-07). Every DRU file carries a `# Last verified:` date. The `VendorDrcProfileInfo.last_verified` field surfaces this in the list op. The `drc_profile_validate` op (stale-flagging) is correctly deferred (CONTEXT.md deferred section). Good.

**Pitfall 6 (Profile licensing / attribution) — Addressed, comprehensively.** Sourcing strategy is sound: Cimos (MIT) for PCBWay/JLCPCB with attribution; authored-from-specs for AISLER/OSH Park/Advanced Circuits (factual data, not copyrightable expression); generic is original. Every file has Source/License headers (DRC-06). The decision to author AISLER from published numeric specs rather than copy their unlicensed files is the legally safer choice and correctly justified (RESEARCH RQ4). Good.

---

## The Critical Pivot — Is the Plan Correct?

**The pivot is correct; the implementation of the pivot has a critical data-access bug.**

The research (RQ1) is exemplary: it empirically disproved the `--custom-rules` assumption with 4 independent tests, identified the root cause (kicad-cli operates on standalone `.kicad_pcb` and does not load the project context that binds `.kicad_dru`), and evaluated 4 alternatives (A: inject into setup — failed; B: load project — dead end for CLI; C: internal evaluation — recommended; D: GUI-only — insufficient). Option C is the right choice: it uses existing infrastructure (`PcbIR`, `ManufacturerProfile`, `NativeBoard`), does not depend on an unsupported CLI flag, and delivers the automated pre-flight gate that is the core value of DRC-01.

The plan correctly adopts Option C and correctly identifies the silent-pass failure mode as the top validation risk. The `.kicad_dru` files still ship for GUI use and documentation, preserving DRC-02/DRC-03/DRC-06 value.

**What the plan gets wrong** is the data source for the evaluator. The plan assumes `ir.board` in the query path is a `NativeBoard`. It is not — it is a kiutils `Board`. The evaluator's field accesses (`ir.board.segments`, `NativeVia.drill`, etc.) will fail. This is fixable in ~10 lines (re-parse to `NativeBoard` in the handler using `file_path`), but it is not a minor typo: it invalidates the evaluator's core loop, the test helpers, and the "silent-pass guard" test (which would pass against a hand-built native IR while the production path crashes). The plan must be revised so the evaluator receives a `NativeBoard` regardless of the query path's IR construction.

---

## Recommendations (ordered by priority)

1. **(CRITICAL, must fix before execution) [ARCH-1]** Revise Task 3 and Task 4 Edit D so the `_handle_drc_vendor` handler obtains a `NativeBoard` by calling `NativeParser.parse_pcb(file_path)` (mirroring `try_native_parse`), and passes it to `run_vendor_drc(board: NativeBoard, profile)`. Decouple the evaluator signature from `PcbIR.board`. Update Task 3 acceptance criteria to verify the evaluator works through the query path (not just via direct unit test). This unblocks DRC-01 and success criteria 1 + 3.

2. **(HIGH, must fix before/with Task 5) [QUAL-1]** Rewrite the Task 5 evaluator test helpers to build `NativeBoard` geometry directly, and add a test that invokes the handler (or `execute_query`) on a real violating PCB fixture (e.g., a copy of an existing fixture with a sub-limit track) and asserts a violation is reported. This ensures the silent-pass guard validates the production code path, not just a synthetic IR.

3. **(MEDIUM, during Task 2) [KCAD-1]** Resolve the OSH Park source-of-truth drift: either update `_OSH_PARK` to match `oshpark.kicad_dru` (0.254mm drill, 0.127mm annular) or document the intended conservative-override relationship. Prefer making them match. Also document that `_JLCPCB_4LAYER` has no DRU companion (intentional) or add one.

4. **(MEDIUM, during Task 3) [QUAL-3]** Specify the clearance check's exact distance metric (edge-to-edge Euclidean), its scope (track-to-track vs track-to-pad vs pad-to-pad — the plan and CONTEXT disagree), and add a track-to-pad clearance test if pad checks are in scope.

5. **(MEDIUM, during Task 4) [SLC-1]** Define the authoritative `passed` semantics for the op when `run_kicad_drc=True`: make op-level `passed` the AND of vendor and kicad-drc verdicts, or explicitly document that consumers must check `out["kicad_drc"]["passed"]` separately.

6. **(MEDIUM, during Task 5) [QUAL-2]** Add a source-of-truth consistency test asserting the DRU file values and the `_PROFILES` / `_PROFILE_INFOS` values agree for each vendor present in both.

7. **(LOW, opportunistic) [ARCH-2]** Add explicit documentation in Task 3 that the query path yields a kiutils `Board` (citing `execution.py:193-230`), so future maintainers understand why the handler re-parses. [ARCH-3] Fix the schema union edit's comma-state snapshot. [SEC-1] Add a threat-model note that `run_drc(file_path)` inherits executor path resolution. [KCAD-2] Confirm `via_diameter` constraint name via the planned GUI manual test.

---

## Decision

# REJECT

**Rationale:** The plan's central architectural decision (internal evaluator pivot away from the non-existent `--custom-rules` flag) is correct, well-researched, and necessary. Requirement coverage, pitfall coverage, and the silent-pass guard are all well-conceived. However, the plan contains **one CRITICAL defect (ARCH-1)**: the evaluator is designed to read `NativeBoard` geometry from `ir.board`, but the `drc_vendor` op routes through `execute_query`, which constructs the `PcbIR` via the kiutils path — so `ir.board` is a kiutils `Board` with no `segments`/`vias` attributes. The evaluator will raise `AttributeError` on every production invocation. This is the same dual-path bug Phase 205 documented and worked around; Phase 206 did not carry the lesson forward.

The fix is mechanical (re-parse to `NativeBoard` in the handler, ~10 lines), but it changes the evaluator's data source, its signature, and the Task 5 test helpers — so it must be reflected in the plan, not deferred to execution. The accompanying HIGH finding (QUAL-1) is a direct consequence: the current test design would give false confidence by validating a synthetic IR rather than the production query path.

**Required for re-approval:**
- ARCH-1 resolved in the plan (handler re-parses to `NativeBoard`; evaluator signature decoupled from `PcbIR.board`).
- QUAL-1 resolved in the plan (test exercises the query path on a real fixture).
- KCAD-1 resolved or explicitly documented (OSH Park value drift).
- SLC-1 resolved (authoritative `passed` semantics defined).

The remaining medium/low findings can be addressed during execution. The plan is close to approvable — the research and design quality is high — but the evaluator's data-source defect is fundamental to DRC-01 and must be fixed in the plan before execution begins.
