# Phase 208: Pattern Mapping — Manufacturer Handoff Package

**Phase:** 208
**Source root:** `src/kicad_agent/`
**Scope:** Handoff orchestrator, profile-driven BOM, manifest extension, `build_handoff_export` op, streaming zip.

Each file below maps a target artifact to its **closest in-repo analog** with a verbatim excerpt and a note on what changes. Copy the shape, not the semantics.

---

## FILE 1 (CREATE): `src/kicad_agent/manufacturing/handoff.py`

### Closest analog: `src/kicad_agent/ops/handlers/build.py` (`_handle_build_create`, lines 34-170)

The handoff orchestrator is a larger pipeline but follows the same skeleton: resolve project_dir → reject traversal → re-parse via NativeParser → create build dir → produce artifacts → build manifest → serialize → return result dict. The `build_create` handler is the canonical "multi-step side-effecting pipeline that never touches the source .kicad_pcb" shape.

**Verbatim excerpt — the pipeline skeleton to copy** (`build.py:34-170`):

```python
@register_build("build_create")
def _handle_build_create(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Create a versioned build snapshot (BUILD-01, BUILD-06).

    ...The target ``.kicad_pcb`` is never modified (registered read-only).

    On any failure (parse error, traversal attempt), returns an error dict and
    ensures NO partial build directory remains (BUILD-04: no partial state).
    """
    import re
    import shutil
    import uuid
    from datetime import datetime, timezone

    from kicad_agent.manufacturing.build import (
        Build,
        BuildStatus,
        _get_git_sha,
    )
    from kicad_agent.parser.pcb_native_parser import NativeParser
    from kicad_agent.validation.gates.manufacturing_manifest import (
        ManufacturingArtifact,
        ManufacturingManifest,
    )

    # 1. Resolve project_dir + reject path traversal (threat model #1).
    if op.project_dir and ".." in Path(op.project_dir).parts:
        return {
            "success": False,
            "error": "Invalid project_dir: path traversal forbidden",
        }
    project_dir = Path(op.project_dir) if op.project_dir else Path(file_path).parent

    build_dir: Path | None = None
    try:
        # 2. Read board_rev via re-parse (dual-path: query ir has _native_board=None).
        board = NativeParser.parse_pcb(file_path)
        board_rev = (
            board.title_block.rev
            if board.title_block and board.title_block.rev
            else "unknown"
        )

        # ... steps 3-9: create dir, snapshot, build manifest, serialize ...

        # 8. Create + serialize manifest (manufacturing subset).
        manifest = ManufacturingManifest(
            project_name=stem,
            board_name=stem,
            fab_profile="unknown",
            artifacts=tuple(artifacts),
            bom_rows=0,
            total_components=0,
            generated_at=created_at,
        )
        manifest.save(build_dir / "manifest.json")

        # 9. Create Build record + serialize full envelope (build.json).
        build = Build(...)
        build.save(build_dir / "build.json")

        # 10. Return success.
        return {
            "success": True,
            "build_id": build_id,
            "board_rev": board_rev,
            # ...
        }
    except Exception as exc:
        # BUILD-04: no partial state -- rmtree the build dir on any failure.
        if build_dir is not None and build_dir.exists():
            shutil.rmtree(build_dir, ignore_errors=True)
        logger.warning("build_create failed: %s", exc)
        return {
            "success": False,
            "error": f"build_create failed: {exc}",
        }
```

**What changes for `handoff.py`:**
- The orchestrator is a **plain function** (not a handler) — `export_handoff(...)` taking explicit `pcb_path`, `sch_path`, `project_dir`, `vendor`, etc.
- The pipeline adds a **pre-handoff validation gate** (DRC/ERC/vendor DRC) before creating any artifacts — if validation fails, return `HandoffResult(success=False, ...)` with NO zip.
- Steps 4-5 call the `export/*` wrappers (`export_gerber`, `export_drill`, `export_bom_profile`, `export_position`, `export_step`, `export_netlist`, `export_schematic_pdf`, `export_pcb_pdf`) instead of `shutil.copy2`.
- Step 6 generates `readme.md` via `atomic_write`.
- Step 9 creates the streaming zip (see FILE 1b below).
- Step 10 transitions a `Build` to `HANDED_OFF` if one exists (optional).
- The function returns a `HandoffResult` dataclass, not a dict (see FILE 1c).

### Validation gate analog: `src/kicad_agent/ops/handlers/query.py` (`_handle_drc_vendor`, lines 88-127)

The validation step calls `run_drc`, `run_erc`, `run_vendor_drc` defensively. The `_handle_drc_vendor` handler shows the pattern for re-parsing via `NativeParser` and degrading gracefully when kicad-cli is absent.

**Verbatim excerpt — defensive DRC call pattern** (`query.py:88-127`):

```python
@register_query("drc_vendor")
def _handle_drc_vendor(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Run vendor-specific DRC checks (DRC-01, DRC-04).

    CRITICAL: re-parse the PCB via NativeParser.parse_pcb(file_path) to get a
    NativeBoard. ``execute_query`` builds PcbIR via the kiutils path where
    _native_board is None (same dual-path issue as Phase 205's
    read_board_metadata handler).
    """
    from dataclasses import asdict

    from kicad_agent.dfm.profiles import load_profile
    from kicad_agent.manufacturing.vendor_drc import run_vendor_drc
    from kicad_agent.parser.pcb_native_parser import NativeParser

    profile = load_profile(op.vendor)  # raises ValueError if unknown
    board = NativeParser.parse_pcb(file_path)
    result = run_vendor_drc(board, profile)

    kicad_drc_result = None
    if op.run_kicad_drc:
        try:
            from kicad_agent.validation.erc_drc import run_drc
            drc = run_drc(file_path)
            kicad_drc_result = {
                "passed": drc.passed,
                "violations": [asdict(v) for v in drc.violations],
            }
        except Exception as exc:
            # kicad-cli may be absent in test/dev — degrade gracefully.
            kicad_drc_result = {"error": str(exc)}

    out = asdict(result)
    out["kicad_drc"] = kicad_drc_result
    return out
```

**What changes for `handoff.py`:** The validation gate wraps `run_drc`, `run_erc` (if sch), `run_vendor_drc` (if vendor) each in try/except. If kicad-cli is absent, set `drc_passed=None` (inconclusive) and include a warning in the readme. The `skip_validation=True` flag bypasses all of this.

### Validation result classes to consume

From `src/kicad_agent/validation/erc_drc.py:58-122`:

```python
@dataclass(frozen=True)
class ErcResult:
    passed: bool
    file_path: Path
    violations: tuple[Violation, ...] = ()
    error_message: Optional[str] = None  # Set if kicad-cli invocation failed

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity == Severity.ERROR)

    @property
    def error_count(self) -> int:
        return len(self.errors)


@dataclass(frozen=True)
class DrcResult:
    passed: bool
    file_path: Path
    violations: tuple[Violation, ...] = ()
    unconnected_items: tuple[Violation, ...] = ()
    error_message: Optional[str] = None
```

From `src/kicad_agent/manufacturing/vendor_drc.py:31-53`:

```python
@dataclass(frozen=True)
class VendorDrcResult:
    vendor: str
    passed: bool
    violations: tuple[Violation, ...] = ()
    profile_name: str = ""
    error_message: Optional[str] = None

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity == Severity.ERROR)
```

**Usage:** `result.passed` is the gate boolean; `result.error_count` or `len(result.errors)` gives the violation count. If `result.error_message` is set, kicad-cli was unavailable → treat as `None` (inconclusive), not `False`.

### Schematic discovery (Claude's discretion)

```python
# Look for .kicad_sch with same stem as .kicad_pcb
sch_path = pcb_path.with_suffix(".kicad_sch")
if not sch_path.is_file():
    sch_path = None  # PCB-only mode: skip BOM and schematic PDF
```

### Build dir naming

```python
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
dir_timestamp = now.strftime("%Y%m%d_%H%M%S")
build_dir_name = f"handoff_{dir_timestamp}"
build_dir = project_dir / "builds" / build_dir_name
build_dir.mkdir(parents=True, exist_ok=False)
```

### FILE 1b: Streaming zip creation (Pitfall 7)

```python
import zipfile

zip_path = build_dir / "handoff.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    # Write files ONE AT A TIME — zipfile.write() streams from disk.
    # NEVER load files into memory (Pitfall 7 — STEP files can be 10-100MB).
    for artifact_file in build_dir.iterdir():
        if artifact_file.is_file() and artifact_file.name != "handoff.zip":
            zf.write(artifact_file, arcname=artifact_file.name)
```

### FILE 1c: `HandoffResult` / `HandoffValidation` dataclasses

Follow the frozen-dataclass pattern from `src/kicad_agent/manufacturing/build.py:54-80` (`Build`) and `src/kicad_agent/manufacturing/vendor_drc.py:31-53` (`VendorDrcResult`):

```python
from dataclasses import dataclass
from kicad_agent.manufacturing.build import Build
from kicad_agent.validation.gates.manufacturing_manifest import ManufacturingManifest


@dataclass(frozen=True)
class HandoffValidation:
    """Pre-handoff DRC/ERC/vendor DRC results."""
    drc_passed: bool | None       # None = inconclusive (kicad-cli absent)
    erc_passed: bool | None       # None = no schematic OR inconclusive
    vendor_drc_passed: bool | None  # None = no vendor specified
    drc_violations: int
    erc_violations: int
    vendor_drc_violations: int


@dataclass(frozen=True)
class HandoffResult:
    """Result of export_handoff."""
    success: bool
    zip_path: str                    # relative to project_dir
    manifest: ManufacturingManifest
    build: Build | None              # associated build record, if any
    validation: HandoffValidation
    error_message: str = ""
```

### `readme.md` generation (HANDOFF-04)

Use `atomic_write` (see FILE 5) to write a markdown string built from BoardSpec + title_block + board stats + DRC/ERC results. The template is in `208-CONTEXT.md:119-148`. Read board stats via `get_board_statistics(pcb_path)` from `export/general.py:298`.

### `ManufacturingArtifact.from_file` pattern for each export

From `src/kicad_agent/validation/gates/manufacturing_manifest.py:33-45`:

```python
@staticmethod
def from_file(name: str, path: str, generated_by: str) -> ManufacturingArtifact:
    """Create artifact record by hashing the file on disk."""
    p = Path(path)
    data = p.read_bytes()
    return ManufacturingArtifact(
        name=name,
        path=str(p),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        generated_by=generated_by,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
```

**Usage in handoff:** For each export result (gerbers, drill, bom, etc.), iterate `result.files` and call `ManufacturingArtifact.from_file(name=<category>, path=str(f), generated_by=result.command)`. The `generated_by` field stores the kicad-cli command string for provenance.

---

## FILE 2 (CREATE): `tests/test_handoff.py`

### Closest analog: `tests/test_build_system.py`

The build system tests show the exact pattern for testing a side-effecting query handler: create a minimal PCB in tmpdir, build a PcbIR, invoke the handler directly via `_QUERY_HANDLERS[op_type]`, then assert on the result dict and the filesystem.

**Verbatim excerpt — shared test helpers** (`test_build_system.py:38-107`):

```python
@pytest.fixture(autouse=True)
def _clear_ir_registry():
    from kicad_agent.ir.base import _clear_registry
    _clear_registry()
    yield
    _clear_registry()


def _create_pcb_with_title_block(tmpdir: Path, rev: str = "1.0") -> Path:
    """Create a minimal PCB with a title_block carrying ``rev``."""
    pcb_path = tmpdir / "test_build.kicad_pcb"
    content = f'''(kicad_pcb (version 20241229) (generator "test")
  (general (thickness 1.6) (layers 2))
  (paper "A4")
  (title_block
    (title "Build Test")
    (date "2026-07-10")
    (rev "{rev}")
    (company "Test Co")
  )
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
  )
)
'''
    pcb_path.write_text(content, encoding="utf-8")
    return pcb_path


def _build_ir(pcb_path: Path):
    """Parse PCB and build PcbIR (mimics executor setup)."""
    from kicad_agent.parser.pcb_parser import parse_pcb
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser.uuid_extractor import extract_uuids
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)


def _make_artifact(name: str = "gerbers") -> ManufacturingArtifact:
    return ManufacturingArtifact(
        name=name,
        path=f"/tmp/{name}",
        sha256="a" * 64,
        size_bytes=1024,
        generated_by="snapshot",
        timestamp="2026-07-10T00:00:00+00:00",
    )
```

**Verbatim excerpt — handler invocation pattern** (`test_build_system.py:293-311`):

```python
def test_build_create_creates_directory(self, tmp_path: Path) -> None:
    """build_create creates builds/v*_*/ with manifest.json + build.json + snapshot."""
    from kicad_agent.ops._schema_pcb import BuildCreateOp
    from kicad_agent.ops.handlers.query import _QUERY_HANDLERS

    pcb_path = _create_pcb_with_title_block(tmp_path, rev="1.0")
    ir = _build_ir(pcb_path)
    handler = _QUERY_HANDLERS["build_create"]
    result = handler(
        BuildCreateOp(target_file="test_build.kicad_pcb", skip_validation=True),
        ir, pcb_path,
    )
    assert result["success"] is True
    build_dir = tmp_path / result["build_dir"]
    assert build_dir.is_dir()
    assert (build_dir / "manifest.json").is_file()
```

**What changes for `test_handoff.py`:**
- The `export_handoff` function is called **directly** (not through a handler dict), since it's a library function. The handler test pattern (`_QUERY_HANDLERS["build_handoff_export"]`) applies only to the op handler test.
- Tests must mock or skip kicad-cli-dependent steps (DRC/ERC/exports). Use `monkeypatch` to stub `run_drc`, `run_erc`, `run_vendor_drc`, and the `export_*` functions, OR use `skip_validation=True` and mock the export wrappers to write dummy files.
- Assert: `HandoffResult.success`, `zip_path` exists, `manifest` has required artifacts, validation fields populated, `readme.md` inside zip.
- The `test_build_create_no_partial_state_on_parse_failure` pattern (`test_build_system.py:402-420`) maps directly to "validation failure → no zip created".

**kicad-cli skip pattern** (`test_export_bom.py:14-18`):

```python
import shutil
kicad_cli_available = shutil.which("kicad-cli") is not None
skip_reason = "kicad-cli not found on PATH -- install KiCad 10+"
pytestmark = pytest.mark.skipif(not kicad_cli_available, reason=skip_reason)
```

For handoff tests that need to run without kicad-cli, mock the export functions via `monkeypatch.setattr`:

```python
def test_handoff_creates_zip(self, tmp_path, monkeypatch):
    pcb_path = _create_pcb_with_title_block(tmp_path)
    # Stub export wrappers to write dummy files
    def _fake_export_gerber(pcb_path, output_dir=None, **kw):
        output_dir = output_dir or pcb_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        f = output_dir / "board-F_Cu.gbr"
        f.write_text("dummy gerber")
        return ExportResult(success=True, output_dir=output_dir, files=(f,), command="stub")
    monkeypatch.setattr("kicad_agent.manufacturing.handoff.export_gerber", _fake_export_gerber)
    # ... similarly stub run_drc to return a passing DrcResult ...
    result = export_handoff(pcb_path=pcb_path, sch_path=None, project_dir=tmp_path, skip_validation=True)
    assert result.success
```

---

## FILE 3 (MODIFY): `src/kicad_agent/export/bom.py` — add `export_bom_profile`

### Closest analog: `export_jlcpcb_bom` in the same file (`bom.py:311-375`)

The new `export_bom_profile` generalizes `export_jlcpcb_bom`. The existing JLCPCB function is the exact template — it exports a standard BOM, enriches it, rewrites columns, and renames the output file. The profile-driven version replaces the hard-coded JLCPCB column list and filename with `profile.bom_columns` / `profile.bom_filename_pattern`.

**Verbatim excerpt — `export_jlcpcb_bom` to generalize** (`bom.py:311-375`):

```python
def export_jlcpcb_bom(
    schematic_path: Path,
    output_path: Path | None = None,
) -> BomResult:
    """Export BOM in JLCPCB-compatible CSV format."""
    if output_path is None:
        output_path = schematic_path.parent / f"{schematic_path.stem}_JLCPCB-BOM.csv"

    # First export the standard BOM
    std_result = export_bom(schematic_path, output_path)

    # Enrich with LCSC codes
    enrichment = enrich_with_lcsc(schematic_path)

    # Rewrite in JLCPCB format
    rows = enrichment["components"]
    if not rows:
        return std_result

    # Write JLCPCB-format CSV
    jlcpcb_rows = []
    for comp in rows:
        ref = comp.get("Reference", "")
        value = comp.get("Value", comp.get("Comment", ""))
        footprint = comp.get("Footprint", "")
        lcsc = comp.get("LCSC", "")
        if ref and ref != "?":
            jlcpcb_rows.append({
                "Comment": value,
                "Designator": ref,
                "Footprint": footprint,
                "LCSC": lcsc,
            })

    # Write CSV
    fieldnames = ["Comment", "Designator", "Footprint", "LCSC"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jlcpcb_rows)

    return BomResult(
        success=True,
        output_path=output_path,
        component_count=...,
        unique_components=len(jlcpcb_rows),
        command=std_result.command,
        stderr=std_result.stderr,
    )
```

**What `export_bom_profile` changes:**

```python
def export_bom_profile(
    sch_path: Path,
    output_dir: Path,
    profile: ManufacturerProfile | None = None,
) -> BomResult:
    """Export BOM using a ManufacturerProfile output format spec (HANDOFF-05).

    If profile has bom_columns/bom_filename_pattern, post-process the kicad-cli
    BOM to match. If profile is None or lacks output spec, use generic format.
    """
    # 1. Determine output filename from profile pattern or default
    if profile and profile.bom_filename_pattern:
        filename = profile.bom_filename_pattern.format(stem=sch_path.stem)
    else:
        filename = f"{sch_path.stem}-BOM.csv"
    output_path = output_dir / filename

    # 2. Export standard BOM via kicad-cli
    std_result = export_bom(sch_path, output_path=output_path)

    # 3. If profile specifies columns, rewrite
    if profile and profile.bom_columns:
        # Enrich with LCSC (for JLCPCB-style profiles)
        enrichment = enrich_with_lcsc(sch_path)
        rows = enrichment["components"]
        # Map columns, write CSV with profile.bom_columns as fieldnames
        ...
    # else: leave kicad-cli default output as-is

    return BomResult(...)
```

**Backward compat:** Update `export_jlcpcb_bom` to delegate:

```python
def export_jlcpcb_bom(schematic_path, output_path=None):
    from kicad_agent.dfm.profiles import load_profile
    profile = load_profile("jlcpcb")
    if output_path is None:
        output_path = schematic_path.parent / f"{schematic_path.stem}_JLCPCB-BOM.csv"
    return export_bom_profile(schematic_path, output_path.parent, profile)
```

**Import to add at top of `bom.py`:**

```python
from kicad_agent.dfm.profiles import ManufacturerProfile
```

---

## FILE 4 (MODIFY): `src/kicad_agent/dfm/profiles.py` — add output format spec fields

### Closest analog: the existing `ManufacturerProfile` class in the same file (`profiles.py:26-57`)

The class is a Pydantic `BaseModel` with `Field(default=..., description=...)` on every field. New fields follow the exact same pattern.

**Verbatim excerpt — current fields to extend** (`profiles.py:46-57`):

```python
class ManufacturerProfile(BaseModel):
    """Manufacturer-specific PCB manufacturing constraints."""

    name: str = Field(min_length=1, max_length=256)
    min_trace_width_mm: float = Field(gt=0, description="Minimum trace width (mm)")
    min_drill_mm: float = Field(gt=0, description="Minimum drill diameter (mm)")
    min_annular_ring_mm: float = Field(ge=0, default=0.1, description="Minimum annular ring (mm)")
    min_solder_mask_sliver_mm: float = Field(ge=0, default=0.1, description="Minimum solder mask sliver (mm)")
    min_clearance_mm: float = Field(ge=0, default=0.127, description="Minimum clearance (mm)")
    min_via_diameter_mm: float = Field(gt=0, default=0.4, description="Minimum via diameter (mm)")
    max_board_dim_mm: float = Field(gt=0, default=500.0, description="Maximum board dimension (mm)")
    supports_blind_vias: bool = Field(default=False)
    supports_castellated: bool = Field(default=False)
    extra: dict[str, Any] = Field(default_factory=dict)
    drc_rules_path: Path | None = Field(default=None, description="Path to vendor .kicad_dru file")
```

**New fields to add** (after `drc_rules_path`):

```python
    # Phase 208 output format spec (HANDOFF-05)
    bom_columns: tuple[str, ...] | None = Field(
        default=None,
        description="BOM column names for vendor-specific CSV format. None = generic default.",
    )
    bom_filename_pattern: str | None = Field(
        default=None,
        description="BOM filename pattern with {stem} placeholder. None = generic default.",
    )
    cpl_filename_pattern: str | None = Field(
        default=None,
        description="Pick-and-place filename pattern with {stem} placeholder.",
    )
    include_step_by_default: bool = Field(
        default=True,
        description="Whether STEP 3D model is included in handoff by default.",
    )
```

**Update the JLCPCB standard profile** (`profiles.py:112-124`) to set the new fields:

```python
_JLCPCB_STANDARD = ManufacturerProfile(
    name="JLCPCB Standard 2-Layer",
    min_trace_width_mm=0.127,
    min_drill_mm=0.2,
    min_annular_ring_mm=0.15,
    min_solder_mask_sliver_mm=0.1,
    min_clearance_mm=0.127,
    min_via_diameter_mm=0.4,
    max_board_dim_mm=500.0,
    supports_blind_vias=False,
    supports_castellated=True,
    drc_rules_path=get_drc_profile_path("jlcpcb"),
    # Phase 208 output spec:
    bom_columns=("Comment", "Designator", "Footprint", "LCSC"),
    bom_filename_pattern="{stem}_JLCPCB-BOM.csv",
    cpl_filename_pattern="{stem}_JLCPCB-CPL.csv",
    include_step_by_default=True,
)
```

All other built-in profiles (`_PCBWAY_STANDARD`, `_OSH_PARK`, `_GENERIC_CONSERVATIVE`, etc.) inherit the `None` defaults for `bom_columns` / `bom_filename_pattern`, so they use the generic format. No changes needed to them unless a vendor-specific format is desired.

---

## FILE 5 (MODIFY): `src/kicad_agent/validation/gates/manufacturing_manifest.py` — add validation result fields

### Closest analog: the existing `ManufacturingManifest` class in the same file (`manufacturing_manifest.py:75-134`)

The manifest is a frozen dataclass with `to_json()`, `save()`, and `load()` methods. New fields must be added to all three to maintain lossless round-trip (RESEARCH RQ1).

**Verbatim excerpt — current manifest + serialization** (`manufacturing_manifest.py:75-134`):

```python
@dataclass(frozen=True)
class ManufacturingManifest:
    """Immutable manufacturing manifest aggregating all export results."""

    project_name: str
    board_name: str
    fab_profile: str
    artifacts: tuple[ManufacturingArtifact, ...] = ()
    bom_rows: int = 0
    total_components: int = 0
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

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

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, self.to_json())

    @classmethod
    def load(cls, path: Path) -> ManufacturingManifest:
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        artifacts = tuple(
            ManufacturingArtifact.from_dict(a) for a in data.get("artifacts", [])
        )
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

**New fields to add** (after `generated_at`):

```python
    # Phase 208: DRC/ERC validation results as proof of manufacturability (HANDOFF-09)
    drc_passed: Optional[bool] = None
    erc_passed: Optional[bool] = None
    vendor_drc_passed: Optional[bool] = None
    drc_violation_count: int = 0
    erc_violation_count: int = 0
```

**Update `to_json()`** — add to the `data` dict:

```python
        data = {
            ...existing fields...,
            "generated_at": self.generated_at,
            "drc_passed": self.drc_passed,
            "erc_passed": self.erc_passed,
            "vendor_drc_passed": self.vendor_drc_passed,
            "drc_violation_count": self.drc_violation_count,
            "erc_violation_count": self.erc_violation_count,
        }
```

**Update `load()`** — add to the constructor call (use `.get(..., default)` for backward compat with old manifests):

```python
        return cls(
            ...existing fields...,
            generated_at=data.get("generated_at", ""),
            drc_passed=data.get("drc_passed"),
            erc_passed=data.get("erc_passed"),
            vendor_drc_passed=data.get("vendor_drc_passed"),
            drc_violation_count=data.get("drc_violation_count", 0),
            erc_violation_count=data.get("erc_violation_count", 0),
        )
```

The `Optional` type is already imported at line 17: `from typing import Any, Optional`.

---

## FILE 6 (MODIFY): `src/kicad_agent/ops/_schema_pcb.py` — add `BuildHandoffExportOp`

### Closest analog: `BuildCreateOp` in the same file (`_schema_pcb.py:1288-1312`)

The handoff op is a read-only query op that creates side-effect artifacts without mutating the source. `BuildCreateOp` is the exact analog — same `project_dir` + `skip_validation` fields, same category rationale.

**Verbatim excerpt — `BuildCreateOp`** (`_schema_pcb.py:1288-1312`):

```python
class BuildCreateOp(BaseModel):
    """Create a versioned build snapshot (BUILD-01, BUILD-06).

    Snapshots source files, captures git SHA + board revision, and writes a
    manifest with SHA256-hashed artifacts to a ``builds/`` directory. The
    target ``.kicad_pcb`` is never modified (registered as a read-only query
    op -- CONTEXT.md IP-4 deviation).

    Attributes:
        op_type: Discriminator literal ``"build_create"``.
        target_file: Relative path to the .kicad_pcb file.
        project_dir: Project root (defaults to target_file parent). Rejected
            if it contains ``..`` path segments (threat-model #1).
        skip_validation: Skip validation (for testing / quick drafts).
    """

    op_type: Literal["build_create"] = "build_create"
    target_file: TargetFile
    project_dir: Optional[str] = Field(
        default=None, description="Project root (defaults to target_file parent)"
    )
    skip_validation: bool = Field(
        default=False, description="Skip validation (for testing / quick drafts)"
    )
```

**New op to add** (in the Phase 207 section, or a new Phase 208 section header):

```python
# ---------------------------------------------------------------------------
# Phase 208: Manufacturer handoff ops (HANDOFF-01, HANDOFF-08)
# ---------------------------------------------------------------------------


class BuildHandoffExportOp(BaseModel):
    """Export a complete manufacturer handoff package (HANDOFF-01, HANDOFF-08).

    Produces a zip bundle with all manufacturing artifacts (gerbers, drill, BOM,
    pick-and-place, STEP, PDFs), a readme, and a manifest with DRC/ERC proof of
    manufacturability. The target ``.kicad_pcb`` is never modified (registered
    as a read-only query op — same rationale as build_create).

    Attributes:
        op_type: Discriminator literal ``"build_handoff_export"``.
        target_file: Relative path to the .kicad_pcb file.
        project_dir: Project root (defaults to target_file parent). Rejected
            if it contains ``..`` path segments (threat-model #1).
        vendor: Optional vendor key (e.g. "jlcpcb", "pcbway"). When set,
            vendor-specific BOM formatting + vendor DRC are applied.
        include_step: Include STEP 3D model in the bundle (default True).
        include_render: Include PCB render image (default False — slow).
        skip_validation: Skip pre-handoff DRC/ERC validation gate.
    """

    op_type: Literal["build_handoff_export"] = "build_handoff_export"
    target_file: TargetFile
    project_dir: Optional[str] = Field(
        default=None, description="Project root (defaults to target_file parent)"
    )
    vendor: Optional[str] = Field(
        default=None, min_length=1, max_length=64,
        pattern=r"^[a-z0-9_]+$",
        description="Vendor key (jlcpcb, pcbway, etc.) for profile-driven output",
    )
    include_step: bool = Field(
        default=True, description="Include STEP 3D model in the bundle"
    )
    include_render: bool = Field(
        default=False, description="Include PCB render image (slow)"
    )
    skip_validation: bool = Field(
        default=False, description="Skip pre-handoff DRC/ERC validation gate"
    )
```

The `vendor` field uses `pattern=r"^[a-z0-9_]+$"` — identical to `DrcVendorOp.vendor` (`_schema_pcb.py:1258-1262`) for path-traversal defense.

---

## FILE 7 (MODIFY): `src/kicad_agent/ops/schema.py` — add to Operation union

### Closest analog: the Phase 207 import block + union additions

**Three edit sites, all matching the `BuildCreateOp` pattern:**

**Edit 1 — import block** (`schema.py:285-287`). Add after `BuildShowOp`:

```python
    BuildCreateOp,
    BuildListOp,
    BuildShowOp,
    BuildHandoffExportOp,
)
```

**Edit 2 — Operation union** (`schema.py:570-572`). Add after `BuildShowOp`:

```python
        | BuildCreateOp
        | BuildListOp
        | BuildShowOp
        | BuildHandoffExportOp,
        Field(discriminator="op_type"),
    ]
```

**Edit 3 — `__all__` list** (`schema.py:789-791`). Add after `"BuildShowOp"`:

```python
    "BuildCreateOp",
    "BuildListOp",
    "BuildShowOp",
    "BuildHandoffExportOp",
```

---

## FILE 8 (MODIFY): `src/kicad_agent/ops/registry.py` — add `_RAW_CATALOG` entry

### Closest analog: the Phase 207 build entries (`registry.py:1462-1489`)

**Verbatim excerpt — `build_create` registry entry** (`registry.py:1463-1471`):

```python
    # Phase 207 build system ops (BUILD-01, BUILD-07, BUILD-08)
    "build_create": {
        "category": "query",
        "description": "Create a versioned build: snapshot source files, capture git SHA + board rev, write manifest",
        "file_types": [".kicad_pcb"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
```

**New entry to add** (after `build_show`, before the closing `}` of `_RAW_CATALOG`):

```python
    # Phase 208 manufacturer handoff op (HANDOFF-01, HANDOFF-08)
    "build_handoff_export": {
        "category": "query",
        "description": "Export a complete manufacturer handoff zip: gerbers, drill, BOM, CPL, STEP, PDFs, readme, manifest with DRC/ERC proof",
        "file_types": [".kicad_pcb"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
```

Note: `is_readonly: True` and `category: "query"` — same as `build_create` (CONTEXT.md IP-4 deviation: creates side-effect artifacts without mutating the source `.kicad_pcb`).

---

## FILE 9 (MODIFY): `src/kicad_agent/ops/handlers/build.py` — add `build_handoff_export` handler

### Closest analog: `_handle_build_create` in the same file (`build.py:34-170`)

The new handler delegates to `export_handoff(...)` from `manufacturing/handoff.py`, converts the `HandoffResult` to a dict, and returns it. It follows the same `register_build` decorator pattern and signature `(op, ir, file_path) -> dict`.

**Verbatim excerpt — handler registration + signature pattern** (`build.py:34-35`):

```python
@register_build("build_create")
def _handle_build_create(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
```

**New handler to add** (after `_handle_build_show`):

```python
@register_build("build_handoff_export")
def _handle_build_handoff_export(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Export a complete manufacturer handoff package (HANDOFF-01, HANDOFF-08).

    Delegates to ``export_handoff()`` from ``manufacturing/handoff.py``.
    The target ``.kicad_pcb`` is never modified (registered read-only).
    """
    from dataclasses import asdict

    from kicad_agent.manufacturing.handoff import export_handoff, HandoffResult

    # 1. Resolve project_dir + reject path traversal (threat model #1).
    if op.project_dir and ".." in Path(op.project_dir).parts:
        return {
            "success": False,
            "error": "Invalid project_dir: path traversal forbidden",
        }
    project_dir = Path(op.project_dir) if op.project_dir else Path(file_path).parent

    # 2. Call the orchestrator.
    result = export_handoff(
        pcb_path=Path(file_path),
        sch_path=None,  # discovered inside export_handoff via stem
        project_dir=project_dir,
        vendor=op.vendor,
        include_step=op.include_step,
        include_render=op.include_render,
        skip_validation=op.skip_validation,
    )

    # 3. Serialize HandoffResult to dict.
    out: dict[str, Any] = {
        "success": result.success,
        "zip_path": result.zip_path,
        "validation": asdict(result.validation),
        "error_message": result.error_message,
    }
    if result.build is not None:
        out["build_id"] = result.build.build_id
        out["build_status"] = result.build.status.value
    if result.error_message:
        out["error"] = result.error_message
    # manifest as JSON string (it has its own to_json)
    out["manifest"] = result.manifest.to_json()
    out["artifact_count"] = len(result.manifest.artifacts)
    return out
```

**Note:** The handler is registered via `@register_build` (adding to `_BUILD_HANDLERS`), which is already merged into `_QUERY_HANDLERS` in `handlers/__init__.py:35`. No change to `__init__.py` is needed — the existing merge line handles it:

```python
# handlers/__init__.py:33-35
# Phase 207: build handlers ARE query handlers (read-only re the target .kicad_pcb;
# they create side-effect artifacts in builds/ without modifying the source).
_QUERY_HANDLERS.update(_BUILD_HANDLERS)
```

---

## FILE 10 (MODIFY): `tests/test_registry.py` — update count assertions

### Two edits required:

**Edit 1 — operation count** (`test_registry.py:23-26`):

```python
    def test_registry_has_98_operations(self) -> None:
        # Phase 208: 160 ops (was 159 after Phase 207; +1: build_handoff_export).
        assert len(OPERATION_REGISTRY) == 160
```

**Edit 2 — readonly operations set** (`test_registry.py:114-158`). Add `"build_handoff_export"` to the `expected_readonly` set, alphabetically between `"build_create"` and `"build_list"`:

```python
        expected_readonly = {
            "analyze_gaps",
            ...
            "build_create",
            "build_handoff_export",   # <-- NEW
            "build_list",
            "build_show",
            ...
        }
```

The set currently has 44 entries (per the assertion `len(readonly) == len(expected_readonly)`); adding one makes it 45.

---

## Cross-cutting reference: `atomic_write` for readme/manifest persistence

From `src/kicad_agent/io/atomic_write.py:15-43`:

```python
def atomic_write(file_path: Path, content: str) -> None:
    """Write content to file atomically via temp file + fsync + rename.

    Uses tempfile.mkstemp for an unpredictable name, os.fsync for durability,
    and try/except cleanup.
    """
    file_path = Path(file_path)
    fd, tmp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=".kicad_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(file_path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

**Usage in handoff:**
- `atomic_write(build_dir / "readme.md", readme_content)` — for the generated readme.
- `manifest.save(build_dir / "manifest.json")` — already uses `atomic_write` internally (see `manufacturing_manifest.py:106-113`).

---

## Cross-cutting reference: `load_board_spec` + `load_profile`

From `src/kicad_agent/manufacturing/board_spec.py:67-72`:

```python
def load_board_spec(pcb_path: Path) -> BoardSpec | None:
    """Load BoardSpec from sidecar JSON. Returns None if sidecar absent."""
    sidecar = pcb_path.with_suffix(".kicad_build_spec.json")
    if not sidecar.is_file():
        return None
    return BoardSpec.model_validate_json(sidecar.read_text(encoding="utf-8"))
```

From `src/kicad_agent/dfm/profiles.py:281-320`:

```python
def load_profile(name_or_path: str) -> ManufacturerProfile:
    """Load a manufacturer profile by name or file path.
    Resolution order:
    1. If name matches a built-in profile key, return it.
    2. If it's a file path that exists on disk, load YAML or JSON.
    3. Otherwise raise ValueError.
    """
    if name_or_path in _PROFILES:
        return _PROFILES[name_or_path]
    ...
```

**Usage in handoff:** Call `load_board_spec(pcb_path)` for readme generation (may return None — handle gracefully). Call `load_profile(vendor)` when vendor is specified (raises ValueError if unknown — catch and return error result).

---

## Summary of edit deltas

| File | Action | Lines changed (est.) |
|------|--------|---------------------|
| `manufacturing/handoff.py` | CREATE | ~250-350 lines |
| `tests/test_handoff.py` | CREATE | ~150-250 lines |
| `export/bom.py` | MODIFY | +40 lines (`export_bom_profile` + delegate) |
| `dfm/profiles.py` | MODIFY | +4 fields on `ManufacturerProfile`, +3 fields on `_JLCPCB_STANDARD` |
| `validation/gates/manufacturing_manifest.py` | MODIFY | +5 fields, +5 `to_json` lines, +5 `load` lines |
| `ops/_schema_pcb.py` | MODIFY | +35 lines (`BuildHandoffExportOp` class) |
| `ops/schema.py` | MODIFY | +1 import, +1 union line, +1 `__all__` entry |
| `ops/registry.py` | MODIFY | +10 lines (`_RAW_CATALOG` entry) |
| `ops/handlers/build.py` | MODIFY | +40 lines (`_handle_build_handoff_export`) |
| `tests/test_registry.py` | MODIFY | count 159→160, +1 readonly entry |
