# Phase 208 Research: Manufacturer Handoff Package

**Gathered:** 2026-07-11
**Status:** Complete
**Purpose:** Answer "What do I need to know to PLAN Phase 208 well?"

Source files verified by direct read (paths absolute under `/Users/bretbouchard/apps/kicad-agent`).

---

## RQ1: Export Wrapper Signatures and Return Types

All wrappers live under `src/kicad_agent/export/`. Two result types are used: `ExportResult` (file-list exports) and `BomResult` (BOM-specific). `render_pcb` uses a separate `RenderResult` (not needed for handoff).

### ExportResult (`export/gerber.py:30`)

```python
@dataclass(frozen=True)
class ExportResult:
    success: bool
    output_dir: Path
    files: tuple[Path, ...]
    command: str
    stderr: str = ""
```

### BomResult (`export/bom.py:32`)

```python
@dataclass(frozen=True)
class BomResult:
    success: bool
    output_path: Path
    component_count: int
    unique_components: int
    command: str
    stderr: str = ""
```

### Wrapper Signatures (exact)

| Function | File:Line | Signature | Returns |
|----------|-----------|-----------|---------|
| `export_gerber` | gerber.py:136 | `(pcb_path: Path, output_dir: Path \| None = None, layers: list[str] \| None = None, use_drill_origin: bool = True, subtract_soldermask: bool = True, no_protel_ext: bool = False) -> ExportResult` | `ExportResult` (multiple files scanned from `output_dir`) |
| `export_drill` | gerber.py:206 | `(pcb_path: Path, output_dir: Path \| None = None, format: str = "excellon", generate_map: bool = True, map_format: str = "gerberx2") -> ExportResult` | `ExportResult` |
| `export_bom` | bom.py:76 | `(sch_path: Path, output_path: Path \| None = None, fields: list[str] \| None = None, group_by: list[str] \| None = None, exclude_dnp: bool = False) -> BomResult` | `BomResult` |
| `export_jlcpcb_bom` | bom.py:311 | `(schematic_path: Path, output_path: Path \| None = None) -> BomResult` | `BomResult` |
| `export_position` | general.py:59 | `(pcb_path: Path, output_dir: Path \| None = None, format: str = "ascii", units: str = "mm", side: str = "both") -> ExportResult` | `ExportResult` |
| `export_step` | general.py:176 | `(pcb_path: Path, output_path: Path \| None = None, no_dnp: bool = True, origin: str = "grid") -> ExportResult` | `ExportResult` (single STEP file) |
| `export_netlist` | general.py:122 | `(pcb_path: Path, output_dir: Path \| None = None, format: str = "kicadsexpr") -> ExportResult` | `ExportResult` |
| `export_schematic_pdf` | general.py:241 | `(sch_path: Path, output_path: Path \| None = None, theme: str \| None = None) -> ExportResult` | `ExportResult` |
| `get_board_statistics` | general.py:298 | `(pcb_path: Path) -> dict` | `dict` (pure Python, no kicad-cli) |
| `export_pcb_pdf` | render.py:296 | `(pcb_path: Path, output_path: Path \| None = None, theme: str \| None = None) -> ExportResult` | `ExportResult` |

### Failure Behavior

Wrappers **do NOT raise** on kicad-cli failure. They return a result object with `success=False` and populated `stderr`. They DO raise for:
- `FileNotFoundError` — if `pcb_path`/`sch_path` does not exist (via `_validate_pcb_path`/`_validate_sch_path`)
- `ValueError` — if the file is the wrong type, or path contains `..` traversal
- `subprocess.TimeoutExpired` — if kicad-cli exceeds the timeout (default 120s; STEP uses 120s, render uses 180s)

The underlying `_run_kicad_export` (gerber.py:101) returns a dict with `success`, `returncode`, `stdout`, `stderr`, `command`. A non-zero kicad-cli exit code is captured, NOT raised.

**Handoff orchestrator implication:** wrap each export call in try/except for the validation exceptions, and check `.success` on the returned result object. Critical exports (gerbers, drill, bom, cpl) failing blocks the handoff; non-critical (STEP, render, PDF) failures should be logged but tolerated (per CONTEXT.md "Error handling" decision).

**Important `output_dir` vs `output_path` divergence:** `export_gerber`, `export_drill`, `export_position`, `export_netlist` take `output_dir`; `export_step`, `export_schematic_pdf`, `export_pcb_pdf` take `output_path` (single file). The orchestrator must pass the correct parameter name per wrapper. The CONTEXT.md pipeline sketch uses `output_dir`/`output_path` interchangeably — verify each call site matches the actual signature.

---

## RQ2: BOM Profile-Driven Formatting

### Hard-coded JLCPCB column mapping (bom.py:311, `export_jlcpcb_bom`)

The exact mapping in `export_jlcpcb_bom` (lines 343-363):

```python
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
```

So the JLCPCB column order is: **`Comment, Designator, Footprint, LCSC`**. The function first calls `export_bom(schematic_path, output_path)` (standard kicad-cli output), then `enrich_with_lcsc(schematic_path)` to extract LCSC codes via regex from the schematic, then rewrites the CSV in JLCPCB format.

### How generic `export_bom` works

`export_bom` (bom.py:76) calls `kicad-cli sch export bom` with optional `--fields` and `--group-by` flags. When `fields=None` (the default), it uses **kicad-cli's default columns**, which are: `Reference, Value, Footprint, Qty, DNP` (per the `parse_bom_csv` docstring at bom.py:178: "Common keys: Reference, Value, Footprint, Qty, DNP").

The function then parses the generated CSV via `parse_bom_csv` to count components (summing the `Qty` or `QUANTITY` column).

### Post-processing the kicad-cli BOM CSV for vendor columns

Yes — this is the clean path. The approach already proven in `export_jlcpcb_bom`:
1. Run `export_bom(sch_path, output_path)` to produce the standard CSV
2. Parse it via `parse_bom_csv(output_path)` (returns `list[dict]`)
3. Map rows to vendor-specific column names
4. Rewrite via `csv.DictWriter` with the vendor `fieldnames`

`parse_bom_csv` (bom.py:168) returns `list[dict]` using `csv.DictReader` — keys are the CSV header names. Standard keys are `Reference, Value, Footprint, Qty, DNP`.

### Cleanest profile-driven addition (no caller breakage)

**Add `export_bom_profile` to `export/bom.py`** — a new function, does not touch `export_bom` or `export_jlcpcb_bom` signatures:

```python
def export_bom_profile(
    sch_path: Path,
    output_dir: Path,
    profile: ManufacturerProfile | None = None,
) -> BomResult:
```

Logic:
- If `profile` is None OR `profile.bom_columns` is None → call `export_bom(sch_path, output_dir / "{stem}-BOM.csv")` (generic default). Return its result.
- If `profile.bom_columns` is set → call `export_bom` first, then post-process: read the generic CSV, remap columns to the profile's `bom_columns` tuple, enrich with LCSC if any column needs it, write to `profile.bom_filename_pattern`-derived filename.
- If `profile.bom_filename_pattern` is set, format it with `{stem}` = schematic stem. Rename the output file.

**Backward compatibility:** `export_jlcpcb_bom` is preserved unchanged (CONTEXT.md decision). Optionally, refactor it to delegate to `export_bom_profile` with the JLCPCB profile — but this is cosmetic and not required for correctness. The handoff orchestrator must call `export_bom_profile`, NEVER `export_jlcpcb_bom` (Pitfall 3).

**Key gotcha:** The `bom_columns` tuple contains *target* column names (e.g. `("Comment", "Designator", "Footprint", "LCSC")`), but the source CSV uses *different* names (`Reference, Value, Footprint`). The post-processor needs a source-to-target mapping. The cleanest approach: define a canonical mapping dict in the profile (e.g. `bom_column_map: dict[str, str]`) OR use a convention (JLCPCB: `Value`→`Comment`, `Reference`→`Designator`, add `LCSC` from enrichment). The CONTEXT.md spec only lists `bom_columns` as a tuple of target names — the implementation will need an implicit mapping (Comment=Value, Designator=Reference) or an explicit field. Recommend: build the mapping inside `export_bom_profile` using a well-known alias table (Comment↔Value, Designator↔Reference), since these are the only non-trivial renames.

---

## RQ3: Streaming Zip Creation

### Existing zip creation code: NONE

Grep for `zipfile` in `src/kicad_agent/` found exactly one module: `src/kicad_agent/project/adi_library/cache.py` — and it only **reads** zips (`zipfile.ZipFile(zip_path, "r")` at line 228). No code anywhere writes zips. Phase 208 introduces the first zip-creation code in the codebase.

### Correct Python streaming pattern

```python
import zipfile

zip_path = build_dir / "handoff.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for artifact_path in all_artifact_paths:
        arcname = artifact_path.name  # flat structure, or relative path for subdirs
        zf.write(artifact_path, arcname=arcname)
    # manifest + readme written after they're generated to disk
    zf.write(build_dir / "manifest.json", arcname="manifest.json")
    zf.write(build_dir / "readme.md", arcname="readme.md")
```

**Critical:** `zf.write(filepath, arcname)` streams from disk — it reads the file in chunks internally and never loads the whole file into memory. This is the key property for Pitfall 7. Do NOT use `zf.writestr(data, ...)` for large files (that requires the full content as a string/bytes in memory).

### Large STEP files (10-100MB)

`zf.write()` handles this gracefully because Python's `zipfile` reads the source file in 64KB-ish chunks during compression. Even a 100MB STEP file will not blow memory — the peak memory is the compression buffer, not the file content. No special handling needed beyond using `zf.write()` (not `zf.writestr()`).

The only concern is **time**: STEP compression on a 100MB file may take a few seconds. The `export_step` wrapper already has a 120s timeout for generation; zip compression is separate and not timeout-bounded. This is acceptable.

### ZIP_DEFLATED vs ZIP_STORED

**Use `ZIP_DEFLATED`.** Rationale:
- Gerbers, drill, BOM CSV, manifest JSON, readme MD are all text — deflate compresses these 3-5x.
- STEP files are already semi-compressed ASCII; deflate yields modest gains (~20-30%) but no harm.
- `ZIP_STORED` (no compression) is faster but produces larger zips — not worth it for a handoff package that may be emailed/uploaded.
- `ZIP_DEFLATED` is the de facto standard for manufacturing bundles. Every fab accepts it.

**Edge case:** If a particular artifact is already compressed (e.g., a `.zip` nested inside), deflate is harmless (Python detects and stores it efficiently). Not a concern for v1.

---

## RQ4: run_erc and run_drc Integration

### Signatures (erc_drc.py)

```python
def run_erc(schematic_path: Path, *, timeout: int = 120) -> ErcResult:        # line 171
def run_drc(pcb_path: Path, *, check_schematic_parity: bool = False, timeout: int = 300) -> DrcResult:  # line 322
```

Both are keyword-only after the path argument (`*` separator).

### kicad-cli unavailable: returns error result, does NOT raise

Both functions catch `FileNotFoundError` from `find_kicad_cli()` and return a result with `passed=False` and `error_message` set:

```python
# erc_drc.py:202 (ERC), erc_drc.py:359 (DRC)
try:
    cli_info = find_kicad_cli()
except FileNotFoundError as e:
    return ErcResult(passed=False, file_path=..., error_message=str(e))
```

They also catch `subprocess.TimeoutExpired`, JSON decode errors, and generic `Exception` — all return an error result rather than raising. The ONLY way they raise is if the input validation itself fails... but actually no: even missing-file and wrong-suffix return error results (not exceptions):
- Missing file → `ErcResult(passed=False, error_message="File not found: ...")` (line 187)
- Wrong suffix → `ErcResult(passed=False, error_message="Expected .kicad_sch ...")` (line 193)

So `run_erc` and `run_drc` **never raise** — they always return a result object. This is important for the orchestrator: no try/except needed around them.

### Distinguishing passed / failed / kicad-cli-unavailable

Check the `error_message` field on the result:

```python
result = run_drc(pcb_path)
if result.error_message is not None:
    # kicad-cli unavailable OR invocation failed OR malformed report
    # → "inconclusive" — CONTEXT.md graceful degradation path
    drc_passed = None  # inconclusive
elif result.passed:
    drc_passed = True   # clean
else:
    drc_passed = False  # violations exist
```

The `error_message` field is `None` on success, and set to a string on any failure (missing CLI, timeout, bad JSON, etc.). This is the exact tri-state the CONTEXT.md `HandoffValidation` needs:
- `drc_passed = True` — `result.passed and result.error_message is None`
- `drc_passed = False` — `not result.passed and result.error_message is None`
- `drc_passed = None` — `result.error_message is not None` (inconclusive / kicad-cli absent)

**Violation counts:** `result.error_count` (property, counts ERROR-severity violations) and `result.warning_count`. For the manifest, use `result.error_count` as the violation count (warnings are non-fatal).

### Running both ERC and DRC in the same pipeline

Yes — they are independent calls (ERC on the schematic, DRC on the PCB). The CONTEXT.md pipeline runs them sequentially in the pre-handoff validation gate (step 2). No shared state, no conflict. They can even be parallelized with `concurrent.futures` if desired, but sequential is simpler and the time cost (DRC can take up to 300s) is acceptable for a handoff operation.

**Conditional ERC:** If no schematic is found (PCB-only mode), skip ERC and set `erc_passed = None`.

---

## RQ5: ManufacturerProfile Extension

### Current fields (dfm/profiles.py:26, `ManufacturerProfile`)

Pydantic BaseModel. Current fields in order:

| Field | Type | Default |
|-------|------|---------|
| `name` | `str` | (required, 1-256 chars) |
| `min_trace_width_mm` | `float` | (required, >0) |
| `min_drill_mm` | `float` | (required, >0) |
| `min_annular_ring_mm` | `float` | `0.1` |
| `min_solder_mask_sliver_mm` | `float` | `0.1` |
| `min_clearance_mm` | `float` | `0.127` |
| `min_via_diameter_mm` | `float` | `0.4` |
| `max_board_dim_mm` | `float` | `500.0` |
| `supports_blind_vias` | `bool` | `False` |
| `supports_castellated` | `bool` | `False` |
| `extra` | `dict[str, Any]` | `{}` |
| `drc_rules_path` | `Path \| None` | `None` (Phase 206) |

### Where to add output format spec fields

Add after `drc_rules_path` (line 57). Pydantic field order is declaration order, so appending at the end is clean:

```python
drc_rules_path: Path | None = Field(default=None, ...)
# Phase 208 output format spec (HANDOFF-05)
bom_columns: tuple[str, ...] | None = Field(default=None, description="...")
bom_filename_pattern: str | None = Field(default=None, description="...")
cpl_filename_pattern: str | None = Field(default=None, description="...")
include_step_by_default: bool = Field(default=True, description="...")
```

### Backward compatibility

New fields all default to `None` (or `True` for `include_step_by_default`). Existing profile instantiations in `profiles.py` (the `_JLCPCB_STANDARD`, `_PCBWAY_STANDARD`, etc. literals at lines 112-254) do NOT set these fields → they get defaults. **No existing profile breaks.** The `from_yaml`, `from_json`, `from_dict` classmethods use `model_validate` which ignores extra keys and applies defaults for missing keys.

Existing YAML/JSON profile files on disk that don't have the new keys will load fine (defaults applied).

### Which profiles need `bom_columns` set

Per CONTEXT.md: **JLCPCB only.** Set on `_JLCPCB_STANDARD`:
```python
bom_columns=("Comment", "Designator", "Footprint", "LCSC"),
bom_filename_pattern="{stem}_JLCPCB-BOM.csv",
```

All other profiles (`_PCBWAY_STANDARD`, `_OSH_PARK`, `_GENERIC_CONSERVATIVE`, `_ADVANCED_CIRCUITS`, all `_AISLER_*`) leave `bom_columns=None` → generic kicad-cli default format. Adding a new vendor's BOM format later is just adding a profile entry, not writing code (the Pitfall 3 goal).

**Note on `_JLCPCB_4LAYER`:** It currently has no `drc_rules_path` set (line 126-144). For consistency, the 4-layer JLCPCB profile could also get the same `bom_columns`/`bom_filename_pattern` since it's the same vendor. Recommend setting it for both JLCPCB profiles.

---

## RQ6: Registry Count

### Current state: 159 ops (confirmed)

`tests/test_registry.py:23-26`:
```python
def test_registry_has_98_operations(self) -> None:
    # Phase 207: 159 ops (was 156 after Phase 206; +3: build_create,
    # build_list, build_show).
    assert len(OPERATION_REGISTRY) == 159
```

(The method name `test_registry_has_98_operations` is stale tech debt — the assertion itself is 159.)

### After Phase 208: 159 + 1 = 160

Adding `build_handoff_export` (1 op) → update assertion to `== 160`. Comment update: `# Phase 208: 160 ops (+1: build_handoff_export)`.

### `test_readonly_operations_count` (test_registry.py:107)

This test asserts an **exact set** of readonly op types (lines 114-158). `build_create`, `build_list`, `build_show` are already in the set (lines 118-120). Phase 208 must **add `"build_handoff_export"`** to the `expected_readonly` set (per CONTEXT.md: `is_readonly: True`, `category: "query"`). Failure to update this set causes the test to fail with an unexpected-extra op.

The full change in `test_registry.py`:
1. Line 26: `assert len(OPERATION_REGISTRY) == 159` → `== 160`
2. Line 24-25 comment: add Phase 208 note
3. Line ~120 (in `expected_readonly` set): add `"build_handoff_export",` (alphabetically after `"build_create"`)

### Registry catalog + schema union additions (IP-1, IP-2)

Three files must change atomically for `build_handoff_export`:
1. `src/kicad_agent/ops/_schema_pcb.py` — add `BuildHandoffExportOp` class (after `BuildShowOp`, line 1361)
2. `src/kicad_agent/ops/schema.py` — add `BuildHandoffExportOp` to imports (line ~287), to the `Operation` union (line ~572), and to `__all__` (line ~791)
3. `src/kicad_agent/ops/registry.py` — add `"build_handoff_export"` entry to `_RAW_CATALOG` (after `build_show`, line ~1489)

The registry entry pattern (mirroring `build_create`):
```python
"build_handoff_export": {
    "category": "query",
    "description": "Build complete manufacturing handoff zip: all exports + readme + manifest",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```

---

## RQ7: Board Statistics for Readme

### `get_board_statistics` (general.py:298)

Returns a `dict` (NOT a dataclass). Pure Python — **does not call kicad-cli**. It parses the PCB via `parse_pcb` + `PcbIR`:

```python
def get_board_statistics(pcb_path: Path) -> dict:
    # ...
    return {
        "component_count": component_count,      # len(board.footprints)
        "unique_footprints": unique_footprints,  # distinct libId count
        "net_count": net_count,                  # named nets (excludes "")
        "layer_count": layer_count,              # copper layers (board.general.layers or board.layers)
        "board_width_mm": board_width_mm,        # from Edge.Cuts bounding box
        "board_height_mm": board_height_mm,      # from Edge.Cuts bounding box
        "has_drc_errors": None,                  # always None (placeholder)
    }
```

### Usable without kicad-cli: YES

This function is explicitly documented as "does NOT call kicad-cli" (general.py:303). It uses the internal parser. It works in environments where kicad-cli is absent (e.g., CI, test). The readme generator can always call this — it never fails due to missing kicad-cli (though it can fail if the PCB is unparseable, in which case it raises).

### Available dimensions for readme

- **Layer count:** `layer_count` (integer) — copper layer count from `board.general.layers`.
- **Board dimensions:** `board_width_mm`, `board_height_mm` (floats) — computed from `gr_line`/`gr_rect`/`gr_arc` on `Edge.Cuts` layer via bounding box (`_extract_board_dimensions`, general.py:375). Returns `(0.0, 0.0)` if no Edge.Cuts geometry found.
- **Component count:** `component_count` (total footprints), `unique_footprints` (distinct lib IDs).
- **Net count:** `net_count` (named nets).

The readme template in CONTEXT.md (lines 119-148) references `layer_count`, `width`, `height` — all available from `get_board_statistics`. The template also references `surface_finish`, `copper_weight`, `soldermask_color`, `silkscreen_color`, `impedance_requirements` — these come from `BoardSpec` (not board stats). And `board_name`, `rev`, `date`, `company` come from `NativeTitleBlock`.

**Full readme data sources:**
- `NativeTitleBlock` (via `NativeParser.parse_pcb`): `title`, `date`, `rev`, `company`
- `BoardSpec` (via `load_board_spec`): `surface_finish`, `copper_weight_outer_oz`, `copper_weight_inner_oz`, `soldermask_color`, `silkscreen_color`, `impedance_requirements`
- `get_board_statistics`: `layer_count`, `board_width_mm`, `board_height_mm`, `component_count`, `net_count`
- DRC/ERC results: pass/fail + violation counts
- Vendor profile (optional): vendor name

---

## RQ8: ManufacturingManifest Extension

### Current ManufacturingManifest fields (manufacturing_manifest.py:75)

```python
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

Serialization methods (Phase 207):
- `to_json()` (line 89) — serializes to JSON string (indent=2), explicit field mapping
- `save(path)` (line 106) — atomic_write to disk
- `load(path)` (classmethod, line 115) — reconstructs from JSON

### Adding validation result fields

Add optional fields with defaults (after `generated_at` or before — dataclass field order matters for positional construction, but all existing callers use keyword args so order is flexible):

```python
# Phase 208 validation results (HANDOFF-09)
drc_passed: bool | None = None
erc_passed: bool | None = None
vendor_drc_passed: bool | None = None
drc_violation_count: int = 0
erc_violation_count: int = 0
```

Since all have defaults, existing positional callers are unaffected (and there are none — all construction is via keyword args or `generate_manifest`).

### Serialization updates required

**`to_json()`** (line 89): must add the 5 new keys to the `data` dict:
```python
data = {
    # ... existing keys ...
    "drc_passed": self.drc_passed,
    "erc_passed": self.erc_passed,
    "vendor_drc_passed": self.vendor_drc_passed,
    "drc_violation_count": self.drc_violation_count,
    "erc_violation_count": self.erc_violation_count,
}
```

**`load()`** (line 115): must read the new keys with `.get()` defaults for backward compat:
```python
return cls(
    # ... existing fields ...
    drc_passed=data.get("drc_passed", None),
    erc_passed=data.get("erc_passed", None),
    vendor_drc_passed=data.get("vendor_drc_passed", None),
    drc_violation_count=data.get("drc_violation_count", 0),
    erc_violation_count=data.get("erc_violation_count", 0),
)
```

The existing `load()` already uses `.get()` with defaults for `bom_rows`, `total_components`, `generated_at` (lines 131-133) — follow the exact same pattern.

**`generate_manifest()`** helper (line 137): optional update to accept the new fields as kwargs, OR leave as-is and let callers construct `ManufacturingManifest(...)` directly. The handoff orchestrator will likely construct directly.

### Migration concern: existing manifest.json files

**No migration needed.** The `load()` method uses `.get(key, default)` for all optional fields. Existing `manifest.json` files (written by Phase 207's `build_create`) lack the new keys → they load with defaults (`drc_passed=None`, counts=0). This is correct behavior: a Phase 207 build manifest has no validation results (DRAFT status, no handoff run yet).

The round-trip is safe: load an old manifest → add validation fields → save → new fields present. Load a new manifest in old code → extra keys ignored (dataclass doesn't error on construction; JSON has the keys but old `to_json` won't emit them — minor, acceptable).

---

## Validation Architecture

Phase 208's pre-handoff validation gate runs three independent checks before creating the zip. The architecture:

### Validation Flow (CONTEXT.md step 2, "Pre-Handoff Validation Gate")

```
export_handoff(pcb_path, sch_path, project_dir, vendor, ...)
  │
  ├─ 1. Parse PCB via NativeParser.parse_pcb(pcb_path) → NativeBoard
  │     (needed for title_block + vendor DRC geometry)
  │
  ├─ 2. Validation gate (fail-fast, NO zip on failure):
  │     ├─ a. run_drc(pcb_path) → DrcResult
  │     │     - error_message set? → drc_passed = None (inconclusive)
  │     │     - not passed? → FAIL: return success=False, no zip
  │     │
  │     ├─ b. IF sch_path exists: run_erc(sch_path) → ErcResult
  │     │     - error_message set? → erc_passed = None
  │     │     - not passed? → FAIL: return success=False, no zip
  │     │     - (no sch? erc_passed = None, skip)
  │     │
  │     ├─ c. IF vendor specified: run_vendor_drc(board, profile) → VendorDrcResult
  │     │     - error_message set? → vendor_drc_passed = None
  │     │     - not passed? → FAIL: return success=False, no zip
  │     │
  │     └─ d. skip_validation=True → bypass a/b/c, mark all as None (inconclusive)
  │
  ├─ 3. (validation passed) → create build dir, run exports, build manifest
  │
  └─ Return HandoffResult(success=True, validation=HandoffValidation(...))
```

### Tri-state validation semantics

Each check has three outcomes, mapped to `HandoffValidation`:
- **Passed (True):** `result.error_message is None and result.passed`
- **Failed (False):** `result.error_message is None and not result.passed` → **blocks handoff**
- **Inconclusive (None):** `result.error_message is not None` (kicad-cli absent) → handoff proceeds with warning (graceful degradation per CONTEXT.md)

The CONTEXT.md decision: "If kicad-cli is not available (DRC/ERC can't run), the handoff still proceeds but marks validation as `drc_passed=None`." This means **only `False` blocks the handoff** — `None` is tolerated. The `skip_validation=True` flag forces all to `None`.

### `run_vendor_drc` requires `NativeBoard`, not `PcbIR`

Critical implementation detail: `run_vendor_drc(board, profile)` (vendor_drc.py:89) expects a `NativeBoard` with `.segments`, `.vias`, `.footprints` attributes (duck-typed via `getattr`). It does NOT accept a `PcbIR`. The orchestrator must call `NativeParser.parse_pcb(file_path)` to get the `NativeBoard` — the same dual-path pattern used by `drc_vendor` handler (query.py:107) and `build_create` handler (build.py:76). This `NativeBoard` is ALSO needed for `title_block` access (Phase 205 pattern), so one parse serves both purposes.

### `VendorDrcResult` error semantics

`run_vendor_drc` never raises (vendor_drc.py:19 docstring: "The evaluator NEVER re-raises"). On total board-access failure it returns `VendorDrcResult(error_message=...)`. So the tri-state check is:
- `vendor_drc_result.error_message is not None` → inconclusive (`None`)
- `not vendor_drc_result.passed` → failed (`False`)
- else → passed (`True`)

### What the manifest records (HANDOFF-09)

After the gate passes, the validation results are embedded in `ManufacturingManifest` (the new optional fields from RQ8):
- `drc_passed`, `erc_passed`, `vendor_drc_passed` (each `True`/`False`/`None`)
- `drc_violation_count`, `erc_violation_count` (integers)

These are "proof of manufacturability" — serialized into `manifest.json` inside the zip.

### Relationship to `ManufacturingReadinessGate`

CONTEXT.md "Claude's Discretion": the full `ManufacturingReadinessGate` (5-check gate used by `build_create`) requires a `dfm_report` context key that Phase 208 does not produce. The handoff orchestrator runs DRC + ERC + vendor DRC **directly** (not through the gate). This is an accepted v1 simplification — the handoff's own validation is sufficient. Full gate integration is deferred.

---

## RESEARCH COMPLETE

All 8 research questions answered with verified code excerpts. Key planning inputs:

1. **Export wrappers** return result objects (never raise on kicad-cli failure); orchestrator must check `.success` and wrap in try/except only for path-validation exceptions.
2. **Profile-driven BOM** adds `export_bom_profile(sch_path, output_dir, profile)`; JLCPCB columns are `Comment, Designator, Footprint, LCSC`; generic uses kicad-cli defaults.
3. **Streaming zip** uses `zipfile.ZipFile("w", ZIP_DEFLATED)` + `zf.write(path, arcname)` — no existing zip-write code in the repo; handles 100MB STEP files without memory issues.
4. **ERC/DRC** never raise; tri-state via `error_message` (None=inconclusive, False=blocks, True=clean); both runnable in one pipeline.
5. **ManufacturerProfile** gets 4 new optional fields after `drc_rules_path`; only JLCPCB profiles set `bom_columns`; full backward compat.
6. **Registry** goes 159 → 160; three test spots to update (count, readonly set, plus the 3-file atomic schema/registry/handler change).
7. **Board stats** via `get_board_statistics` (pure Python, no kicad-cli) + `BoardSpec` + `NativeTitleBlock` cover all readme fields.
8. **ManufacturingManifest** gets 5 optional validation fields; `to_json`/`load` updated with `.get()` defaults; no migration needed for Phase 207 manifests.
