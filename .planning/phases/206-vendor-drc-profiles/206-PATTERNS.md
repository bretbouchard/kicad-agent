# Phase 206: Vendor DRC Profiles — Pattern Mapping

**Phase:** 206 — Vendor DRC Profiles
**Generated:** 2026-07-10
**Source docs:** 206-CONTEXT.md (decisions), 206-RESEARCH.md (technical research)

This document maps each file to be created/modified to its closest existing codebase analog, with concrete code excerpts and integration notes. The implementer reads this alongside CONTEXT.md and RESEARCH.md.

---

## CRITICAL CONTEXT (read first)

1. **The internal evaluator pivot (CONTEXT.md lines 84-120, RESEARCH RQ1).** `kicad-cli pcb drc --custom-rules` does NOT exist. The `drc_vendor` op must NOT call kicad-cli with vendor rules. Instead, `manufacturing/vendor_drc.py` walks `PcbIR` geometry in Python and compares against `ManufacturerProfile` numeric limits. This is Option C from research. The `.kicad_dru` files ship for GUI use + documentation, but the automated gate is our evaluator.

2. **Package-data is mandatory (RESEARCH RQ8).** `pyproject.toml` currently has NO `[tool.setuptools.package-data]` section. Without adding it, the `.kicad_dru` files will work in editable/dev mode but be silently dropped from wheels/`pip install`. This is the highest-frequency integration pitfall.

3. **Two new ops = registry count 154 → 156 (test_registry.py:27).** Both ops must land in `_RAW_CATALOG`, the `Operation` union, and `__all__` together, or `validate_registry_completeness` fails.

4. **PCBWay/JLCPCB annular ring correction (DRC-07).** Both `_PCBWAY_STANDARD` (profiles.py:146) and `_JLCPCB_STANDARD` (profiles.py:113) currently have `min_annular_ring_mm=0.1`, which is more permissive than the vendors' actual 0.15mm limit. Update to `0.15`.

---

## FILE 1 (CREATE): `src/volta/manufacturing/drc_profiles/__init__.py`

**Role:** Package init + static-data registry. Resolves vendor name → bundled `.kicad_dru` path, and enumerates available profiles with capabilities metadata.

**Data flow:** Static data only. Reads bundled `.kicad_dru` files from the same directory. Consumed by `dfm/profiles.py` (for `drc_rules_path`), by `vendor_drc.py` (indirectly, via profile limits), and by the `list_vendor_drc_profiles` handler.

### Closest analog: `dfm/profiles.py` (built-in profile registry pattern)

`profiles.py` already has the exact structure this file needs: a module-level dict of built-in profiles, `get_builtin_profiles()`, and `load_profile()` with a ValueError listing available keys. Mirror this shape for the DRU registry.

**Excerpt — `_PROFILES` dict + `load_profile` error pattern** (`dfm/profiles.py:181-239`):
```python
_PROFILES: dict[str, ManufacturerProfile] = {
    "jlcpcb": _JLCPCB_STANDARD,
    "jlcpcb-4layer": _JLCPCB_4LAYER,
    ...
}

def load_profile(name_or_path: str) -> ManufacturerProfile:
    if name_or_path in _PROFILES:
        return _PROFILES[name_or_path]
    path = Path(name_or_path)
    if path.is_file():
        ...
    available = ", ".join(sorted(_PROFILES.keys()))
    raise ValueError(
        f"Unknown profile '{name_or_path}'. "
        f"Available built-in profiles: {available}. ..."
    )
```

### Bundled-file access: `Path(__file__).parent` (recommended by RESEARCH RQ8)

RESEARCH RQ8 verified that `importlib.resources` is NOT used anywhere in the codebase, and that the existing bundled-data pattern (`part-mappings.yaml` via `pcb_bom.py:37`) navigates OUTSIDE the package (fragile, breaks in wheels). Use `Path(__file__).parent` for the DRU files since they live in the same directory as `__init__.py`:

```python
from pathlib import Path
_PROFILES_DIR = Path(__file__).parent

def get_drc_profile_path(vendor: str) -> Path:
    path = _PROFILES_DIR / f"{vendor}.kicad_dru"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in _PROFILES_DIR.glob("*.kicad_dru")))
        raise ValueError(
            f"Unknown vendor '{vendor}'. Available DRC profiles: {available}."
        )
    return path
```

**Note:** RESEARCH RQ8 recommends `importlib.resources.files()` as the more robust alternative for wheels. Either works for Phase 206; `Path(__file__).parent` is simpler and matches CONTEXT.md line 66. The package-data entry in pyproject.toml (FILE 12) is what actually makes the files survive packaging.

### `VendorDrcProfileInfo` dataclass — pattern

Use `@dataclass(frozen=True)` to match every other result/info type in this codebase (`Violation`, `DrcResult`, `SpatialViolation`, `NativeBoard`, all frozen). CONTEXT.md lines 159-173 give the exact field list. Follow the `BoardSpec` pydantic-vs-dataclass precedent: BoardSpec uses pydantic because it persists to JSON sidecar. `VendorDrcProfileInfo` is pure in-memory metadata, so a frozen dataclass is the lighter-weight choice (matches `Violation`/`DrcResult`).

**Excerpt — frozen dataclass pattern** (`validation/erc_drc.py:47-55`):
```python
@dataclass(frozen=True)
class Violation:
    description: str
    severity: Severity
    type: str
    items: tuple[dict[str, Any], ...] = ()
    sheet_path: str = "/"
```

### `list_drc_profiles()` — return shape

Return `list[VendorDrcProfileInfo]`, one entry per bundled `.kicad_dru` file (9 files). The handler (`list_vendor_drc_profiles`) converts each to a dict via `dataclasses.asdict()`. CONTEXT.md lines 153-154 specify the handler serializes: `vendor`, `display_name`, `drc_rules_path`, numeric limits, capability flags, `source`, `last_verified`.

**Implementation approach:** Define a `_PROFILE_INFOS` dict at module level (keyed by vendor string → `VendorDrcProfileInfo`), mirroring the `_PROFILES` dict in `profiles.py`. This keeps the metadata co-located with the resolution logic and avoids re-parsing `.kicad_dru` files at runtime.

---

## FILE 2 (CREATE): `src/volta/manufacturing/drc_profiles/*.kicad_dru` (9 files)

**Role:** Static data files (KiCad S-expression DRC rule format). Source of truth for vendor numeric limits; also loadable in the KiCad GUI for manual DRC.

**Data flow:** Read by `get_drc_profile_path()` (FILE 1) and shipped as package data (FILE 12). NOT read by `run_drc()` — kicad-cli ignores `.kicad_dru` sidecars (RESEARCH RQ1, verified empirically).

### File format: S-expression rules (RESEARCH RQ6)

```
(version 1)
(rule "Minimum track width"
    (constraint track_width (min 0.15mm))
)
(rule "Minimum clearance"
    (constraint clearance (min 0.15mm))
)
```

### Attribution header (required by DRC-06, CONTEXT.md lines 48-57)

Every file starts with this comment block:
```
# Source: {repo URL or "Authored from published specs"}
# License: {MIT | "No license — authored from published numeric specifications" | "N/A — data"}
# Last verified: 2026-07-10
# Vendor: {vendor name}
# Capabilities: min track {X}mm, min clearance {Y}mm, min drill {Z}mm, min annular {W}mm
```

### Numeric values (from RESEARCH RQ3 — all verified July 2026)

| Vendor | min track | min clearance | min drill | min annular | blind/buried | castellated |
|--------|-----------|---------------|-----------|-------------|--------------|-------------|
| pcbway | 0.127mm | 0.127mm | 0.2mm | **0.15mm** (DRC-07) | yes | yes |
| jlcpcb | 0.127mm | 0.127mm | 0.2mm | **0.15mm** (DRC-07) | yes | yes |
| aisler_2layer..8layer | 0.15mm | 0.15mm | 0.2mm | **0.2mm** (hard limit) | no | no |
| oshpark | 0.1524mm | 0.1524mm | 0.254mm | 0.127mm | no | no |
| advanced_circuits | 0.1524mm | 0.1524mm | 0.15mm | 0.15mm | — | — |
| generic | 0.2mm | 0.2mm | 0.3mm | 0.15mm | no | no |

### Constraint types to use (RESEARCH RQ6 table)

- `track_width` — min copper trace width
- `clearance` — min spacing between copper objects
- `hole_size` — min drill hole diameter
- `annular_width` — annular ring on pads/vias
- `via_diameter` — min via pad diameter

### Sourcing (CONTEXT.md lines 36-48)

- **pcbway, jlcpcb:** Pull from Cimos/KiCad-CustomDesignRules (MIT), verify annular=0.15mm. License header: `MIT`.
- **aisler_2layer..8layer, oshpark, advanced_circuits, generic:** Author from published specs. License header: `No license — authored from published numeric specifications` (or `N/A — data` for the generic).

### Closest analog: there are NO existing `.kicad_dru` files in the repo

`find ... -name "*.kicad_dru"` returns nothing. These are the first DRU files. The format spec in RESEARCH RQ6 + the Cimos JLCPCB excerpt (RESEARCH RQ4) is the reference. KiCad 8 format `(version 1)` header is forward-compatible with KiCad 10.

---

## FILE 3 (CREATE): `src/volta/manufacturing/vendor_drc.py`

**Role:** Internal vendor DRC evaluator. Reads board geometry from `PcbIR` (via `NativeBoard`), compares against `ManufacturerProfile` numeric limits, returns `VendorDrcResult` with `Violation` instances.

**Data flow:** `PcbIR` + `ManufacturerProfile` → `VendorDrcResult`. Called by the `drc_vendor` handler. Does NOT call kicad-cli (the pivot). Optionally, the handler ALSO calls `run_drc()` for standard KiCad DRC and merges results (CONTEXT.md line 120).

### Result dataclass — closest analog: `DrcResult` (`validation/erc_drc.py:91-122`)

CONTEXT.md lines 108-117 define `VendorDrcResult` as a frozen dataclass with: `vendor`, `passed`, `violations: tuple[Violation, ...]`, `profile_name`, `checks_run: tuple[str, ...]`. Mirror the `DrcResult` structure exactly:

**Excerpt — `DrcResult` frozen dataclass with computed properties** (`validation/erc_drc.py:91-122`):
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

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity == Severity.ERROR)
```

Reuse the EXISTING `Violation` frozen dataclass from `validation/erc_drc.py:47` — do NOT define a new violation type. CONTEXT.md line 103 explicitly says "Reuses existing `Violation` frozen dataclass". Construct violations with `type` strings like `"vendor_trace_width"`, `"vendor_drill_size"`, etc.

**Excerpt — `Violation` + `Severity`** (`validation/erc_drc.py:39-55`):
```python
class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    EXCLUSION = "exclusion"

@dataclass(frozen=True)
class Violation:
    description: str
    severity: Severity
    type: str
    items: tuple[dict[str, Any], ...] = ()
    sheet_path: str = "/"
```

### Geometry extraction from `PcbIR` — closest analog: `extract_track_obstacles` / `extract_netlist`

`PcbIR` already has the exact iteration patterns needed. The evaluator walks `ir.board.segments` (for track widths), `ir.board.vias` (for drill/diameter), and `ir.board.footprints[*].pads` (for pad drills). Use the same getattr-based backend-agnostic access shown in `extract_track_obstacles`.

**Excerpt — iterating segments with width/net/layer** (`ir/pcb_ir.py:957-996`):
```python
segments = getattr(board, "segments", None) or []
for seg in segments:
    layer = getattr(seg, "layer", "") or ""
    net_name = getattr(seg, "net_name", "") or ""
    start = getattr(seg, "start", None)
    end = getattr(seg, "end", None)
    width = float(getattr(seg, "width", 0.2)) or 0.2
```

The `NativeSegment` dataclass (`parser/pcb_native_types.py:173-190`) confirms the field names: `width: float`, `layer: str`, `net_name: str`, `start/end: _NativePosition`.

`NativeVia` (`pcb_native_types.py:193-206`): `position: tuple[float,float]`, `drill: float`, `diameter: float`, `net_name: str`, `uuid: str`.

`NativePad` (`pcb_native_types.py:95-113`): `number: str`, `net_name: str`, `position: tuple`, `size: tuple[float,float]`, `drill: float`, `pad_type: str` (one of `"smd"`, `"thru_hole"`, `"np_thru_hole"`).

### Check logic (CONTEXT.md lines 96-101)

For each `ManufacturerProfile` limit, iterate geometry and emit `Violation` on breach:

| Profile field | Iterate | Annular ring formula |
|---------------|---------|----------------------|
| `min_trace_width_mm` | `board.segments` → `seg.width` | — |
| `min_drill_mm` | `board.vias` → `via.drill`; `footprints[*].pads` where `pad_type == "thru_hole"` → `pad.drill` | — |
| `min_annular_ring_mm` | `board.vias`; thru-hole pads | `(diameter - drill) / 2` |
| `min_via_diameter_mm` | `board.vias` → `via.diameter` | — |
| `min_clearance_mm` | pairwise track/track, track/pad on same layer | bounding-box pre-filter |

### Clearance check optimization (CONTEXT.md line 119)

Full pairwise clearance is O(n²). For v1, use bounding-box pre-filtering per layer. The codebase already has `shapely>=2.0` as a dependency (`pyproject.toml:30`) and `shapely.STRtree` is available for spatial indexing if needed. `PcbIR.extract_track_obstacles` shows the bounding-box-from-segments pattern (lines 978-986).

### `run_vendor_drc` signature (CONTEXT.md line 89)

```python
def run_vendor_drc(ir: PcbIR, profile: ManufacturerProfile) -> VendorDrcResult:
```

`passed = len([v for v in violations if v.severity == Severity.ERROR]) == 0` — mirror the `run_drc` passed logic at `erc_drc.py:439`.

### Serialization (RESEARCH RQ7)

The handler converts `VendorDrcResult` to a dict. Use `dataclasses.asdict()` but be aware it does NOT stringify nested non-JSON types. Since `VendorDrcResult` has no `Path` field (unlike `DrcResult.file_path`), `asdict()` works directly. If `Violation.items` contains coordinate floats, they serialize fine. Follow whatever the `query_connectivity` handler return shape is (plain dict).

---

## FILE 4 (CREATE): `tests/test_vendor_drc.py`

**Role:** Unit tests for the internal evaluator (`manufacturing/vendor_drc.py`).

### Closest analog: `tests/test_board_metadata_ops.py`

This is the closest test pattern — it tests a manufacturing-layer module by building a `PcbIR` from a minimal inline PCB string, then calling the function under test. The handler-invocation tests use the same `_build_ir` helper.

**Excerpt — `_build_ir` helper + inline PCB** (`test_board_metadata_ops.py:20-49`):
```python
def _create_pcb_with_title_block(tmpdir: Path) -> Path:
    pcb_path = tmpdir / "test_meta.kicad_pcb"
    content = '''(kicad_pcb (version 20241229) (generator "test")
      ...
    )
    '''
    pcb_path.write_text(content, encoding="utf-8")
    return pcb_path

def _build_ir(pcb_path: Path):
    from volta.parser.pcb_parser import parse_pcb
    from volta.ir.pcb_ir import PcbIR
    from volta.parser.uuid_extractor import extract_uuids
    result = parse_pcb(pcb_path)
    uuid_map = extract_uuids(result.raw_content, "pcb")
    return PcbIR(_parse_result=result, _uuid_map=uuid_map)
```

### The silent-pass failure mode test (RESEARCH "Validation risk")

The single most important test: construct a board with a deliberately violating feature (e.g. a 0.1mm trace checked against the `generic` profile's 0.2mm min) and assert the evaluator reports a violation. If this test passes, the evaluator actually detects violations (the whole point of the Option C pivot).

Suggested test cases:
- `test_track_below_min_width_violation` — 0.1mm trace vs generic 0.2mm → violation.
- `test_via_drill_below_min_violation` — 0.1mm drill vs generic 0.3mm → violation.
- `test_annular_ring_below_min_violation` — via diameter 0.4mm, drill 0.3mm → annular = 0.05mm < 0.15mm.
- `test_clean_board_passes` — all geometry at-or-above limits → `passed=True`, empty violations.
- `test_checks_run_lists_all_evaluated_checks`.

### Importing `run_vendor_drc`

```python
from volta.manufacturing.vendor_drc import run_vendor_drc, VendorDrcResult
from volta.dfm.profiles import load_profile
```

### IR-registry fixture

Include the autouse fixture from `test_board_metadata_ops.py:12-17` (`_clear_registry` before/after) to avoid cross-test IR registration leaks.

---

## FILE 5 (CREATE): `tests/test_drc_vendor_ops.py`

**Role:** Operation-level tests for the two new ops (`drc_vendor`, `list_vendor_drc_profiles`), exercising the handler registry + schema validation + (optionally) the full executor pipeline.

### Closest analog: `tests/test_connectivity_query.py`

This file tests query ops through both the handler registry and the full `OperationExecutor` pipeline, including read-only verification (file mtime unchanged). Mirror its structure.

**Excerpt — schema validation + executor pipeline + mtime check** (`test_connectivity_query.py:46-54, 283-298`):
```python
def test_net_stats_schema_valid(self):
    op = Operation.model_validate({
        "root": {
            "op_type": "query_connectivity",
            "target_file": "test.kicad_pcb",
            "query_type": "net_stats",
        }
    })
    assert op.root.query_type == "net_stats"

def test_file_mtime_unchanged_after_query(self, arduino_pcb_tmp):
    mtime_before = arduino_pcb_tmp.stat().st_mtime
    executor = _make_executor(arduino_pcb_tmp)
    op = Operation.model_validate({...})
    executor.execute(op)
    mtime_after = arduino_pcb_tmp.stat().st_mtime
    assert mtime_before == mtime_after, "Query must not modify file"
```

### Closest analog for handler-direct testing: `test_board_metadata_ops.py:52-63`

```python
from volta.ops.handlers.query import _QUERY_HANDLERS
handler = _QUERY_HANDLERS["read_board_metadata"]
result = handler(ReadBoardMetadataOp(target_file="test_meta.kicad_pcb"), ir, pcb_path)
```

Apply this to `drc_vendor` and `list_vendor_drc_profiles`.

### Suggested test cases

**`drc_vendor`:**
- `test_drc_vendor_schema_valid` — `Operation.model_validate` with `op_type: "drc_vendor"`, `vendor: "generic"`.
- `test_drc_vendor_detects_violation` — violating board + generic profile → result with `passed=False` and non-empty violations (ties into the silent-pass guard).
- `test_drc_vendor_clean_board_passes` — clean board → `passed=True`.
- `test_drc_vendor_unknown_vendor_raises` — `vendor: "nonexistent"` → ValueError listing available vendors.
- `test_drc_vendor_run_kicad_drc_flag` — when `run_kicad_drc=True`, result includes KiCad DRC violations too (skip if kicad-cli absent, like `test_board_metadata_ops.py:158-177`).

**`list_vendor_drc_profiles`:**
- `test_list_profiles_returns_9` — `result["count"] == 9`, each entry has all required fields.
- `test_list_profiles_schema_valid` — `Operation.model_validate` with `op_type: "list_vendor_drc_profiles"`.
- `test_list_profiles_ignores_ir` — the handler returns profiles even when `ir` is a dummy; `target_file` is required by dispatch but unused by the handler body.

### Fixtures

Reuse the `arduino_pcb_tmp` fixture pattern from `test_connectivity_query.py:29-36` (copy Arduino_Mega fixture to tmpdir) for executor-level tests. For handler-direct tests, use the inline-PCB `_build_ir` helper.

---

## FILE 6 (MODIFY): `src/volta/dfm/profiles.py`

**Role:** Add `drc_rules_path` field to `ManufacturerProfile`, update existing built-in profiles to reference DRU files, add new vendor profiles, correct annular-ring values (DRC-07).

### Change 1: Add `drc_rules_path` field (DRC-05)

Add to the `ManufacturerProfile` BaseModel (after `extra` field, line 54):

```python
drc_rules_path: Path | None = Field(default=None, description="Path to vendor .kicad_dru file")
```

`Path | None` is valid on Python 3.11+ (project targets 3.11 per `pyproject.toml:11,106`). Pydantic v2 validates `Path` natively. The field is optional (default `None`) so existing code that constructs `ManufacturerProfile` without it is unaffected.

**Imports:** `from pathlib import Path` is already present (profiles.py:14).

### Change 2: Wire up `drc_rules_path` on existing profiles + correct annular rings (DRC-07)

This creates a circular import risk: `profiles.py` would call `get_drc_profile_path()` from `manufacturing/drc_profiles/__init__.py`, but `manufacturing/__init__.py` does not import `profiles.py`, so the risk is low. HOWEVER, to be safe, use a **lazy import inside a module-level helper** or set `drc_rules_path` AFTER profile construction using a deferred pattern.

**Safest approach (avoid import cycle):** Set `drc_rules_path` as a post-construction assignment at module load time, after importing the resolver:

```python
from volta.manufacturing.drc_profiles import get_drc_profile_path

_JLCPCB_STANDARD = ManufacturerProfile(
    name="JLCPCB Standard 2-Layer",
    min_trace_width_mm=0.127,
    min_drill_mm=0.2,
    min_annular_ring_mm=0.15,   # DRC-07: was 0.1
    ...
)
_JLCPCB_STANDARD.drc_rules_path = get_drc_profile_path("jlcpcb")
```

Wait — `ManufacturerProfile` is a pydantic BaseModel, so frozen-style attribute assignment is NOT allowed by default. Pydantic v2 allows mutation unless `model_config = ConfigDict(frozen=True)`. Since `ManufacturerProfile` has no frozen config (verified — no `model_config` in the class), direct attribute assignment works. Alternatively, pass `drc_rules_path=...` into the constructor directly, which is cleaner:

```python
_JLCPCB_STANDARD = ManufacturerProfile(
    name="JLCPCB Standard 2-Layer",
    min_annular_ring_mm=0.15,   # DRC-07: was 0.1
    drc_rules_path=get_drc_profile_path("jlcpcb"),
    ...
)
```

**Import-cycle check:** `manufacturing/__init__.py` imports only from `board_spec.py`, NOT from `dfm/profiles.py`. And `manufacturing/drc_profiles/__init__.py` will import only stdlib + its own dataclasses, NOT `dfm/profiles.py`. So `dfm/profiles.py` importing `get_drc_profile_path` is safe. Put the import at the top of `profiles.py` after the existing imports.

### Change 3: Correct annular ring values (DRC-07)

- `_JLCPCB_STANDARD` (line 113): `min_annular_ring_mm=0.1` → `0.15`
- `_PCBWAY_STANDARD` (line 146): `min_annular_ring_mm=0.1` → `0.15`

Per RESEARCH RQ3, these vendors' actual published annular ring is 0.15mm. The current 0.1mm is more permissive than reality (would pass designs the vendor rejects).

### Change 4: Add new vendor profiles + `_PROFILES` entries (CONTEXT.md lines 79-81)

Add `advanced_circuits` and `aisler_2layer`..`aisler_8layer` to `_PROFILES` with appropriate limits from RESEARCH RQ3. Example for AISLER 2L (annular=0.2mm hard limit):

```python
_AISLER_2LAYER = ManufacturerProfile(
    name="AISLER 2-Layer",
    min_trace_width_mm=0.15,
    min_drill_mm=0.2,
    min_annular_ring_mm=0.2,   # AISLER hard limit (larger than JLC/PCBWay)
    min_clearance_mm=0.15,
    min_via_diameter_mm=0.4,
    max_board_dim_mm=500.0,
    supports_blind_vias=False,
    supports_castellated=False,
    drc_rules_path=get_drc_profile_path("aisler_2layer"),
)
```

Add to `_PROFILES` dict (line 181): `"advanced_circuits": _ADVANCED_CIRCUITS`, `"aisler_2layer": _AISLER_2LAYER`, ..., `"aisler_8layer": _AISLER_8LAYER`.

### Vendor key normalization (RESEARCH RQ5 note)

`_PROFILES` uses mixed conventions: `"jlcpcb-4layer"` (hyphen) vs `"osh_park"` (underscore). The new AISLER keys use underscores (`aisler_2layer`). The `drc_vendor` handler's `vendor` field should document valid keys, or `load_profile()` should normalize (accept both `aisler-2layer` and `aisler_2layer`). CONTEXT.md does not mandate normalization; simplest is to require exact key match and let the handler's ValueError list available keys (which `load_profile` already does at line 234).

---

## FILE 7 (MODIFY): `src/volta/ops/_schema_pcb.py`

**Role:** Define `DrcVendorOp` and `ListVendorDrcProfilesOp` Pydantic models.

### Closest analog for `DrcVendorOp`: `AnalyzeSplitPlaneOp` (`_schema_pcb.py:670-686`)

It's a read-only-ish PCB op with `target_file` + a few typed fields, no complex validators. `DrcVendorOp` is structurally identical: `target_file` + `vendor: str` + `run_kicad_drc: bool`.

**Excerpt — `AnalyzeSplitPlaneOp`** (`_schema_pcb.py:670-686`):
```python
class AnalyzeSplitPlaneOp(BaseModel):
    op_type: Literal["analyze_split_plane"] = "analyze_split_plane"
    target_file: TargetFile
    layer: str = Field(default="GND", min_length=1, max_length=64, description="Net name to analyze")
    min_gap_mm: float = Field(default=0.0, ge=0.0, description="Min gap mm to flag")
```

### `DrcVendorOp` (CONTEXT.md lines 125-131)

```python
class DrcVendorOp(BaseModel):
    """Run vendor-specific DRC checks against manufacturing limits."""
    op_type: Literal["drc_vendor"] = "drc_vendor"
    target_file: TargetFile
    vendor: str = Field(
        min_length=1, max_length=64,
        description="Vendor name (pcbway, jlcpcb, aisler_2layer, oshpark, advanced_circuits, generic)",
    )
    run_kicad_drc: bool = Field(
        default=True,
        description="Also run KiCad's built-in DRC alongside vendor checks",
    )
```

Add `vendor` validation: `min_length=1, max_length=64` (matches the safe-string conventions; do NOT apply `_validate_sexpr_safe_string` since vendor names are identifiers, not S-expression content — but consider a pattern validator like `^[a-z0-9_-]+$` for safety).

### `ListVendorDrcProfilesOp` (CONTEXT.md lines 143-148)

Closest analog: `ListDesignRulesOp` (`_schema_pcb.py:342-353`) — a read-only list op with just `target_file`.

```python
class ListVendorDrcProfilesOp(BaseModel):
    """List available vendor DRC profiles and their capabilities."""
    op_type: Literal["list_vendor_drc_profiles"] = "list_vendor_drc_profiles"
    target_file: TargetFile  # Required by execute_query dispatch, handler ignores ir
```

### Imports already present

`_schema_pcb.py:8-11` imports `TargetFile` and `_validate_sexpr_safe_string` from `volta.ops.schema`. `Literal`, `Optional`, `BaseModel`, `Field` are all imported (line 2-6). No new imports needed unless adding a pattern validator.

---

## FILE 8 (MODIFY): `src/volta/ops/schema.py`

**Role:** Add the 2 new Op classes to the `Operation` discriminated union + the import/re-export section + `__all__`.

### Three edits required (mirror exactly how Phase 205 ops were added)

**Edit A — add to the `_schema_pcb` import block** (schema.py:239-283). The existing import already pulls `ReadBoardMetadataOp`, `SetBoardMetadataOp`, `SetBoardRevisionOp`. Append the two new ones:

```python
from volta.ops._schema_pcb import (  # noqa: E402
    ...existing...
    ReadBoardMetadataOp,
    SetBoardMetadataOp,
    SetBoardRevisionOp,
    DrcVendorOp,                  # NEW
    ListVendorDrcProfilesOp,      # NEW
)
```

**Edit B — add to the `Operation.root` union** (schema.py:405-562). Add the two new ops to the `Annotated[... | ...]` union. Place them near the other Phase 205 / query ops for locality:

```python
    | ReadBoardMetadataOp
    | SetBoardMetadataOp
    | SetBoardRevisionOp
    | DrcVendorOp                 # NEW
    | ListVendorDrcProfilesOp,    # NEW  (note: comma because it's the last in the union)
    Field(discriminator="op_type"),
```

IMPORTANT: The last item in the union before `Field(...)` MUST have a trailing comma. Currently `SetBoardRevisionOp` is last (line 562) with a comma. If the new ops are appended after it, ensure the trailing comma is on the new last item.

**Edit C — add to `__all__`** (schema.py:577-778). Add under the "PCB ops" or a new "Vendor DRC ops" comment block:

```python
    # Phase 206 vendor DRC ops (DRC-01, DRC-08)
    "DrcVendorOp",
    "ListVendorDrcProfilesOp",
```

### Pitfall: the union is a single `Annotated[...]` expression

The union uses `|` between types. Adding new types is mechanical but error-prone (a missing `|` or misplaced comma breaks the whole schema). The `validate_registry_completeness()` test (registry.py:1517) will catch drift, but only at test time.

---

## FILE 9 (MODIFY): `src/volta/ops/registry.py`

**Role:** Add `_RAW_CATALOG` entries for the 2 new ops.

### Closest analog: `query_connectivity` and `read_board_metadata` entries

Both are `category: "query"`, `is_readonly: True`, `file_types: [".kicad_pcb"]`. The new ops match exactly.

**Excerpt — `query_connectivity` catalog entry** (registry.py:309-317):
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

**Excerpt — `read_board_metadata`** (registry.py:381-389):
```python
"read_board_metadata": {
    "category": "query",
    "description": "Read board metadata (title, date, rev, company, comments) from PCB",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```

### New entries to add

```python
"drc_vendor": {
    "category": "query",
    "description": "Run vendor-specific DRC checks against manufacturer manufacturing limits",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
"list_vendor_drc_profiles": {
    "category": "query",
    "description": "List available vendor DRC profiles and their manufacturing capabilities",
    "file_types": [".kicad_pcb"],
    "is_readonly": True,
    "scope": "single_file",
    "requires": [],
    "conflicts": [],
},
```

Add these before the closing `}` of `_RAW_CATALOG` (after the `auto_layout_sch` entry at line 1442). The dict comprehension at line 1445-1448 (`OpMeta(op_type=op_type, **data)`) automatically picks them up.

### Read-only correctness (CONTEXT.md line 133)

Both ops are correctly `is_readonly: True` — DRC reads the PCB and produces a report; it does not modify the file. This routes them through `execute_query` (executor.py:138-139), which skips Transaction wrapping and file writes.

---

## FILE 10 (MODIFY): `src/volta/ops/handlers/query.py`

**Role:** Add `drc_vendor` and `list_vendor_drc_profiles` handlers via `@register_query`.

### Closest analog: existing handlers in the same file

`query.py` has two handlers. The `read_board_metadata` handler (line 31-85) is the better analog because it does real work (parses title block, loads sidecar) vs `query_connectivity` which just delegates.

**Excerpt — handler registration + signature** (`query.py:25-29`):
```python
@register_query("query_connectivity")
def _handle_query_connectivity(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from volta.ops.connectivity_query import handle_connectivity_query
    return handle_connectivity_query(op, ir, file_path)
```

Handler signature is always `(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]`. Use **lazy imports** inside the handler body (the existing handlers do this — see `query.py:27, 41-45, 74`) to avoid import cycles at module load.

### `drc_vendor` handler (CONTEXT.md lines 135-140)

```python
@register_query("drc_vendor")
def _handle_drc_vendor(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from volta.dfm.profiles import load_profile
    from volta.manufacturing.vendor_drc import run_vendor_drc

    profile = load_profile(op.vendor)  # raises ValueError if unknown
    result = run_vendor_drc(ir, profile)

    kicad_drc_result = None
    if op.run_kicad_drc:
        from volta.validation.erc_drc import run_drc
        drc = run_drc(file_path)
        kicad_drc_result = {
            "passed": drc.passed,
            "violations": [dataclasses.asdict(v) for v in drc.violations],
        }

    from dataclasses import asdict
    out = asdict(result)
    out["kicad_drc"] = kicad_drc_result
    return out
```

**Serialization note (RESEARCH RQ7):** `asdict(result)` on `VendorDrcResult` recurses into `tuple[Violation, ...]` → `list[dict, ...]`, and `Violation.severity` (a `Severity(str, Enum)`) serializes as its string value. Since `VendorDrcResult` has no `Path` field, no manual stringification is needed (unlike `DrcResult.file_path`).

### `list_vendor_drc_profiles` handler (CONTEXT.md lines 152-154)

```python
@register_query("list_vendor_drc_profiles")
def _handle_list_vendor_drc_profiles(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from dataclasses import asdict
    from volta.manufacturing.drc_profiles import list_drc_profiles

    profiles = [asdict(p) for p in list_drc_profiles()]
    return {"profiles": profiles, "count": len(profiles)}
```

The handler ignores `ir` and `file_path` (CONTEXT.md line 149 accepts this trade-off — `execute_query` always builds a `PcbIR` before dispatching, so `target_file` is required by the schema even though unused).

### No change to `handlers/__init__.py` needed

`handlers/__init__.py:18` already imports `_QUERY_HANDLERS` and `register_query` from `.query`. The `@register_query` decorators on the new handlers execute at import time and populate the dict automatically. No merge step is needed (unlike `_PCB_HANDLERS` which merges sub-registries at lines 27-31).

---

## FILE 11 (MODIFY): `tests/test_registry.py`

**Role:** Update the count assertion 154 → 156.

### The single edit (test_registry.py:23-27)

```python
def test_registry_has_98_operations(self) -> None:
    # Phase 205-01: 154 ops ...
    assert len(OPERATION_REGISTRY) == 154   # ← change to 156
```

Change to:
```python
def test_registry_has_98_operations(self) -> None:
    # Phase 206: 156 ops (was 154 after Phase 205; +2: drc_vendor, list_vendor_drc_profiles).
    assert len(OPERATION_REGISTRY) == 156
```

### `validate_registry_completeness` — no change needed to the known-missing set

`test_validate_registry_completeness_passes` (line 29-47) has `_KNOWN_PREEXISTING_MISSING = {"add_design_note", "apply_floor_plan", "place_and_wire_power_units"}`. The two new ops must NOT appear in `missing_from_registry` — they will be in both schema and `_RAW_CATALOG`, so the test passes unchanged.

### `test_readonly_operations_count` (line 108-156) — UPDATE REQUIRED

This test asserts an EXACT set of readonly op types (`expected_readonly`, line 115-154). Both new ops are `is_readonly: True`. If this set is not updated, the test fails because `drc_vendor` and `list_vendor_drc_profiles` will be in `readonly_types` but not in `expected_readonly`.

Add to `expected_readonly` (alphabetically):
```python
    "drc_vendor",                    # NEW
    "list_vendor_drc_profiles",      # NEW
```

The count assertion `len(readonly) == len(expected_readonly)` (line 156) will then be 39 instead of 37.

### `test_pcb_ops` spot-check (line 101-106)

Optional: add `assert "drc_vendor" in op_types` and `assert "list_vendor_drc_profiles" in op_types` to confirm the new ops are discoverable via file-type query.

---

## FILE 12 (MODIFY): `pyproject.toml`

**Role:** Add `[tool.setuptools.package-data]` so `.kicad_dru` files survive `pip install` / wheel builds.

### CRITICAL — current state (RESEARCH RQ8)

`pyproject.toml` has NO `[tool.setuptools.package-data]` section, NO `include-package-data`, NO `MANIFEST.in`. Non-Python files in `src/volta/` are NOT included in built distributions. This will silently work in dev (editable install) and silently fail in production.

### The edit

Add after the `[tool.setuptools.packages.find]` block (line 90-91):

```toml
[tool.setuptools.package-data]
"volta.manufacturing.drc_profiles" = ["*.kicad_dru"]
```

This is the exact form RESEARCH RQ8 recommends. The package key must match the full dotted package path (`volta.manufacturing.drc_profiles`), and the glob `*.kicad_dru` matches all 9 DRU files.

### Verification

After this change, `pip install .` and `python -m build` will include the DRU files. A test should verify `get_drc_profile_path("pcbway").is_file()` returns True after install (the Nyquist gate criterion #2 from RESEARCH). Without the package-data entry, this test would pass in editable mode and fail in a fresh venv install.

### Alternative not needed

`include-package-data = true` (via `[tool.setuptools]`) would include ALL non-Python files tracked by version control, which is broader than needed. The explicit `package-data` entry is more precise and matches RESEARCH RQ8's recommendation.

---

## Integration order (recommended)

The files have dependencies. Implement in this order to keep the registry/schema in sync at each step:

1. **FILE 2** (`.kicad_dru` files) — pure data, no code dependencies.
2. **FILE 1** (`drc_profiles/__init__.py`) — depends on FILE 2 existing.
3. **FILE 12** (`pyproject.toml`) — depends on FILE 2 existing (package-data glob).
4. **FILE 6** (`dfm/profiles.py`) — depends on FILE 1 (`get_drc_profile_path`).
5. **FILE 3** (`vendor_drc.py`) — depends on FILE 6 (`ManufacturerProfile`).
6. **FILE 7** (`_schema_pcb.py`) — standalone (just Pydantic models).
7. **FILE 8** (`schema.py`) — depends on FILE 7.
8. **FILE 9** (`registry.py`) — depends on FILE 7 (op_type strings must match).
9. **FILE 10** (`handlers/query.py`) — depends on FILES 3, 6.
10. **FILE 11** (`test_registry.py`) — depends on FILES 8, 9 (count must match).
11. **FILES 4, 5** (tests) — depend on everything above.

FILES 7, 8, 9 must land together — adding an op to the schema union without a registry entry (or vice versa) breaks `validate_registry_completeness`.

---

## Key pitfalls (from CONTEXT + RESEARCH)

| # | Pitfall | Mitigation |
|---|---------|------------|
| 1 | Calling `kicad-cli --custom-rules` (does not exist) | Use internal evaluator (FILE 3). Never invoke kicad-cli with vendor rules. |
| 2 | Forgetting `package-data` in pyproject.toml | FILE 12 is mandatory; without it DRU files vanish from wheels. |
| 3 | Schema/registry drift (op in one but not the other) | Land FILES 7+8+9 together; `validate_registry_completeness` catches drift. |
| 4 | Silent-pass evaluator (reports no violations on a violating board) | FILE 4 must include a deliberately-violating board test. |
| 5 | Stale annular ring (0.1mm instead of 0.15mm for PCBWay/JLCPCB) | FILE 6 Change 3 corrects to 0.15mm per DRC-07. |
| 6 | `test_readonly_operations_count` exact-set assertion | FILE 11 must add both new ops to `expected_readonly`. |
| 7 | Import cycle: `profiles.py` ↔ `drc_profiles/__init__.py` | Verified safe — `drc_profiles/__init__.py` imports only stdlib. Use lazy import if any cycle appears. |
| 8 | `dataclasses.asdict()` not stringifying `Path` | `VendorDrcResult` has no `Path` field, so this is a non-issue. If merging `DrcResult` (which has `file_path: Path`), stringify manually. |
