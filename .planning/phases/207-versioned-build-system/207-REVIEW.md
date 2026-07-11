# Phase 207 Code Review

**Reviewer:** code-reviewer agent
**Date:** 2026-07-10
**Phase:** 207-versioned-build-system
**Verdict:** APPROVE (with minor findings, non-blocking)

## Scope

Files reviewed:
- `src/kicad_agent/manufacturing/build.py` (new)
- `src/kicad_agent/ops/handlers/build.py` (new)
- `src/kicad_agent/validation/gates/manufacturing_manifest.py` (modified)
- `src/kicad_agent/ops/_schema_pcb.py` (modified — 3 Op classes)
- `src/kicad_agent/ops/handlers/__init__.py` (modified)
- `src/kicad_agent/ops/registry.py` (modified)
- `src/kicad_agent/ops/schema.py` (modified)
- `tests/test_build_system.py` (new)
- `tests/test_registry.py` (modified)
- `.gitignore` (modified)

## 1. Code Quality

**Strengths:**
- Clean separation: the frozen `Build`/`BuildStatus`/`BuildDiff` model lives in `manufacturing/build.py`; the op-side I/O (disk snapshots, git capture) lives in the handler. The model is pure data with no filesystem coupling, which makes it trivially testable.
- `Build.transition_to` uses `dataclasses.replace` on the frozen dataclass, matching the CR-01 pattern. Forward-only transitions are enforced via `_ALLOWED_TRANSITIONS`; disallowed moves raise `ValueError` with a clear message listing allowed targets.
- The no-partial-state error path in `_handle_build_create` wraps the entire body in `try/except`, captures `build_dir` in an outer variable, and calls `shutil.rmtree(build_dir, ignore_errors=True)` on any failure. This correctly satisfies BUILD-04.
- `diff_builds` returns sorted tuples for determinism (RQ8 compliance) and uses semantic identity (artifact `name`, not `path`) for artifact set arithmetic.
- The handler module documents its design choices in module/ function docstrings (IP-4 deviation, dual-path re-parse, simplified v1 validation). This is exactly the kind of provenance a downstream maintainer needs.

**Minor issues:**

- **CR-LOW-1 (unused field):** `BuildCreateOp.skip_validation` is declared in the schema (`_schema_pcb.py:1310-1312`) and passed in every test, but the handler `_handle_build_create` never reads `op.skip_validation`. It is a no-op. This is harmless for Phase 207 (validation is always simplified / DRAFT), but the field is misleading. Either wire it up in Phase 208 or remove it. All 9 `TestBuildCreate` tests pass `skip_validation=True` yet the outcome would be identical without it.

- **CR-LOW-2 (broad except):** `_handle_build_create` catches bare `except Exception as exc`. This is intentional for BUILD-04 (no partial state on ANY failure), and the failure is logged + returned as an error dict, so it is defensible. Noting it for awareness — a parse failure and a disk-full error produce indistinguishable user messages.

- **CR-LOW-3 (duplicated traversal check):** The `..` check is duplicated three times: once inline in `_handle_build_create` and twice via the shared `_resolve_project_dir` helper. `_handle_build_create` does NOT use `_resolve_project_dir` (it inlines its own copy), while `build_list`/`build_show` use the helper. Minor inconsistency — the inline copy in build_create should call `_resolve_project_dir` for DRY. Functionally identical.

## 2. Security

**Threat model coverage (per 207-CONTEXT.md threat_model):**

- **#1 Path traversal via project_dir:** Mitigated. The handler checks `".." in Path(op.project_dir).parts` and rejects with a clear error. Source-file discovery additionally uses `candidate.resolve().is_relative_to(resolved_project)` as defense-in-depth, so even a symlinked source file cannot escape the project root. Board rev is sanitized via `re.sub(r"[^A-Za-z0-9._-]", "_", board_rev)[:64]` before interpolation into the directory name. The `test_build_create_rejects_path_traversal` test covers the `..` case.

  - **CR-MED-1 (absolute path not rejected):** The traversal check rejects `..` but NOT absolute paths. `Path("/etc/passwd").parts == ('/', 'etc', 'passwd')` contains no `..`, so `project_dir="/etc"` would pass the check and cause `build_create` to write `builds/` under `/etc`. On macOS/Linux this would fail at `mkdir` for non-root users (permission denied), but a user running as root, or a project_dir under a writable absolute path, could create build artifacts outside the intended tree. Recommend adding `if op.project_dir and Path(op.project_dir).is_absolute():` rejection, matching the `TargetFile` pattern (`_validate_target_file` rejects `v.startswith("/")`). Low exploitability in the kicad-agent single-user model, but it is a gap relative to the threat model's intent.

- **#2 Subprocess injection via project_dir:** Correctly mitigated. `subprocess.run(["git", "rev-parse", "HEAD"], cwd=...)` uses an argument list (no `shell=True`), so command injection is impossible. Wrapped in `try/except (subprocess.SubprocessError, FileNotFoundError, OSError)` returning `"unknown"`. `_get_git_sha` never raises. The `test_git_sha_unknown_when_not_a_repo` and `test_git_sha_from_repo` tests cover both paths.

- **#3 Manifest JSON injection:** `json.dumps` escapes all special characters. `project_name`/`board_name` are derived from `Path(file_path).stem`, not raw user input, further limiting attack surface. No issue.

- **#4 Source snapshot escape:** Stem-based discovery (`project_dir / f"{stem}{ext}"`) is inherently bounded to the project dir. The `is_relative_to` check adds belt-and-suspenders. No symlink-following escape possible because `resolve()` is called before the containment check. Correct.

- **`is_readonly: True` honesty:** The target `.kicad_pcb` is snapshotted via `shutil.copy2` (read + copy) and never written. `test_build_create_target_file_unchanged` asserts byte-identity + mtime preservation. The registry claim is defended.

## 3. SLC (Sub-Least-Commit) Compliance

- Registry count: **159** (156 + 3), matches `test_registry_has_98_operations` assertion. Confirmed via `len(OPERATION_REGISTRY)`.
- `validate_registry_completeness()` reports `extra_in_registry: []` and `missing_from_registry` contains only the 3 pre-existing entries (`add_design_note`, `apply_floor_plan`, `place_and_wire_power_units`) — none introduced by Phase 207. The 3 new ops appear in BOTH the schema union and the registry.
- `test_readonly_operations_count` exact-set assertion updated with `build_create`, `build_list`, `build_show` in alphabetical position. Passes.
- Schema union (`schema.py:570-572`) includes all 3 ops; `__all__` (`schema.py:788-791`) re-exports them; import block (`schema.py:285-287`) pulls them from `_schema_pcb`. All three locations in sync.
- The `..` in handlers/__init__.py merge (`_QUERY_HANDLERS.update(_BUILD_HANDLERS)`) matches the established `_FILL_ZONES_HANDLERS` pattern.

No SLC violations.

## 4. Manifest Round-Trip Fidelity

**ManufacturingArtifact:** `to_dict()` does explicit field mapping (NOT `dataclasses.asdict`), `from_dict()` reconstructs via explicit kwargs. `test_artifact_to_from_dict` asserts `from_dict(a.to_dict()) == a`. Correct per RQ1.

**ManufacturingManifest:** `to_json()` converts artifacts tuple to list of dicts; `load()` rebuilds the tuple via `ManufacturingArtifact.from_dict`. `test_manifest_to_json_round_trip` creates a 2-artifact manifest, saves, loads, and asserts equality including `isinstance(loaded.artifacts, tuple)`. The `bom_rows`/`total_components`/`generated_at` fields use `.get()` with defaults so a partial JSON degrades gracefully. Correct.

**Build:** `to_dict()` serializes `status` as `status.value` and artifacts as list-of-dicts; `load()` reconstructs via `BuildStatus(data["status"])` and `ManufacturingArtifact.from_dict`. `test_build_to_dict_round_trip` confirms status enum survives (VALIDATED), and `test_build_create_build_json_round_trip` confirms the end-to-end handler -> disk -> `Build.load` path is lossless. The two-file approach (manifest.json + build.json) keeps `ManufacturingManifest` focused on manufacturing fields while build.json carries the full envelope — a clean separation that avoids coupling.

Round-trip fidelity is lossless across all three types.

## 5. Handler Correctness (board_rev via NativeParser.parse_pcb)

The question flagged in the review brief — "NativeParser.parse_pcb for board_rev?" — is answered: **this is correct and necessary.**

`execute_query` builds `PcbIR` via the parse path that leaves `_native_board = None`. The `ir` passed to the handler therefore does NOT carry a populated `NativeBoard.title_block`. The handler MUST re-parse via `NativeParser.parse_pcb(file_path)` to read `board.title_block.rev`, exactly as Phase 205's `read_board_metadata` and Phase 206's `drc_vendor` do. This is the documented "dual-path" issue (CONTEXT.md CRITICAL CONTEXT #4). `NativeParser.parse_pcb` is a classmethod that returns `NativeBoard` and raises `FileNotFoundError` on missing files — which is caught by the BUILD-04 cleanup path.

- `board_rev` defaults to `"unknown"` when `title_block` or `rev` is absent. `test_build_create_reads_board_rev` confirms `"2.3"` round-trips from a PCB with `rev "2.3"`.
- `build_list` sorts by `created_at` descending and skips corrupt dirs (logged warning, no crash). `test_build_list_skips_corrupt_dir` and `test_build_list_sorted_descending` cover both.
- `build_show` tolerates a missing/corrupt manifest (logs warning, returns `manifest: None` but still returns build details) — defensive.
- `build_show` diff integration: on unknown `diff_build_id`, returns primary build + `diff_error`; on success, includes `diff` via `asdict(diff)`. Both branches tested.

## Test Assessment

35 tests across 4 classes. Coverage is thorough:
- `TestBuildModel` (14): lifecycle transitions, git SHA (repo + non-repo), manifest/artifact round-trips, diff logic.
- `TestBuildCreate` (11): directory creation, board_rev, git_sha, draft status, source snapshot hash verification, sch+pro discovery, no-partial-state, target-unchanged, traversal rejection, UUID format, build.json round-trip.
- `TestBuildList` (4): returns builds, empty, corrupt-skip, sort order.
- `TestBuildShow` (6): details, not-found, manifest round-trip, diff, diff-not-found, no-diff-when-omitted.

One test gap: no test asserts that `build_create` on a board that fails a real validation gate produces no build (BUILD-04's "validation fails" arm). The `test_build_create_no_partial_state_on_parse_failure` test covers parse failure (missing file), not gate failure. This is acceptable for Phase 207 because the full `ManufacturingReadinessGate` is deferred to Phase 208 (CONTEXT.md explicit decision), and the DRAFT status honestly reflects "not fully validated." But it means BUILD-04's literal "build is not created if validation fails" is only partially demonstrated today.

## Findings Summary

| ID | Severity | Description |
|----|----------|-------------|
| CR-MED-1 | Medium | Path traversal check does not reject absolute `project_dir` (e.g. `/etc`). Add `is_absolute()` rejection. |
| CR-LOW-1 | Low | `skip_validation` field is dead code (never read by handler). |
| CR-LOW-2 | Low | Broad `except Exception` in build_create (intentional for BUILD-04, noted). |
| CR-LOW-3 | Low | Duplicated traversal-check logic; build_create inlines instead of calling `_resolve_project_dir`. |

## Verdict

**APPROVE.** The implementation is clean, well-tested (35 passing tests), security threat models are addressed (with one medium finding on absolute-path rejection worth a follow-up), manifest round-trip is lossless, and the handler correctly uses the re-parse path for board_rev. The findings are all minor/non-blocking. CR-MED-1 is recommended for a follow-up fix but does not block Phase 207 because the single-user kicad-agent threat model limits exploitability.
