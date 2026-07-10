# Phase 207: Versioned Build System — Pattern Mapping

**Phase:** 207 — Versioned Build System
**Generated:** 2026-07-10
**Source docs:** 207-CONTEXT.md (decisions), codebase pattern analysis

This document maps each file to be created/modified to its closest existing codebase analog, with concrete code excerpts and integration notes. The implementer reads this alongside CONTEXT.md.

---

## CRITICAL CONTEXT (read first)

1. **All 3 new ops are `query` ops, NOT cross-file ops (CONTEXT.md lines 87-89, IP-4 deviation).** `build_create` creates side-effect artifacts in `builds/` but does NOT touch the `.kicad_pcb` source. Registering as `category: "query"`, `is_readonly: True` routes them through `execute_query` (`execution.py:193`), which skips Transaction wrapping and source serialization. This is simpler and correct — the CROSS_FILE path would try to serialize the unchanged PCB.

2. **Three new ops = registry count 156 → 159 (test_registry.py:26).** All three must land in `_RAW_CATALOG`, the `Operation` union, and `__all__` together, or `validate_registry_completeness` fails.

3. **The `build_create` handler writes side-effect files from a query path.** `execute_query` (`execution.py:193-230`) parses the PCB, builds a PcbIR, then calls the handler with signature `(op, ir, file_path) -> dict`. The query path makes NO guarantees about read-only disk behavior — it only skips *source file* writes. The handler is free to create `builds/` artifacts. The PCB mtime is unchanged (the source file is never written).

4. **The PcbIR in the query path has `_native_board = None` (dual-path issue).** `execute_query` builds PcbIR via `parse_pcb` + `extract_uuids` (the kiutils path, `execution.py:218-219`). `ir.board` is a kiutils Board, and `ir.board.title_block` does NOT have a reliable `.rev`. To read `board_rev`, re-parse via `NativeParser.parse_pcb(file_path)` — exactly as `drc_vendor` (`query.py:88-127`) re-parses for the NativeBoard geometry. See FILE 7 step 1.

5. **Manifest serialization is a new method on an existing frozen dataclass.** `ManufacturingManifest` and `ManufacturingArtifact` (`manufacturing_manifest.py:19,45`) are already frozen dataclasses. Phase 207 ADDS `to_json()/save()/load()` to the manifest and `to_dict()/from_dict()` to the artifact. Do not change the existing constructor or the `generate_manifest`/`validate_manifest` helpers.

6. **`build_create` validation is simplified for v1 (CONTEXT.md lines 101, 181).** The full `ManufacturingReadinessGate` requires a context dict (DRC, DFM, exports) that Phase 208's handoff orchestrator assembles. For Phase 207, `skip_validation=False` runs a basic PCB-parses check and the build defaults to `DRAFT`. Do NOT attempt to assemble the full gate context.

---

## FILE 1 (CREATE): `src/kicad_agent/manufacturing/build.py`

**Role:** Core build data model — `Build` frozen dataclass, `BuildStatus` enum, `BuildDiff`, `_get_git_sha` helper, build-dir creation utilities, `diff_builds` function.

**Data flow:** Built and returned by the `build_create` handler; reconstructed from disk by `build_list`/`build_show`. Serialized form is `manifest.json` (which embeds a `ManufacturingManifest`). The `Build` record is the source of truth; the manifest on disk is its persisted projection.

### Closest analog A (frozen dataclass with lifecycle + replace): `DataManifest` (`training/manifest.py:27-192`)

`DataManifest` is the strongest analog: a frozen dataclass with a `from_directory` classmethod factory, `save(path)`/`load(path)` round-trip, and `assign_splits` returning a new frozen instance via `replace`. The `Build` model mirrors this — `transition_to` returns a new `Build` via `dataclasses.replace`.

**Excerpt — frozen dataclass + save/load + replace for transitions** (`training/manifest.py:27-44, 77-124, 192`):
```python
@dataclass(frozen=True)
class DataManifest:
    files: dict[str, str] = field(default_factory=dict)
    split_seed: int = 42
    split_assignments: dict[int, str] = field(default_factory=dict)
    generation_config: dict = field(default_factory=dict)
    created_at: str = ""

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = { ... }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> DataManifest:
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        ...
        return cls(files=files, split_seed=split_seed, ...)

    def assign_splits(self, ...) -> DataManifest:
        ...
        return replace(self, split_assignments=assignments)   # frozen-safe transition
```

Use `dataclasses.replace(self, status=new_status)` for `Build.transition_to` — this is the CR-01 frozen-pattern (CONTEXT.md line 54).

### `BuildStatus` enum — closest analog: `SurfaceFinish` (`manufacturing/board_spec.py:17-24`)

A `str, Enum` in the manufacturing package. CONTEXT.md lines 37-38 give the four states.

**Excerpt — `str, Enum` pattern** (`manufacturing/board_spec.py:17-24`):
```python
class SurfaceFinish(str, Enum):
    HASL = "HASL"
    ENIG = "ENIG"
    HASL_LEAD_FREE = "HASL_LEAD_FREE"
    ...
```

`BuildStatus(str, Enum)` with `DRAFT`, `VALIDATED`, `EXPORTED`, `HANDED_OFF`. Use string values matching the state names lowercased (`"draft"`, `"validated"`, `"exported"`, `"handed_off"`) so JSON round-trip is clean (the enum serializes as its string value).

### `Build` dataclass fields (CONTEXT.md lines 41-53)

```python
@dataclass(frozen=True)
class Build:
    build_id: str
    board_rev: str
    source_files: tuple[str, ...]
    git_sha: str
    created_at: str
    status: BuildStatus
    artifacts: tuple[ManufacturingArtifact, ...]
    manifest_path: str
    build_dir: str
```

Note `artifacts: tuple[ManufacturingArtifact, ...]` — reuse the EXISTING `ManufacturingArtifact` from `validation/gates/manufacturing_manifest.py:19` (promoted in FILE 4). Import it lazily inside methods if a cycle appears, but top-level import is safe since `manufacturing_manifest.py` imports only stdlib.

### `_get_git_sha` helper (CONTEXT.md lines 156-160)

**Excerpt pattern — graceful subprocess fallback.** No existing `git rev-parse` call exists in the codebase. Use `subprocess.run` with `capture_output=True, text=True, timeout=10`, wrapped in `try/except (subprocess.SubprocessError, FileNotFoundError, OSError)` returning `"unknown"`. Never raise.

```python
def _get_git_sha(project_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_dir), capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return "unknown"
```

### Build-dir creation + timestamp format (CONTEXT.md lines 95, 178)

- Directory name: `builds/v{rev}_{timestamp}` where timestamp is `YYYYMMDD_HHMMSS` (use `datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")`).
- `created_at` field: `datetime.now(timezone.utc).isoformat()` (matches `ManufacturingArtifact.from_file` timestamp at `manufacturing_manifest.py:41`).
- `build_id`: `str(uuid.uuid4())`.

### `BuildDiff` + `diff_builds` (CONTEXT.md lines 135-147)

A frozen dataclass with tuple fields. `diff_builds` compares two `Build` records using set operations on `source_files` and `artifact.name` sets.

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

This is a pure utility function (not a handler, not an op). Return tuples sorted for determinism.

### Imports

`from dataclasses import dataclass, field, replace`, `from datetime import datetime, timezone`, `from enum import Enum`, `from pathlib import Path`, `import subprocess, uuid`, and `from kicad_agent.validation.gates.manufacturing_manifest import ManufacturingArtifact, ManufacturingManifest`.

---

## FILE 2 (CREATE): `src/kicad_agent/ops/handlers/build.py`

**Role:** Three `@register_query` handlers (`build_create`, `build_list`, `build_show`) + the module's own `_BUILD_HANDLERS` registry dict + `register_build` decorator, merged into `_QUERY_HANDLERS` in FILE 8.

### Closest analog A (own registry dict + merge pattern): `pcb_fill_zones.py` (`handlers/pcb_fill_zones.py:27-35`)

CONTEXT.md line 164 explicitly calls this out. The fill_zones module defines its own `_FILL_ZONES_HANDLERS` dict and `register_fill_zones` decorator, then `handlers/__init__.py:27` merges it into `_PCB_HANDLERS`. Mirror this exactly, but merge into `_QUERY_HANDLERS` instead.

**Excerpt — module-owned registry + decorator** (`handlers/pcb_fill_zones.py:27-35`):
```python
_FILL_ZONES_HANDLERS: dict[str, Callable] = {}

def register_fill_zones(op_type: str) -> Callable:
    """Decorator to register a fill_zones operation handler."""
    def decorator(fn: Callable) -> Callable:
        _FILL_ZONES_HANDLERS[op_type] = fn
        return fn
    return decorator
```

So build.py should have:
```python
_BUILD_HANDLERS: dict[str, Callable] = {}

def register_build(op_type: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        _BUILD_HANDLERS[op_type] = fn
        return fn
    return decorator
```

CONTEXT.md line 165: merge in `handlers/__init__.py` via `_QUERY_HANDLERS.update(_BUILD_HANDLERS)` (see FILE 8).

### Closest analog B (query handler signature + lazy imports): `query.py` (`handlers/query.py:17-29, 88-127`)

Handler signature is always `(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]`. Use **lazy imports** inside the handler body (existing handlers do this at `query.py:27, 41-45, 74, 100-104`) to avoid import cycles at module load.

**Excerpt — handler registration + signature + lazy import** (`handlers/query.py:17-29`):
```python
def register_query(op_type: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        _QUERY_HANDLERS[op_type] = fn
        return fn
    return decorator

@register_query("query_connectivity")
def _handle_query_connectivity(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.connectivity_query import handle_connectivity_query
    return handle_connectivity_query(op, ir, file_path)
```

The `drc_vendor` handler (`query.py:88-127`) is the better structural analog for `build_create` because it re-parses via `NativeParser.parse_pcb(file_path)` and calls out to a manufacturing-layer module with graceful degradation.

### `build_create` handler steps (CONTEXT.md lines 91-101)

Use `register_build("build_create")`. Steps (all imports lazy):

1. **Resolve `project_dir`:** `Path(op.project_dir) if op.project_dir else Path(file_path).parent`.
2. **Read `board_rev`:** `board = NativeParser.parse_pcb(file_path)`; `board_rev = board.title_block.rev if board.title_block and board.title_block.rev else "unknown"`. (Re-parse is required — see CRITICAL CONTEXT #4. The `NativeTitleBlock.rev` field is at `pcb_native_types.py:353`.)
3. **Capture git SHA:** `_get_git_sha(project_dir)` from FILE 1.
4. **Generate build_id + timestamps:** `str(uuid.uuid4())`, `datetime.now(timezone.utc)`.
5. **Create build dir:** `builds/v{rev}_{YYYYMMDD_HHMMSS}/` under `project_dir` (`Path.mkdir(parents=True, exist_ok=True)`).
6. **Validation (simplified v1):** If `skip_validation` is False, attempt `NativeParser.parse_pcb(file_path)` (already done in step 2). If it succeeds, status stays `DRAFT`. Do NOT run the full gate (CRITICAL CONTEXT #6). Wrap in try/except; on parse failure return an error dict with `success=False` and NO build dir created (BUILD-04: no partial state).
7. **Snapshot source files:** Discover `.kicad_pcb`, `.kicad_sch`, `.kicad_pro` with the same stem as `file_path` in `project_dir`. Copy each into the build dir with `shutil.copy2`. Collect relative path strings for `source_files`.
8. **Create artifacts:** For each snapshot, `ManufacturingArtifact.from_file(name=..., path=copy_path, generated_by="snapshot")` (the `from_file` helper at `manufacturing_manifest.py:30-42` hashes + sizes + timestamps).
9. **Create + serialize manifest:** Build a `ManufacturingManifest` (FILE 4) and `manifest.save(build_dir / "manifest.json")` (FILE 4 adds `save`). The `manifest_path` is relative to `project_dir`.
10. **Return:** A dict with `success=True`, `build_id`, `board_rev`, `git_sha`, `status`, `build_dir`, `manifest_path`, `artifacts` (list of `asdict`).

**Note on `source_files` path semantics:** Store paths relative to `project_dir` (e.g. `"board.kicad_pcb"`) for portability across machines.

### `build_list` handler (CONTEXT.md lines 104-116)

Use `register_build("build_list")`. Scan `project_dir / "builds"` for subdirs matching `v*_*` (`path.glob("v*_*")`). For each, if `(subdir / "manifest.json").is_file()`, load it via `ManufacturingManifest.load` (FILE 4) and reconstruct a `Build`-like dict. Return `{"builds": [...], "count": N}`. Tolerate missing/corrupt manifests (skip with a warning) — never crash the whole list on one bad dir.

### `build_show` handler (CONTEXT.md lines 118-131)

Use `register_build("build_show")`. Scan `project_dir / "builds" / "v*_*" / "manifest.json"`, load each, find the one whose reconstructed `build_id` matches `op.build_id`. Return full build details + artifacts + status. If not found, return `{"success": False, "error": "build not found: {build_id}"}`.

**Storing `build_id` on disk:** The `ManufacturingManifest` does NOT currently have a `build_id` field (FILE 4 adds serialization, not new fields). Two options: (a) extend the manifest JSON with a top-level `build_id`/`build` envelope, or (b) write a separate `build.json` next to `manifest.json`. CONTEXT.md line 229 says "manifest.json is its serialized form" — so prefer extending the manifest's JSON envelope (wrap the manifest fields plus build-level fields). Document the chosen shape in the handler docstring and FILE 4.

### No circular import risk

`handlers/build.py` imports from `manufacturing/build.py` (FILE 1) and `manufacturing_manifest.py` (FILE 4), both of which import only stdlib + each other. `handlers/__init__.py` imports `build.py` at module load. Safe.

---

## FILE 3 (CREATE): `tests/test_build_system.py`

**Role:** Tests for the build model, manifest serialization round-trip, and the three ops.

### Closest analog A (handler-direct test pattern): `test_board_metadata_ops.py`

This is the canonical pattern for testing a query handler by building a PcbIR from an inline PCB and calling the handler via its registry dict. Reuse the `_create_pcb_with_title_block` + `_build_ir` helpers and the autouse `_clear_ir_registry` fixture.

**Excerpt — inline PCB + `_build_ir` + handler invocation** (`test_board_metadata_ops.py:12-63`):
```python
@pytest.fixture(autouse=True)
def _clear_ir_registry():
    from kicad_agent.ir.base import _clear_registry
    _clear_registry()
    yield
    _clear_registry()

def _create_pcb_with_title_block(tmpdir: Path) -> Path:
    pcb_path = tmpdir / "test_meta.kicad_pcb"
    content = '''(kicad_pcb (version 20241229) (generator "test")
      (title_block (title "T") (date "2020-01-01") (rev "1.0") (company "C"))
      (layers (0 "F.Cu" signal))
    )
    '''
    pcb_path.write_text(content, encoding="utf-8")
    return pcb_path

def _build_ir(pcb_path: Path):
    from kicad_agent.parser.pcb_parser import parse_pcb
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser.uuid_extractor import extract_uuids
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)
```

For build ops, handler invocation goes through the merged registry:
```python
from kicad_agent.ops.handlers.query import _QUERY_HANDLERS
handler = _QUERY_HANDLERS["build_create"]
result = handler(BuildCreateOp(target_file="test.kicad_pcb", skip_validation=True), ir, pcb_path)
```
(after FILE 8 merges `_BUILD_HANDLERS` into `_QUERY_HANDLERS`, all build handlers are reachable via `_QUERY_HANDLERS`.)

### Closest analog B (frozen dataclass + save/load round-trip): `test_training_manifest.py`

The cleanest pattern for asserting a serialization round-trip is lossless.

**Excerpt — round-trip test shape** (`test_training_manifest.py:1-60`):
```python
from kicad_agent.training.manifest import DataManifest

class TestDataManifestFromDirectory:
    def test_round_trip(self, tmp_path):
        m = DataManifest.from_directory(data_dir)
        m.save(tmp_path / "manifest.json")
        loaded = DataManifest.load(tmp_path / "manifest.json")
        assert loaded == m
```

Apply the same shape to `ManufacturingManifest.save`/`load` (FILE 4) and `Build` reconstruction (`build_show` round-trip — CONTEXT.md line 230 "round-trip must be lossless").

### Closest analog C (manifest construction): `test_manufacturing_gate.py:21-70`

Shows how to construct `ManufacturingArtifact` and `ManufacturingManifest` directly with literal fields for unit tests.

**Excerpt — artifact + manifest construction** (`test_manufacturing_gate.py:36-49`):
```python
artifacts = [
    ManufacturingArtifact(
        name="gerbers", path="/tmp/gerbers", sha256="abc123",
        size_bytes=1024, generated_by="kicad-cli pcb export gerbers",
        timestamp="2024-01-01T00:00:00Z",
    ),
]
m = generate_manifest("proj", "board", "2-layer", artifacts, bom_rows=5, total_components=10)
```

### Suggested test cases

**Build model (FILE 1):**
- `test_build_status_transition_allowed` — `DRAFT → VALIDATED` succeeds; returns new frozen Build.
- `test_build_status_transition_disallowed` — e.g. `HANDED_OFF → DRAFT` raises.
- `test_git_sha_unknown_when_not_a_repo` — `_get_git_sha(tmp_path)` in a non-git dir returns `"unknown"`; never raises.
- `test_git_sha_from_repo` — `git init` in tmp_path, commit, assert SHA prefix matches (skip if git absent).
- `test_diff_builds_detects_changes` — two Builds differing in source_files, artifacts, status, git_sha, board_rev → correct `BuildDiff` flags.
- `test_diff_builds_identical` — same Build → all empty tuples, all `*_changed=False`.

**Manifest serialization (FILE 4):**
- `test_manifest_to_json_round_trip` — `ManufacturingManifest.load(path)` after `save(path)` equals original.
- `test_manifest_to_json_handles_tuples` — artifacts tuple serializes to JSON list and back to tuple.
- `test_artifact_to_from_dict` — `ManufacturingArtifact.from_dict(a.to_dict()) == a`.
- `test_manifest_load_missing_file_raises` — `load(nonexistent)` raises `FileNotFoundError`.

**Ops (FILE 2):**
- `test_build_create_creates_build_dir` — `skip_validation=True`, assert `builds/v1.0_*` exists with `manifest.json` + snapshot copies.
- `test_build_create_snapshots_source_files` — `.kicad_pcb` copied; artifact has correct sha256 (re-hash the copy and compare).
- `test_build_create_reads_board_rev` — PCB with `rev "2.3"` → `result["board_rev"] == "2.3"`.
- `test_build_create_skip_validation_creates_draft` — `skip_validation=True` → `status == "draft"`.
- `test_build_list_returns_builds` — create 2 builds, list → `count == 2`.
- `test_build_list_empty_when_no_builds` — no `builds/` dir → `count == 0`, `builds == []`.
- `test_build_show_returns_manifest` — create then show by build_id → artifacts + status present.
- `test_build_show_not_found` — unknown build_id → `success=False`.
- `test_build_create_idempotent_artifacts` — re-showing a build yields identical artifact hashes.

### Fixtures

Reuse the `_clear_ir_registry` autouse fixture. For the git tests, use `tmp_path` with `subprocess.run(["git", "init"])` guarded by `pytest.mark.skipif(not shutil.which("git"))`.

---

## FILE 4 (MODIFY): `src/kicad_agent/validation/gates/manufacturing_manifest.py`

**Role:** Add serialization methods to the existing frozen dataclasses (`ManufacturingArtifact`, `ManufacturingManifest`). No change to existing fields, constructors, `from_file`, `generate_manifest`, or `validate_manifest`.

### Current state (`manufacturing_manifest.py:19-57`)

Both classes are already `@dataclass(frozen=True)`. `ManufacturingArtifact.from_file` (line 30) already does SHA256 + size + timestamp. `ManufacturingManifest` has fields: `project_name`, `board_name`, `fab_profile`, `artifacts: tuple`, `bom_rows`, `total_components`, `generated_at`.

### Add to `ManufacturingArtifact` — `to_dict()` / `from_dict()` (CONTEXT.md line 63)

**Closest analog: `DataManifest.save/load` dict-shape** (`training/manifest.py:85-124`). Mirror the explicit-field mapping (do not use `dataclasses.asdict` for load — reconstruct explicitly).

```python
def to_dict(self) -> dict:
    return {
        "name": self.name,
        "path": self.path,
        "sha256": self.sha256,
        "size_bytes": self.size_bytes,
        "generated_by": self.generated_by,
        "timestamp": self.timestamp,
    }

@staticmethod
def from_dict(d: dict) -> ManufacturingArtifact:
    return ManufacturingArtifact(
        name=d["name"],
        path=d["path"],
        sha256=d["sha256"],
        size_bytes=d["size_bytes"],
        generated_by=d["generated_by"],
        timestamp=d["timestamp"],
    )
```

### Add to `ManufacturingManifest` — `to_json()` / `save()` / `load()` (CONTEXT.md lines 58-62)

**JSON structure** (CONTEXT.md lines 64-75):
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

**`to_json()`** — `json.dumps` with indent=2, converting `artifacts` tuple → list of dicts via `to_dict()`:
```python
def to_json(self) -> str:
    data = {
        "project_name": self.project_name,
        "board_name": self.board_name,
        "fab_profile": self.fab_profile,
        "artifacts": [a.to_dict() for a in self.artifacts],
        "bom_rows": self.bom_rows,
        "total_components": self.total_components,
        "generated_at": self.generated_at,
    }
    return json.dumps(data, indent=2)
```

**`save(path)`** — use `atomic_write` (CONTEXT.md line 61). `atomic_write` is the crash-safe writer used by `save_board_spec` (`board_spec.py:75-83`).

**Excerpt — atomic_write usage** (`manufacturing/board_spec.py:81-83`):
```python
from kicad_agent.io.atomic_write import atomic_write
atomic_write(sidecar, spec.model_dump_json(indent=2))
```

So:
```python
def save(self, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, self.to_json())
```

**`load(path)` classmethod** — `json.loads` + reconstruct frozen dataclasses (CONTEXT.md line 62). Mirror `DataManifest.load` (`training/manifest.py:95-124`):
```python
@classmethod
def load(cls, path: Path) -> ManufacturingManifest:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    artifacts = tuple(ManufacturingArtifact.from_dict(a) for a in data.get("artifacts", []))
    return cls(
        project_name=data["project_name"],
        board_name=data["board_name"],
        fab_profile=data["fab_profile"],
        artifacts=artifacts,
        bom_rows=data.get("bom_rows", 0),
        total_components=data.get("total_components", 0),
        generated_at=data.get("generated_at", ""),
    )
```

### New imports needed in this file

`import json` (line 14 area) and `from kicad_agent.io.atomic_write import atomic_write`. `hashlib`, `datetime`, `Path`, `dataclass/field` are already imported (lines 12-16).

### Backwards compatibility

The existing `generate_manifest` (line 60) and `validate_manifest` (line 79) functions are unchanged. `from_file` (line 30) is unchanged. Existing tests in `test_manufacturing_gate.py` that construct `ManufacturingManifest(...)` positionally still work since no field is added or reordered.

### Build envelope (FILE 2 dependency)

`build_show` needs to persist/recover `build_id`, `git_sha`, `status`, `source_files`, `build_dir`. The cleanest approach: write the manifest via `manifest.save(...)`, then ALSO persist a thin `build.json` envelope (or extend the manifest JSON) carrying the build-level fields. Either works; pick ONE and keep `to_json/load` of the manifest strictly about manufacturing fields (matches CONTEXT.md JSON structure). Recommend a separate `build.json` envelope written by the `build_create` handler to avoid coupling the two dataclasses. Document the choice in FILE 2.

---

## FILE 5 (MODIFY): `src/kicad_agent/ops/_schema_pcb.py`

**Role:** Define `BuildCreateOp`, `BuildListOp`, `BuildShowOp` Pydantic models.

### Closest analog: `ReadBoardMetadataOp` / `ListVendorDrcProfilesOp` (`_schema_pcb.py:1168-1182, 1269-1280`)

These are the simplest read-only PCB ops: `op_type` Literal + `target_file: TargetFile`. `ListVendorDrcProfilesOp` is the exact shape for `BuildListOp` (target_file required by dispatch, otherwise minimal).

**Excerpt — minimal read-only op** (`_schema_pcb.py:1269-1280`):
```python
class ListVendorDrcProfilesOp(BaseModel):
    op_type: Literal["list_vendor_drc_profiles"] = "list_vendor_drc_profiles"
    target_file: TargetFile
```

### `BuildCreateOp` (CONTEXT.md lines 80-86)

```python
class BuildCreateOp(BaseModel):
    op_type: Literal["build_create"] = "build_create"
    target_file: TargetFile
    project_dir: Optional[str] = Field(default=None, description="Project root (defaults to target_file parent)")
    skip_validation: bool = Field(default=False, description="Skip ManufacturingReadinessGate (for testing / quick drafts)")
```

`target_file` must be `.kicad_pcb` (the handler reads `board_rev` from the PCB title block). `Optional[str]`, `Literal`, `Field` are all already imported (`_schema_pcb.py:2-6`). `TargetFile` is imported at line 8-11.

### `BuildListOp` (CONTEXT.md lines 106-110)

```python
class BuildListOp(BaseModel):
    op_type: Literal["build_list"] = "build_list"
    target_file: TargetFile
    project_dir: Optional[str] = Field(default=None, description="Project root (defaults to target_file parent)")
```

### `BuildShowOp` (CONTEXT.md lines 120-125)

```python
class BuildShowOp(BaseModel):
    op_type: Literal["build_show"] = "build_show"
    target_file: TargetFile
    build_id: str = Field(min_length=1, max_length=64, description="UUID of the build to show")
    project_dir: Optional[str] = Field(default=None, description="Project root (defaults to target_file parent)")
```

`build_id` is a UUID string — constrain with `min_length=1, max_length=64`. Do NOT apply `_validate_sexpr_safe_string` (it's a UUID, not S-expression content). A `pattern=r"^[A-Za-z0-9-]+$"` is an optional hardening matching the UUID character set.

### Placement

Add after `ListVendorDrcProfilesOp` (line 1280), under a new `# Phase 207: Build system ops` comment block. All imports needed are already present.

---

## FILE 6 (MODIFY): `src/kicad_agent/ops/schema.py`

**Role:** Add the 3 new Op classes to the `Operation` discriminated union + the import/re-export section + `__all__`. Three edits, mirroring exactly how Phase 205/206 ops were added.

### Edit A — add to the `_schema_pcb` import block (schema.py:239-285)

The import block already ends with `DrcVendorOp, ListVendorDrcProfilesOp,` (lines 283-284). Append:
```python
    DrcVendorOp,
    ListVendorDrcProfilesOp,
    BuildCreateOp,                  # NEW (Phase 207)
    BuildListOp,                    # NEW (Phase 207)
    BuildShowOp,                    # NEW (Phase 207)
)
```

### Edit B — add to the `Operation.root` union (schema.py:407-567)

The union currently ends with `| ListVendorDrcProfilesOp,` at line 566 (trailing comma + `Field(discriminator="op_type")` follow). Insert the new ops before it, preserving the trailing comma on the new last item:

```python
        | ReadBoardMetadataOp
        | SetBoardMetadataOp
        | SetBoardRevisionOp
        | DrcVendorOp
        | ListVendorDrcProfilesOp
        | BuildCreateOp             # NEW (Phase 207)
        | BuildListOp               # NEW (Phase 207)
        | BuildShowOp,              # NEW (Phase 207) — trailing comma, last item
        Field(discriminator="op_type"),
```

**Pitfall:** The union is a single `Annotated[A | B | ... | Z, Field(...)]` expression. Each new type needs a leading `|`. The last type before `Field(...)` needs a trailing comma. A missing `|` or misplaced comma breaks the whole schema (caught only by `validate_registry_completeness` at test time).

### Edit C — add to `__all__` (schema.py:581-785)

Add under a new comment block near the existing Phase 205/206 entries (around line 779-781):
```python
    # Phase 207 build system ops (BUILD-01, BUILD-07, BUILD-08)
    "BuildCreateOp",
    "BuildListOp",
    "BuildShowOp",
```

---

## FILE 7 (MODIFY): `src/kicad_agent/ops/registry.py`

**Role:** Add 3 `_RAW_CATALOG` entries.

### Closest analog: `query_connectivity` / `read_board_metadata` (registry.py:309-317, 381-389)

Both are `category: "query"`, `is_readonly: True`, `file_types: [".kicad_pcb"]`, `scope: "single_file"`. All three build ops match exactly (CONTEXT.md lines 88, 112, 128 — all registered as query ops).

**Excerpt — query catalog entry** (registry.py:309-317):
```python
"query_connectivity": {
    "category": "query",
    "description": "Query PCB connectivity via NetGraph",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```

### New entries (add before the closing `}` of `_RAW_CATALOG`, after `list_vendor_drc_profiles` at line 1461)

```python
"build_create": {
    "category": "query",
    "description": "Create a versioned build: snapshot source files, capture git SHA + board rev, write manifest",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
"build_list": {
    "category": "query",
    "description": "List all builds for a project (scan builds/ directory)",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
"build_show": {
    "category": "query",
    "description": "Show build details: manifest, artifacts, validation status",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```

The dict comprehension at registry.py:1464-1467 (`OpMeta(op_type=op_type, **data)`) picks these up automatically.

### Why `is_readonly: True` despite writing to disk (CRITICAL CONTEXT #1)

`is_readonly` in this registry means "does not modify the *target source file*." `build_create` writes to `builds/` (a side-effect artifact dir) but never touches the `.kicad_pcb`. This routes through `execute_query` which skips source serialization. CONTEXT.md lines 87-89 document this as a deliberate deviation from ROADMAP IP-4. `build_handoff_export` (Phase 208) will follow the same convention.

---

## FILE 8 (MODIFY): `src/kicad_agent/ops/handlers/__init__.py`

**Role:** Import `_BUILD_HANDLERS` + `register_build` from the new module, and merge `_BUILD_HANDLERS` into `_QUERY_HANDLERS`.

### Closest analog: the `_FILL_ZONES_HANDLERS` merge (`handlers/__init__.py:10, 27`)

**Excerpt — import + merge pattern** (`handlers/__init__.py:10, 27, 40-41`):
```python
from .pcb_fill_zones import _FILL_ZONES_HANDLERS, register_fill_zones
...
_PCB_HANDLERS.update(_FILL_ZONES_HANDLERS)
...
__all__ = [ ..., "_FILL_ZONES_HANDLERS", "register_fill_zones", ... ]
```

### Edits

**Edit A — add import** (after the `.query` import at line 18):
```python
from .query import _QUERY_HANDLERS, register_query
from .build import _BUILD_HANDLERS, register_build   # NEW (Phase 207)
```

**Edit B — add merge** (after line 31, near the existing `.update(...)` calls). Build handlers ARE query handlers, so merge into `_QUERY_HANDLERS` (CONTEXT.md line 165):
```python
_PCB_HANDLERS.update(_STITCH_HANDLERS)
_QUERY_HANDLERS.update(_BUILD_HANDLERS)   # NEW (Phase 207)
```

**Edit C — add to `__all__`** (after the `_QUERY_HANDLERS`/`register_query` entries, ~line 57):
```python
    "_BUILD_HANDLERS",
    "register_build",
```

### Ordering pitfall

The merge `_QUERY_HANDLERS.update(_BUILD_HANDLERS)` must run AFTER both `_QUERY_HANDLERS` and `_BUILD_HANDLERS` are imported. The existing merges (lines 27-31) run after all imports (lines 7-20), so placing the new `.update` alongside them (line 31 area) is correct. The build handlers are decorated at import time of `.build`, so the dict is populated before the merge.

---

## FILE 9 (MODIFY): `tests/test_registry.py`

**Role:** Update count assertion (156 → 159) and the readonly exact-set.

### Edit 1 — count assertion (test_registry.py:23-26)

```python
def test_registry_has_98_operations(self) -> None:
    # Phase 207: 159 ops (was 156 after Phase 206; +3: build_create,
    # build_list, build_show).
    assert len(OPERATION_REGISTRY) == 159
```

### Edit 2 — `test_readonly_operations_count` exact set (test_registry.py:107-157)

This test asserts an EXACT set of readonly op types (`expected_readonly`, lines 114-155). All three new ops are `is_readonly: True`. If this set is not updated, the test fails because `build_create`, `build_list`, `build_show` will be in `readonly_types` but not in `expected_readonly`.

Add to `expected_readonly` (alphabetically — they sort as `build_*`):
```python
    "analyze_gaps",
    ...
    "build_create",                  # NEW (Phase 207)
    "build_list",                    # NEW (Phase 207)
    "build_show",                    # NEW (Phase 207)
    "classify_violations",
    ...
```

The count assertion `len(readonly) == len(expected_readonly)` (line 157) becomes 42 (was 39).

### `validate_registry_completeness` — no change to the known-missing set

`test_validate_registry_completeness_passes` (lines 28-46) has `_KNOWN_PREEXISTING_MISSING = {"add_design_note", "apply_floor_plan", "place_and_wire_power_units"}`. The three new ops must NOT appear in `missing_from_registry` — they land in both schema and `_RAW_CATALOG`, so the test passes unchanged.

### Optional spot-check (test_registry.py:100-106)

Add to `test_pcb_ops`:
```python
    assert "build_create" in op_types
    assert "build_list" in op_types
```

---

## FILE 10 (MODIFY): `.gitignore`

**Role:** Add `builds/` so build artifacts don't pollute git (CONTEXT.md lines 150-153, Pitfall 4).

### Current state

`.gitignore` already has `build/` (Python build artifacts) but NOT `builds/` (the plural — the versioned build dir). These are different directories.

### The edit

Add a line, grouped with the other phase-specific ignores (near the `# Phase 204` block):
```gitignore
# Phase 207: versioned build artifacts (snapshot copies + manifests)
builds/
```

### Pitfall (CONTEXT.md line 152)

Do NOT ignore `build/` (already present, for Python artifacts) and do NOT ignore `.kicad_build_spec.json` (Phase 205 sidecar — that is a source file users may commit). The trailing-slash `builds/` matches the directory at the repo root and any nested project `builds/`.

---

## Integration order (recommended)

The files have dependencies. Implement in this order to keep the registry/schema in sync:

1. **FILE 4** (`manufacturing_manifest.py`) — add `to_json/save/load` + `to_dict/from_dict`. Standalone, only stdlib + `atomic_write`.
2. **FILE 1** (`manufacturing/build.py`) — depends on FILE 4 (`ManufacturingArtifact`/`ManufacturingManifest`).
3. **FILE 5** (`_schema_pcb.py`) — standalone Pydantic models.
4. **FILE 6** (`schema.py`) — depends on FILE 5.
5. **FILE 7** (`registry.py`) — depends on FILE 5 (op_type strings must match).
6. **FILE 2** (`handlers/build.py`) — depends on FILES 1, 4.
7. **FILE 8** (`handlers/__init__.py`) — depends on FILE 2.
8. **FILE 9** (`test_registry.py`) — depends on FILES 6, 7 (count must match).
9. **FILE 10** (`.gitignore`) — standalone.
10. **FILE 3** (`tests/test_build_system.py`) — depends on everything.

FILES 5, 6, 7 must land together — adding an op to the schema union without a registry entry (or vice versa) breaks `validate_registry_completeness`. FILE 8 must land with FILE 2 or the handlers are unreachable.

---

## Key pitfalls (from CONTEXT)

| # | Pitfall | Mitigation |
|---|---------|------------|
| 1 | Registering build ops as cross-file instead of query | All 3 ops are `category: "query"`, `is_readonly: True` (FILE 7). Routes through `execute_query`, skipping source serialization. |
| 2 | Reading `board_rev` from `ir.board.title_block` (None on query path) | Re-parse via `NativeParser.parse_pcb(file_path)` in the handler (CRITICAL CONTEXT #4). `NativeTitleBlock.rev` at `pcb_native_types.py:353`. |
| 3 | Schema/registry drift (op in one but not the other) | Land FILES 5+6+7 together; `validate_registry_completeness` catches drift. |
| 4 | `test_readonly_operations_count` exact-set assertion | FILE 9 must add all 3 new ops to `expected_readonly` (count 39 → 42). |
| 5 | `_get_git_sha` raising outside a git repo | Wrap in try/except, return `"unknown"`, never raise (FILE 1). |
| 6 | Manifest round-trip not lossless (tuple↔list) | `to_json` converts artifacts tuple → list of dicts; `load` reconstructs tuple via `from_dict` (FILE 4). Test in FILE 3. |
| 7 | `build_create` leaving partial state on validation failure | If validation fails, return error BEFORE creating the build dir (BUILD-04). |
| 8 | Confusing `build/` (Python artifacts) with `builds/` (versioned builds) | FILE 10 adds `builds/` only; leaves existing `build/` untouched. |
| 9 | Import cycle: `handlers/build.py` ↔ `manufacturing/build.py` | Verified safe — `manufacturing/build.py` imports stdlib + `manufacturing_manifest.py` (stdlib only). Use lazy imports in handler body if any cycle appears. |
| 10 | Full ManufacturingReadinessGate context unavailable in Phase 207 | Use simplified validation (PCB parses → DRAFT). Full gate deferred to Phase 208 (CRITICAL CONTEXT #6). |
