---
phase: 207
plan: 01
review_type: plan
date: 2026-07-10
decision: APPROVE
severity_counts:
  critical: 0
  high: 1
  medium: 4
  low: 4
specialists:
  - Architecture Rick
  - Security Rick
  - Quality Rick
  - SLC Rick
  - KiCad Rick
---

# Council of Ricks — Phase 207 Plan Review

**Phase:** 207 — Versioned Build System
**Plan reviewed:** `207-01-PLAN.md` (5 tasks, wave 0, autonomous)
**Supporting docs:** `207-CONTEXT.md`, `207-RESEARCH.md`, `207-VALIDATION.md`, `207-PATTERNS.md`
**Cross-referenced against:** `ROADMAP.md` (Phase 207), `REQUIREMENTS.md` (BUILD-01..10), `PITFALLS.md` (Pitfall 4, Pitfall 5)

**Prior gate status:** Plan-checker PASSED all 10 checks (requirement coverage, must_haves alignment, dispatch correctness, registry count, dual-path, .gitignore, read_first/acceptance coverage, threat model, task dependencies, file paths).

---

## Executive Summary

The plan carries forward the single most important lesson from Phase 206's CRITICAL defect (ARCH-1 in the 206 review: the evaluator read `ir.board` assuming a `NativeBoard`, but the query path yields a kiutils `Board`). Phase 207's `build_create` handler explicitly re-parses via `NativeParser.parse_pcb(file_path)` for `board_rev` (Task 3, step 2, citing CRITICAL CONTEXT #4 and the `drc_vendor` precedent). This is exactly the fix the 206 review demanded. The plan also correctly diagnoses that `execute_query` does not serialize the target file, so registering `build_create` as a `category: "query"` op is safe — the `.kicad_pcb` source is never rewritten, even though the handler writes side-effect artifacts to `builds/`. The `is_readonly: True` contract is honored and defended with a dedicated byte-identity test (`test_build_create_target_file_unchanged`).

The central architectural decision — `build_create` as a **query op** that creates side-effect artifacts rather than a `CROSS_FILE_OP_TYPES` entry — is **sound and well-justified**. The RESEARCH (RQ3) verified `execute_query` returns after the handler without touching the file, and the threat model correctly scopes "read-only" to mean "the target file is unchanged" (not "no filesystem effects"). This is the right call: `CROSS_FILE_OP_TYPES` wraps the source in an `AtomicOperation` and expects to serialize it back, which would be wrong for build creation. Phase 206 made a similar deviation (vendor DRC as query) and it shipped cleanly.

Requirement coverage is **complete**: all 10 BUILD requirements map to specific tasks with acceptance criteria and tests. BUILD-04 (no build on validation failure) is honestly scoped — the plan explicitly defers the full `ManufacturingReadinessGate` to Phase 208 and produces `DRAFT` status in v1, with a clear justification that DRAFT is honest (avoids Pitfall 5 false confidence). The two-tier validation model (Tier 1 simplified / Tier 2 full gate) is well-documented.

There are **no CRITICAL findings**. The plan is ready for execution after addressing one HIGH finding (a vacuous test assertion) and the medium findings during implementation. The HIGH finding is a one-line fix in the acceptance criteria, not an architectural defect.

Decision: **APPROVE** — with the HIGH finding (QUAL-1) to be fixed at execution time (it is a test assertion bug, not a plan-architecture issue). The remaining findings are medium/low and can be resolved during task implementation.

---

## Specialist Findings

### Architecture Rick — Query-op dispatch, dual-path correctness, file serialization

**Verdict: SOUND. The query-op-for-build_create decision is correct, the dual-path bug is proactively avoided, and the target file is provably untouched.**

**Verified against the codebase:**

- **Query op dispatch is correct for `build_create`.** The plan registers all 3 ops as `category: "query"`, `is_readonly: True` (Task 2). The executor (`executor.py:138`) routes `root.op_type in _QUERY_HANDLERS` to `execute_query`. I confirmed `execute_query` (`execution.py:193-230`) calls `dispatch_query(root.op_type, root, ir, file_path)` and returns `{"success", "operation", "target_file", "details"}` — it does NOT call `serialize_pcb`, does NOT create a `Transaction`, does NOT `atomic_write` the target. The `.kicad_pcb` source is never rewritten. This validates the plan's CRITICAL CONTEXT #1 and the deviation from ROADMAP IP-4 (which suggested `CROSS_FILE_OP_TYPES`).

- **The dual-path bug (206's ARCH-1) is correctly avoided.** Task 3 step 2 explicitly re-parses: `board = NativeParser.parse_pcb(file_path)` to read `board_rev`. I confirmed `NativeParser.parse_pcb` (`pcb_native_parser.py:268`) is a classmethod returning `NativeBoard`, and `NativeTitleBlock.rev` (`pcb_native_types.py:352`) is the correct field. The plan cites the `drc_vendor` handler (`query.py:88-127`) which carries the same `CRITICAL` comment about the query path leaving `_native_board = None`. Phase 206's review demanded this exact fix; Phase 207's plan bakes it in from the start. This is the strongest aspect of the plan.

- **`_QUERY_HANDLERS` merge is correct.** Task 2 creates `_BUILD_HANDLERS` + `register_build` decorator, then merges via `_QUERY_HANDLERS.update(_BUILD_HANDLERS)` in `handlers/__init__.py`. I confirmed the executor's routing check (`executor.py:138`) reads `_QUERY_HANDLERS` (imported from `handlers/__init__.py`), and the merge pattern mirrors `_FILL_ZONES_HANDLERS` exactly. The 3 new ops will be reachable post-merge. Task 2's acceptance criterion (`_QUERY_HANDLERS['build_create']` is resolvable) correctly validates this.

- **Registry count 156 → 159 is correct.** I confirmed `test_registry.py:26` currently asserts `len(OPERATION_REGISTRY) == 156` with a Phase 206 comment. Adding 3 ops yields 159. The `test_readonly_operations_count` asserts an exact `expected_readonly` frozenset (40 ops currently) — the plan correctly adds all 3 new ops to this set alphabetically (Task 2, test edit #2). Verified the set currently contains `drc_vendor`, `list_vendor_drc_profiles`, `read_board_metadata` as readonly query precedents.

**[ARCH-1, MEDIUM] The plan stores BOTH `build.json` (full Build envelope) AND `manifest.json` (ManufacturingManifest subset) in the build dir (Task 3 step 11), but `build_show` (Task 4) only loads `build.json` for the Build record and separately loads `manifest.json` for the manifest.** This is two files with overlapping data (artifacts appear in both). The RESEARCH (RQ1, "Open question for the planner") explicitly raised this: "Single-file vs. two-file on disk." The CONTEXT.md JSON example shows only manifest fields, but success criterion #3 requires "reloading reproduces the build record exactly," which needs the Build envelope fields (build_id, git_sha, status). The plan chose two files. This works, but creates a consistency risk: if `build.json` and `manifest.json` ever diverge (e.g., a future tool edits one), `build_show` could return inconsistent data. **Recommendation:** Either (a) make `manifest.json` the single source of truth by embedding the Build envelope fields (build_id, git_sha, status, source_files, build_dir) into it, or (b) document explicitly that `build.json` is authoritative for Build fields and `manifest.json` is a manufacturing-only projection. Option (a) is cleaner and matches success criterion #3's "one file" implication. Non-blocking — the two-file approach is functional, just slightly redundant.

**[ARCH-2, LOW] The `build_list` handler scans `builds_root.glob("v*_*")` and loads each `build.json` (Task 4 step 3).** This is an O(n) directory scan + O(n) JSON parse per list call. For a project with dozens of builds, this is fine. For hundreds, it could be slow. The plan does not include a build index file. Non-blocking for v1 (correctly deferred), but worth noting for Phase 209's CLI if build counts grow. The `skip corrupt dirs with a warning` resilience (Task 4 step 3) is good defensive design.

### Security Rick — Path traversal, subprocess injection, manifest injection

**Verdict: THREAT MODEL IS THOROUGH AND WELL-MITIGATED. No exploitable vectors found. Defense-in-depth is present.**

**Verified mitigations:**

- **Path traversal via `project_dir` (threat #1) — well-mitigated.** Task 3 step 1 rejects `..` in `Path(op.project_dir).parts`. This is a robust check (catches `../`, `..\\`, path-segment-level traversal, not naive substring matching). Additionally, the source-file snapshot loop (step 8) uses `candidate.resolve().is_relative_to(project_dir.resolve())` as defense-in-depth — I confirmed `Path.is_relative_to` is available on Python 3.11 (the project's runtime). The `build_show`/`build_list` handlers reuse the same `..` check (Task 4 step 1). The `safe_rev` sanitization (`re.sub(r"[^A-Za-z0-9._-]", "_", board_rev)[:64]`) prevents the board rev (user-controlled via PCB file) from injecting path separators into the directory name. Solid multi-layer defense.

- **Subprocess injection via `project_dir` (threat #2) — correctly analyzed.** The git SHA capture uses `subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(project_dir))` — an **argument list**, not a shell string. Shell injection is impossible. The threat model correctly states this. The only residual risk (malicious `project_dir` pointing to an attacker-controlled git repo) is mitigated by the same `..` validation on `project_dir`. The `try/except (subprocess.SubprocessError, FileNotFoundError, OSError)` returning `"unknown"` is correct — I confirmed `FileNotFoundError` is a subclass of `OSError`, so a missing `git` binary is caught. Never raises. Good.

- **Manifest JSON injection (threat #3) — correctly assessed as non-exploitable.** `json.dumps` escapes all special characters. The deferral of HTML escaping to Phase 208 (if manifest fields are rendered into a readme) is the right scoping decision. Non-blocking.

- **Source file snapshot bounded scope (threat #4) — correctly analyzed.** The stem-based discovery (`project_dir / f"{stem}{ext}"`) cannot reach arbitrary files outside the project because candidates are constructed from the fixed stem + 3 extensions. The `is_relative_to` check is defense-in-depth. The plan correctly notes "never follow symlinks out of the project dir" — recommend the implementation also add `candidate.is_symlink()` rejection or `resolve()` checks, but this is minor.

**[SEC-1, LOW] The `project_dir` validation (`if ".." in Path(op.project_dir).parts`) rejects literal `..` segments, but does not reject absolute paths pointing outside the expected root.** For example, `project_dir="/etc"` or `project_dir="/Users/attacker"` would pass the `..` check (no `..` in `.parts`) but write the build dir to an unintended location. In the kicad-agent trust model, the caller controls `project_dir` intentionally (it's an op field for "run this build in this project root"), so this is arguably by-design. However, if this op is ever exposed via MCP to untrusted input (Phase 209), an absolute `project_dir` could be abused. **Recommendation:** Document that `project_dir` is caller-trusted, OR add a check that `build_dir.resolve().is_relative_to(project_dir.resolve())` after construction (the snapshot loop already does this for candidates, but not for the `build_dir` itself). Non-blocking for Phase 207 (no untrusted MCP exposure yet), but flag for Phase 209.

**[SEC-2, LOW] The `FileExistsError` collision retry (Task 3 step 6) appends `build_id[:8]` and retries `mkdir(parents=True, exist_ok=False)`, but if THAT also collides (astronomically unlikely with UUID4), the handler would raise uncaught.** This is not a security issue, but the retry loop should either be bounded or fall back to `exist_ok=True` with a unique suffix. Given UUID4 collision probability (~10^-37), this is theoretical. Non-blocking.

### Quality Rick — Test coverage, edge cases, false-confidence guards

**Verdict: STRONG test strategy. The dual-path guard, no-partial-state test, and byte-identity test are exactly right. One vacuous acceptance criterion must be fixed.**

**Strengths:**

- **The byte-identity test (`test_build_create_target_file_unchanged`, Task 3) is the correct guard for the `is_readonly: True` contract.** This directly addresses the 206 review's SEC caveat ("add a test asserting the target `.kicad_pcb` is byte-identical before/after"). It checks both hash and mtime. This is the most important defensive test in the plan.

- **The no-partial-state test (`test_build_create_no_partial_state_on_parse_failure`, Task 3) correctly targets BUILD-04.** It asserts both `result["success"] == False` AND no `builds/` directory remains. The `shutil.rmtree(build_dir, ignore_errors=True)` cleanup in the except block is the right pattern.

- **The round-trip tests (Task 1: `test_manifest_to_json_round_trip`, `test_build_to_dict_round_trip`) correctly verify lossless serialization** — the `status` enum surviving round-trip is explicitly tested, which is a common dataclass-serialization failure point.

- **The diff tests (Task 1 + Task 4) cover both change-detection and identity** — `test_diff_builds_identical` is a good negative case.

- **The corrupt-dir resilience test (`test_build_list_skips_corrupt_dir`, Task 4) prevents one bad build from breaking the entire list op.** Good defensive design.

**[QUAL-1, HIGH] Task 5's acceptance criterion contains a vacuous Python assertion that will always pass, regardless of whether the 3 ops are in the registry.** The criterion reads:
```python
.venv/bin/python -c "from kicad_agent.ops.registry import validate_registry_completeness; r=validate_registry_completeness(); assert set(['build_create','build_list','build_show']) not in set(r['missing_from_registry'])"
```
The expression `set(['build_create','build_list','build_show']) not in set(r['missing_from_registry'])` is a **category error**: it checks whether the *set object* `{build_create, build_list, build_show}` is an *element* of the `missing_from_registry` list (which contains strings, not sets). Since a set is never equal to a string, this always evaluates to `True` — the assertion passes even if all 3 ops ARE missing. The correct assertion should be:
```python
assert not (set(['build_create','build_list','build_show']) & set(r['missing_from_registry']))
```
or simply:
```python
assert 'build_create' not in r['missing_from_registry']
```
This same vacuous-expression bug appears in the `<verification_criteria>` block (line 433). **Action:** Fix both occurrences. The `test_registry.py` count assertion (`== 159`) and the readonly-set assertion are the real coverage guards and they are correct — this vacuous check is just dead weight that gives false confidence. One-line fix.

**[QUAL-2, MEDIUM] The `test_build_create_no_partial_state_on_parse_failure` test (Task 3) has a hedged implementation note: "If parse can't be easily forced to fail, test the error path by pointing target at a non-PCB file."** This leaves the test design ambiguous. A non-PCB file (e.g., a text file) may not fail `NativeParser.parse_pcb` the same way a malformed PCB does — it might parse as an empty board or raise a different exception. The plan should specify the exact failure mode: either (a) create a fixture with intentionally corrupt S-expression syntax (e.g., unbalanced parens), or (b) mock `NativeParser.parse_pcb` to raise. Option (a) is more faithful to production. The current hedging risks the test being a no-op or testing the wrong path. **Action:** Pin the failure mechanism in the test (recommend a corrupt-parens fixture).

**[QUAL-3, MEDIUM] No test verifies that `build_create` with `skip_validation=False` (the default) produces a `DRAFT` build with honest status semantics.** The plan has `test_build_create_skip_validation_creates_draft` (with `skip_validation=True`), but the DEFAULT path (`skip_validation=False`) is the production behavior and it also produces DRAFT (per CRITICAL CONTEXT #6 — the full gate is deferred to Phase 208). There should be a test asserting that the default `build_create` (no `skip_validation`) still succeeds and produces DRAFT (not VALIDATED), confirming the two-tier model works and Pitfall 5 is avoided. **Action:** Add `test_build_create_default_produces_draft` exercising the default path.

### SLC Rick — No workarounds, no stubs, complete solutions

**Verdict: COMPLIANT. Task 2 creates skeleton stubs but explicitly implements them in Tasks 3-4 within the same plan — not shipped as stubs.**

- Every task has full implementation specification. The `Build` model, serialization, handlers, and tests are concretely specified with field lists, step sequences, and code patterns.
- Task 2's "stub" handlers (skeleton `_BUILD_HANDLERS` dict + decorated functions) are a sequencing device for dependency ordering — Task 3 and Task 4 replace them with full implementations. This is not a shipped stub; it's incremental development within one plan. The acceptance criteria for Task 2 validate the wiring (imports, registry, merge), not the stub behavior.
- The `must_haves` (11 items) are concrete and falsifiable. The `<verification_criteria>` maps all 7 ROADMAP success criteria to specific test assertions.
- Deferred items (CLI, MCP, handoff zip, full gate) are correctly out of scope per CONTEXT.md's deferred section and ROADMAP Phase 208/209 boundaries. No scope creep.

**[SLC-1, MEDIUM] BUILD-04 ("build is not created if validation fails") is satisfied only for the Tier-2 (full gate) path, which Phase 207 does NOT exercise — it always produces DRAFT.** The plan acknowledges this honestly (CRITICAL CONTEXT #6, RESEARCH Validation Architecture), but the requirement as written in REQUIREMENTS.md says "Build creation runs `ManufacturingReadinessGate` (existing 5-check gate) — build is not created if validation fails." In v1, `build_create` does NOT run the full 5-check gate; it runs a lightweight parse check and produces DRAFT. This is a **deliberate scope reduction** documented in CONTEXT.md ("Claude's Discretion: Simplified validation"). The plan is transparent about this, and the DRAFT status honestly reflects "not fully validated" (avoiding Pitfall 5). However, strictly reading BUILD-04, the gate is not run. **Assessment:** This is an acceptable v1 scoping decision (the full gate requires Phase 208's context: DRC/DFM/export artifacts), and the status semantics are honest. The plan correctly documents this in the threat model's note and the `<phase_context>` decision #7. Recommend the plan add an explicit note in Task 3 that BUILD-04's full gate enforcement is deferred to Phase 208 and cite this as an intentional, documented deviation — so an auditor reading BUILD-04 against the shipped code understands why `ManufacturingReadinessGate` is not invoked.

**[SLC-2, LOW] The `Build.transition_to` method is specified but no test exercises it through a real state transition driven by an op.** Task 1 tests `transition_to` directly (unit test), which is correct. But in Phase 207, nothing transitions a build from DRAFT → VALIDATED (that's Phase 208). The method is correct and tested in isolation — this is fine for v1, but the plan should note that `transition_to` is not yet wired to any op (it's a model-level capability awaiting Phase 208's orchestrator). Non-blocking.

### KiCad Rick — Build provenance, manifest fidelity, source-file completeness

**Verdict: ACCURATE on KiCad file model and manifest semantics. One completeness gap (multi-sheet schematics) is correctly flagged as deferred.**

**Verified:**

- **`board_rev` provenance is correct.** Reading `title_block.rev` via `NativeParser.parse_pcb` (Task 3 step 2) is the right source — Phase 205 froze this field at `pcb_native_types.py:352`. The fallback to `"unknown"` when `title_block` is None or `rev` is empty is correct (not all boards have title blocks).

- **Source-file discovery is stem-based and bounded.** The `.kicad_pcb` + `.kicad_sch` + `.kicad_pro` triple (Task 3 step 8) captures the primary files. The RESEARCH (RQ7) correctly notes the multi-sheet limitation: "Multi-sheet projects have multiple `.kicad_sch` files (root + sub-sheets). The stem-based approach captures only the root schematic." This is honestly documented as a Phase 208+ concern. For v1, snapshotting the root files is a reasonable MVP.

- **`shutil.copy2` is correct** (preserves mtime/permissions). The RESEARCH (RQ7) confirms this is the codebase standard (`transaction.py:138`, `gap_fill_engine.py:151`, etc.).

- **Manifest SHA256 hashing via `ManufacturingArtifact.from_file` is correct.** The existing `from_file` (`manufacturing_manifest.py:31`) hashes file bytes. The plan reuses it for snapshots (`generated_by="snapshot"`), which is semantically honest — these are snapshot copies, not kicad-cli-generated artifacts.

**[KCAD-1, MEDIUM] The manifest's `project_name` and `board_name` are both set to the file stem (Task 3 step 9: `project_name=stem, board_name=stem`).** This is a simplification. In KiCad, the project name comes from the `.kicad_pro` file stem, and the board name may differ (it's set in the board's title block or derived from the project). For a project named `power-board` with the PCB `power-board.kicad_pcb`, stem == project name == board name — fine. But if the PCB is in a subdirectory or has a different name than the project, this conflates them. Non-blocking for v1 (the stem is a reasonable default), but the plan should note that `project_name` ideally comes from the `.kicad_pro` (if present) and `board_name` from `title_block.title`. Recommend a follow-up note.

**[KCAD-2, LOW] The build directory naming `v{safe_rev}_{timestamp}` uses `safe_rev` derived from `board_rev`, but `board_rev` may be `"unknown"` (when title_block.rev is empty).** This produces `vunknown_20260710_120000/` — functional but ugly. The plan does not special-case this. Minor; recommend defaulting to `"norev"` or `"0"` when rev is unknown, for cleaner directory names. Non-blocking.

---

## Severity Summary

| Severity | Count | IDs |
|----------|-------|-----|
| Critical | 0 | — |
| High | 1 | QUAL-1 |
| Medium | 4 | ARCH-1, QUAL-2, QUAL-3, SLC-1 |
| Low | 4 | ARCH-2, SEC-1, SEC-2, KCAD-2 |

(Note: KCAD-1 and SLC-2 are assessed as informational/minor and folded into the medium/low counts where material. ARCH-1 is the two-file redundancy, classified medium.)

---

## Requirement Coverage Check (BUILD-01 through BUILD-10)

| REQ | Covered? | By Task(s) | Acceptance Criterion | Notes |
|-----|----------|------------|----------------------|-------|
| BUILD-01 (create versioned build) | YES | 2, 3 | `test_build_create_creates_directory`, `_handle_build_create` grep | Sound. Snapshots + git SHA + board rev. |
| BUILD-02 (build record fields) | YES | 1 | `class Build` grep, `test_build_to_dict_round_trip` | All 9 fields specified (build_id, board_rev, source_files, git_sha, created_at, status, artifacts, manifest_path, build_dir). |
| BUILD-03 (status lifecycle) | YES | 1 | `class BuildStatus` grep, `test_build_status_transition_allowed/disallowed` | DRAFT→VALIDATED→EXPORTED→HANDED_OFF via `transition_to`. |
| BUILD-04 (no build on validation fail) | PARTIAL (v1 scope) | 3 | `test_build_create_no_partial_state_on_parse_failure` | **See SLC-1:** full 5-check gate deferred to Phase 208; v1 produces DRAFT. Honestly documented. Parse-failure path IS tested (no partial state). |
| BUILD-05 (manifest serialized) | YES | 1, 3 | `def to_json/save/load` grep, `test_manifest_to_json_round_trip` | Serialization round-trip verified lossless. |
| BUILD-06 (build dir structure) | YES | 3 | `test_build_create_creates_directory`, `builds/v*_*/` glob | `builds/v{rev}_{timestamp}/` confirmed. |
| BUILD-07 (list builds) | YES | 4 | `test_build_list_returns_builds`, `_handle_build_list` grep | O(n) scan + sort desc. Sound. |
| BUILD-08 (show build details) | YES | 4 | `test_build_show_returns_details`, `_handle_build_show` grep | Round-trip manifest verified. |
| BUILD-09 (builds/ in .gitignore) | YES | 5 | `grep "^builds/" .gitignore` | Confirmed `builds/` absent currently; plan adds it. `build/` (singular) preserved. |
| BUILD-10 (diff two builds) | YES | 1, 4 | `def diff_builds` grep, `test_diff_builds_detects_changes`, `diff_build_id` param | `diff_builds()` utility + `build_show` integration. |

All 10 requirements have a clear model → handler → test path. BUILD-04 is scope-reduced in v1 (documented, honest). No orphan requirements.

---

## Success Criteria Check (ROADMAP Phase 207)

| SC | Plan coverage | Status |
|----|---------------|--------|
| 1. `build_create` returns build_id, board_rev, git_sha, timestamp; dir created | Task 3 (handler) + Task 3 (`test_build_create_creates_directory`, `test_build_create_reads_board_rev`, `test_build_create_records_git_sha`) | Covered. |
| 2. `build_create` on parse failure → error, NO build | Task 3 step 7 (rmtree cleanup) + `test_build_create_no_partial_state_on_parse_failure` | Covered (for parse failure; full gate failure deferred to Phase 208 — see SLC-1). |
| 3. `manifest.json` serialized with SHA256; `build_show` reproduces record exactly | Task 1 (serialization) + Task 3 (save) + Task 4 (`build_show` loads + `test_build_show_round_trip_manifest`) | Covered. See ARCH-1 on two-file redundancy. |
| 4. `build_list` shows all builds with status | Task 4 + `test_build_list_returns_builds` | Covered. |
| 5. `builds/` in `.gitignore` | Task 5 + `grep "^builds/" .gitignore` | Covered. |

5 of 5 success criteria covered. SC #2 is scoped to parse-failure in v1 (full-gate failure is Phase 208).

---

## Pitfall Coverage

**Pitfall 4 (Build Directory Pollution / Git Noise) — Addressed, comprehensively.** Task 5 adds `builds/` to `.gitignore`. The plan explicitly preserves `build/` (singular, Python artifacts) and does NOT ignore `.kicad_build_spec.json` (Phase 205 source sidecar). I confirmed `builds/` is currently absent from `.gitignore` and `build/` is present. The bare `builds/` (no leading slash) correctly matches at any depth for project-scoped trees. Good.

**Pitfall 5 (Manifest Incompleteness / False Confidence) — Addressed via honest status semantics.** The DRAFT status explicitly signals "not fully validated." The plan's CRITICAL CONTEXT #6 and the threat model's note document that full `ManufacturingReadinessGate` runs in Phase 208. The two-tier validation model (Tier 1 simplified / Tier 2 full gate) avoids false confidence: a v1 build is honestly DRAFT, not VALIDATED. See SLC-1 for the BUILD-04 scoping nuance.

---

## The Central Decision — Is `build_create` as a Query Op Sound?

**Yes. This is the correct architecture.**

The RESEARCH (RQ3) empirically verified that `execute_query` (`execution.py:193-230`) does not serialize the target file after the handler returns — no `serialize_pcb`, no `Transaction`, no `atomic_write`. The target `.kicad_pcb` mtime is unchanged. Therefore, registering `build_create` as `category: "query"`, `is_readonly: True` is semantically honest: the *target file* is read-only, even though the handler creates side-effect artifacts in `builds/`.

The alternative (`CROSS_FILE_OP_TYPES`, per ROADMAP IP-4) would be wrong: that dispatch path wraps the source in an `AtomicOperation` and expects to serialize it back, which is unnecessary and incorrect for build creation (the source doesn't change). The query-op path is simpler, correct, and consistent with Phase 206's precedent (`drc_vendor` also writes side-effect reports yet is `is_readonly: True`).

The plan's `<phase_context>` decision #1 and the threat model correctly document this as a deliberate, justified deviation from IP-4. The `test_build_create_target_file_unchanged` test (byte-identity + mtime) is the right defensive guard to prove the contract holds.

---

## Recommendations (ordered by priority)

1. **(HIGH, fix at execution start) [QUAL-1]** Fix the vacuous acceptance-criterion assertion in Task 5 (and the `<verification_criteria>` block). Replace `set([...]) not in set(r['missing_from_registry'])` with `assert 'build_create' not in r['missing_from_registry']` (and the same for the other two ops). The `test_registry.py` count/set assertions are the real guard; this is a one-line correctness fix to avoid false confidence.

2. **(MEDIUM, during Task 3) [QUAL-2]** Pin the failure mechanism in `test_build_create_no_partial_state_on_parse_failure`: use a corrupt-S-expression fixture (unbalanced parens) or an explicit mock of `NativeParser.parse_pcb` raising. Remove the "if parse can't be easily forced to fail" hedge.

3. **(MEDIUM, during Task 3) [QUAL-3]** Add `test_build_create_default_produces_draft` exercising the default `skip_validation=False` path to confirm it produces DRAFT (not VALIDATED), defending the two-tier model and Pitfall 5 avoidance.

4. **(MEDIUM, during Task 3) [SLC-1]** Add an explicit note in Task 3 that BUILD-04's full `ManufacturingReadinessGate` enforcement is deferred to Phase 208, citing CONTEXT.md "Claude's Discretion: Simplified validation." Make the intentional scope reduction auditable.

5. **(MEDIUM, during Task 3/4) [ARCH-1]** Decide single-file vs. two-file manifest strategy. Prefer embedding the full Build envelope in `manifest.json` (so `build_show` reads one file), or document that `build.json` is authoritative and `manifest.json` is a projection. Eliminate the consistency risk.

6. **(LOW, opportunistic) [SEC-1]** Add a note that `project_dir` is caller-trusted, or add `build_dir.resolve().is_relative_to(project_dir.resolve())` post-construction. [SEC-2] Bound the collision retry or fall back to a unique suffix. [KCAD-1] Note that `project_name`/`board_name` stem-based assignment is a v1 simplification. [KCAD-2] Default `safe_rev` to `"norev"` when board_rev is `"unknown"` for cleaner dir names.

---

## Decision

# APPROVE

**Rationale:** The plan is architecturally sound, carries forward the critical lesson from Phase 206's CRITICAL defect (dual-path re-parse is baked into the handler from the start), and correctly justifies the query-op-for-build_create deviation with empirical evidence from the RESEARCH. All 10 BUILD requirements are covered with clear model → handler → test paths. The threat model is thorough, the security mitigations are defense-in-depth, and the `is_readonly: True` contract is both correct and test-defended.

There are **no CRITICAL findings**. The single HIGH finding (QUAL-1) is a vacuous test assertion — a one-line fix that does not affect the plan's architecture or requirement coverage. The medium findings (two-file redundancy, test-failure-mode pinning, default-path test, BUILD-04 scoping note) are implementation refinements that can be resolved during task execution without re-planning.

**Required for execution (address QUAL-1 at task start):**
- QUAL-1: Fix the vacuous assertion in Task 5 acceptance criteria and `<verification_criteria>`.

**Strongly recommended during execution:**
- QUAL-2, QUAL-3: Harden the parse-failure test and add the default-path DRAFT test.
- SLC-1: Document the BUILD-04 v1 scope reduction explicitly.
- ARCH-1: Resolve single-file vs. two-file manifest strategy.

The plan demonstrates that the Phase 206 review's hardest lesson (query-path dual-parse) was learned and applied proactively. This is exactly the cross-phase knowledge transfer the Council process is designed to enforce. The plan is ready for execution.
