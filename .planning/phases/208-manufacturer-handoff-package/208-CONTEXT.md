# Phase 208: Manufacturer Handoff Package - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning
**Source:** Derived from v7.0 ROADMAP.md + REQUIREMENTS.md + codebase pattern analysis + user directive ("maximum flexibility, no compromises")

<domain>
## Phase Boundary

Phase 208 is the capstone of v7.0 — one call (`build_handoff_export`) produces a complete zip bundle with all manufacturing artifacts + readme + manifest, with pre-handoff validation preventing incomplete bundles. It also generalizes the hard-coded JLCPCB BOM formatter into a profile-driven system and adds vendor output profiles.

**What ships:**
- `manufacturing/handoff.py` orchestrator — the one-call "prepare for manufacturing" command
- Pre-handoff validation gate: DRC clean + ERC clean + manifest complete before bundling
- Streaming zip creation (`handoff.zip`) for large STEP files (Pitfall 7)
- `readme.md` generated from BoardSpec + board stats + DRC/ERC results
- Profile-driven BOM formatter (replaces hard-coded `export_jlcpcb_bom`)
- `ManufacturerProfile` extended with output format spec (BOM columns, file naming, STEP optional)
- `build_handoff_export` operation (query op — creates artifacts without mutating source)
- DRC/ERC validation results included in manifest as proof of manufacturability

**What does NOT ship (Phase 209):**
- CLI subcommands (`handoff`)
- MCP auto-exposure
- ProjectContext discovery of builds/
- ManufacturerClient ABC

</domain>

<decisions>
## Implementation Decisions

### Handoff Orchestrator (HANDOFF-01, HANDOFF-02, HANDOFF-03)

- **New file:** `src/kicad_agent/manufacturing/handoff.py`
- **Function:** `export_handoff(pcb_path: Path, sch_path: Path | None, project_dir: Path, vendor: str | None = None, board_spec: BoardSpec | None = None, include_step: bool = True, include_render: bool = False) -> HandoffResult`
- **Pipeline (11 steps):**
  1. Read BoardSpec (from sidecar if not provided) + title_block (via NativeParser.parse_pcb)
  2. Run pre-handoff validation: DRC clean (run_drc) + ERC clean (run_erc if sch available) + vendor DRC (run_vendor_drc if vendor specified). FAIL → no zip, return error
  3. Create build directory: `builds/handoff_{timestamp}/` (or reuse existing build if build_id provided)
  4. Run all exports via existing `export/` wrappers:
     - Gerbers: `export_gerber(pcb_path, output_dir=build_dir)`
     - Drill: `export_drill(pcb_path, output_dir=build_dir)`
     - BOM: `export_bom(sch_path, output_dir=build_dir, profile=vendor_profile)` (profile-driven)
     - Pick-and-place: `export_position(pcb_path, output_dir=build_dir)`
     - STEP (if include_step): `export_step(pcb_path, output_path=build_dir)`
     - Netlist: `export_netlist(pcb_path, output_dir=build_dir)`
     - Schematic PDF (if sch available): `export_schematic_pdf(sch_path, output_path=build_dir)`
     - PCB PDF: `export_pcb_pdf(pcb_path, output_path=build_dir)`
  5. Build ManufacturingArtifact entries for each export (SHA256 via from_file)
  6. Generate `readme.md` from BoardSpec + board stats (get_board_statistics) + DRC/ERC results
  7. Create ManufacturingManifest with all artifacts + DRC/ERC results embedded
  8. Serialize `manifest.json` via atomic_write
  9. Create streaming zip: `handoff.zip` — writes files one at a time to disk (NOT memory) for large STEP handling (Pitfall 7)
  10. Transition build status to HANDED_OFF (if a Build record was created/used)
  11. Return HandoffResult with zip path, manifest, artifact count, validation status

### HandoffResult Dataclass

```python
@dataclass(frozen=True)
class HandoffResult:
    success: bool
    zip_path: str  # relative to project_dir
    manifest: ManufacturingManifest
    build: Build | None  # associated build record, if any
    validation: HandoffValidation  # DRC/ERC/vendor DRC results
    error_message: str = ""

@dataclass(frozen=True)
class HandoffValidation:
    drc_passed: bool
    erc_passed: bool | None  # None if no schematic
    vendor_drc_passed: bool | None  # None if no vendor specified
    drc_violations: int
    erc_violations: int
    vendor_drc_violations: int
```

### Pre-Handoff Validation Gate (HANDOFF-06, Pitfall 5)

- **NO zip created if validation fails** — the pipeline returns early with `success=False` and the error message
- **Validation checks (in order):**
  1. DRC clean: `run_drc(pcb_path)` — `drc_result.passed` must be True
  2. ERC clean (if schematic available): `run_erc(sch_path)` — `erc_result.passed` must be True
  3. Vendor DRC (if vendor specified): `run_vendor_drc(board, profile)` — `vendor_drc_result.passed` must be True
  4. Manifest complete: all required artifacts (gerbers, drill, bom, cpl) must exist and have non-zero size
- **Pitfall 5 prevention:** The manifest must validate required artifact names. If any required artifact is missing, the handoff fails — NO partial zip.
- **Graceful degradation:** If kicad-cli is not available (DRC/ERC can't run), the handoff still proceeds but marks validation as `drc_passed=None` (inconclusive) and includes a warning in the readme. The user can override with `skip_validation=True`.

### Profile-Driven BOM Formatter (HANDOFF-05, Pitfall 3)

- **Extend `ManufacturerProfile`** with output format spec:
  ```python
  # New fields in dfm/profiles.py ManufacturerProfile:
  bom_columns: tuple[str, ...] | None = None  # None = generic default
  bom_filename_pattern: str | None = None  # None = generic default
  cpl_filename_pattern: str | None = None
  include_step_by_default: bool = True
  ```
- **JLCPCB profile updated:** `bom_columns=("Comment", "Designator", "Footprint", "LCSC")`, `bom_filename_pattern="{stem}_JLCPCB-BOM.csv"`
- **Generic profile:** `bom_columns=None` (uses kicad-cli default columns), `bom_filename_pattern=None`
- **New function in `export/bom.py`:** `export_bom_profile(sch_path, output_dir, profile: ManufacturerProfile | None = None) -> BomResult`
  - If profile has `bom_columns`, post-process the kicad-cli BOM output to match the specified columns
  - If profile has `bom_filename_pattern`, rename the output file
  - If profile is None or has no output spec, use generic format
- **`export_jlcpcb_bom` preserved** for backward compatibility but internally delegates to `export_bom_profile` with JLCPCB profile
- **The handoff orchestrator calls `export_bom_profile`** — NEVER `export_jlcpcb_bom` directly (Pitfall 3)

### readme.md Generation (HANDOFF-04)

- **Generated from:**
  - BoardSpec: surface finish, copper weight, soldermask/silkscreen color, impedance requirements
  - title_block: board name, revision, date, company
  - Board statistics: layer count, dimensions, component count, net count
  - DRC/ERC results: pass/fail status, violation counts
  - Vendor profile (if specified): vendor name, capabilities
- **Template structure:**
  ```markdown
  # Manufacturing Handoff: {board_name}

  **Revision:** {rev}
  **Date:** {date}
  **Company:** {company}
  **Generated:** {timestamp}

  ## Board Specifications
  - Surface Finish: {surface_finish}
  - Copper Weight: {outer}oz outer / {inner}oz inner
  - Soldermask: {soldermask_color}
  - Silkscreen: {silkscreen_color}
  - Layer Count: {layer_count}
  - Dimensions: {width}mm x {height}mm

  ## Impedance Requirements
  {if impedance_requirements: table of net, target ohms, reference layer}

  ## Validation Results
  - DRC: {passed/failed} ({violation_count} violations)
  - ERC: {passed/failed/N/A} ({violation_count} violations)
  - Vendor DRC ({vendor}): {passed/failed/N/A}

  ## Artifacts
  {table of all files in the zip with SHA256 hashes}

  ## Contact
  Designed by: {company}
  ```
- **Written via `atomic_write`** to the build directory before zipping

### Streaming Zip Creation (HANDOFF-03, Pitfall 7)

- **Use `zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED)`**
- **Write files one at a time** — `zipfile.write(filepath, arcname=filename)` for each artifact
- **NEVER load files into memory** — `zipfile.write()` streams from disk
- **STEP files (10-100MB) are handled gracefully** — they're written directly to the zip without buffering
- **Zip includes:** all export artifacts + `manifest.json` + `readme.md`
- **Zip path:** `builds/handoff_{timestamp}/handoff.zip`

### build_handoff_export Operation (HANDOFF-01, HANDOFF-08)

- **Schema:** `BuildHandoffExportOp` in `_schema_pcb.py`:
  ```python
  class BuildHandoffExportOp(BaseModel):
      op_type: Literal["build_handoff_export"] = "build_handoff_export"
      target_file: TargetFile
      project_dir: str | None = None
      vendor: str | None = None
      include_step: bool = True
      include_render: bool = False
      skip_validation: bool = False
  ```
- **Registry:** `is_readonly: True`, `category: "query"`, `file_types: [".kicad_pcb"]`
  - Same rationale as Phase 207: creates side-effect artifacts without mutating the source file
- **Handler:** `@register_query("build_handoff_export")` in `handlers/build.py`
  - Calls `export_handoff(...)` from `manufacturing/handoff.py`
  - Returns serialized `HandoffResult` as dict

### STEP/Render Optional (HANDOFF-07)

- **Controlled by `include_step` parameter** on `build_handoff_export` (defaults to True)
- **Also controllable via vendor profile:** `include_step_by_default` field on `ManufacturerProfile`
- **Bare-board orders:** User passes `include_step=False` → no STEP in the bundle
- **Renders:** `include_render` parameter (defaults to False — renders are optional and slow)

### DRC/ERC in Manifest (HANDOFF-09)

- **ManufacturingManifest extended** with validation results:
  ```python
  # New optional fields on ManufacturingManifest:
  drc_passed: bool | None = None
  erc_passed: bool | None = None
  vendor_drc_passed: bool | None = None
  drc_violation_count: int = 0
  erc_violation_count: int = 0
  ```
- These are serialized in `manifest.json` as proof of manufacturability
- Existing `to_json()`/`load()` methods extended to handle the new fields

### Schema Union + Registry (IP-1, IP-2)

- Add `BuildHandoffExportOp` to `Operation` union in `schema.py`
- Add `_RAW_CATALOG` entry in `registry.py`
- **Update `test_registry.py` count assertion** (159 → 160 for +1 op)
- **Update `test_readonly_operations_count`** if it asserts an exact set

### Claude's Discretion

- **DFM report gap:** The full ManufacturingReadinessGate requires a `dfm_report` context key. For Phase 208, the handoff orchestrator runs DRC + ERC + vendor DRC directly (not through the gate), and includes the results in the manifest. The full ManufacturingReadinessGate integration is deferred — the handoff's own validation is sufficient for v1.
- **Schematic discovery:** Look for `.kicad_sch` with the same stem as the `.kicad_pcb` file. If not found, skip BOM and schematic PDF exports.
- **Build directory naming:** `builds/handoff_{YYYYMMDD_HHMMSS}/` — separate from Phase 207's `builds/v{rev}_{timestamp}/` since handoff is a different operation (though it could reuse an existing build if build_id is provided)
- **Error handling:** Each export step wrapped in try/except. If a non-critical export fails (e.g., STEP generation times out), the handoff continues but logs the failure. Critical exports (gerbers, drill, BOM, CPL) failing blocks the handoff.

</decisions>

<canonical_refs>
## Canonical References

### Export Wrappers (to call)
- `src/kicad_agent/export/gerber.py` — `export_gerber` (line 136), `export_drill` (line 206), `export_manufacturing_package` (line 312)
- `src/kicad_agent/export/bom.py` — `export_bom` (line 76), `export_jlcpcb_bom` (line 311), `enrich_with_lcsc` (line 242), `parse_bom_csv` (line 168)
- `src/kicad_agent/export/general.py` — `export_position` (line 59), `export_step` (line 176), `export_netlist` (line 122), `export_schematic_pdf` (line 241), `get_board_statistics` (line 298)
- `src/kicad_agent/export/render.py` — `export_pcb_pdf`, `render_pcb` (line 87)

### Phase 207 (Build system)
- `src/kicad_agent/manufacturing/build.py` — `Build` dataclass, `BuildStatus` (EXPORTED → HANDED_OFF transition)
- `src/kicad_agent/validation/gates/manufacturing_manifest.py` — `ManufacturingManifest`, `ManufacturingArtifact`, `to_json()/save()/load()`

### Phase 206 (Vendor DRC)
- `src/kicad_agent/manufacturing/vendor_drc.py` — `run_vendor_drc(board, profile) -> VendorDrcResult`
- `src/kicad_agent/dfm/profiles.py` — `ManufacturerProfile`, `load_profile()`

### Phase 205 (BoardSpec + title_block)
- `src/kicad_agent/manufacturing/board_spec.py` — `BoardSpec`, `load_board_spec()`, `save_board_spec()`
- `src/kicad_agent/parser/pcb_native_parser.py` — `NativeParser.parse_pcb()` for title_block access

### Validation
- `src/kicad_agent/validation/erc_drc.py` — `run_erc()` (line 171), `run_drc()` (line 322), `DrcResult`, `ErcResult`

### Infrastructure
- `src/kicad_agent/io/atomic_write.py` — `atomic_write(file_path, content)`
- `src/kicad_agent/ops/handlers/build.py` — existing build handlers (Phase 207), `_BUILD_HANDLERS` merge pattern
- `src/kicad_agent/ops/handlers/__init__.py` — handler merge pattern

### Pitfalls
- `.planning/research/PITFALLS.md` — Pitfall 3 (vendor lock-in), Pitfall 5 (false confidence), Pitfall 7 (large files in zips)

</canonical_refs>

<specifics>
## Specific Ideas

- The handoff orchestrator is the "one call" that makes the entire v7.0 milestone useful — everything before it (metadata, DRC profiles, builds) feeds into this single operation
- The zip bundle is the universal fallback — it works with EVERY fab, not just those with APIs
- The readme is what a manufacturer reads first — it must contain everything they need without opening KiCad
- DRC/ERC results in the manifest are "proof of manufacturability" — the user can show the fab that the board passed validation
- Profile-driven BOM formatting means adding a new vendor is just adding a profile, not writing new code
- The handoff can work with or without a schematic (PCB-only mode skips BOM and schematic PDF)
- STEP/render inclusion is configurable — bare-board orders don't waste time generating STEP files

</specifics>

<deferred>
## Deferred Ideas

- CLI subcommand `handoff` — Phase 209
- MCP auto-exposure — Phase 209
- ProjectContext discovery of handoff zips — Phase 209
- Full ManufacturingReadinessGate integration (5-check gate) — future enhancement
- Handoff package versioning (v1, v2 formats) — future
- Multi-board handoff (panelized) — future
- Handoff package signing (cryptographic) — future
- Direct manufacturer upload (API-based) — Phase 210 (DEFERRED)

</deferred>

---

*Phase: 208-manufacturer-handoff-package*
*Context gathered: 2026-07-11 via user directive ("maximum flexibility") + codebase pattern analysis*
