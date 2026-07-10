# Phase 206: Vendor DRC Profiles — Research

**Date:** 2026-07-10
**Objective:** Answer "What do I need to know to PLAN this phase well?"
**Context document:** `.planning/phases/206-vendor-drc-profiles/206-CONTEXT.md` (locked design decisions)

---

## CRITICAL BLOCKER (Read This First)

**The `--custom-rules` CLI flag does not exist. The `.kicad_dru` sidecar file is not loaded by `kicad-cli` at all.** The CONTEXT.md plan at lines 95-99 and 230 is technically infeasible as written. This was verified empirically against the installed `kicad-cli` 10.0.3 (`/usr/local/bin/kicad-cli`) using four separate test methods. See RQ1 for full evidence and the alternative approach.

---

## RQ1: How does `run_drc()` work, and can we extend it to inject custom DRC rules?

### Current implementation

File: `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/validation/erc_drc.py`

`run_drc()` at **line 322**:
```python
def run_drc(
    pcb_path: Path,
    *,
    check_schematic_parity: bool = False,
    timeout: int = 300,
) -> DrcResult:
```

Command construction at **lines 373-385**:
```python
cmd = [
    cli_info.path,
    "pcb",
    "drc",
    "--format",
    "json",
    "--severity-all",
    "--output",
    str(output_file),
]
if check_schematic_parity:
    cmd.append("--schematic-parity")
cmd.append(str(pcb_path))
```

The function creates a tempdir (`line 370`), writes JSON output to it, parses violations, and cleans up in `finally` (`line 466`). Security hardening: `os.chmod(output_file, 0o600)` at `line 409`.

### CRITICAL FINDING: `--custom-rules` flag does NOT exist

The installed `kicad-cli` reports version `10.0.3` (note: `AGENTS.md` says 10.0.1 — a separate staleness issue). The full `pcb drc --help` output is:

```
Usage: pcb drc [--help] [--output OUTPUT_FILE] [--define-var KEY=VALUE]...
  [--format FORMAT] [--all-track-errors] [--schematic-parity]
  [--units UNITS] [--severity-all] [--severity-error]
  [--severity-warning] [--severity-exclusions]
  [--exit-code-violations] [--refill-zones] [--save-board] INPUT_FILE
```

There is **no** `--custom-rules`, `--rules`, `--rule-file`, `--dru`, or `--preset` flag. The CONTEXT.md assertion at line 230 ("KiCad 10's `kicad-cli pcb drc --custom-rules <file>` flag runs DRC using the provided rules") is factually wrong.

### Empirical proof (4 tests, all negative)

Tested on the installed `kicad-cli 10.0.3` using `/Users/bretbouchard/apps/kicad-agent/tests/fixtures/smd_test_board.kicad_pcb` and `Arduino_Mega.kicad_pcb`:

1. **Sidecar DRU file (same-name convention).** Placed `smd_test_board.kicad_dru` alongside `smd_test_board.kicad_pcb` with a `(constraint track_width (min 5.0mm))` rule that would produce hundreds of violations if applied. Result: 0 track-width violations. The DRC produced identical output to a baseline run with no DRU file (8 violations, all `lib_footprint_issues` warnings).

2. **Sidecar DRU + minimal `.kicad_pro` project file.** Added `smd_test_board.kicad_pro` alongside the PCB and DRU. Result: identical 8 violations, 0 clearance violations.

3. **Deliberately invalid DRU syntax.** Wrote `Arduino_Mega.kicad_dru` containing garbage text ("THIS IS INVALID SYNTAX..."). `kicad-cli` ran successfully (exit 0, 15 violations). If the DRU file were being read at all, this would have produced a parse error. It did not — proving the file is never opened.

4. **Format-upgraded board.** Used `kicad-cli pcb upgrade` to upgrade `Arduino_Mega.kicad_pcb` to KiCad 10 format (version `20260206`). Placed a matching `Arduino_Mega_v10.kicad_dru` with the 5mm track-width rule alongside. Result: 0 track-width violations. The format upgrade did not change the behavior.

A separate attempt to embed `(rule ...)` S-expressions directly inside the `.kicad_pcb` file (inserted after the `(setup ...)` block) caused `kicad-cli` to fail with "Failed to load board" — the PCB parser does not accept rule forms there.

### Why this happens

Per the KiCad file format spec (`https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/`), custom design rules live in a separate `.kicad_dru` file that is loaded by the **KiCad project manager** (the GUI) via the `.kicad_pro` project file. The `kicad-cli pcb drc` subcommand operates on a standalone `.kicad_pcb` file and does **not** load the project context, so it never reads the `.kicad_dru` sidecar. This is consistent with GitLab issue [#24264](https://gitlab.com/kicad/code/kicad/-/issues/24264) ("Custom DRC exceptions not honored by kicad-cli"), which documents the same root cause for DRC exclusions.

### Recommended alternative approach (for the planner)

Since `kicad-cli` will not apply external custom rules, Phase 206 has two viable paths. The planner must choose:

**Option A — Temporarily inject rules into the board's `(setup ...)` section.** Copy the `.kicad_pcb` to a temp file, insert the vendor's rule S-expressions into a location the parser accepts, run DRC on the temp file, then delete it. **Risk:** the correct insertion point is not documented and my naive attempt to insert after `(setup ...)` failed ("Failed to load board"). This approach requires research into exactly where KiCad stores rule overrides in the board file, which may not be a supported write location. Not recommended without further investigation.

**Option B (recommended) — Embed vendor rules into the board's `.kicad_dru` sidecar and load the project.** This requires invoking DRC with the project context, which `kicad-cli pcb drc` does not support. Effectively a dead end for CLI-only operation.

**Option C (recommended, pragmatic) — Internal rule evaluation.** Instead of asking `kicad-cli` to enforce vendor rules, read the board's actual geometry (trace widths, clearances, drill sizes, annular rings) from the `PcbIR` and check them against the `ManufacturerProfile` numeric limits directly in Python. The `ManufacturerProfile` already carries `min_trace_width_mm`, `min_clearance_mm`, `min_drill_mm`, `min_annular_ring_mm`. The `drc_vendor` op would:
  1. Load the board via `PcbIR` (already built by `execute_query`).
  2. Walk tracks, vias, pads to extract actual dimensions.
  3. Compare against `ManufacturerProfile` thresholds.
  4. Return a `DrcResult`-shaped structure (or a new lightweight result type) with violations for any feature below the vendor limit.

This sidesteps `kicad-cli` entirely for vendor-specific checks, uses infrastructure that already exists (`PcbIR`, `ManufacturerProfile`), and does not depend on an unsupported CLI flag. The bundled `.kicad_dru` files still ship (DRC-02, DRC-03) for documentation and for users who want to load them in the GUI, but the `drc_vendor` op does not rely on `kicad-cli` applying them.

**Option D — Keep shipping `.kicad_dru` files and document the manual GUI workflow.** Ship the profile files and the `list_vendor_drc_profiles` op, but scope `drc_vendor` down to: copy the vendor `.kicad_dru` next to the user's board (renaming to match), and instruct the user to run DRC from the KiCad GUI. This is the lowest-effort path but does not deliver an automated pre-flight gate, which is the core value of DRC-01.

**The planner must resolve this before implementation can begin.** The CONTEXT.md lines 16, 82-101, and 230 all assume the `--custom-rules` flag and are invalid. Recommend surfacing this to the user as a design decision rather than silently picking an option.

---

## RQ2: What is the existing query handler pattern, and how do the two new ops integrate?

### Handler registry

File: `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/ops/handlers/query.py`

The `_QUERY_HANDLERS` dict at **line 14** maps `op_type` strings to callables. The `register_query` decorator at **line 17** registers handlers:

```python
_QUERY_HANDLERS: dict[str, Callable] = {}

def register_query(op_type: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        _QUERY_HANDLERS[op_type] = fn
        return fn
    return decorator
```

Handler signature: `(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]`. Two handlers exist today: `query_connectivity` (`line 25`) and `read_board_metadata` (`line 31`).

### Dispatch requires a valid PCB file

File: `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/ops/execution.py`

`execute_query` at **line 193** always calls `parse_pcb(file_path)` and builds a `PcbIR` before dispatching via `_QUERY_HANDLERS` lookup in `dispatch_query` at **line 233**. There is no early-skip path for ops that don't need the IR. The CONTEXT.md acknowledges this at line 128-131 and accepts that `list_vendor_drc_profiles` must receive a `target_file` even though it ignores the IR.

### Implications for the new ops

- **`drc_vendor`**: Naturally needs a `.kicad_pcb` file and a `PcbIR`, so this fits cleanly. If Option C (internal evaluation) from RQ1 is chosen, the handler walks `ir` to find violations. If Option A is chosen, the handler calls `run_drc()` on a temp board with injected rules.
- **`list_vendor_drc_profiles`**: Must accept `target_file` but ignores `ir`. Returns static profile metadata. The handler calls `list_drc_profiles()` from the new `drc_profiles` package and returns `{"profiles": [...], "count": N}`. No PCB parsing dependency in the handler body itself, but `execute_query` will still parse the file before calling it (a minor inefficiency, not a blocker).

### Schema union and registry parity

File: `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/ops/schema.py`

The `Operation` discriminated union at **line 397** currently ends with Phase 205 ops. Adding `DrcVendorOp` and `ListVendorDrcProfilesOp` requires:
1. Defining the two Op classes in `_schema_pcb.py`.
2. Importing and adding them to the `Operation` union in `schema.py`.
3. Adding `_RAW_CATALOG` entries in `registry.py` (`line 47`).

The `TargetFile` validator at **line 143** already allows `.kicad_dru` as a valid extension, which is relevant if any op ever targets a DRU file directly (not needed for the current design, but good to know).

File: `/Users/bretbouchard/apps/kicad-agent/tests/test_registry.py`

The count assertion at **line 27** is currently:
```python
assert len(OPERATION_REGISTRY) == 154
```
This must become `== 156` for the +2 ops. The `validate_registry_completeness` test at **line 29** has 3 known pre-existing missing ops (`add_design_note`, `apply_floor_plan`, `place_and_wire_power_units`) that must remain in the `_KNOWN_PREEXISTING_MISSING` set at **line 35**. The two new ops must NOT be missing from the registry.

---

## RQ3: What are the current published vendor manufacturing specifications?

All values verified July 2026. Sources cited inline.

### PCBWay (https://www.pcbway.com/capabilities.html)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Min trace width | **0.1mm (4mil)** manufacturable, **0.15mm (6mil)** recommended | Narrower than 6mil incurs higher cost |
| Min clearance | **0.1mm (4mil)** | |
| Min drill (CNC) | **0.2mm** | Range 0.2-6.3mm |
| Min annular ring | **0.15mm (6mil)** | This is the corrected value per DRC-07 (Pitfall 1) |
| Min solder mask sliver | 0.1mm (typical) | |
| Blind/buried vias | Yes | |
| Castellated holes | Yes | |

**DRC-07 correction:** The existing `_PCBWAY_STANDARD` profile at `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/dfm/profiles.py` **line 146** currently has `min_annular_ring_mm=0.1`. This should be updated to `0.15` to match PCBWay's published 0.15mm (6mil) spec. (Note: `0.1` is more permissive than PCBWay's actual limit — it would pass designs that PCBWay would reject.)

### JLCPCB (https://jlcpcb.com/capabilities/pcb-capabilities)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Min trace width | **0.15mm (6mil)** standard 1oz, **0.1mm (4mil)** achievable | Inner layers can reach 0.09mm |
| Min clearance | **0.15mm (6mil)** standard, **0.1mm** achievable | |
| Min drill (mechanical) | **0.15mm** absolute min, **0.2mm** preferred | 0.05mm increments |
| Min annular ring | **0.15mm (6mil)** | 0.075mm (3mil) for advanced/impedance orders |
| Blind/buried vias | Yes (HDI) | |
| Castellated holes | Yes | |
| Max layers | 32 | |

The existing `_JLCPCB_STANDARD` at `profiles.py` **line 113** has `min_annular_ring_mm=0.1` — same correction needed to `0.15`.

### AISLER (https://community.aisler.net/t/pcb-portfolio/101)

AISLER publishes per-stackup design rules. Layer variants: 2L, 4L, 6L, 8L.

| Parameter | 2L | 4L | 6L | 8L |
|-----------|-----|-----|-----|-----|
| Min trace width | 0.15mm (6mil) | 0.15mm (6mil) | 0.15mm | 0.15mm |
| Min clearance | 0.15mm (6mil) | 0.15mm (6mil) | 0.15mm | 0.15mm |
| Min drill | 0.2mm | 0.2mm | 0.2mm | 0.2mm |
| Min annular ring | **0.2mm** | **0.2mm** | **0.2mm** | **0.2mm** |

**Key note:** AISLER's 0.2mm annular ring is a **hard limit** (per community posts) and notably larger than JLCPCB/PCBWay's 0.15mm. The DRU files for `aisler_2layer` through `aisler_8layer` must reflect this 0.2mm minimum. The 4 variants differ mainly in layer count and copper weight (6L/8L use 70um outer / 35um inner), not in the core DRC geometry limits.

Finish: 2L available in HASL and ENIG; 4L/6L/8L ENIG only. Thickness: 1.6mm standard (0.8mm available for 4L).

### OSH Park (https://docs.oshpark.com/services/)

| Parameter | 2-Layer | 4-Layer |
|-----------|---------|---------|
| Min trace width | 0.1524mm (6mil) | 0.127mm (5mil) |
| Min clearance | 0.1524mm (6mil) | 0.127mm (5mil) |
| Min drill | 0.254mm (10mil) | 0.254mm (10mil) |
| Min annular ring | 0.127mm (5mil) | 0.1016mm (4mil) |
| Blind/buried vias | No | No |
| Castellated holes | No | No |

The existing `_OSH_PARK` at `profiles.py` **line 155** has `min_annular_ring_mm=0.1524` (6mil) and `min_drill_mm=0.3556` (14mil). The current OSH Park docs show **5mil (0.127mm) annular** and **10mil (0.254mm) drill** for 2-layer — the existing profile is more conservative than OSH Park's actual limits, which is safe but not tight. The CONTEXT.md at line 177 references "13mil min annular" which is a stale older value; current is 5mil. No correction strictly required (conservative is safe), but the DRU file should use the current published values.

### Advanced Circuits (https://www.4pcb.com/)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Min trace width | 0.1524mm (6mil) | Standard |
| Min clearance | 0.1524mm (6mil) | Standard |
| Min drill | 0.15mm (6mil) | |
| Min annular ring | 0.15mm (6mil) | |

Standard prototype-grade specs. Author from their capabilities page.

### Generic conservative defaults (per CONTEXT.md line 175)

| Parameter | Value |
|-----------|-------|
| Min trace width | 0.2mm |
| Min clearance | 0.2mm |
| Min drill | 0.3mm |
| Min annular ring | 0.15mm |

The existing `_GENERIC_CONSERVATIVE` at `profiles.py` **line 168** already matches these values closely (`min_drill_mm=0.4`, `min_annular_ring_mm=0.15`, `min_trace_width_mm=0.2`, `min_clearance_mm=0.2`).

---

## RQ4: What is the Cimos/KiCad-DesignRules repo, and is it usable?

**Repo:** `https://github.com/Cimos/KiCad-CustomDesignRules` (note: the actual repo name is `KiCad-CustomDesignRules`, not `KiCad-DesignRules` as the CONTEXT.md abbreviates it)

**License:** MIT (confirmed in repo)

**Coverage:** JLCPCB and PCBWay only. Each vendor has a directory with a `.kicad_dru` file.

**DRU file structure** (from `JLCPCB.kicad_dru`):
```
(version 1)
# Custom Design Rules (DRC) for KiCAD 8.0 (Stored in '.kicad_dru' file).
#
# Matching JLCPCB capabilities: https://jlcpcb.com/capabilities/pcb-capabilities
# ...

(rule "Minimum track width"
    (constraint track_width (min 0.127mm))
)
(rule "Minimum clearance outer"
    (constraint clearance (min 0.127mm))
    (condition "A.outer != B.outer")
)
(rule "Hole to copper clearance"
    (constraint hole_to_copper (min 0.127mm))
)
...
```

**Key observations:**
- Files target **KiCad 8.0** format (`(version 1)` header). This format is forward-compatible with KiCad 10.
- Rules use constraint types: `track_width`, `clearance`, `hole_size`, `annular_width`, `hole_to_copper`, `min_via_diameter`, `solder_mask_pads`.
- Conditions scope rules by layer (`A.outer != B.outer` etc.).
- The PCBWay file similarly matches `https://www.pcbway.com/capabilities.html`.

**Licensing conclusion:** MIT-licensed, safe to pull and redistribute with attribution. The CONTEXT.md sourcing table at lines 36-46 is correct for PCBWay and JLCPCB. For AISLER, OSH Park, Advanced Circuits, and generic: author from published numeric specs (factual data, not copyrightable expression).

**Important:** These DRU files are designed to be loaded by the KiCad **GUI** (renamed to match the project). As established in RQ1, `kicad-cli` does not load them. They are still valuable as shipped artifacts (DRC-02, DRC-03) for users who want to apply them manually, and as the source of truth for the numeric values that the internal evaluation (Option C) would check against.

---

## RQ5: How should the `drc_vendor` and `list_vendor_drc_profiles` ops be structured?

### `drc_vendor` (DRC-01, DRC-04)

Per CONTEXT.md lines 103-120:

```python
class DrcVendorOp(BaseModel):
    op_type: Literal["drc_vendor"] = "drc_vendor"
    target_file: TargetFile
    vendor: str = Field(description="Vendor name (pcbway, jlcpcb, ...)")
    check_schematic_parity: bool = False
```

Registry metadata: `is_readonly: True`, `category: "query"`, `file_types: [".kicad_pcb"]`.

**Handler flow** (depends on RQ1 resolution):
- Resolve vendor name via `load_profile(vendor)` from `dfm/profiles.py` **line 200**.
- If vendor not found, raise `ValueError` listing available vendors.
- If `drc_rules_path is None`, raise `ValueError("Vendor '{vendor}' has no DRC rules file")`.
- Run the vendor check (see RQ1 options) and return a dict.

**Vendor resolution edge case:** The current `_PROFILES` dict at `profiles.py` **line 181` uses keys like `"jlcpcb-4layer"` (hyphen) and `"osh_park"` (underscore). The new AISLER profiles would use `"aisler_2layer"` etc. The `vendor` field in `DrcVendorOp` must document the exact valid keys or the handler must normalize input (e.g., accept both `aisler-2layer` and `aisler_2layer`).

### `list_vendor_drc_profiles` (DRC-08)

Per CONTEXT.md lines 122-135:

```python
class ListVendorDrcProfilesOp(BaseModel):
    op_type: Literal["list_vendor_drc_profiles"] = "list_vendor_drc_profiles"
    target_file: TargetFile  # Required by dispatch, handler ignores it
```

Handler returns `{"profiles": [...], "count": N}` where each profile entry is a `VendorDrcProfileInfo` dict. The `target_file` requirement is a known design trade-off accepted by CONTEXT.md line 130.

### VendorDrcProfileInfo (CONTEXT.md lines 137-154)

Frozen dataclass in `manufacturing/drc_profiles/__init__.py`:
```python
@dataclass(frozen=True)
class VendorDrcProfileInfo:
    vendor: str
    display_name: str
    drc_rules_path: str
    min_trace_width_mm: float
    min_clearance_mm: float
    min_drill_mm: float
    min_annular_ring_mm: float
    supports_blind_vias: bool
    supports_castellated: bool
    source: str
    last_verified: str
```

`list_drc_profiles()` returns one entry per bundled `.kicad_dru` file (9 files total per CONTEXT.md line 62). `get_drc_profile_path(vendor: str) -> Path` resolves vendor name to file path.

---

## RQ6: What is the `.kicad_dru` file format, and how do we author valid files?

### Format

The `.kicad_dru` format is S-expression based (per CONTEXT.md lines 219-229 and the Cimos files). Structure:

```
(version 1)
(rule "Rule name"
    (constraint <type> (min <value>))
    (condition "<optional sexpr-like condition>")
    (layer "<optional layer scope>")
)
```

### Supported constraint types

From KiCad 10 PCB Editor documentation and the Cimos files:

| Constraint | Purpose | Example |
|------------|---------|---------|
| `clearance` | Min spacing between copper objects | `(constraint clearance (min 0.15mm))` |
| `track_width` | Min copper trace width | `(constraint track_width (min 0.15mm))` |
| `annular_width` | Annular ring size on pads/vias | `(constraint annular_width (min 0.15mm))` |
| `hole_size` | Min/max drill hole diameter | `(constraint hole_size (min 0.2mm))` |
| `via_diameter` | Min via pad diameter | `(constraint via_diameter (min 0.4mm))` |
| `hole_to_copper` | Hole edge to nearest copper | `(constraint hole_to_copper (min 0.15mm))` |
| `solder_mask_pads` | Min solder mask sliver between pads | `(constraint solder_mask_pads (min 0.1mm))` |
| `disallow` | Forbid certain element types | `(constraint disallow track)` |

### Attribution header requirement (DRC-06)

Per CONTEXT.md lines 48-55, every file starts with:
```
# Source: {repo URL or "Authored from published specs"}
# License: {MIT | "No license — authored from published numeric specifications" | "N/A — data"}
# Last verified: {YYYY-MM-DD}
# Vendor: {vendor name}
# Capabilities: min track {X}mm, min clearance {Y}mm, min drill {Z}mm, min annular {W}mm
```

### File list and locations

Directory: `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/manufacturing/drc_profiles/`

9 files (per CONTEXT.md line 62):
- `pcbway.kicad_dru` — pull from Cimos (MIT), verify annular=0.15mm
- `jlcpcb.kicad_dru` — pull from Cimos (MIT)
- `aisler_2layer.kicad_dru` — authored from specs, annular=0.2mm
- `aisler_4layer.kicad_dru` — authored from specs, annular=0.2mm
- `aisler_6layer.kicad_dru` — authored from specs, annular=0.2mm
- `aisler_8layer.kicad_dru` — authored from specs, annular=0.2mm
- `oshpark.kicad_dru` — authored from specs
- `advanced_circuits.kicad_dru` — authored from specs
- `generic.kicad_dru` — conservative defaults

Plus `__init__.py` exporting `get_drc_profile_path`, `list_drc_profiles`, `VendorDrcProfileInfo`.

---

## RQ7: How do we serialize `DrcResult` for the handler return value?

### Current state

`DrcResult` at `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/validation/erc_drc.py` **line 91** is a frozen dataclass with tuple fields:

```python
@dataclass(frozen=True)
class DrcResult:
    passed: bool
    file_path: Path
    violations: tuple[Violation, ...] = ()
    unconnected_items: tuple[Violation, ...] = ()
    schematic_parity: tuple[dict[str, Any], ...] = ()
    ignored_checks: tuple[dict[str, str], ...] = ()
    kicad_version: str = ""
    error_message: Optional[str] = None
```

`Violation` at **line 47** is also frozen:
```python
@dataclass(frozen=True)
class Violation:
    description: str
    severity: Severity  # str Enum
    type: str
    items: tuple[dict[str, Any], ...] = ()
    sheet_path: str = "/"
```

There is **no existing `to_dict()` method** on either class. A grep for `asdict`, `to_dict`, `model_dump` in `erc_drc.py` returned no matches.

### Serialization options

**`dataclasses.asdict()`** works on frozen dataclasses. It recursively converts:
- `Severity` enum → its value string (because `Severity(str, Enum)` — `asdict` returns the enum member, which JSON serialization will handle as its `.value` since it's a str subclass).
- `tuple[Violation, ...]` → `list[dict, ...]` (recursively).
- `Path` → stays as a `Path` object (NOT automatically stringified). Must be converted: `str(result.file_path)`.
- `tuple[dict, ...]` → `list[dict, ...]`.

**Recommended approach:** Add a `to_dict()` method to `DrcResult` (and optionally `Violation`) that handles the `Path` conversion explicitly:

```python
def to_dict(self) -> dict[str, Any]:
    from dataclasses import asdict
    d = asdict(self)
    d["file_path"] = str(d["file_path"])
    return d
```

Alternatively, the handler can do the conversion inline. Either way, the `Path` field must be stringified before JSON serialization, or the MCP/response layer will fail.

**Note for Option C (internal evaluation):** If `drc_vendor` does its own geometric checks instead of calling `run_drc()`, it may construct `DrcResult` and `Violation` instances directly from its own analysis, then serialize them the same way. The `Violation` structure is flexible enough: `type` can be `"vendor_clearance"`, `description` can describe the specific failure, `items` can carry the coordinates.

---

## RQ8: How do we bundle and access `.kicad_dru` data files in the package?

### Current package-data configuration

File: `/Users/bretbouchard/apps/kicad-agent/pyproject.toml`

The project uses:
```toml
[tool.setuptools.packages.find]
where = ["src"]
```

There is **no** `[tool.setuptools.package-data]` section, **no** `include-package-data` setting, and **no** `MANIFEST.in` file. This means non-Python files inside `src/kicad_agent/` are **not automatically included** in the built distribution unless explicitly configured.

### Existing data file patterns in the codebase

1. **`part-mappings.yaml`** at `/Users/bretbouchard/apps/kicad-agent/src/kicad_agent/ops/handlers/pcb_bom.py` **line 37**:
   ```python
   _BUNDLED_MAPPINGS_PATH = Path(__file__).parent.parent.parent.parent.parent / "data" / "part-mappings.yaml"
   ```
   This navigates **outside** the package to a top-level `data/` directory. This is fragile (depends on install layout) and would break in a wheel install.

2. **`importlib.resources`** is NOT used anywhere in the codebase (grep for `importlib.resources`, `importlib_resources`, `pkg_resources`, `files(` returned no matches in `src/`).

3. **Sidecar files** like `.kicad_build_spec.json` (board_spec.py) are loaded from alongside the user's PCB file, not bundled.

### Recommended approach for `.kicad_dru` files

**Use `Path(__file__).parent`** (simplest, matches the CONTEXT.md suggestion at line 64). Since the DRU files live in the same package directory as `__init__.py`:

```python
from pathlib import Path
_PROFILES_DIR = Path(__file__).parent

def get_drc_profile_path(vendor: str) -> Path:
    path = _PROFILES_DIR / f"{vendor}.kicad_dru"
    if not path.is_file():
        raise ValueError(...)
    return path
```

**CRITICAL — must add package-data configuration to `pyproject.toml`:**

```toml
[tool.setuptools.package-data]
"kicad_agent.manufacturing.drc_profiles" = ["*.kicad_dru"]
```

Without this, `pip install` and wheel builds will **not include** the `.kicad_dru` files. They will work in development (editable install / running from source) but fail in production. This is the single most likely integration pitfall for this phase.

**Alternative (more robust):** Use `importlib.resources.files()`:
```python
from importlib.resources import files
import kicad_agent.manufacturing.drc_profiles as drc_pkg

def get_drc_profile_path(vendor: str) -> Path:
    path = files(drc_pkg) / f"{vendor}.kicad_dru"
    ...
```
This is the modern Python 3.9+ approach and works correctly with wheels. Since the project targets Python 3.11 (`pyproject.toml` sets `target-version = "py311"`), this is safe to use. Recommend `importlib.resources` over `Path(__file__)` for correctness across install types.

---

## Validation Architecture

### Nyquist gate: what must be true for this phase to be considered done?

The "Nyquist gate" requires that the phase delivers its value proposition at at least the minimum viable fidelity, with no silent failures. For Phase 206:

**Gate criteria:**

1. **DRU files ship and are valid.** All 9 `.kicad_dru` files exist at the correct path, are valid KiCad S-expression syntax (parseable by KiCad's rule engine), contain attribution headers (DRC-06), and carry the correct numeric values per RQ3 (especially PCBWay annular=0.15mm per DRC-07).

2. **Package-data includes DRU files.** `pyproject.toml` has a `[tool.setuptools.package-data]` entry so `.kicad_dru` files survive `pip install` / wheel builds. A test must verify `get_drc_profile_path("pcbway")` returns an existing file path after install, not just in editable mode.

3. **`list_vendor_drc_profiles` op works end-to-end.** Registered in the query handler dict, dispatches through `execute_query`, returns 9 profiles with correct metadata. Registry count is 156.

4. **`drc_vendor` op returns meaningful results.** Given a vendor name and a `.kicad_pcb` file, the op returns a result structure that distinguishes pass/fail and lists violations. **The exact mechanism depends on the RQ1 resolution**, but whatever approach is chosen, it must actually detect violations against vendor limits — not silently pass everything (the failure mode of the naive `--custom-rules` approach).

5. **Registry parity holds.** `test_registry.py` count assertion is 156. `validate_registry_completeness` passes with no new missing ops.

6. **Existing profiles corrected.** `min_annular_ring_mm` updated to 0.15 for `_PCBWAY_STANDARD` (line 146) and `_JLCPCB_STANDARD` (line 113) in `profiles.py` per DRC-07.

### Validation risk: the silent-pass failure mode

The highest risk for this phase is that `drc_vendor` appears to work but silently passes boards that violate vendor rules. This is exactly what the naive `--custom-rules` approach would produce (RQ1): the op would run `kicad-cli`, get back a clean `DrcResult(passed=True)`, and report "no violations" — while the vendor's actual limits are violated. The validation architecture must include at least one test case with a deliberately violating board (e.g., a 0.1mm trace checked against the generic 0.2mm profile) and assert that the op reports a violation. If that test fails, the mechanism is broken.

---

## RESEARCH COMPLETE
