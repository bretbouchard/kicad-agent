# Phase 207: Versioned Build System - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning
**Source:** Derived from v7.0 ROADMAP.md + REQUIREMENTS.md + codebase pattern analysis + user directive ("maximum flexibility, no compromises")

<domain>
## Phase Boundary

Phase 207 creates a versioned build system that snapshots source files, records git SHA + board revision, and serializes a manifest with SHA256-hashed artifacts to disk. This builds on Phase 205's `title_block` rev field and feeds into Phase 208 (Handoff Package).

**What ships:**
- `Build` frozen dataclass in `manufacturing/build.py` (build_id UUID, board_rev, source_files, git_sha, created_at, status, artifacts, manifest_path, build_dir)
- `BuildStatus` lifecycle: draft → validated → exported → handed_off
- `ManufacturingManifest`/`ManufacturingArtifact` promoted with serialization (`to_json()`, `save()`, `load()`)
- `build_create` operation: snapshot source files → run ManufacturingReadinessGate → record git SHA + board rev → create build dir
- `build_list` operation: list all builds for a project
- `build_show` operation: view build details (manifest, artifacts, validation status)
- Build diffing: diff two builds (source diffs, artifact diffs, validation status changes)
- `builds/` directory added to `.gitignore`

**What does NOT ship (Phase 208):**
- Handoff package / zip bundling (Phase 208)
- Export orchestration — Gerbers, drill, BOM, STEP (Phase 208 calls existing export wrappers)
- Pre-handoff validation gate (Phase 208)
- CLI subcommands (Phase 209)
- MCP auto-exposure (Phase 209 — free, but not the focus)

</domain>

<decisions>
## Implementation Decisions

### Build Data Model (BUILD-02, BUILD-03)

- **New file:** `src/kicad_agent/manufacturing/build.py`
- **`BuildStatus` enum** (`str, Enum`): `DRAFT`, `VALIDATED`, `EXPORTED`, `HANDED_OFF`
  - Transitions: DRAFT → VALIDATED (gate passes) → EXPORTED (artifacts generated) → HANDED_OFF (zip created in Phase 208)
  - `Build` has a `transition_to(new_status)` method that validates allowed transitions
- **`Build` frozen dataclass:**
  ```python
  @dataclass(frozen=True)
  class Build:
      build_id: str           # UUID4 as string
      board_rev: str          # from title_block.rev (Phase 205)
      source_files: tuple[str, ...]  # relative paths to .kicad_pcb, .kicad_sch, .kicad_pro
      git_sha: str            # HEAD commit SHA (or "unknown" if not a git repo)
      created_at: str         # ISO 8601 timestamp
      status: BuildStatus
      artifacts: tuple[ManufacturingArtifact, ...]  # promoted from gates/
      manifest_path: str      # relative path to manifest.json
      build_dir: str          # relative path to builds/v{rev}_{timestamp}/
  ```
- Uses `dataclasses.replace` for status transitions (consistent with CR-01 frozen pattern)

### Manifest Serialization (BUILD-05)

- **Promote existing `ManufacturingManifest`/`ManufacturingArtifact`** in `validation/gates/manufacturing_manifest.py`
- **Add methods:**
  - `ManufacturingManifest.to_json() -> str` — `json.dumps` with indent=2, handles tuple→list conversion
  - `ManufacturingManifest.save(path: Path) -> None` — uses `atomic_write` from `io/atomic_write.py`
  - `ManufacturingManifest.load(path: Path) -> ManufacturingManifest` — classmethod, `json.loads` + reconstruct frozen dataclasses
  - `ManufacturingArtifact.to_dict() -> dict` and `from_dict(d: dict) -> ManufacturingArtifact` for nested serialization
- **JSON structure:**
  ```json
  {
    "project_name": "...",
    "board_name": "...",
    "fab_profile": "...",
    "artifacts": [{"name": "...", "path": "...", "sha256": "...", "size_bytes": 123, "generated_by": "...", "timestamp": "..."}],
    "bom_rows": 42,
    "total_components": 42,
    "generated_at": "2026-07-10T..."
  }
  ```

### build_create Operation (BUILD-01, BUILD-04, BUILD-06)

- **Schema:** `BuildCreateOp` in `_schema_pcb.py`:
  ```python
  class BuildCreateOp(BaseModel):
      op_type: Literal["build_create"] = "build_create"
      target_file: TargetFile  # the .kicad_pcb file
      project_dir: str | None = None  # project root (defaults to target_file parent)
      skip_validation: bool = False  # for testing — skips ManufacturingReadinessGate
  ```
- **Registry:** `is_readonly: True`, `category: "query"`, `file_types: [".kicad_pcb"]`
  - **Design decision (deviation from ROADMAP IP-4):** `build_create` is registered as a **query op** (not CROSS_FILE_OP_TYPES). Rationale: `build_create` does NOT modify the `.kicad_pcb` source file — it creates build artifacts in a `builds/` directory. The CROSS_FILE_OP_TYPES dispatch path wraps source files in `AtomicOperation` and expects to serialize them back, which is wrong for build creation. Query ops don't write to the target file. The handler creates side-effect artifacts (build dir, manifest) without touching the source. This is simpler and correct — no Transaction overhead, no serialization of unchanged source files.
  - **Note:** `build_handoff_export` (Phase 208) will also be a query op for the same reason.
- **Handler:** `@register_query("build_create")` in a new `handlers/build.py` module (merged in `handlers/__init__.py`)
  - **Steps:**
    1. Parse the PCB via `NativeParser.parse_pcb(file_path)` to get `title_block.rev` for `board_rev`
    2. Capture git SHA: `subprocess.run(["git", "rev-parse", "HEAD"], cwd=project_dir, capture_output=True, text=True, timeout=10)` — fallback to `"unknown"` if not a git repo or git is missing
    3. Generate `build_id` (UUID4), `created_at` (ISO timestamp)
    4. Create build directory: `builds/v{rev}_{timestamp}/` (timestamp format: `YYYYMMDD_HHMMSS`)
    5. If `skip_validation` is False: run `ManufacturingReadinessGate` with required context. If gate fails, return error — NO build is created (BUILD-04: no partial state)
    6. Snapshot source files: copy `.kicad_pcb`, `.kicad_sch`, `.kicad_pro` into the build directory
    7. Create `ManufacturingArtifact` entries for each snapshot file (SHA256 via `from_file`)
    8. Create `ManufacturingManifest` and serialize to `manifest.json` via `atomic_write`
    9. Return `Build` record as dict
  - **Validation context:** Building the ManufacturingReadinessGate context dict requires DRC results, DFM report, export artifacts, etc. For Phase 207 v1, if the full context is not available, the handler runs a **simplified validation** (DRC clean check + file existence check) and marks the build as `DRAFT` status. The full 5-check gate runs when the context is provided. This gives flexibility — users can create quick draft builds without running the full gate.

### build_list Operation (BUILD-07)

- **Schema:** `BuildListOp` in `_schema_pcb.py`:
  ```python
  class BuildListOp(BaseModel):
      op_type: Literal["build_list"] = "build_list"
      target_file: TargetFile  # any .kicad_pcb in the project
      project_dir: str | None = None
  ```
- **Registry:** `is_readonly: True`, `category: "query"`, `file_types: [".kicad_pcb"]`
- **Handler:** `@register_query("build_list")` in `handlers/build.py`
  - Scans `builds/` directory for subdirectories matching `v*_*` pattern
  - For each, loads `manifest.json` and reconstructs `Build` record
  - Returns `{"builds": [...], "count": N}`

### build_show Operation (BUILD-08)

- **Schema:** `BuildShowOp` in `_schema_pcb.py`:
  ```python
  class BuildShowOp(BaseModel):
      op_type: Literal["build_show"] = "build_show"
      target_file: TargetFile
      build_id: str  # UUID of the build to show
      project_dir: str | None = None
  ```
- **Registry:** `is_readonly: True`, `category: "query"`, `file_types: [".kicad_pcb"]`
- **Handler:** `@register_query("build_show")` in `handlers/build.py`
  - Finds build directory by `build_id` (scan `builds/*/manifest.json` for matching `build_id`)
  - Loads manifest, returns full build details + artifacts + validation status

### Build Diffing (BUILD-10)

- **Function:** `diff_builds(build_a: Build, build_b: Build) -> BuildDiff` in `manufacturing/build.py`
- **`BuildDiff` frozen dataclass:**
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
- **Not a separate operation** — exposed as a utility function callable from Python. Phase 209 may expose it as a CLI subcommand. For now, `build_show` can optionally accept a `diff_build_id` parameter to return a diff.

### .gitignore (BUILD-09, Pitfall 4)

- Add `builds/` to `.gitignore` (NOT `build/` which already exists for Python artifacts)
- The `.kicad_build_spec.json` sidecar from Phase 205 is NOT ignored (it's a source file the user may want to commit)

### Git SHA Helper

- **Function:** `_get_git_sha(project_dir: Path) -> str` in `manufacturing/build.py`
  - `subprocess.run(["git", "rev-parse", "HEAD"], cwd=project_dir, capture_output=True, text=True, timeout=10)`
  - Returns stripped SHA string, or `"unknown"` if git fails (not a repo, git not installed, etc.)
  - Never raises — degrades gracefully

### Handler Registry (Integration Pitfall IP-3)

- New handler module: `src/kicad_agent/ops/handlers/build.py` with `_BUILD_HANDLERS` dict + `register_build` decorator
- Merge in `handlers/__init__.py`: `_QUERY_HANDLERS.update(_BUILD_HANDLERS)` (build handlers ARE query handlers — read-only, no file mutation)
- This follows the `_FILL_ZONES_HANDLERS` merge pattern

### Schema Union + Registry Parity (IP-1, IP-2)

- Add `BuildCreateOp`, `BuildListOp`, `BuildShowOp` to `Operation` discriminated union in `schema.py`
- Add `_RAW_CATALOG` entries in `registry.py`
- **Update `test_registry.py` count assertion** (156 → 159 for +3 ops)
- **Update `test_readonly_operations_count`** if it asserts an exact set — add the 3 new readonly ops

### Claude's Discretion

- **UUID generation:** Use `uuid.uuid4()` for build_id — standard, no external dependency
- **Timestamp format:** `datetime.now(timezone.utc).isoformat()` for `created_at`, `YYYYMMDD_HHMMSS` for directory names
- **Source file discovery:** Look for `.kicad_pcb`, `.kicad_sch`, `.kicad_pro` with the same stem as the target file in the project directory. Include all that exist.
- **Build directory location:** `builds/` relative to the project directory (the directory containing the `.kicad_pcb` file, or the `project_dir` parameter if provided)
- **Simplified validation:** For Phase 207 v1, `build_create` with `skip_validation=False` runs a basic check (PCB file parses, DRC clean if kicad-cli available). The full ManufacturingReadinessGate requires context (DFM report, export artifacts) that Phase 208's handoff orchestrator will provide. For now, builds default to `DRAFT` status with a note that full validation happens in Phase 208.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Manifest Classes (to promote)
- `src/kicad_agent/validation/gates/manufacturing_manifest.py` — `ManufacturingArtifact` (line 19, frozen dataclass, `from_file` helper), `ManufacturingManifest` (line 45, frozen dataclass), `generate_manifest` (line 60), `validate_manifest` (line 79)

### Manufacturing Readiness Gate
- `src/kicad_agent/validation/gates/manufacturing_gate.py` — `ManufacturingReadinessGate` (line 38), `run(context)` method (line 52), 5 checks: `_check_drc_clean` (111), `_check_dfm_pass` (133), `_check_required_exports` (157), `_check_layer_completeness` (180), `_check_bom_completeness` (196)
- `src/kicad_agent/validation/gate_types.py` — `GateResult` type

### Phase 205 (title_block)
- `src/kicad_agent/parser/pcb_native_types.py` — `NativeTitleBlock.rev` (line 353), `NativeBoard.title_block` (line 392)
- `src/kicad_agent/parser/pcb_native_parser.py` — `_extract_title_block` (line 1260)

### Atomic Write
- `src/kicad_agent/io/atomic_write.py` — `atomic_write(file_path: Path, content: str) -> None` (line 15)

### Operation Patterns
- `src/kicad_agent/ops/handlers/query.py` — `register_query` decorator (line 17), handler signature `(op, ir, file_path) -> dict`
- `src/kicad_agent/ops/handlers/__init__.py` — handler merge pattern (`_FILL_ZONES_HANDLERS` merge)
- `src/kicad_agent/ops/_schema_pcb.py` — Op class pattern with `Literal` discriminator
- `src/kicad_agent/ops/registry.py` — `_RAW_CATALOG`, `OpMeta` fields
- `src/kicad_agent/ops/schema.py` — `Operation` discriminated union

### Manufacturing Package (prior phases)
- `src/kicad_agent/manufacturing/__init__.py` — package init
- `src/kicad_agent/manufacturing/board_spec.py` — Phase 205 BoardSpec (atomic_write usage precedent)
- `src/kicad_agent/manufacturing/vendor_drc.py` — Phase 206 evaluator

### Test Patterns
- `tests/test_board_metadata_ops.py` — Phase 205 handler test pattern
- `tests/test_registry.py` — count assertion, readonly set

### Pitfalls
- `.planning/research/PITFALLS.md` — Pitfall 4 (build dir git pollution), Pitfall 5 (manifest false confidence)

</canonical_refs>

<specifics>
## Specific Ideas

- Build directory structure: `builds/v{rev}_{timestamp}/` containing `manifest.json` + snapshot copies of source files
- The `Build` record is the source of truth — `manifest.json` is its serialized form on disk
- `build_show` reconstructs the `Build` from `manifest.json` — round-trip must be lossless
- Build diffing compares two `Build` records: source file sets, artifact sets, status, git SHA, board rev
- The git SHA is captured at build creation time — if the repo is dirty, the SHA is still HEAD (uncommitted changes are NOT captured in the SHA, but the source file snapshots DO capture the working tree state)
- `ManufacturingReadinessGate` context dict is complex — Phase 207 v1 may use a simplified validation path. The full gate runs in Phase 208's handoff orchestrator which has all the context.

</specifics>

<deferred>
## Deferred Ideas

- Full ManufacturingReadinessGate integration in build_create — Phase 208 provides the complete context (DRC, DFM, exports)
- `build_handoff_export` operation — Phase 208
- CLI subcommands (`build`, `handoff`) — Phase 209
- MCP auto-exposure — Phase 209
- Build deletion/cleanup operation — future
- Build artifact retention policy — future
- Remote build storage (S3, etc.) — future

</deferred>

---

*Phase: 207-versioned-build-system*
*Context gathered: 2026-07-10 via user directive ("maximum flexibility") + codebase pattern analysis*
