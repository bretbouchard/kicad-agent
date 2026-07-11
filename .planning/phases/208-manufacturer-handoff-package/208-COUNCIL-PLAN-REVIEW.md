# Phase 208 — Council of Ricks Plan Review

**Phase:** 208 — Manufacturer Handoff Package
**Plan reviewed:** `208-01-PLAN.md`
**Review type:** Plan review (pre-execution)
**Reviewed:** 2026-07-11
**Reviewer:** Council of Ricks (plan-reviewer seat)
**Verdict:** APPROVE WITH MINOR CONDITIONS

---

## Executive Summary

The Phase 208 plan is strong. It is the capstone of the v7.0 milestone — one call
(`build_handoff_export`) produces a complete, validated, manufacturer-ready zip bundle.
The plan correctly generalizes the hard-coded JLCPCB BOM into a profile-driven formatter,
introduces the codebase's first zip-creation code with a correct streaming pattern, and
builds a pre-handoff validation gate that blocks incomplete bundles.

Requirement coverage is complete (all 9 HANDOFF requirements mapped to tasks and
must_haves). The threat model is unusually thorough for a plan document (6 entries). The
dual-path `NativeParser.parse_pcb` usage for vendor DRC + title_block matches the proven
Phase 207 `build_create` pattern. The registry/schema/handler atomic-change discipline is
correct.

The plan has **no blocking issues**. It has two minor findings (both LOW severity) and
one observation about a documented contradiction with a prior roadmap note (IP-4). These
are documented below for the execution phase to handle or explicitly accept.

---

## Severity Summary

| Severity | Count | Meaning |
|----------|-------|---------|
| CRITICAL | 0 | Blocks execution — must fix before plan approval |
| HIGH | 0 | Will cause test failures or incorrect behavior if not addressed |
| MEDIUM | 0 | Should address during execution; non-blocking but worth fixing |
| LOW | 3 | Minor inconsistencies / suggestions; accept or defer |
| INFO | 2 | Observations for awareness; no action required |

---

## Role 1: Plan Checker Results

| # | Check | Result | Notes |
|---|-------|--------|-------|
| 1 | All 9 HANDOFF requirements in plan frontmatter AND addressed by tasks | PASS | Frontmatter lists HANDOFF-01..09. Must Haves 1-9 map 1:1. Task headers cite requirements. Full traceability matrix below. |
| 2 | must_haves align with ROADMAP success criteria | PASS | Must Haves 1,2,3 ↔ ROADMAP SC-1; MH-4 ↔ SC-2; MH-6 ↔ SC-3; MH-5,8 ↔ SC-4; MH-7 ↔ SC-5. All 5 ROADMAP success criteria covered. |
| 3 | Query op dispatch correct (build_handoff_export doesn't write target file) | PASS | Registry: `is_readonly: True`, `category: "query"`, `scope: "single_file"`. Plan Task 5 explicitly does NOT add to `CROSS_FILE_OP_TYPES`. Matches shipped Phase 207 `build_create` pattern (verified build.py docstring: "registered as a read-only query op because it never modifies the target .kicad_pcb"). |
| 4 | Registry count 159 → 160 | PASS | Verified `tests/test_registry.py:26` currently asserts `== 159`. Plan Task 6 updates to `== 160`. +1 op (build_handoff_export). Arithmetic correct. |
| 5 | Handler uses NativeParser.parse_pcb for vendor DRC + title_block (dual-path) | PASS | Task 3 Step 2 + Step 3 call `NativeParser.parse_pcb(pcb_path)`. The NativeBoard feeds both `title_block` (rev/title/date/company) AND `run_vendor_drc(board, profile)` (which needs `.segments`/`.vias`/`.footprints`, NOT a PcbIR). Matches Phase 207 build_create (build.py:76) and Phase 206 drc_vendor (query.py:107) dual-path. |
| 6 | Streaming zip creation (not in-memory) | PASS | Task 3 Step 9: `zipfile.ZipFile(zip_path, "w", ZIP_DEFLATED)` + `zf.write(filepath, arcname=...)`. Acceptance criteria assert `ZIP_DEFLATED` present and arcname uses `.name`. Never `zf.writestr()` for large files. Pitfall 7 mitigated. |
| 7 | Pre-handoff validation gate (no zip on failure) | PASS | Task 3 Step 3: if ANY check is `False` → return `HandoffResult(success=False, ...)` with NO zip created. Acceptance criterion `test_handoff_blocks_on_drc_failure` asserts no `handoff.zip` exists. `test_handoff_no_partial_state_on_failure` asserts no build dir remains. Pitfall 5 mitigated. |
| 8 | Profile-driven BOM (not calling export_jlcpcb_bom directly) | PASS | Task 2 creates `export_bom_profile`. Task 3 Step 5 uses `export_bom_profile` — NEVER `export_jlcpcb_bom`. Acceptance criterion asserts `grep "export_jlcpcb_bom" handoff.py` returns 0. Pitfall 3 mitigated. |
| 9 | Every task has read_first + acceptance_criteria | PASS | Tasks 1-6 each have `<read_first>` and `<acceptance_criteria>` sections. Verification section also has both. |
| 10 | threat_model present | PASS | 6-entry threat model table at plan top (TM-1 through TM-6). Each TM maps to a specific task/step mitigation. Covers path traversal, zip-slip, profile injection, markdown injection, CSV formula injection, symlink escape. |

**Plan Checker Verdict: VERIFICATION PASSED** (10/10 checks pass).

---

## Role 2: Council of Ricks Plan Review

### Requirement Coverage (Traceability Matrix)

| REQ-ID | Must Have | Task(s) | Status |
|--------|-----------|---------|--------|
| HANDOFF-01 | MH-1 | Task 3 (orchestrator), Task 5 (op wiring) | Covered |
| HANDOFF-02 | MH-2 | Task 3 Step 5 (all exports) | Covered |
| HANDOFF-03 | MH-3 | Task 3 Step 9 (streaming zip) | Covered |
| HANDOFF-04 | MH-4 | Task 4 (readme generation) | Covered |
| HANDOFF-05 | MH-5 | Task 1 (profile fields), Task 2 (formatter) | Covered |
| HANDOFF-06 | MH-6 | Task 3 Step 3 (validation gate) | Covered |
| HANDOFF-07 | MH-7 | Task 5 schema (include_step/include_render), Task 3 Step 5 | Covered |
| HANDOFF-08 | MH-8 | Task 1 (JLCPCB bom_columns), Task 2 (profile application) | Covered |
| HANDOFF-09 | MH-9 | Task 1 (manifest fields), Task 3 Step 8 (manifest construction) | Covered |

All 9 requirements have a clear must_have, task, and acceptance criteria chain. No orphan requirements. No orphan tasks.

---

### SLC (Single Level of Correctness) Compliance

**Score: STRONG.**

The plan demonstrates good SLC discipline:

1. **Single definition of the export list.** Task 3 Step 5 enumerates the exports once. The readme (Task 4) and manifest (Task 3 Step 6) derive from the same produced file paths, not from a re-declared list.
2. **Single validation gate.** The tri-state logic (True/False/None via `error_message`) is defined once in Task 3 Step 3 and consumed by both the gate decision and the `HandoffValidation` dataclass and the manifest fields. No duplicate "did it pass?" logic.
3. **Single profile source of truth.** `ManufacturerProfile.bom_columns` (Task 1) is the only place BOM formatting is declared. `export_bom_profile` (Task 2) reads it. The handoff (Task 3) passes the profile. No hardcoded JLCPCB column list in the handoff path.
4. **Single registry entry.** The `_RAW_CATALOG` entry (Task 5) is the one source; `OPERATION_REGISTRY` is derived; the test asserts the derived count.

**Minor SLC risk (LOW):** Task 2 action step 3 builds the source-to-target column alias map "inside the function" via a convention (Comment=Value, Designator=Reference). This mapping logic partially duplicates knowledge already encoded in the existing `export_jlcpcb_bom` (bom.py:343-363). If `export_jlcpcb_bom` is refactored to delegate to `export_bom_profile` (Task 2 action step 4, "Optionally"), there would be two copies of the mapping until that refactor. The plan marks the delegation as optional/cosmetic — acceptable, but the executor should prefer doing the delegation to collapse the duplication.

---

### Security Review

**Score: STRONG.** The threat model is the best part of this plan.

#### Path Traversal (TM-1) — MITIGATED
`project_dir` on `BuildHandoffExportOp` is rejected if `".." in Path(op.project_dir).parts`. This mirrors the shipped `build_create` handler (build.py:66-71, verified) and reuses the existing `_resolve_project_dir` helper (build.py:173-185, verified). The helper returns `Path | dict` (Path on success, error dict on traversal) — Task 5 action step 4 correctly handles both returns.

#### Zip-Slip (TM-2) — MITIGATED
The arcname is always `artifact_file.name` (basename), never a full path. The acceptance criterion `test_handoff_arcname_no_path_separator` asserts no `/` or `\` in any namelist entry. This is the correct mitigation. The codebase has no existing zip-write code (verified — only zip-read in `project/adi_library/cache.py`), so this establishes the safe pattern for the first time.

**Council note (INFO):** Since all files are written flat into `build_dir` and zipped flat, two exports producing files with the same basename would silently overwrite. Gerber exports produce multiple files with distinct extensions (.gbr, .gbl, etc.), and drill produces distinct extensions, so collision is unlikely in practice. But if a future export produces a file named identically to another, the zip would lose one. This is acceptable for v1 — the build_dir is a fresh timestamped directory per handoff — but worth a comment in the orchestrator.

#### Profile Name Injection (TM-3) — MITIGATED
`vendor` field has `pattern=r"^[a-z0-9_]+$"` (verified against the `DrcVendorOp.vendor` pattern). `load_profile` (profiles.py:281, verified) resolves against a dict of known keys — an unknown key raises, it does not interpolate into a path. `vendor="../../etc/passwd"` is rejected by the regex before it reaches `load_profile`.

#### Markdown / Data Injection (TM-4) — MITIGATED
The readme is plain markdown written via `atomic_write`, never rendered as HTML by this codebase. User-controlled values (title, company) are interpolated as data. The plan correctly documents this as "data, not a trusted executable context."

#### CSV Formula Injection (TM-5) — MITIGATED
Task 2 applies defensive quoting: cells starting with `=`, `+`, `-`, `@`, `\t`, `\r` are prefixed with `'`. This is the standard mitigation (OWASP CSV injection). Notably this is a **new** defense not present in the existing `export_jlcpcb_bom` — the plan is improving on the prior art. Good.

#### Symlink Escape (TM-6) — PARTIALLY MITIGATED
`build_dir` is created with `mkdir(parents=True, exist_ok=False)` under the resolved `project_dir`. The plan states wrappers "receive absolute build_dir paths." This is reasonable. However, the threat model entry is slightly weaker than the others: it does not explicitly address what happens if a *source* file (the `.kicad_pcb` or `.kicad_sch`) is itself a symlink pointing outside the project. In practice, export wrappers validate paths via `_validate_pcb_path`/`_validate_sch_path` which reject `..` traversal, but symlink-following behavior is not explicitly tested.

**Council finding (LOW-2):** Consider adding a test that a symlinked `.kicad_pcb` pointing outside `project_dir` is handled safely (either resolved-and-allowed or rejected). This is defensive hardening, not a blocker — the wrappers already reject `..` and the zip only reads from `build_dir`, so the blast radius is small.

---

### Architectural Soundness

**Score: STRONG.**

#### Dual-path parsing — CORRECT
The plan correctly recognizes that the query handler receives a `PcbIR` with `_native_board=None` (the same constraint Phase 207 documented in build.py:75: "dual-path: query ir has _native_board=None"). It re-parses via `NativeParser.parse_pcb` to get the `NativeBoard` needed for both `title_block` and `run_vendor_drc`. This is the established pattern. One parse serves both needs.

#### Query dispatch for side-effect ops — CORRECT (with documented deviation)
The plan registers `build_handoff_export` as `is_readonly: True, category: "query", scope: "single_file"` and deliberately does NOT add it to `CROSS_FILE_OP_TYPES`. This matches the shipped Phase 207 decision for `build_create` (verified: `CROSS_FILE_OP_TYPES` does not contain any build op; build.py docstring explicitly documents this as an "IP-4 deviation").

**Council observation (INFO):** PITFALLS.md IP-4 states build_create AND build_handoff_export "must be added to CROSS_FILE_OP_TYPES in execution.py." Phase 207 deviated from this for build_create, and Phase 208 follows the same deviation. This is a documented contradiction between the pitfalls doc and the shipped architecture. The deviation is architecturally sound (the ops read the target file and write side-effect artifacts to a separate `builds/` dir; they do not need the cross-file `ir_map` dispatch). The council accepts the deviation but recommends the pitfalls doc be updated to reflect the actual decision so future phases don't get confused. **Not a blocker for Phase 208.**

#### Handler registration merge — CORRECT
Task 5 correctly relies on the existing `_QUERY_HANDLERS.update(_BUILD_HANDLERS)` in `handlers/__init__.py:35` (verified) rather than adding a new merge. The acceptance criterion asserts the handler appears in `_QUERY_HANDLERS`. This avoids IP-3 (handler merge pitfall).

#### Validation gate tri-state — CORRECT
The tri-state mapping (error_message set → None/inconclusive; not passed with no error → False/blocks; passed → True) is well-reasoned. It correctly distinguishes "kicad-cli absent" (graceful degradation, proceed) from "DRC ran and found violations" (hard block). The `skip_validation` flag forces all to None. This is more sophisticated than a binary pass/fail and matches the CONTEXT.md graceful-degradation decision.

#### Orchestrator as a pure function — GOOD
`export_handoff` takes explicit paths and returns a `HandoffResult` dataclass. It does not mutate the target file (acceptance criterion `test_target_file_unchanged` asserts byte-identical `.kicad_pcb`). The no-partial-state guarantee (rmtree on failure) mirrors build_create. Clean.

---

### Missing Edge Cases

The plan handles most edge cases well. A few worth flagging:

1. **Empty Edge.Cuts (zero-dimension board):** `get_board_statistics` returns `(0.0, 0.0)` for dimensions if no Edge.Cuts geometry exists (RQ7). The readme generator should handle this gracefully (e.g., "Dimensions: not specified" rather than "0.0mm x 0.0mm"). Task 4 does not explicitly call this out. **(LOW — handle during execution.)**

2. **BOM with zero components:** If the schematic has no components (or all DNP), `export_bom` may produce an empty CSV. The handoff should still succeed (a bare board with no parts is valid). Task 3 Step 5 does not treat empty BOM as critical failure, which is correct, but the readme/manifest `bom_rows` count of 0 should be presented neutrally. **(LOW — handle during execution.)**

3. **Concurrent handoff runs (sub-second collision):** Task 3 Step 4 appends a uuid suffix on timestamp collision — good. But two concurrent runs could still race on `mkdir(exist_ok=False)`. The uuid fallback handles this. **(Already mitigated.)**

4. **Disk-full during zip creation:** If disk fills mid-zip, `zf.write()` raises. Task 3 Step 10 catches this via the blanket try/except + rmtree. A partial/corrupt zip will not survive (the whole build_dir is removed). **(Already mitigated.)**

5. **Vendor DRC with no profile match:** `load_profile("nonexistent")` raises (verified). The plan does not explicitly catch this before calling `run_vendor_drc`. However, the `vendor` regex (`^[a-z0-9_]+$`) plus the handler's validation would surface a bad vendor key. Still, the orchestrator's Step 3 could wrap `load_profile(vendor)` in the try/except. **(LOW — the blanket except in Step 10 catches it, but an explicit early error message would be clearer.)**

6. **JLCPCB 4-layer profile missing bom_columns:** RQ5 recommends setting `bom_columns` on BOTH `_JLCPCB_STANDARD` and `_JLCPCB_4LAYER` since they're the same vendor. Task 1 action step 2 sets it only on `_JLCPCB_STANDARD`. A user calling `build_handoff_export(vendor="jlcpcb-4layer")` (verified: this key exists at profiles.py:258) would get the generic BOM format, not JLCPCB columns. This is a minor inconsistency with HANDOFF-08's intent ("vendor-specific handoff"). **(LOW — see Findings.)**

---

## Findings Detail

### FINDING-1 (LOW): JLCPCB 4-layer profile not given bom_columns

**Where:** Task 1, action step 2.
**Issue:** Only `_JLCPCB_STANDARD` gets the new `bom_columns`/`bom_filename_pattern`. The `_JLCPCB_4LAYER` profile (profiles.py:126, key `"jlcpcb-4layer"`) inherits `None` defaults. RQ5 explicitly recommends setting it for both.
**Impact:** `build_handoff_export(vendor="jlcpcb-4layer")` produces a generic BOM, not JLCPCB-formatted. Mild HANDOFF-08 gap for the 4-layer variant.
**Fix:** Add the same 3 fields to `_JLCPCB_4LAYER` in Task 1. One-line addition.

### FINDING-2 (LOW): Typo in profile variable name

**Where:** Task 1, action step 2, line 66.
**Issue:** Plan references `_ADVANCED_CIRCITS` (missing the second C). The actual variable is `_ADVANCED_CIRCUITS` (profiles.py:188, verified).
**Impact:** Negligible — the instruction says "Do NOT modify" these profiles, and Claude won't find the misspelled name, so the actual variable simply goes unmodified as intended. But it's a documentation error.
**Fix:** Correct to `_ADVANCED_CIRCUITS`.

### FINDING-3 (LOW): Symlink-following not explicitly tested

**Where:** TM-6 mitigation.
**Issue:** The threat model addresses symlink escape at a high level but no test asserts safe behavior when a source `.kicad_pcb` is a symlink.
**Impact:** Low — wrappers reject `..` traversal and the zip only reads from `build_dir`.
**Fix:** Add `test_handoff_symlinked_source_safe` or document acceptance of current behavior.

### OBSERVATION-1 (INFO): IP-4 deviation vs PITFALLS doc

**Where:** Task 5 (CROSS_FILE_OP_TYPES not modified).
**Issue:** PITFALLS.md IP-4 says build_handoff_export "must be added to CROSS_FILE_OP_TYPES." The plan deliberately does not, following the Phase 207 build_create deviation. Both build.py docstring and this plan document the rationale.
**Impact:** None operationally. The deviation is sound.
**Action:** Update PITFALLS.md IP-4 to reflect the decided architecture (build ops are single_file query ops). Not a Phase 208 blocker.

### OBSERVATION-2 (INFO): Flat zip structure and basename collision

**Where:** Task 3 Step 9.
**Issue:** All files zipped flat with basename-only arcnames. Same-basename files would overwrite.
**Impact:** Low in practice (distinct extensions per export type; fresh build_dir per run).
**Action:** Add a code comment noting the flat-structure assumption. No test change needed.

---

## SLC Compliance Checklist

- [x] Single export list (Task 3 Step 5) consumed by manifest + readme
- [x] Single validation tri-state logic (Task 3 Step 3)
- [x] Single BOM column source (`ManufacturerProfile.bom_columns`)
- [x] Single registry entry derives registry + test count
- [x] `_resolve_project_dir` reused (not duplicated) from Phase 207
- [x] `ManufacturingArtifact.from_file` reused (not reimplemented)
- [~] Column alias map defined once in `export_bom_profile`; partial duplication risk with `export_jlcpcb_bom` if delegation not done (LOW)

## Security Checklist

- [x] Path traversal on `project_dir` rejected (TM-1)
- [x] Zip-slip prevented via basename-only arcname + test (TM-2)
- [x] Vendor/profile name regex-validated (TM-3)
- [x] Markdown treated as data, not executable context (TM-4)
- [x] CSV formula injection defended (TM-5) — improves on prior art
- [~] Symlink-following not explicitly tested (TM-6, LOW)
- [x] No partial state on failure (rmtree guarantee)
- [x] Target file never mutated (byte-identical assertion)

## Requirement Coverage Checklist

- [x] HANDOFF-01 (op exists + registered)
- [x] HANDOFF-02 (all 8 artifact types)
- [x] HANDOFF-03 (single zip + readme + manifest)
- [x] HANDOFF-04 (readme completeness)
- [x] HANDOFF-05 (profile-driven BOM)
- [x] HANDOFF-06 (pre-handoff validation gate)
- [x] HANDOFF-07 (STEP/render optional)
- [x] HANDOFF-08 (vendor-specific via profile)
- [x] HANDOFF-09 (DRC/ERC in manifest)

---

## Verdicts

### Plan Checker Verdict: VERIFICATION PASSED

All 10 automated checks pass. The plan satisfies every structural requirement: frontmatter requirements complete, must_haves aligned, query dispatch correct, registry math correct, dual-path parsing specified, streaming zip specified, validation gate specified, profile-driven BOM specified, all tasks have read_first + acceptance_criteria, threat model present.

### Council Verdict: APPROVE WITH MINOR CONDITIONS

The plan is well-researched, architecturally sound, and security-conscious. It correctly addresses Pitfalls 3, 5, and 7. The threat model is exemplary for a plan document. The three LOW findings (JLCPCB 4-layer bom_columns, profile name typo, symlink test) are minor and can be addressed during execution without re-planning. The two INFO observations (IP-4 deviation, flat zip structure) are awareness items, not action items.

**Conditions (non-blocking, address during execution):**
1. Consider extending `bom_columns` to `_JLCPCB_4LAYER` (FINDING-1).
2. Fix the `_ADVANCED_CIRCITS` typo when writing the do-not-modify list (FINDING-2).
3. Prefer doing the optional `export_jlcpcb_bom` delegation to collapse the column-map duplication (SLC).

**Recommendation:** Proceed to execution. This plan is ready.

---

*Review by: Council of Ricks (plan-reviewer seat)*
*Date: 2026-07-11*
