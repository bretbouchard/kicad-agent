# Phase 206: Vendor DRC Profiles - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning
**Source:** Derived from v7.0 ROADMAP.md + REQUIREMENTS.md + codebase pattern analysis + user directive ("maximum flexibility for users")

<domain>
## Phase Boundary

Phase 206 ships verified `.kicad_dru` files for 5+ PCB manufacturers and adds the ability to run DRC against a specific vendor's manufacturing limits as a pre-flight gate. This is independent of Phase 205 (can be worked in parallel) but feeds into Phase 208 (Handoff Package) which uses vendor DRC in its pre-handoff validation gate.

**What ships:**
- 8+ static `.kicad_dru` files in `src/kicad_agent/manufacturing/drc_profiles/` (PCBWay, JLCPCB, AISLER 2/4/6/8L, OSH Park, Advanced Circuits, generic) — shipped as reference artifacts for GUI use and as source of truth for numeric limits
- Source attribution header comments in each profile file (repo URL, license, last-verified date)
- `ManufacturerProfile` extended with `drc_rules_path: Path | None` field (DRC-05)
- **Internal vendor DRC evaluator** in `manufacturing/vendor_drc.py` — reads board geometry from `PcbIR` and checks against `ManufacturerProfile` numeric limits (track width, clearance, drill size, annular ring) in Python. Returns `DrcResult`-shaped structure with violations for any feature below vendor limits.
- `drc_vendor` operation: resolve vendor profile → run internal evaluator → return `VendorDrcResult`
- `list_vendor_drc_profiles` query operation: list available vendor profiles + their capabilities

**CRITICAL PIVOT (from RESEARCH RQ1):** `kicad-cli pcb drc --custom-rules` does NOT exist in KiCad 10. Verified empirically. The `drc_vendor` op uses **internal Python-based geometric evaluation** (Option C from research) instead of relying on kicad-cli to enforce vendor rules. The `.kicad_dru` files still ship for GUI use and as documentation, but the automated pre-flight gate is our own evaluator. This gives MORE flexibility than the CLI approach — we can check any vendor's limits without depending on KiCad's rule engine.

**What does NOT ship (later phases):**
- BOM/CPL profile-driven formatting (Phase 208)
- Handoff package validation gate using vendor DRC (Phase 208)
- CLI subcommands `drc-vendor` (Phase 209)
- MCP auto-exposure (Phase 209 — free, but not the focus)
- Vendor API adapters (Phase 210, DEFERRED)

</domain>

<decisions>
## Implementation Decisions

### DRU File Sourcing and Licensing (DRC-02, DRC-03, DRC-06, Pitfall 1, Pitfall 6)

**Sourcing strategy — pull from upstream where available, author from specs otherwise:**

| Vendor | Source | License | Approach |
|--------|--------|---------|----------|
| PCBWay | Cimos/KiCad-DesignRules (MIT) | MIT | Pull, verify annular ring = 0.15mm (DRC-07 — not the stale 0.25mm from 2023) |
| JLCPCB | Cimos/KiCad-DesignRules (MIT) | MIT | Pull from Cimos aggregator (cleanest source per Pitfall 6) |
| AISLER 2L | AislerHQ/aisler-support | No license | Author from published numeric specs (AISLER publishes their capabilities) |
| AISLER 4L | AislerHQ/aisler-support | No license | Author from published numeric specs |
| AISLER 6L | AislerHQ/aisler-support | No license | Author from published numeric specs |
| AISLER 8L | AislerHQ/aisler-support | No license | Author from published numeric specs |
| OSH Park | Published specs (oshpark.com) | N/A (data) | Author from published numeric specs |
| Advanced Circuits | Published specs (4pcb.com) | N/A (data) | Author from published numeric specs |
| Generic | Conservative defaults | N/A | Author conservative defaults for unknown vendors |

**Attribution headers (DRC-06):** Every `.kicad_dru` file starts with comment block:
```
# Source: {repo URL or "Authored from published specs"}
# License: {MIT | "No license — authored from published numeric specifications" | "N/A — data"}
# Last verified: {YYYY-MM-DD}
# Vendor: {vendor name}
# Capabilities: min track {X}mm, min clearance {Y}mm, min drill {Z}mm, min annular {W}mm
```

**Pitfall 1 prevention:** PCBWay annular ring updated to 0.15mm (current capability), NOT 0.25mm (stale 2023 value). Cross-check each profile against the vendor's current published capabilities page during implementation.

### .kicad_dru File Location and Package Structure

- **Directory:** `src/kicad_agent/manufacturing/drc_profiles/` (creates `drc_profiles/` subpackage under the `manufacturing/` package from Phase 205)
- **Files:** `pcbway.kicad_dru`, `jlcpcb.kicad_dru`, `aisler_2layer.kicad_dru`, `aisler_4layer.kicad_dru`, `aisler_6layer.kicad_dru`, `aisler_8layer.kicad_dru`, `oshpark.kicad_dru`, `advanced_circuits.kicad_dru`, `generic.kicad_dru`
- **Package init:** `manufacturing/drc_profiles/__init__.py` — exports `get_drc_profile_path(vendor: str) -> Path` and `list_drc_profiles() -> list[VendorDrcProfileInfo]`
- **Profile resolution:** `get_drc_profile_path(vendor)` resolves a vendor name string to the bundled `.kicad_dru` file path. Uses `importlib.resources` or `Path(__file__).parent / f"{vendor}.kicad_dru"` for bundled file access.

### ManufacturerProfile Extension (DRC-05)

- **Add to existing `dfm/profiles.py` `ManufacturerProfile`:**
  ```python
  drc_rules_path: Path | None = Field(default=None, description="Path to vendor .kicad_dru file")
  ```
- **Update existing built-in profiles** to reference their DRC rule files:
  - `_JLCPCB_STANDARD.drc_rules_path = get_drc_profile_path("jlcpcb")`
  - `_PCBWAY_STANDARD.drc_rules_path = get_drc_profile_path("pcbway")` (also update annular ring to 0.15mm per DRC-07)
  - `_OSH_PARK.drc_rules_path = get_drc_profile_path("oshpark")`
  - `_GENERIC_CONSERVATIVE.drc_rules_path = get_drc_profile_path("generic")`
- **Add new profiles** for vendors not yet in `_PROFILES`:
  - `advanced_circuits` → `ManufacturerProfile(name="Advanced Circuits", ..., drc_rules_path=get_drc_profile_path("advanced_circuits"))`
  - `aisler_2layer` through `aisler_8layer` → 4 new profiles with layer-appropriate constraints
- **`load_profile(name_or_path)` unchanged** — still resolves built-in keys or file paths. The `drc_rules_path` field just points to the bundled file.

### Internal Vendor DRC Evaluator (DRC-01) — REPLACES run_drc() extension

**CRITICAL:** `kicad-cli pcb drc --custom-rules` does NOT exist in KiCad 10 (verified empirically in RESEARCH RQ1). Instead of extending `run_drc()`, we build an **internal evaluator** that checks board geometry against vendor limits.

- **New file:** `src/kicad_agent/manufacturing/vendor_drc.py`
- **Function:** `run_vendor_drc(ir: PcbIR, profile: ManufacturerProfile) -> VendorDrcResult`
  - Walks `PcbIR` native board to extract actual geometry:
    - Track/segment widths from `NativeSegment.width`
    - Via drill sizes from `NativeVia.drill` and via diameter from `NativeVia.size`
    - Pad drill sizes from `NativePad.drill` (if through-hole)
    - Annular ring: computed as `(pad_or_via_diameter - drill) / 2`
    - Clearance: computed from pairwise distance between copper elements (tracks, pads) on the same layer — use existing spatial query infrastructure if available, or a simplified bounding-box check
  - Compares each dimension against `ManufacturerProfile` limits:
    - `min_trace_width_mm` → check all segments
    - `min_drill_mm` → check all via drills and pad drills
    - `min_annular_ring_mm` → check all vias and PTH pads
    - `min_clearance_mm` → check track-to-track, track-to-pad, pad-to-pad distances
    - `min_via_diameter_mm` → check all via diameters
  - Returns `VendorDrcResult` with violations for any feature below limits
- **Violation type:** Reuses existing `Violation` frozen dataclass from `validation/erc_drc.py`:
  - `type`: `"vendor_trace_width"`, `"vendor_drill_size"`, `"vendor_annular_ring"`, `"vendor_clearance"`, `"vendor_via_diameter"`
  - `severity`: `Severity.ERROR` (below min) or `Severity.WARNING` (at boundary)
  - `description`: human-readable, e.g. `"Track width 0.15mm below PCBWay minimum 0.20mm"`
  - `items`: list of dicts with coordinates, net name, actual value, required value
- **Result type:** `VendorDrcResult` frozen dataclass in `manufacturing/vendor_drc.py`:
  ```python
  @dataclass(frozen=True)
  class VendorDrcResult:
      vendor: str
      passed: bool
      violations: tuple[Violation, ...]
      profile_name: str
      checks_run: tuple[str, ...]  # which checks were evaluated
  ```
  - `passed = len(violations) == 0` (or only warnings)
- **Clearance check optimization:** Full pairwise clearance checking is O(n²). For Phase 206 v1, use a spatial index (existing `SpatialQueryEngine` if available, or `shapely.STRtree`) to avoid brute force. If no spatial index is available, limit to track-to-track and track-to-pad checks on the same layer with bounding-box pre-filtering.
- **Also run standard DRC:** The `drc_vendor` handler should ALSO run the standard `run_drc()` (KiCad's built-in DRC) alongside the vendor checks, so users get both KiCad's design rule violations AND vendor-specific manufacturing limit violations. Return both in the result.

### drc_vendor Operation (DRC-01, DRC-04)

- **Schema:** `DrcVendorOp` in `_schema_pcb.py`:
  ```python
  class DrcVendorOp(BaseModel):
      op_type: Literal["drc_vendor"] = "drc_vendor"
      target_file: TargetFile
      vendor: str = Field(description="Vendor name (pcbway, jlcpcb, aisler_2layer, oshpark, advanced_circuits, generic)")
      run_kicad_drc: bool = Field(default=True, description="Also run KiCad's built-in DRC alongside vendor checks")
  ```
- **Registry:** `is_readonly: True`, `category: "query"`, `file_types: [".kicad_pcb"]`
  - Rationale: DRC doesn't modify the PCB file — it reads it and produces a report. Read-only is correct.
- **Handler:** `@register_query("drc_vendor")` in `handlers/query.py`
  - Resolves vendor name → `ManufacturerProfile` via `load_profile(vendor)`
  - Calls `run_vendor_drc(ir, profile)` from `manufacturing/vendor_drc.py`
  - If `op.run_kicad_drc` is True, also calls `run_drc(pcb_path)` from `validation/erc_drc.py` and merges results
  - Returns serialized `VendorDrcResult` as dict
- **Vendor resolution:** If vendor name not found in `load_profile()`, raise `ValueError` listing available vendors.

### list_vendor_drc_profiles Operation (DRC-08)

- **Schema:** `ListVendorDrcProfilesOp` in `_schema_pcb.py`:
  ```python
  class ListVendorDrcProfilesOp(BaseModel):
      op_type: Literal["list_vendor_drc_profiles"] = "list_vendor_drc_profiles"
      target_file: TargetFile  # Required by execute_query dispatch, but handler ignores it
  ```
  - **Design decision:** The existing `execute_query` dispatch requires a `target_file` and builds a `PcbIR`. Rather than creating a new dispatch path (scope creep), we require a `target_file` (any `.kicad_pcb` file) but the handler ignores `ir` and just returns static profile data. This is the simplest approach that reuses existing infrastructure. The user provides their PCB file as context even though it's not parsed for profile listing.
  - **Alternative considered:** A new "meta query" dispatch path that doesn't require a file. Rejected — adds complexity for one op, violates YAGNI. The `target_file` requirement is a minor inconvenience, not a blocker.
- **Registry:** `is_readonly: True`, `category: "query"`, `file_types: [".kicad_pcb"]`
- **Handler:** `@register_query("list_vendor_drc_profiles")` in `handlers/query.py`
  - Calls `list_drc_profiles()` from `manufacturing/drc_profiles/__init__.py`
  - Returns `{"profiles": [...], "count": N}` where each profile entry has: `vendor`, `display_name`, `drc_rules_path`, `min_trace_width_mm`, `min_clearance_mm`, `min_drill_mm`, `min_annular_ring_mm`, `supports_blind_vias`, `supports_castellated`, `source`, `last_verified`

### VendorDrcProfileInfo Data Model

- **New dataclass in `manufacturing/drc_profiles/__init__.py`:**
  ```python
  @dataclass(frozen=True)
  class VendorDrcProfileInfo:
      vendor: str           # "pcbway", "jlcpcb", etc.
      display_name: str     # "PCBWay", "JLCPCB", etc.
      drc_rules_path: str   # relative path to .kicad_dru file
      min_trace_width_mm: float
      min_clearance_mm: float
      min_drill_mm: float
      min_annular_ring_mm: float
      supports_blind_vias: bool
      supports_castellated: bool
      source: str           # "Cimos/KiCad-DesignRules (MIT)" or "Authored from published specs"
      last_verified: str    # "2026-07-10"
  ```
- **`list_drc_profiles()`** returns `list[VendorDrcProfileInfo]` — one entry per bundled `.kicad_dru` file.
- **`get_drc_profile_path(vendor: str) -> Path`** resolves vendor name to file path. Raises `ValueError` if vendor not found, listing available vendors.

### Schema Union + Registry Parity (Integration Pitfalls IP-1, IP-2)

- Add `DrcVendorOp` and `ListVendorDrcProfilesOp` to the `Operation` discriminated union in `schema.py`
- Add `_RAW_CATALOG` entries for both ops in `registry.py`
- Import/re-export the 2 new Op classes in `schema.py`
- **Update `test_registry.py` count assertion** (currently `== 154` after Phase 205 → becomes `== 156` for +2 ops)
- **`validate_registry_completeness()` must pass**

### Handler Registry (Integration Pitfall IP-3)

- Both new handlers (`drc_vendor`, `list_vendor_drc_profiles`) go in `handlers/query.py` via `@register_query`
- No new handler module needed — both are query ops
- Both registries are already aggregated in `handlers/__init__.py`

### Claude's Discretion

- **AISLER layer variants:** The 4 AISLER profiles (2/4/6/8L) share most rules but differ in layer-specific constraints (min annular ring, min track width for inner vs outer layers). The exact numeric values come from AISLER's published specs — the researcher should verify current values during research.
- **Generic profile values:** Conservative defaults that work for most prototype-grade manufacturers. Use the most restrictive common values (0.2mm min track, 0.2mm min clearance, 0.3mm min drill, 0.15mm min annular ring).
- **Advanced Circuits values:** Their published specs are relatively standard (6/6mil trace/clearance, 0.15mm annular). Author from their capabilities page.
- **OSH Park values:** Their published specs are well-documented (6mil min track, 6mil min clearance, 0.20mm min drill, 13mil min annular). Author from oshpark.com specs page.
- **DrcResult serialization:** The handler returns the `DrcResult` as a dict. The frozen dataclass can be converted via `dataclasses.asdict()` or a custom `to_dict()` method. Follow whatever pattern the existing `query_connectivity` handler uses for its return shape.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Profile Model
- `src/kicad_agent/dfm/profiles.py` — `ManufacturerProfile` pydantic BaseModel (line 24), `_PROFILES` dict (line 181), `load_profile` function (line 200), `get_builtin_profiles` (line 190)

### DRC Runner (for standard DRC alongside vendor checks)
- `src/kicad_agent/validation/erc_drc.py` — `run_drc()` (line 322), `DrcResult` frozen dataclass (line 91), `Violation` frozen dataclass (line 47), `Severity` enum (line 39), `_parse_violations()` (line 137)

### PcbIR (for internal vendor DRC evaluator)
- `src/kicad_agent/ir/pcb_ir.py` — `PcbIR` class wrapping `NativeBoard`
- `src/kicad_agent/parser/pcb_native_types.py` — `NativeSegment` (width field), `NativeVia` (size, drill fields), `NativePad` (drill field), `NativeFootprint` (pads tuple)
- `src/kicad_agent/cli_resolver.py` — `find_kicad_cli()` (line 104), `CliInfo` frozen dataclass (line 31)

### Operation Patterns
- `src/kicad_agent/ops/_schema_query.py` — `QueryConnectivityOp` literal-discriminator pattern (line 41), `@model_validator` cross-field validation (line 69)
- `src/kicad_agent/ops/handlers/query.py` — `register_query` decorator (line 17), `_QUERY_HANDLERS` dict (line 14), handler signature `(op, ir, file_path) -> dict`
- `src/kicad_agent/ops/execution.py` — `execute_query` (line 193), `dispatch_query` (line 233) — read-only dispatch, no Transaction/write
- `src/kicad_agent/ops/registry.py` — `OpMeta` fields (line 17), `_RAW_CATALOG` (line 47), query op entry pattern (`query_connectivity` line 309)
- `src/kicad_agent/ops/schema.py` — `Operation` discriminated union, `TargetFile` validator, import/re-export section

### Test Patterns
- `tests/test_registry.py` — count assertion (currently `== 154` after Phase 205), `validate_registry_completeness`
- `tests/test_connectivity_query.py` — query op test pattern (read-only, no file mutation)

### Pitfalls
- `.planning/research/PITFALLS.md` — Pitfall 1 (stale DRC values), Pitfall 6 (profile licensing/attribution)

### Phase 205 (Prior Phase)
- `src/kicad_agent/manufacturing/__init__.py` — manufacturing package created
- `src/kicad_agent/manufacturing/board_spec.py` — BoardSpec model (sibling pattern for drc_profiles package)

</canonical_refs>

<specifics>
## Specific Ideas

- The `.kicad_dru` file format is S-expression based, similar to `.kicad_pcb`. Example structure:
  ```
  (version 1)
  (rule "Minimum track width"
    (constraint track_width (min 0.15mm))
    (layer "F.Cu")
  )
  (rule "Minimum clearance"
    (constraint clearance (min 0.15mm))
  )
  ```
- KiCad 10's `kicad-cli pcb drc --custom-rules <file>` flag runs DRC using the provided rules IN ADDITION TO the board's existing design rules. This means vendor-specific constraints are layered on top, not replacing the board's own rules.
- The Cimos/KiCad-DesignRules repo (https://github.com/Cimos/KiCad-DesignRules) is MIT-licensed and aggregates rules for multiple vendors. It's the cleanest source for PCBWay and JLCPCB.
- The AislerHQ/aisler-support repo has AISLER's rules but without a license. Since these are factual manufacturing capability numbers (not creative works), authoring from their published specs is legally safer than copying their files.
- PCBWay's current published annular ring is 0.15mm (not 0.25mm from the stale 2023 DRU file). This is Pitfall 1 — must be verified against PCBWay's current capabilities page.

</specifics>

<deferred>
## Deferred Ideas

- `drc_profile_validate` op that flags rules older than 12 months (mentioned in Pitfall 1 prevention, but not in the requirements — deferred to future)
- Vendor-specific DRC rule customization (user overrides vendor defaults) — future enhancement
- DRC profile auto-update from vendor websites — future, requires web scraping
- Integration with `IntelligentDrcAnalyzer` for fix suggestions on vendor DRC violations — Phase 208+ scope
- CLI subcommand `drc-vendor` — Phase 209 (Integration)
- MCP auto-exposure — Phase 209 (free via auto-generation, but not the focus of this phase)

</deferred>

---

*Phase: 206-vendor-drc-profiles*
*Context gathered: 2026-07-10 via user directive ("maximum flexibility") + codebase pattern analysis*
