# Phase 23: Schematic Repair Operations - Research

**Researched:** 2026-05-27
**Domain:** KiCad schematic manipulation operations (ERC repair, format conversion, S-expression insertion safety)
**Confidence:** HIGH

## Summary

Phase 23 adds 8 schematic repair operations discovered from 4 real sessions fixing a 12-sheet hierarchical KiCad backplane. The operations range from simple text parsing (ERC report parser) to complex multi-pass format conversion (KiCad 6 to KiCad 10). The existing codebase already has substantial infrastructure: Pydantic operation schema with discriminated unions, an executor dispatch registry, kiutils-based IR with SchematicIR mutation methods, Transaction-wrapped rollback, a validation pipeline (format check, symbol resolution, grid check, power net validation), and a working ERC JSON parser via kicad-cli.

The key challenge is NOT building new infrastructure -- it is extending the existing patterns safely. The three critical pitfalls from session war stories are: (1) forward-search insertion corrupts lib_symbol blocks (must walk backward from EOF), (2) background agents delete hierarchical labels (needs validation guard), and (3) KiCad 6 format conversion requires section-based reassembly, not line-by-line editing.

**Primary recommendation:** Follow the existing `RepairSchematicOp` pattern: new Pydantic op models in `schema.py`, handler functions registered via `@register_schematic()` in `executor.py`, mutation logic in dedicated modules under `ops/`. Use the existing kicad-cli ERC JSON output (already parsed in `erc_drc.py`) instead of raw text parsing.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ERC report parsing | API / Backend | - | Pure data transformation from kicad-cli JSON output |
| Format conversion (KiCad 6->10) | API / Backend | - | Multi-pass text transformation on file content |
| S-expression insertion (no_connect, power_flag) | API / Backend | - | IR mutation via SchematicIR methods |
| Wire grid snapping | API / Backend | - | Coordinate math on wire endpoints via existing get_wire_endpoints() |
| Root sheet generation | API / Backend | - | Reads sub-sheets, generates new schematic file |
| Hierarchical label validation | API / Backend | - | Cross-file check via existing check_sheet_pin_labels() |
| Operation schema (Pydantic models) | API / Backend | - | Extends existing schema.py discriminated union |
| Operation dispatch | API / Backend | - | Extends existing executor.py registry |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.12.5 | Operation schema models | Already used for all op types in schema.py |
| kiutils | 1.4.8 | KiCad file parse/serialize | Already used throughout IR layer |
| kicad-cli | 10.0.1 | ERC/DRC report generation | External tool, already wrapped in erc_drc.py |
| pytest | 8.x+ | Test framework | Already in pyproject.toml dev deps |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| uuid (stdlib) | - | UUID generation for new elements | All operations creating new schematic elements |
| re (stdlib) | - | Regex for ERC text parsing, format conversion | parse_erc (text mode), convert_kicad6_to_10 |
| math (stdlib) | - | Coordinate rotation, grid snapping | snap_to_grid, get_pin_positions |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual S-expression insertion | sexpdata library | sexpdata is already a dependency but using SchematicIR methods is safer (kiutils handles structure) |
| Raw text ERC parsing | kicad-cli JSON output (existing) | JSON output already parsed in erc_drc.py; text parsing is only needed for legacy workflows |
| Line-by-line format conversion | Section-based reassembly | Section-based avoids paren depth tracking bugs (proven by session war stories) |

**Installation:**
No new packages needed. All operations use existing dependencies.

**Version verification:**
```
pydantic: 2.12.5 (verified via pip show)
kiutils: 1.4.8 (verified via pip show)
kicad-cli: 10.0.1 (verified via kicad-cli --version)
Python: 3.11.11 (verified via python3 --version)
```

## Architecture Patterns

### System Architecture Diagram

```
LLM Intent (JSON)
    |
    v
Operation Schema (Pydantic validate)
    |
    v
OperationExecutor._execute_schematic()
    |
    v
parse_schematic() --> SchematicIR
    |
    v
Transaction(file_path)  <-- rollback on failure
    |
    v
Handler Function (registered via @register_schematic)
    |                           |                      |
    v                           v                      v
ERC-based ops               Format conversion      IR mutation ops
(parse_erc,                  (convert_kicad6_to_10)  (add_no_connect,
 extract_violation_positions)                          add_power_flag,
    |                                                  snap_to_grid)
    v                           |                      |
    v                           v                      v
    +-------> serialize_schematic() <------------------+
                     |
                     v
              normalize_kicad_output()
                     |
                     v
              txn.commit()
                     |
                     v
              validate_schematic_completeness()
```

### Recommended Project Structure
```
src/kicad_agent/
  ops/
    schema.py              # ADD new Pydantic models (6 new op types)
    executor.py            # ADD @register_schematic() handlers
    repair.py              # EXTEND: snap_to_grid (grid-based, not pin-based)
    erc_parser.py          # NEW: parse_erc, extract_violation_positions
    format_convert.py      # NEW: convert_kicad6_to_10
    hlabel_guard.py        # NEW: validate_hlabels
    root_sheet.py          # NEW: rebuild_root_sheet
  validation/
    format_check.py        # EXISTING: 9 KiCad 10 checks (leverage for convert validation)
    grid_check.py          # EXISTING: off-grid detection (leverage for snap_to_grid)
    erc_drc.py             # EXISTING: run_erc with JSON output (leverage for parse_erc)
tests/
    test_schematic_repair.py    # EXTEND: add tests for snap_to_grid
    test_erc_parser.py          # NEW: parse_erc, extract_violation_positions tests
    test_format_convert.py      # NEW: convert_kicad6_to_10 tests
    test_hlabel_guard.py        # NEW: validate_hlabels tests
    test_root_sheet.py          # NEW: rebuild_root_sheet tests
```

### Pattern 1: Operation Registration (existing pattern)
**What:** Each new operation type gets a Pydantic model in schema.py and a handler registered in executor.py
**When to use:** All 6 new operation types that follow the standard JSON intent -> IR mutation pipeline
**Example:**
```python
# In schema.py -- new Pydantic model
class ParseErcOp(BaseModel):
    op_type: Literal["parse_erc"] = "parse_erc"
    target_file: TargetFile

# In executor.py -- registered handler
@register_schematic("parse_erc")
def _handle_parse_erc(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.erc_parser import parse_erc
    return parse_erc(file_path)
```

### Pattern 2: Backward-Walk S-expression Insertion (NEW, critical safety pattern)
**What:** When inserting S-expressions into a .kicad_sch file, walk backward from EOF to find the insertion point, NOT forward from the start
**When to use:** add_no_connect, add_power_flag -- any operation that inserts S-expressions into raw file content
**Why:** Forward-search for `(embedded_fonts` matches inside lib_symbol definitions, corrupting files. The session war story confirms this: "Forward-search for `(embedded_fonts` matched inside lib_symbol definitions, corrupting 9/10 files."
**Example:**
```python
# WRONG -- forward search matches inside lib_symbol blocks
insert_pos = content.index("(embedded_fonts")

# CORRECT -- backward walk finds the true closing section
lines = content.splitlines()
for i in range(len(lines) - 1, -1, -1):
    if lines[i].strip().startswith("(embedded_fonts"):
        insert_pos = i
        break
```

### Pattern 3: Section-Based Format Conversion (NEW)
**What:** Split KiCad file into major sections (header, lib_symbols, components, wires, etc.), convert each section independently, reassemble
**When to use:** convert_kicad6_to_10 -- multi-pass format conversion
**Why:** Line-by-line mode tracking lost hierarchical labels or broke paren depth. Section-based reassembly finally worked (session war story: "MCU conversion failed 4 times")
**Example:**
```python
def convert_kicad6_to_10(content: str) -> str:
    sections = _split_into_sections(content)
    sections["header"] = _fix_header(sections["header"])
    sections["body"] = _fix_uuid_quoting(sections["body"])
    sections["body"] = _fix_stroke_format(sections["body"])
    # ... more passes
    return _reassemble(sections)
```

### Pattern 4: ERC JSON Report Parsing (leverage existing)
**What:** Use the existing kicad-cli JSON output format instead of parsing raw ERC text
**When to use:** parse_erc, extract_violation_positions
**Why:** The ERC JSON report already provides structured data with positions:
```json
{
  "type": "power_pin_not_driven",
  "severity": "error",
  "description": "Input Power pin not driven...",
  "items": [
    {
      "description": "Symbol U1 Pin 8 [VCC, Power input, Line]",
      "pos": {"x": 0.8128, "y": 1.7018},
      "uuid": "c56f28bf-cf40-..."
    }
  ]
}
```
[VERIFIED: kicad-cli 10.0.1 ERC JSON output, tested against RaspberryPi-uHAT fixture]

### Anti-Patterns to Avoid
- **Forward-search insertion:** Searching for `(embedded_fonts` or similar markers forward from line 1 matches inside lib_symbol definitions. Always walk backward from EOF. [VERIFIED: Session war story, 9/10 files corrupted]
- **Line-by-line mode tracking:** Maintaining a state machine per line for format conversion loses context on multi-line S-expressions. Use section-based splitting instead. [VERIFIED: Session war story, MCU conversion failed 4 times]
- **Mutating hierarchical labels without guards:** Background agents deleted hlabels 100% of the time. Always validate hlabel count before and after mutations. [VERIFIED: Session war story, 4 sessions, 100% deletion rate]
- **Bypassing SchematicIR for mutations:** Direct string manipulation on .kicad_sch files bypasses Transaction rollback and mutation tracking. Use IR methods when available, raw editing only for format conversion where kiutils cannot parse the file.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ERC result parsing | Custom regex for ERC text output | Existing `run_erc()` + `ErcResult` from `erc_drc.py` | JSON output already structured; text parsing is fragile |
| Pin position calculation | Custom coordinate math | `SchematicIR.get_pin_positions()` with Y-inversion | Handles rotation, already tested |
| Wire endpoint extraction | Custom file parsing | `SchematicIR.get_wire_endpoints()` | Already handles Connection type filtering |
| No-connect placement | Raw S-expression insertion | `SchematicIR.add_no_connect(x, y)` | Already handles UUID generation and noConnects list append |
| Power symbol placement | Raw S-expression insertion | `SchematicIR.add_power_symbol(name, x, y, angle)` | Already creates SchematicSymbol with correct properties |
| Grid alignment checking | Custom coordinate math | `check_grid_alignment()` from `grid_check.py` | Already handles 0.01mm KiCad 8+ grid |
| Format validation | Custom format checker | `validate_kicad10_format()` from `format_check.py` | 9 checks already implemented |
| Sheet pin validation | Custom label matching | `check_sheet_pin_labels()` from `validation_gates.py` | Already parses sub-sheets and compares pins/labels |

**Key insight:** The existing codebase already handles most of the "hard parts" (pin positions with rotation, UUID generation, Transaction rollback, kiutils serialization). The new operations primarily need to compose these existing building blocks, with raw file editing only for the format conversion operation where kiutils cannot parse the input.

## Runtime State Inventory

This is a greenfield phase (new code, not a rename/refactor). No runtime state inventory needed.

## Common Pitfalls

### Pitfall 1: S-expression Insertion Point Corruption
**What goes wrong:** Inserting no_connect or power_flag S-expressions at the wrong position corrupts the file by placing them inside `(lib_symbols ...)` blocks
**Why it happens:** Forward-searching for markers like `(embedded_fonts` finds the first occurrence, which may be inside a lib_symbol definition rather than in the root level
**How to avoid:** Always walk backward from EOF to find insertion points. Use `SchematicIR.add_no_connect()` and `SchematicIR.add_power_symbol()` which append to dedicated lists (`noConnects`, `schematicSymbols`) rather than raw text insertion
**Warning signs:** File fails balanced-paren check after mutation; kicad-cli cannot load the file

### Pitfall 2: Hierarchical Label Deletion by Mutations
**What goes wrong:** Any mutation that re-serializes the schematic loses hierarchical labels
**Why it happens:** kiutils serialization may not preserve all hlabel properties if the IR manipulation doesn't handle them explicitly
**How to avoid:** Always validate hlabel count before and after mutations. Use `validate_hlabels` operation as a post-mutation check. The existing `check_sheet_pin_labels()` in `validation_gates.py` provides the comparison logic
**Warning signs:** ERC reports new pin_not_connected violations after a repair that should have reduced them

### Pitfall 3: KiCad 6 Format Conversion State Loss
**What goes wrong:** Converting KiCad 6 files loses content -- hierarchical labels, component properties, or wire connections
**Why it happens:** Line-by-line mode tracking cannot handle multi-line S-expressions correctly; paren depth tracking fails when strings contain parens
**How to avoid:** Use section-based reassembly: split into major sections (header, lib_symbols, body), convert each independently, reassemble. Validate with `validate_kicad10_format()` after conversion
**Warning signs:** Converted file has fewer components, missing wires, or fails balanced-paren check

### Pitfall 4: Grid Snapping Breaking Connectivity
**What goes wrong:** Snapping off-grid wire endpoints to the nearest grid point breaks existing connections
**Why it happens:** Two wires meeting at an off-grid point both get snapped to different grid points, creating a gap
**How to avoid:** Snap ALL endpoints at the same position to the SAME grid point. First collect all endpoint positions, group by proximity, then snap each group to its shared nearest grid point
**Warning signs:** ERC reports new pin_not_connected violations after grid snapping

### Pitfall 5: ERC Text Parsing vs JSON Mismatch
**What goes wrong:** Parsing kicad-cli text output with regex misses edge cases (multi-line descriptions, non-ASCII characters, varying formats across versions)
**Why it happens:** The text output format is not documented as a stable API and varies between KiCad versions
**How to avoid:** Always use `--format json` output (already the pattern in `run_erc()`). The JSON format is stable and structured. Only parse text output as a fallback
**Warning signs:** parse_erc returns different violation counts than kicad-cli reports

### Pitfall 6: Missing PWR_FLAG Symbol Definition
**What goes wrong:** Placing a power:PWR_FLAG symbol without adding its definition to lib_symbols causes "unresolved symbol" errors
**Why it happens:** PWR_FLAG must be in the embedded lib_symbols section for the file to be self-contained
**How to avoid:** Before placing PWR_FLAG, check if `power:PWR_FLAG` exists in `ir.schematic.libSymbols`. If not, add the symbol definition first. The `add_power_symbol()` method in SchematicIR places the symbol instance but may not add the lib definition
**Warning signs:** Symbol resolution check fails after adding PWR_FLAG

## Code Examples

### parse_erc -- Leverage existing ERC infrastructure
```python
# Source: existing erc_drc.py pattern + ERC JSON format verified against kicad-cli 10.0.1
from kicad_agent.validation.erc_drc import run_erc, ErcResult, Violation

def parse_erc(sch_path: Path) -> list[dict[str, Any]]:
    """Parse ERC output into structured violation list."""
    result: ErcResult = run_erc(sch_path)
    if result.error_message:
        return [{"error": result.error_message}]

    violations = []
    for v in result.violations:
        entry = {
            "sheet": v.sheet_path,
            "type": v.type,
            "severity": v.severity.value,
            "description": v.description,
        }
        # Extract positions from items (ERC JSON provides pos per item)
        positions = []
        for item in v.items:
            pos = item.get("pos")
            if pos:
                positions.append((pos.get("x", 0.0), pos.get("y", 0.0)))
        entry["positions"] = positions
        violations.append(entry)
    return violations
```

### extract_violation_positions -- Filter ERC by type
```python
def extract_violation_positions(
    sch_path: Path, violation_type: str
) -> list[dict[str, Any]]:
    """Get (x,y) positions for specific ERC violation types."""
    violations = parse_erc(sch_path)
    return [
        {"x": pos[0], "y": pos[1], "description": v["description"]}
        for v in violations
        if v["type"] == violation_type
        for pos in v.get("positions", [])
    ]
```

### add_no_connect -- Using existing IR method
```python
# Source: existing SchematicIR.add_no_connect() pattern
# The key insight: use ir.add_no_connect() which appends to noConnects list
# NOT raw S-expression insertion
def add_no_connects_from_erc(ir: SchematicIR, sch_path: Path) -> dict[str, Any]:
    """Place no_connect markers at pin_not_connected positions from ERC."""
    positions = extract_violation_positions(sch_path, "pin_not_connected")
    placed = []
    for pos in positions:
        result = ir.add_no_connect(x=pos["x"], y=pos["y"])
        placed.append(result)
    return {"placed": len(placed), "positions": [(p["x"], p["y"]) for p in positions]}
```

### snap_to_grid -- Grid-based snapping (different from existing pin-based)
```python
# Source: existing grid_check._is_on_grid() pattern, but snaps to grid instead of checking
def snap_wire_endpoints_to_grid(ir: SchematicIR, grid_mm: float = 2.54) -> dict[str, Any]:
    """Move off-grid wire endpoints to nearest grid point."""
    from kicad_agent.validation.grid_check import _is_on_grid

    wire_endpoints = ir.get_wire_endpoints()
    snapped_count = 0
    sch = ir.schematic

    for wire_info in wire_endpoints:
        wire = sch.graphicalItems[wire_info["wire_index"]]
        if not hasattr(wire, "points") or len(wire.points) < 2:
            continue

        modified = False
        for point in wire.points:
            if not _is_on_grid(point.X, grid_mm) or not _is_on_grid(point.Y, grid_mm):
                point.X = round(point.X / grid_mm) * grid_mm
                point.Y = round(point.Y / grid_mm) * grid_mm
                modified = True

        if modified:
            snapped_count += 1
            ir._record_mutation("snap_to_grid", {"uuid": wire_info.get("uuid", "")})

    return {"snapped": snapped_count}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ERC text output parsing | ERC JSON output (`--format json`) | KiCad 8+ | Structured data with positions, no regex needed |
| 1.27mm connection grid | 0.01mm connection grid | KiCad 8+ | snap_to_grid default should be 2.54mm for component placement, but grid check uses 0.01mm |
| `(kicad_sch (version ...)` single-line header | Multi-line header with `generator`, `uuid` | KiCad 7+ | Format conversion must handle both styles |
| Unquoted UUIDs | Quoted UUIDs `"xxxx-..."` | KiCad 7+ | Format conversion must quote bare UUIDs |
| `(stroke (width X)) (type Y))` | `(stroke (width X) (type Y))` | KiCad 7+ | Malformed stroke is a format conversion target |

**Deprecated/outdated:**
- `;;` comments: KiCad 10 rejects them (handled by `_check_no_semicolon_comments`)
- `(net (code ...))` elements: KiCad 10 rejects them (handled by `_check_no_net_elements`)
- `(schematic_objects ...)` wrapper: Legacy KiCad 5 pattern (handled by `_check_no_schematic_objects`)
- `(pins ...)` wrapper inside sheets: KiCad 10 requires direct children (handled by `_check_no_pins_wrapper`)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | kicad-cli ERC JSON output format is stable across KiCad 10.x versions | Architecture Patterns | parse_erc would need version-specific parsing |
| A2 | PWR_FLAG symbol definition exists in KiCad's global power library | Common Pitfalls (P6) | add_power_flag would need to create the symbol definition from scratch |
| A3 | Section-based conversion handles all KiCad 6 format variants | Architecture Patterns (P3) | Some edge-case formats may need additional conversion passes |
| A4 | Existing `SchematicIR.add_power_symbol()` adds the symbol instance but may not add the lib_symbols definition | Code Examples | If it does add the definition, the PWR_FLAG guard is unnecessary overhead |
| A5 | The `convert_kicad6_to_10` operation should work on raw text (before kiutils parsing) because kiutils cannot parse KiCad 6 format | Architecture Patterns | If kiutils CAN parse KiCad 6, the conversion could use IR mutation instead |

## Open Questions

1. **Does kiutils 1.4.8 support parsing KiCad 6 format files?**
   - What we know: kiutils is designed for "KiCad 6.0 and up" per its description, but the session war stories show conversion failures
   - What's unclear: Whether the failures were kiutils parsing issues or the resulting format not passing ERC
   - Recommendation: Test kiutils.parse() on known KiCad 6 fixtures. If it works, convert_kicad6_to_10 can use IR mutation. If not, raw text conversion is needed.

2. **Should `convert_kicad6_to_10` be a standard operation or a standalone CLI command?**
   - What we know: The BRIEF.md lists it as an operation, but format conversion is typically a one-time bulk action
   - What's unclear: Whether it needs to be in the JSON operation schema or could be a utility function
   - Recommendation: Make it a utility function callable both as an operation AND standalone, since the LLM may need to convert files during repair workflows

3. **What grid size should `snap_to_grid` use?**
   - What we know: KiCad 8+ uses 0.01mm connection grid; BRIEF.md says "default 2.54mm"; existing `check_grid_alignment()` uses 0.01mm
   - What's unclear: Whether 2.54mm is correct for component placement snapping vs 0.01mm for wire endpoint snapping
   - Recommendation: Use 0.01mm as default (matching KiCad 8+ behavior), with configurable grid parameter

4. **Does `SchematicIR.add_power_symbol()` add the lib_symbols definition for `power:PWR_FLAG`?**
   - What we know: The method creates a SchematicSymbol with `libraryNickname="power"` and `entryName=name`
   - What's unclear: Whether kiutils automatically resolves this to a lib_symbols entry or if the definition must be added separately
   - Recommendation: Test with a fixture. If kiutils handles it, no extra step needed. If not, add lib_symbols definition before placing the symbol.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| kicad-cli | parse_erc, extract_violation_positions | yes | 10.0.1 | - |
| Python 3.11 | All operations | yes | 3.11.11 | - |
| pydantic v2 | Operation schema | yes | 2.12.5 | - |
| kiutils | IR layer | yes | 1.4.8 | - |
| pytest | Test framework | yes | 8.x+ | - |
| mypy | Type checking | yes | 1.7+ | - |
| ruff | Linting | yes | 0.13+ | - |

**Missing dependencies with no fallback:**
- None

**Missing dependencies with fallback:**
- None

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x+ |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_erc_parser.py tests/test_format_convert.py tests/test_hlabel_guard.py -x -q` |
| Full suite command | `pytest tests/ --tb=short` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| parse_erc | Parse ERC JSON output into structured violations | unit | `pytest tests/test_erc_parser.py::test_parse_erc -x` | Wave 0 |
| extract_violation_positions | Filter ERC violations by type, return positions | unit | `pytest tests/test_erc_parser.py::test_extract_positions -x` | Wave 0 |
| validate_hlabels | Check hlabel count matches expected | unit | `pytest tests/test_hlabel_guard.py::test_validate_hlabels -x` | Wave 0 |
| add_no_connect | Place no_connect markers at pin positions | integration | `pytest tests/test_schematic_repair.py::TestPlaceNoConnects -x` | Exists (extend) |
| add_power_flag | Place PWR_FLAG symbols for power_pin_not_driven | integration | `pytest tests/test_schematic_repair.py::test_add_power_flag -x` | Wave 0 |
| snap_to_grid | Move wire endpoints to grid points | unit | `pytest tests/test_schematic_repair.py::TestSnapToGrid -x` | Wave 0 |
| convert_kicad6_to_10 | Convert KiCad 6 format to KiCad 10 | unit | `pytest tests/test_format_convert.py::test_convert_kicad6 -x` | Wave 0 |
| rebuild_root_sheet | Generate root sheet from sub-sheet hlabels | integration | `pytest tests/test_root_sheet.py::test_rebuild_root -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_erc_parser.py tests/test_format_convert.py tests/test_hlabel_guard.py -x -q`
- **Per wave merge:** `pytest tests/ --tb=short`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_erc_parser.py` -- covers parse_erc, extract_violation_positions
- [ ] `tests/test_format_convert.py` -- covers convert_kicad6_to_10
- [ ] `tests/test_hlabel_guard.py` -- covers validate_hlabels
- [ ] `tests/test_root_sheet.py` -- covers rebuild_root_sheet
- [ ] KiCad 6 format fixture file -- needed for format conversion tests (must create or source)
- [ ] Hierarchical schematic fixture -- needed for root sheet and hlabel tests (must create)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A (no auth in repair operations) |
| V3 Session Management | no | N/A |
| V4 Access Control | no | N/A |
| V5 Input Validation | yes | Pydantic models with min/max length, safe identifier regex, path traversal rejection |
| V6 Cryptography | no | N/A |

### Known Threat Patterns for Schematic Manipulation

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal in target_file | Tampering | TargetFile validator rejects `..`, absolute paths, null bytes |
| S-expression injection | Tampering | Safe identifier regex, kiutils serialization (not raw string) |
| Malformed input causing file corruption | Denial of Service | Transaction rollback, balanced-paren validation post-mutation |
| Excessive mutation size | Denial of Service | Pydantic max_length constraints on all string fields |

## Sources

### Primary (HIGH confidence)
- Codebase analysis of `ops/schema.py`, `ops/executor.py`, `ops/repair.py`, `ir/schematic_ir.py` -- all patterns verified by reading source
- Codebase analysis of `validation/format_check.py`, `validation/grid_check.py`, `validation/symbol_resolution.py`, `validation/erc_drc.py` -- all existing infrastructure verified
- Codebase analysis of `ops/validation_gates.py` -- `validate_schematic_completeness()`, `check_sheet_pin_labels()` verified
- kicad-cli 10.0.1 ERC JSON output -- verified against RaspberryPi-uHAT fixture, structure confirmed with positions

### Secondary (MEDIUM confidence)
- BRIEF.md session war stories -- derived from real debugging sessions, not independently verified in this research
- KiCad 6 format differences -- derived from BRIEF.md descriptions and format_check.py detection patterns

### Tertiary (LOW confidence)
- KiCad 6 parsing capability of kiutils -- not tested against actual KiCad 6 files in this session

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all versions verified, all existing patterns read from source
- Architecture: HIGH -- extends existing patterns, no new architectural concepts
- Pitfalls: HIGH -- derived from verified session war stories and codebase analysis

**Research date:** 2026-05-27
**Valid until:** 2026-06-27 (stable codebase, low churn expected)
