# Phase 207: Versioned Build System - Research

**Researched:** 2026-07-10
**Answers:** "What do I need to know to PLAN this phase well?"
**Source:** Codebase analysis of src/volta/ against 207-CONTEXT.md, REQUIREMENTS.md, ROADMAP.md, PITFALLS.md

---

## RQ1: ManufacturingManifest/Artifact Serialization

### Current class definitions

Both are `@dataclass(frozen=True)` in `src/volta/validation/gates/manufacturing_manifest.py`:

```python
@dataclass(frozen=True)
class ManufacturingArtifact:
    name: str
    path: str
    sha256: str
    size_bytes: int
    generated_by: str   # actual kicad-cli command string
    timestamp: str
    # + staticmethod from_file(name, path, generated_by) -> ManufacturingArtifact

@dataclass(frozen=True)
class ManufacturingManifest:
    project_name: str
    board_name: str
    fab_profile: str
    artifacts: tuple[ManufacturingArtifact, ...] = ()
    bom_rows: int = 0
    total_components: int = 0
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

### Can `dataclasses.asdict()` handle nested artifact tuples?

Partially. `asdict()` DOES recurse into nested dataclasses and converts them to dicts, so a `ManufacturingManifest` round-trips through `asdict()` into a plain-dict structure with `artifacts` as a list of dicts. BUT it is a one-way transform:

- `asdict()` converts the `artifacts` tuple into a `list` (lossy for the "tuple" type, fine for JSON).
- There is no inverse (`from_dict`), so reconstruction must be manual.
- The fields are all JSON-native (str, int, nested dict), so no custom encoder is needed for serialization.

**Decision:** Implement explicit `to_dict()`/`from_dict()` (mirroring `GateResult.from_dict` at `validation/gate_types.py:78`). Do NOT rely on `asdict()` for the load path — round-trip must reconstruct frozen dataclasses explicitly.

### Serialization precedent: `training/manifest.py`

`DataManifest` (`src/volta/training/manifest.py:27`) is the closest precedent — a `@dataclass(frozen=True)` with `save(path)` (classmethod-free, writes JSON via `json.dump`) and `load(path)` (classmethod, reads JSON and reconstructs via `cls(...)`). Key differences from what Phase 207 needs:

- `DataManifest` has NO nested dataclass fields (only `dict`, `int`, `str`). Phase 207's manifest nests `ManufacturingArtifact`, so we must map the artifacts list back to tuples of dataclass instances.
- `DataManifest.save` uses plain `open()` + `json.dump`. Phase 207 should use `atomic_write` (already used by `board_spec.save_board_spec` at `manufacturing/board_spec.py:81`).
- `DataManifest.load` converts JSON string keys back to int (`{int(k): v ...}`). Phase 207 needs the analogous tuple reconstruction: `tuple(ManufacturingArtifact(**a) for a in data["artifacts"])`.

### Exact JSON structure for lossless round-trip

```json
{
  "project_name": "my-board",
  "board_name": "my-board",
  "fab_profile": "2-layer",
  "artifacts": [
    {
      "name": "gerbers",
      "path": "/abs/or/rel/path",
      "sha256": "abc123...",
      "size_bytes": 12345,
      "generated_by": "kicad-cli pcb export gerbers ...",
      "timestamp": "2026-07-10T12:00:00+00:00"
    }
  ],
  "bom_rows": 42,
  "total_components": 42,
  "generated_at": "2026-07-10T12:00:00+00:00"
}
```

This matches the CONTEXT.md spec exactly. Round-trip = `load(save(m).path)` reproduces an equal `ManufacturingManifest` as long as `ManufacturingArtifact.from_dict` reconstructs each entry and the tuple is rebuilt. No field is lost because all fields are str/int.

**Note on the `Build` record:** The `Build` dataclass has MORE fields than the manifest (build_id, board_rev, source_files, git_sha, created_at, status, manifest_path, build_dir). The serialized `manifest.json` on disk must therefore be a SUPERSET of the `ManufacturingManifest` — i.e. `build_show` reconstructs `Build` from a richer JSON document. Two options:
1. Serialize `Build` directly to `manifest.json` (Build.to_dict/from_dict), embedding the artifact list. Simpler round-trip.
2. Serialize `ManufacturingManifest` + a separate `build.json` for the Build envelope.

Option 1 is cleaner (one file = one source of truth, matches CONTEXT.md "manifest.json is its serialized form on disk"). The CONTEXT.md JSON structure shows only the manifest fields, but the success criterion #3 says "manifest.json is serialized ... reloading it via build_show reproduces the build record exactly." Recommendation: extend the on-disk JSON to carry the full `Build` envelope, with `manifest` fields nested or flattened. Planner must resolve this — see open question in Validation Architecture.

---

## RQ2: ManufacturingReadinessGate Context Requirements

### Required context keys

From the class docstring and `run()` body (`validation/gates/manufacturing_gate.py:38-109`), the gate reads 8 context keys via `context.get(...)`:

| Key | Check | Behavior if missing |
|-----|-------|---------------------|
| `drc_result` | `_check_drc_clean` | Returns blocker: "No DRC result in context" |
| `dfm_report` | `_check_dfm_pass` | Returns blocker: "No DFM report in context" |
| `export_artifacts` | `_check_required_exports` | Defaults to `[]` → blocker for each missing required name |
| `export_layers` | `_check_layer_completeness` | Defaults to `[]` → blocker "Missing layers for {profile}" |
| `fab_profile` | `_check_layer_completeness`, `_generate_manifest` | Defaults to `"2-layer"` |
| `bom_data` | `_check_bom_completeness` | Defaults to `[]` → no blocker (empty BOM = skip check) |
| `has_mechanical_constraints` | `_check_required_exports` | Defaults to `False` |
| `export_dir` | failure cleanup | `.get()` → None → skip cleanup |

### Does it raise or degrade gracefully?

**It never raises.** Every check uses `context.get(key, default)` with fail-closed defaults. Missing context produces blocker strings, not exceptions. The `run()` method aggregates blockers and returns `GateResult(pass_=False, blockers=[...])`. The only exception path is `_cleanup_partial_exports`, which itself is wrapped in try/except (logs a warning on failure).

### Simplified validation path (DRC + file existence only)?

Yes, this is feasible and matches CONTEXT.md's v1 decision. The gate is a class with a stateless `run(context)` method — nothing forces all 8 keys. For Phase 207 v1, the handler can:
- Run a lightweight pre-check (PCB parses, file exists) without invoking the full gate.
- OR construct a partial context and accept that the gate returns blockers (DRC/DFM missing), then treat that as "DRAFT status" rather than a hard failure.

CONTEXT.md (Claude's Discretion) explicitly chooses the DRAFT-status path: builds default to `DRAFT` with full validation deferred to Phase 208. BUILD-04 ("build is not created if validation fails") is therefore satisfied for the cases where the gate IS run with full context; the v1 simplified path produces DRAFT builds that have not passed the full gate (status reflects this honestly, avoiding Pitfall 5 false confidence).

### GateResult shape

`GateResult` is a **pydantic BaseModel** (NOT a dataclass) in `validation/gate_types.py:28`, frozen:

```python
class GateResult(BaseModel):
    model_config = {"populate_by_name": True, "frozen": True}
    pass_: bool = Field(alias="pass", default=True)
    gate_name: str = ""
    stage: DesignStage = DesignStage.SCHEMATIC
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
```

It already has `to_dict()`, `from_dict()`, and `to_json()`. A model_validator enforces the invariant: `pass=True` requires empty blockers, `pass=False` requires non-empty. The handler should check `gate_result.pass_bool` (the `pass_` alias-safe property) to decide build status.

---

## RQ3: Query Handler Dispatch for build_create

### Does `execute_query` require the target file to exist?

**Yes.** The routing in `ops/executor.py:134-135` checks existence BEFORE dispatching to `execute_query`:

```python
if not file_path.exists():
    raise FileNotFoundError(f"Target file not found: {file_path}")

# Query operations: read-only, no Transaction, no serialization
if root.op_type in _QUERY_HANDLERS:
    return execute_query(op, file_path, self._cache)
```

So `build_create`'s `target_file` (the `.kicad_pcb`) MUST exist. This is correct — the build snapshots an existing board. The `builds/` directory itself is created by the handler, not by the executor, so there is no conflict.

### Does `execute_query` serialize/write the target file after the handler returns?

**No.** `execute_query` (`ops/execution.py:193-230`) parses the file into a `PcbIR`, calls `dispatch_query`, and returns `{"success", "operation", "target_file", "details"}`. It does NOT touch the file afterward — no `serialize_pcb`, no `Transaction`, no `atomic_write`. The target file's mtime is unchanged. This confirms CONTEXT.md's design decision: `build_create` as a query op is safe — the `.kicad_pcb` source is never rewritten.

### Can the handler create side-effect files (build dir, manifest)?

Yes. The handler receives `(op, ir, file_path)` and can freely create files anywhere reachable. The executor does not inspect or constrain handler side effects for query ops. The `builds/` directory and `manifest.json` are created by the handler via direct `Path.mkdir` + `atomic_write`, entirely outside the executor's awareness.

### Precedent for query handlers creating side effects

There is no existing query handler that writes files — all current `_QUERY_HANDLERS` (query_connectivity, read_board_metadata, drc_vendor, list_vendor_drc_profiles) are pure reads. `build_create` will be the FIRST query handler with side effects. This is acceptable because:
- The "query" category in the registry means `is_readonly: True` (the `.kicad_pcb` target is not modified).
- The side effects are in a separate `builds/` tree, not the source file.
- CONTEXT.md explicitly documents this as a deliberate deviation from ROADMAP IP-4 (which suggested CROSS_FILE_OP_TYPES).

**Caveat for the planner:** The registry `is_readonly: True` is a claim about the TARGET file, not about all filesystem effects. The Phase 207 tests should verify the target `.kicad_pcb` is byte-identical after `build_create` (mtime + hash check) to defend the "read-only" contract. The `drc_vendor` handler sets this precedent — it calls `kicad-cli` which can write reports, yet is registered `is_readonly: True`.

---

## RQ4: Registry Count and Schema Union

### Current count: 156 (confirmed)

`tests/test_registry.py:26` asserts `len(OPERATION_REGISTRY) == 156`, with a comment: "Phase 206: 156 ops (was 154 after Phase 205; +2: drc_vendor, list_vendor_drc_profiles)." After adding 3 ops (build_create, build_list, build_show): **156 → 159**.

### `test_readonly_operations_count` asserts an EXACT set

Yes — `tests/test_registry.py:107-157` asserts a hardcoded frozenset `expected_readonly` (currently 40 ops including `drc_vendor`, `list_vendor_drc_profiles`, `read_board_metadata`). It compares `readonly_types == expected_readonly` (exact equality) AND `len(readonly) == len(expected_readonly)`.

**Three updates needed in test_registry.py:**
1. `test_registry_has_98_operations` (line 23): update comment + change `== 156` to `== 159`.
2. `test_readonly_operations_count` (line 114 `expected_readonly` set): add `"build_create"`, `"build_list"`, `"build_show"` (all three are `is_readonly: True` per CONTEXT.md).
3. The `test_validate_registry_completeness_passes` known-missing set (line 34) is unaffected — the 3 pre-existing missing ops are unchanged.

### Exact assertions to update

```python
# Line 26 (count):
assert len(OPERATION_REGISTRY) == 156   # -> 159

# Line 114-155 (readonly set) — add alphabetically:
expected_readonly = {
    ...
    "build_create",          # NEW (alphabetically near top, after analyze_*)
    "build_list",            # NEW
    "build_show",            # NEW
    ...
}
```

Note the test method is still named `test_registry_has_98_operations` (stale name from an earlier phase). Renaming is optional cleanup; the planner can leave it.

### Schema union sync (IP-2)

`validate_registry_completeness()` cross-checks registry op_types against the `Operation` discriminated union in `schema.py:407-567`. Adding to the union requires adding `BuildCreateOp`, `BuildListOp`, `BuildShowOp` to BOTH:
- The `from volta.ops._schema_pcb import (...)` re-export block (schema.py:239-285)
- The `Annotated[ ... | BuildCreateOp | BuildListOp | BuildShowOp, Field(discriminator="op_type")]` union (schema.py:562-566, add before the closing)
- The `__all__` list (schema.py:581-785)

Forgetting any of the three causes `validate_registry_completeness` to report drift.

---

## RQ5: Git SHA Capture

### Is `subprocess` imported in manufacturing/ or gates/?

**No.** No file under `src/volta/manufacturing/` or `src/volta/validation/gates/` imports subprocess. The only validation-path subprocess usage is `src/volta/validation/erc_drc.py:27` (`import subprocess`) for running `kicad-cli`. Phase 207 will add the first subprocess import to `manufacturing/`.

### Safest capture without raising

Use `subprocess.run(...)` (NOT `check_output`, which raises `CalledProcessError` on non-zero exit) and wrap the whole call in try/except. The CONTEXT.md helper signature:

```python
def _get_git_sha(project_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return "unknown"
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"
```

### `subprocess.run` vs `check_output`

Use `subprocess.run`. Rationale:
- `check_output` raises on non-zero exit (e.g., not a git repo → exit 128). We'd have to catch `CalledProcessError` anyway.
- `subprocess.run` with `capture_output=True` lets us inspect `returncode` and degrade to `"unknown"` without an exception path for the common "not a repo" case.
- This matches `erc_drc.py:237` which uses `subprocess.run` for the same reason (though it lets timeouts/exceptions propagate to a result object; Phase 207 instead returns the sentinel).

### Handling "not a git repo"

Three failure modes, all returning `"unknown"`:
1. `git` binary not installed → `FileNotFoundError` (subclass of `OSError`) → caught.
2. `project_dir` is not inside a git repo → `returncode == 128` → caught by returncode check.
3. Timeout (`subprocess.TimeoutExpired`, subclass of `SubprocessError`) → caught.

The sentinel `"unknown"` is documented in the `Build.git_sha` field contract. Pitfall to flag for the planner: do NOT use an empty string as the sentinel — `"unknown"` is distinguishable from a real (impossible) empty SHA and survives JSON serialization/reconstruction.

---

## RQ6: Build Directory and .gitignore

### `builds/` is NOT in `.gitignore` (confirmed)

`.gitignore` line 7 has `build/` (Python build artifacts) but there is NO `builds/` entry anywhere in the file. The Phase 207 task is to ADD `/builds/` (or `builds/`) per BUILD-09 and Pitfall 4. Important: the existing `build/` (no `s`) MUST remain — it covers Python packaging. Adding `builds/` is additive and non-conflicting.

Recommendation: add `builds/` as a top-level entry (matches the style of `build/`, `dist/`). Since builds are project-scoped (INTEG-04) and created next to the `.kicad_pcb`, the entry should match wherever they appear — a bare `builds/` line (no leading slash) matches `builds/` at any depth, which is what we want for project-scoped build trees.

### Where should `builds/` be created?

Relative to the **project directory** — the directory containing the `.kicad_pcb` file. Per CONTEXT.md "Claude's Discretion": the build directory location is `builds/` relative to the project directory (the directory containing the `.kicad_pcb`, or `project_dir` if provided). The handler resolves:
- `project_dir = Path(op.project_dir) if op.project_dir else file_path.parent`
- `build_dir = project_dir / "builds" / f"v{rev}_{timestamp}"`

This matches INTEG-04 (project-scoped) and keeps builds adjacent to source.

### Atomic directory creation (race conditions)

`Path.mkdir(parents=True, exist_ok=True)` is the standard idiom and is race-safe in practice for the single-process volta model (the executor is explicitly NOT concurrency-safe per `execution.py:9` O-BUG-008 note). The directory name includes a second-precision timestamp + a UUID4 `build_id`, so collisions are effectively impossible. Two layers:
1. `(project_dir / "builds").mkdir(parents=True, exist_ok=True)` — idempotent.
2. `build_dir.mkdir(parents=True, exist_ok=False)` — raises `FileExistsError` only on timestamp collision (sub-second); the UUID in the manifest disambiguates even if the dir name collides. If collision is a concern, append a short UUID suffix to the dir name.

For Phase 207 v1, `mkdir(parents=True, exist_ok=True)` on the final dir is acceptable — the timestamp makes collisions a non-issue.

---

## RQ7: Source File Snapshot

### Discovering source files

Per CONTEXT.md: look for `.kicad_pcb`, `.kicad_sch`, `.kicad_pro` with the **same stem** as the target file in the project directory. Include all that exist. This is stem-based, not glob-based:

```python
stem = file_path.stem  # e.g. "my-board" from "my-board.kicad_pcb"
source_files = []
for ext in (".kicad_pcb", ".kicad_sch", ".kicad_pro"):
    candidate = project_dir / f"{stem}{ext}"
    if candidate.exists():
        source_files.append(candidate)
```

**Caveat for the planner:** Multi-sheet projects have multiple `.kicad_sch` files (root + sub-sheets). The stem-based approach captures only the root schematic. Phase 207's CONTEXT.md accepts this (snapshots the primary files); full sheet-tree capture is a Phase 208+ concern. Document this limitation in the build record's `source_files` tuple so `build_show` makes it explicit.

### `shutil.copy2` vs `shutil.copy`

Use **`shutil.copy2`** — it preserves metadata (mtime, permissions). This is the codebase standard: `transaction.py:138`, `gap_fill_engine.py:151`, `batch_executor.py:85`, and `local_client.py:79` all use `copy2`. Preserving mtime matters for the build record's integrity (the snapshot should be indistinguishable from the source for diffing purposes).

### Missing files (PCB-only project)

Handle gracefully — the discovery loop above only appends candidates that `.exists()`. A PCB-only project (no schematic, no project file) produces a `source_files` tuple with just the `.kicad_pcb`. The handler must NOT require all three extensions; the build record's `source_files` tuple simply reflects what was found. Each snapshot becomes a `ManufacturingArtifact` via `ManufacturingArtifact.from_file`.

---

## RQ8: Build Diffing

### Simplest diff structure (BUILD-10)

The `BuildDiff` dataclass from CONTEXT.md is the right shape:

```python
@dataclass(frozen=True)
class BuildDiff:
    source_files_added: tuple[str, ...]
    source_files_removed: tuple[str, ...]
    artifacts_added: tuple[str, ...]
    artifacts_removed: tuple[str, ...]
    status_changed: bool
    git_sha_changed: bool
    board_rev_changed: bool
```

This covers BUILD-10's three concerns:
- **Source diffs:** set difference of `source_files` tuples.
- **Artifact diffs:** set difference on artifact `name` fields (not paths — names are the semantic identity).
- **Validation status changes:** `status_changed` (bool comparing `BuildStatus`), plus the underlying `git_sha_changed` and `board_rev_changed` flags explain WHY a rebuild happened.

Implementation is pure set arithmetic — no file reads needed if both `Build` records are in memory.

### Diff manifests directly, or load both Build records first?

**Load both Build records first.** The diff operates on the `Build` dataclass (which contains the manifest-derived artifacts as a tuple). Diffing raw manifest JSON would require re-parsing the artifact names and status fields. Since `build_show` already reconstructs `Build` from disk, the diff function takes two `Build` instances:

```python
def diff_builds(a: Build, b: Build) -> BuildDiff:
    a_src = set(a.source_files); b_src = set(b.source_files)
    a_art = {art.name for art in a.artifacts}
    b_art = {art.name for art in b.artifacts}
    return BuildDiff(
        source_files_added=tuple(sorted(b_src - a_src)),
        source_files_removed=tuple(sorted(a_src - b_src)),
        artifacts_added=tuple(sorted(b_art - a_art)),
        artifacts_removed=tuple(sorted(a_art - b_art)),
        status_changed=a.status != b.status,
        git_sha_changed=a.git_sha != b.git_sha,
        board_rev_changed=a.board_rev != b.board_rev,
    )
```

### Separate op or parameter on build_show?

CONTEXT.md decision: **parameter on build_show**, not a separate op. `build_show` gains an optional `diff_build_id: str | None`. When set, the handler loads both builds and returns the diff alongside the primary build's details. This avoids adding a 4th op (keeping the count delta at +3, not +4) and keeps the registry/schema changes minimal. The pure `diff_builds` function in `manufacturing/build.py` is independently testable and available for Phase 209's CLI to expose as `build diff`.

---

## Validation Architecture

Phase 207 has a two-tier validation story that the planner must make explicit to avoid Pitfall 5 (false confidence):

### Tier 1: Simplified (Phase 207 default)
`build_create` with no extra context runs a lightweight check:
- Target `.kicad_pcb` parses (via NativeParser).
- Optional: DRC clean if kicad-cli is available (non-blocking — degrade to DRAFT if absent).
- Result: `BuildStatus.DRAFT`. The build IS created, status honestly reflects "not fully validated."

### Tier 2: Full ManufacturingReadinessGate (Phase 208 context)
When the handler receives a complete context dict (drc_result, dfm_report, export_artifacts, export_layers, bom_data), it runs the full 5-check gate. On pass: `BuildStatus.VALIDATED`. On fail: NO build created (BUILD-04 hard gate). This path is exercised by Phase 208's handoff orchestrator, which has all the context.

### Transition model
```
DRAFT ──(gate passes)──> VALIDATED ──(artifacts exported)──> EXPORTED ──(zip created)──> HANDED_OFF
```
Phase 207 only produces DRAFT (Tier 1). VALIDATED requires the full gate; EXPORTED/HANDED_OFF are Phase 208. `Build.transition_to()` validates allowed transitions via `dataclasses.replace`.

### Open question for the planner
1. **Single-file vs. two-file on disk:** Does `manifest.json` hold the full `Build` envelope (build_id, git_sha, status, etc.) or just the `ManufacturingManifest` subset? Success criterion #3 ("reloading reproduces the build record exactly") implies the former. Recommend: ONE file (`build.json` or `manifest.json`) = full `Build` serialization, with the manifest fields as a subset. The CONTEXT.md JSON example shows only manifest fields — the planner should extend it.

2. **BUILD-04 scope:** "Build is not created if validation fails" — in Tier 1 (simplified), the gate isn't fully run, so a DRAFT build is created even if DRC isn't clean. Is this compliant with BUILD-04? CONTEXT.md says yes (DRAFT status is honest). The planner should make this explicit in the plan and write a test that a Tier-2 gate failure produces NO build (cleanup of partial dir via the gate's `_cleanup_partial_exports`).

3. **`is_readonly: True` honesty:** Since `build_create` writes to `builds/`, add a test asserting the target `.kicad_pcb` is byte-identical (hash + mtime) before/after. This defends the registry contract.

---

## RESEARCH COMPLETE
