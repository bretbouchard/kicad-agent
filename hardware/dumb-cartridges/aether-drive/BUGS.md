# Aether Drive — Bugs & Feature Requests

Created: 2026-06-06
Last updated: 2026-06-06

## Bugs

### BUG-001 — kicad-cli 10.0.1 can't read nightly format
**Severity:** CRITICAL — blocks all automated validation
**Status:** MITIGATED
**Description:** KiCad nightly builds produce .kicad_sch/.kicad_pcb files with a slightly different format than the stable 10.0.1 release. `kicad-cli sch erc` and `kicad-cli pcb drc` fail to parse these files, blocking automated ERC/DRC validation in CI.
**Impact:** Cannot validate schematics generated from nightly KiCad installations
**Reproduction:** Open any schematic from nightly KiCad, run `kicad-cli sch erc <file>` — parser error
**Mitigation:** Created `cli_resolver.py` with nightly detection, version-aware CLI discovery, and stable/nightly fallback. Requires nightly KiCad to be installed for full resolution.

### BUG-002 — `generate_blocks_1_4.py` write() silently drops wires
**Severity:** CRITICAL
**Status:** NOT APPLICABLE — script does not exist in codebase
**Description:** The block generation script calls `write()` to serialize a SchematicIR but the wire S-expressions are silently omitted from output.
**Note:** The referenced `generate_blocks_1_4.py` script does not exist in the current codebase. This bug may have been resolved by deleting the script, or it was never created. Marking N/A.

### BUG-003 — `get_courtyard()` undefined variable `fp`
**Severity:** MEDIUM
**Status:** NOT APPLICABLE — function does not exist in codebase
**Description:** `get_courtyard()` in `ops/footprint_creation.py` references an undefined variable `fp`.
**Note:** No `ops/footprint_creation.py` file exists in the current codebase. The `get_courtyard()` function has been refactored away or was never created. Marking N/A.

### BUG-004 — A* router OOM on boards >80mm
**Severity:** MEDIUM
**Status:** FIXED
**Description:** The A* pathfinding router in `routing/pathfinder.py` allocates an O(n^2) adjacency matrix in memory. For boards larger than ~80mm with dense routing, this exceeds available memory and crashes with OOM.
**Impact:** Cannot auto-route large PCBs — only small boards (<80mm) are routable.
**Root Cause:** `_route_multi_pin_net()` made O(k^2) A* calls by trying every routed position for each unrouted pin.
**Fix:** Changed to nearest-neighbor heuristic — only routes from the closest already-routed position to each unrouted pin (O(k) A* calls). Falls back to checking all positions only if the nearest is blocked.

### BUG-005 — No post-generation wire count validation
**Severity:** MEDIUM
**Status:** FIXED
**Description:** After generating or modifying a schematic, there is no validation that the wire count matches expectations. Silent wire drops go undetected.
**Fix:** Created `validation/post_gen.py` with `validate_generated()` function that checks wire count, component count, net count, and flags suspicious patterns (e.g., 0 wires with multiple components). Integrated into generation pipeline as Step 7.

## Feature Requests

### FEAT-001 — Install Freerouting for auto-routing
**Priority:** HIGH
**Status:** IMPLEMENTED (infrastructure)
**Description:** Freerouting integration for production-quality PCB routing.
**Implementation:** Created `routing/freerouting.py` with:
- `export_dsn()` — Export PCB to Specctra DSN format
- `route_with_freerouting()` — Run Freerouting with auto-detection
- `import_ses()` — Import Freerouting results back to KiCad
- `is_freerouting_available()` — Check if Freerouting is installed
**Remaining:** Download Freerouting JAR to `~/.volta/tools/freerouting.jar` and set `FREEROUTING_JAR` env var.

### FEAT-002 — KiCad nightly CLI for validation/export
**Priority:** HIGH
**Status:** IMPLEMENTED
**Description:** Support for KiCad nightly build CLI alongside stable 10.0.1.
**Implementation:** Created `cli_resolver.py` with:
- `find_kicad_cli()` — Platform-aware CLI discovery with nightly detection
- `find_nightly_cli()` — Explicit nightly CLI finder
- `find_stable_cli()` — Stable-only CLI finder with fallback warning
- `CliInfo` dataclass with version parsing and nightly detection
- Caching to avoid repeated PATH lookups
- All 3 duplicate `_find_kicad_cli()` functions consolidated to shared module

### FEAT-003 — Complete Gerber export (Edge.Cuts, silk, paste)
**Priority:** MEDIUM
**Status:** IMPLEMENTED
**Description:** Manufacturing-complete Gerber export with all required layers.
**Implementation:** Added to `export/gerber.py`:
- `ALL_MANUFACTURING_LAYERS` — Complete manufacturing layer set (copper + Edge.Cuts + silk + mask + paste)
- Layer presets: `COPPER_LAYERS_2/4`, `EDGE_CUTS`, `SILKSCREEN_LAYERS`, `SOLDERMASK_LAYERS`, `SOLDERPASTE_LAYERS`
- `export_manufacturing_package()` — One-call export with gerber + drill in organized output directory
- `ManufacturingPackage` dataclass with combined results

### FEAT-004 — BOM.md with complete LCSC codes
**Priority:** MEDIUM
**Status:** IMPLEMENTED
**Description:** BOM export with LCSC/JLCPCB part numbers for direct JLCPCB ordering.
**Implementation:** Added to `export/bom.py`:
- `enrich_with_lcsc()` — Extract LCSC codes from schematic fields, match to BOM entries
- `export_jlcpcb_bom()` — Export BOM in JLCPCB-compatible CSV format (Comment, Designator, Footprint, LCSC)
- `_extract_lcsc_from_schematic()` — Parse LCSC/JLCPCB fields from .kicad_sch
- Coverage reporting (fraction of components with LCSC codes)

### FEAT-005 — Post-generation validation pipeline
**Priority:** MEDIUM
**Status:** IMPLEMENTED
**Description:** Automated validation pipeline for generated schematics/PCBs.
**Implementation:** Created `validation/post_gen.py`:
- `validate_generated()` — Full post-generation validation with wire count, component count, net count, zero-wire detection
- Optional ERC/DRC integration
- `GenerationValidationResult` with structured issues (ERROR/WARNING/INFO)
- `format_validation_report()` — Human-readable report output
- Integrated into generation pipeline as Step 7 (after statistics collection)
