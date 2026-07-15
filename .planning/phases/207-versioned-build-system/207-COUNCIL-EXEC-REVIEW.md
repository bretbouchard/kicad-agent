# Phase 207 — Council of Ricks Execution Review

**Reviewer:** Council-of-Ricks execution-reviewer agent
**Date:** 2026-07-10
**Phase:** 207-versioned-build-system
**Verdict:** APPROVE

## Executive Summary

Phase 207 shipped a versioned build system: a frozen `Build` record, `BuildStatus` lifecycle, lossless manifest serialization, and three query ops (`build_create`/`build_list`/`build_show`) with build diffing. Execution followed the plan exactly (5 tasks, 5 atomic commits, "no deviations from plan" per the summary). All 10 BUILD requirements are addressed. 73 build+registry tests pass; 42 regression tests (manufacturing gate + board metadata) pass. One medium security finding (absolute-path project_dir not rejected) and three low findings; none block approval.

## 1. SLC Compliance

| Check | Status | Evidence |
|-------|--------|----------|
| Registry count == 159 | PASS | `len(OPERATION_REGISTRY) == 159`; `test_registry_has_98_operations` passes |
| Schema/registry in sync | PASS | `validate_registry_completeness()` → `extra_in_registry: []`; `missing_from_registry` has only the 3 pre-existing entries, none from Phase 207 |
| 3 ops in readonly set | PASS | `test_readonly_operations_count` exact-set includes `build_create`, `build_list`, `build_show` |
| All 3 ops reachable via `_QUERY_HANDLERS` | PASS | `_QUERY_HANDLERS.update(_BUILD_HANDLERS)` in `handlers/__init__.py:35`; confirmed via the test imports `from volta.ops.handlers.query import _QUERY_HANDLERS` |
| Schema union + import + `__all__` all updated | PASS | `schema.py:570-572` (union), `285-287` (import), `788-791` (`__all__`) |
| No partial state on failure (BUILD-04) | PASS | `try/except` wraps handler body; `shutil.rmtree(build_dir, ignore_errors=True)` on any failure |
| Target `.kicad_pcb` byte-identical | PASS | `test_build_create_target_file_unchanged` asserts hash + mtime unchanged |

SLC compliance is clean. The summary's note about "92 pre-existing failures (SLC SKILL.md operation-count drift `149 != 156`)" refers to stale `prompt.md`/`SKILL.md` documentation (the skill lists "19 operation types" and `prompt.md` has 81 `op_type` references vs. 159 actual ops) — this predates Phase 207 and is not a Phase 207 regression.

## 2. Security

Reviewed against the 207-CONTEXT.md threat model:

- **TM#1 (path traversal via project_dir):** `..` segments rejected. `is_relative_to` defense-in-depth on resolved source candidates. Board rev sanitized to `[A-Za-z0-9._-]` before directory-name interpolation. **Gap:** absolute paths (e.g. `/etc`) are NOT rejected by the `..` check (COR-MED-1). Low exploitability in the single-user model; the executor runs as the invoking user and `mkdir` under `/etc` fails for non-root. Recommend follow-up.
- **TM#2 (subprocess injection):** `subprocess.run(["git","rev-parse","HEAD"], cwd=...)` uses argument list, no shell. Wrapped in try/except returning `"unknown"`. Never raises. Correct.
- **TM#3 (JSON injection):** `json.dumps` escapes safely. project_name/board_name derived from file stem. No issue.
- **TM#4 (snapshot escape):** Stem-based discovery bounded to project_dir; `is_relative_to(resolved_project)` after `resolve()`. No symlink escape. Correct.
- **`is_readonly: True` honesty:** `is_readonly` is a claim about the TARGET `.kicad_pcb`, not all filesystem effects. The handler writes to `builds/` (a side-effect tree) but never touches the target. Test defends this with byte+mtime identity. This matches the `drc_vendor` precedent and is documented as a deliberate IP-4 deviation in CONTEXT.md. Correct.

Security posture is strong. One medium finding (COR-MED-1) is worth a follow-up but is not exploitable in the deployment model.

## 3. Code Quality

See 207-REVIEW.md for the detailed code review. Summary:
- Frozen dataclass pattern used consistently (CR-01).
- `transition_to` via `dataclasses.replace` enforces forward-only lifecycle.
- Clean model/handler separation.
- Thorough docstrings documenting design decisions.
- Minor: dead `skip_validation` field (COR-LOW-1), broad except (COR-LOW-2, intentional), duplicated traversal check (COR-LOW-3).

Code quality is high.

## 4. Requirement Coverage (BUILD-01 through BUILD-10)

| Req | Description | Status | Evidence |
|-----|-------------|--------|----------|
| BUILD-01 | `build_create` snapshots source files, records git SHA, captures board revision | PASS | `_handle_build_create` does all three; tests verify each field |
| BUILD-02 | Build record has build_id, board_rev, source paths, git_sha, timestamp, status, artifacts | PASS | `Build` dataclass has all 9 fields (build_id, board_rev, source_files, git_sha, created_at, status, artifacts, manifest_path, build_dir) |
| BUILD-03 | Status lifecycle draft→validated→exported→handed_off with clear transitions | PASS | `BuildStatus` enum + `_ALLOWED_TRANSITIONS` + `transition_to`; full-chain + skip + backwards tests pass |
| BUILD-04 | Build not created if validation fails (no partial state) | PASS (partial) | Parse-failure path tested; rmtree cleanup present. Full gate deferred to Phase 208 per CONTEXT.md; DRAFT status is honest |
| BUILD-05 | Manifest serialized as manifest.json with SHA256-hashed artifacts | PASS | `ManufacturingManifest.save` + `ManufacturingArtifact.from_file` (sha256); round-trip tests pass |
| BUILD-06 | Build artifacts in `builds/v{rev}_{timestamp}/` | PASS | `build_dir_name = f"v{safe_rev}_{dir_timestamp}"`; directory-creation tests pass |
| BUILD-07 | `build_list` lists all builds for a project | PASS | `_handle_build_list` scans `builds/v*_*`; 4 tests cover returns/empty/corrupt/sort |
| BUILD-08 | `build_show` views build details (manifest, artifacts, status) | PASS | `_handle_build_show` returns full details; 6 tests cover details/not-found/manifest/diff |
| BUILD-09 | `builds/` in `.gitignore` | PASS | `.gitignore:9` `builds/`; original `build/` preserved at line 7 |
| BUILD-10 | Diff two builds (source diffs, artifact diffs, status changes) | PASS | `diff_builds()` + `BuildDiff`; exposed via `build_show` `diff_build_id` param; 4 diff tests |

All 10 requirements addressed. BUILD-04 is the only one with a caveat: the literal "gate fails → no build" arm is not tested because the full `ManufacturingReadinessGate` is deferred to Phase 208. The CONTEXT.md and plan explicitly justify this (DRAFT status is honest, avoids Pitfall 5 false confidence). This is an acceptable scope decision, not a gap.

## 5. Test Quality

35 tests in `test_build_system.py`. Quality assessment:

**Strengths:**
- Tests verify load-bearing security/contract properties, not just happy paths: `test_build_create_target_file_unchanged` (hash + mtime), `test_build_create_rejects_path_traversal`, `test_build_create_snapshots_source_files` (re-hash the copy and compare to artifact sha256), `test_build_create_no_partial_state_on_parse_failure` (asserts no `builds/` dir).
- Round-trip tests assert type preservation (`isinstance(loaded.artifacts, tuple)`, `loaded.status == BuildStatus.VALIDATED`), not just value equality.
- Lifecycle tests cover allowed transitions, the full chain, backwards (disallowed), skip (disallowed), and terminal (no transitions).
- Git SHA test is properly guarded with `pytest.mark.skipif(not shutil.which("git"))` and tests both repo and non-repo paths.
- Corrupt-dir handling tested for both `build_list` (skip + continue) and `build_show` (not-found + diff-not-found).

**Gaps (non-blocking):**
- No test for BUILD-04's gate-failure arm (full `ManufacturingReadinessGate` deferred — acceptable).
- No test for the absolute-path `project_dir` (COR-MED-1).
- `skip_validation=True` is passed in every `TestBuildCreate` test but is a no-op — the tests would pass identically without it, masking the dead-field issue.

Test quality is strong.

## Findings

Carried over from the code review:
- COR-MED-1: absolute-path `project_dir` not rejected (security gap, low exploitability).
- COR-LOW-1: `skip_validation` dead field.
- COR-LOW-2: broad except (intentional).
- COR-LOW-3: duplicated traversal check.

No additional Council-level findings. The execution matches the plan, requirements are covered, and no SLC or security issue rises to a blocking level.

## Verdict

**APPROVE.** Phase 207 is well-executed: plan adherence is exact, all 10 BUILD requirements are addressed, 73 phase tests + 42 regression tests pass, registry/schema are in sync, and the threat model is substantially mitigated. The one medium finding (absolute-path rejection) is recommended for a follow-up but does not block — it is not exploitable in the single-user volta model and the `mkdir` permission check provides a backstop.
