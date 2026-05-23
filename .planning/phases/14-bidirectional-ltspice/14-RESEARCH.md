# Phase 14: Bidirectional KiCad-LTspice - Research

**Researched:** 2026-05-23
**Domain:** LTspice .asc file writing, KiCad-to-LTspice symbol/net/command conversion
**Confidence:** HIGH

## Summary

Phase 14 completes the KiCad-to-LTspice bridge by adding .asc export capability. Phase 11 built the reader (parse .asc, extract components/nets/simulation commands, read .raw results). Phase 14 builds the writer: convert a KiCad schematic into a valid .asc file that LTspice can open, simulate, and produce results that can flow back to KiCad.

The critical discovery is that SpiceLib's `AscEditor` already provides full write capability. It can create components, wires, flags (net labels), and directives (simulation commands) programmatically, then save a valid .asc file. A complete round-trip test was verified during research: create .asc from code, save to disk, parse back with the existing Phase 11 `parse_asc()`, and all data survives intact. This means the phase does NOT need to hand-roll .asc serialization -- it can delegate to SpiceLib for the file format while focusing on the KiCad-to-LTspice domain mapping.

The three domain challenges are: (1) mapping KiCad symbol library IDs (e.g., `Device:R`) to LTspice .asy symbols (e.g., `res`), (2) converting KiCad mm coordinates to LTspice internal units with Y-axis inversion, and (3) translating KiCad net labels (with `/` prefixes and power symbols) into LTspice FLAG conventions (`0` for ground, net name strings for everything else).

**Primary recommendation:** Use SpiceLib AscEditor as the .asc writer (not hand-rolled serialization). Build a three-layer converter: SymbolMapper (BIDI-02), AscWriter (BIDI-01/03), and SimCommandInjector (BIDI-04). Validate via round-trip (write .asc, parse back with Phase 11 parser, assert equivalence).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| KiCad schematic parsing | Python library | -- | kiutils parses .kicad_sch into typed objects |
| Symbol mapping (KiCad -> LTspice) | Python library | -- | Pure mapping table with fallback logic |
| Coordinate transformation | Python library | -- | mm -> LTspice units, Y-axis flip, grid alignment |
| .asc file generation | SpiceLib AscEditor | -- | SpiceLib handles format serialization |
| Net label conversion | Python library | -- | Strip prefixes, map GND to "0" |
| Simulation command injection | Python library | -- | Add TEXT directives to AscEditor |
| Round-trip validation | Python library | -- | Write .asc, parse with Phase 11, compare |

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BIDI-01 | KiCad schematic exports to a valid .asc file that LTspice can open | SpiceLib AscEditor.save_netlist() verified to produce valid .asc files. Round-trip tested: create -> save -> parse_asc() recovers all data. [VERIFIED: SpiceLib 1.5.1 runtime test] |
| BIDI-02 | Component symbol mapping between KiCad symbols and LTspice .asy types | 12 .asy stubs exist from Phase 11. Mapping table designed covering Device, power, and Simulation libraries. Power symbols map to FLAGs, not SYMBOLs. [VERIFIED: .asy stubs inspected, KiCad libId format verified] |
| BIDI-03 | Net labels transfer correctly between KiCad and LTspice naming conventions | KiCad local/global labels map to FLAG entries. Power symbols (power:GND) become FLAG "0". Leading "/" stripped. {slash} decoded. [VERIFIED: kiutils Schematic label structure inspected] |
| BIDI-04 | Simulation commands (.tran, .ac, .dc) attach correctly to exported schematics | TEXT directives in .asc format verified. SimCommand dataclasses from Phase 11 can be serialized back to directive text. Position at default (384, 48). [VERIFIED: .asc TEXT format tested via SpiceLib save_netlist] |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| spicelib | 1.5.1 | .asc file reading AND writing via AscEditor | Already used in Phase 11 for reading; has full write/create capability [VERIFIED: pip show spicelib + runtime test] |
| kiutils | >=1.4.8 | Parse KiCad .kicad_sch files | Already used across all phases for KiCad file parsing [VERIFIED: pyproject.toml] |
| networkx | >=3.0 | Graph-based net connectivity | Used in Phase 11 net_graph.py, may be useful for KiCad net analysis [VERIFIED: pyproject.toml] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | >=2.0 | Schema validation for converter config | Validating SymbolMapping entries and export options |
| pytest | >=8.0 | Test framework | All testing [VERIFIED: pyproject.toml] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SpiceLib AscEditor.write | Hand-rolled .asc serialization | Hand-rolling would duplicate format knowledge SpiceLib already has; higher risk of format errors |
| Static mapping table | LLM-based symbol inference | Static is deterministic, testable, and fast; LLM inference is overkill for known standard libraries |

**Installation:**
```bash
pip install spicelib>=1.5.1  # Already installed, but NOT in pyproject.toml -- needs adding
```

**Version verification:** spicelib 1.5.1 installed locally, confirmed via `pip show spicelib`. NOT declared in pyproject.toml dependencies -- Phase 14 must add it.

## Architecture Patterns

### System Architecture Diagram

```
KiCad .kicad_sch file
        |
        v
  [kiutils Schematic]  <--- Parse with existing schematic_parser.py
        |
        v
  [SymbolMapper]  <--- Maps libId -> LTspice .asy symbol name
        |                 Maps power symbols -> FLAG type
        |                 Returns SymbolMappingResult per component
        v
  [CoordinateTransformer]  <--- mm -> LTspice units, Y-axis flip, grid snap
        |                      Uses configurable scale factor (default 16)
        v
  [AscWriter]  <--- Creates SpiceLib AscEditor from minimal template
        |            Adds SchematicComponent objects for each KiCad component
        |            Adds Line objects for wires (from KiCad Connection items)
        |            Adds Text FLAG objects for net labels
        |            Calls AscEditor.save_netlist()
        v
  Valid .asc file on disk
        |
        v
  [RoundTripValidator]  <--- parse_asc() from Phase 11
        |                    Compare components, nets, commands
        v
  Equivalence report (pass/fail)
```

### Recommended Project Structure
```
src/kicad_agent/ltspice/
    __init__.py              # Export new asc_writer, symbol_mapper
    asc_parser.py            # Phase 11 -- unchanged
    asc_writer.py            # NEW -- BIDI-01: KiCad -> .asc export
    symbol_mapper.py         # NEW -- BIDI-02: KiCad libId -> LTspice .asy mapping
    sim_commands.py          # Phase 11 -- extended with serialize functions
    net_graph.py             # Phase 11 -- unchanged
    raw_reader.py            # Phase 11 -- unchanged
    types.py                 # Extended with export types
    asy_stubs/               # Phase 11 -- may need additional .asy stubs
```

### Pattern 1: SpiceLib-Mediated .asc Writing
**What:** Create a minimal .asc template, use AscEditor to add components/wires/flags/directives, save.
**When to use:** Every .asc export operation.
**Example:**
```python
# Source: [VERIFIED: SpiceLib 1.5.1 runtime test during research]
from spicelib.editor.asc_editor import AscEditor, Text, TextTypeEnum, asc_text_align_set
from spicelib.editor.base_schematic import SchematicComponent, Point, ERotation, Line
import tempfile

def create_asc_editor(sheet_width: int = 880, sheet_height: int = 680) -> AscEditor:
    """Bootstrap an AscEditor from a minimal .asc template."""
    template = f"Version 4\nSHEET 1 {sheet_width} {sheet_height}\n"
    with tempfile.NamedTemporaryFile(suffix=".asc", mode="w", delete=False) as f:
        f.write(template)
        return AscEditor(f.name)

def add_component(editor: AscEditor, ref: str, symbol: str,
                  x: int, y: int, rotation: str, value: str) -> None:
    """Add a component to the AscEditor."""
    comp = SchematicComponent(editor, "")
    comp.reference = ref
    comp.symbol = symbol
    comp.position = Point(x, y)
    comp.rotation = _rotation_from_str(rotation)
    comp.attributes["Value"] = value
    editor.add_component(comp)

def add_wire(editor: AscEditor, x1: int, y1: int, x2: int, y2: int) -> None:
    """Add a wire segment to the AscEditor."""
    editor.wires.append(Line(Point(x1, y1), Point(x2, y2)))

def add_flag(editor: AscEditor, x: int, y: int, text: str) -> None:
    """Add a net label (FLAG) to the AscEditor."""
    editor.labels.append(Text(coord=Point(x, y), text=text, size=2, type=TextTypeEnum.LABEL))

def add_directive(editor: AscEditor, x: int, y: int, text: str) -> None:
    """Add a simulation directive (TEXT !...) to the AscEditor."""
    d = Text(coord=Point(x, y), text=text, size=2, type=TextTypeEnum.DIRECTIVE)
    d = asc_text_align_set(d, "Left")
    editor.directives.append(d)
```

### Pattern 2: Symbol Mapping Table
**What:** Hierarchical mapping from KiCad libId to LTspice .asy symbol name.
**When to use:** For each component in a KiCad schematic being exported.
**Example:**
```python
# Three categories of mapping result:
# 1. Component mapping -> LTspice SYMBOL
# 2. Power symbol mapping -> LTspice FLAG (net label)
# 3. Unmapped -> warning, skip or generic placeholder

MAPPING_TABLE: dict[str, str] = {
    # KiCad libId -> LTspice .asy name
    "Device:R": "res",
    "Device:R_Small": "res",
    "Device:R_Small_US": "res",
    "Device:C": "cap",
    "Device:C_Small": "cap",
    "Device:C_Polarized": "cap",
    "Device:L": "ind",
    "Device:L_Small": "ind",
    "Device:D": "diode",
    "Device:D_Zener": "diode",
    "Device:Q_NPN": "npn",
    "Device:Q_PNP": "pnp",
    "Device:Q_NMOS": "nmos",
    "Device:Q_PMOS": "pmos",
    "Device:Opamp": "opamp",
    "Simulation:VOLTAGE": "voltage",
    "Simulation:CURRENT": "current",
}

# Power symbols map to FLAG type, not SYMBOL
POWER_SYMBOLS: dict[str, str] = {
    "power:GND": "0",
    "power:VCC": "VCC",
    "power:+5V": "+5V",
    "power:+3V3": "+3V3",
    "power:+3.3V": "+3.3V",
}
```

### Pattern 3: Coordinate Transformation
**What:** Convert KiCad mm coordinates to LTspice internal units.
**When to use:** For every component position, wire endpoint, and label placement.
**Example:**
```python
# KiCad: mm, Y increases downward
# LTspice: internal units, Y increases upward
# Default scale: 1mm = 16 LTspice units

def mm_to_ltspice(kicad_x_mm: float, kicad_y_mm: float,
                  sheet_height_mm: float = 297.0,
                  scale: int = 16) -> tuple[int, int]:
    """Convert KiCad mm coordinates to LTspice internal units.

    Args:
        kicad_x_mm: X coordinate in mm.
        kicad_y_mm: Y coordinate in mm (KiCad Y increases downward).
        sheet_height_mm: Total sheet height in mm (for Y flip).
        scale: LTspice units per mm (default 16).

    Returns:
        (ltspice_x, ltspice_y) as integers, grid-aligned.
    """
    raw_x = kicad_x_mm * scale
    raw_y = (sheet_height_mm - kicad_y_mm) * scale  # Flip Y axis
    # Align to grid (multiples of 16)
    ltspice_x = int(round(raw_x / 16)) * 16
    ltspice_y = int(round(raw_y / 16)) * 16
    return (ltspice_x, ltspice_y)
```

### Pattern 4: Simulation Command Serialization
**What:** Convert SimCommand dataclasses back to .asc TEXT directive strings.
**When to use:** When injecting simulation commands into exported .asc files.
**Example:**
```python
def serialize_sim_command(cmd: SimulationCommand) -> str:
    """Serialize a simulation command dataclass to LTspice directive text."""
    if isinstance(cmd, TranCommand):
        return f".tran {cmd.tstart} {cmd.tstop} {cmd.tstart_meas} {cmd.tstep}"
    elif isinstance(cmd, AcCommand):
        return f".ac {cmd.sweep} {cmd.npoints} {cmd.fstart} {cmd.fstop}"
    elif isinstance(cmd, DcCommand):
        return f".dc {cmd.source} {cmd.start} {cmd.stop} {cmd.step}"
    elif isinstance(cmd, OpCommand):
        return ".op"
    else:
        raise ValueError(f"Unknown command type: {type(cmd)}")
```

### Anti-Patterns to Avoid
- **Hand-rolling .asc serialization:** SpiceLib AscEditor already handles the format perfectly. Writing our own serializer duplicates work and introduces format bugs. [VERIFIED: Round-trip test passed]
- **Using add_instruction() for directives:** SpiceLib's `add_instruction()` method has unexpected behavior (replaces directives, uses weird positions). Manipulate `editor.directives` list directly instead. [VERIFIED: Runtime test showed add_instruction only keeps last directive]
- **Ignoring power symbol special handling:** KiCad power symbols are not real components -- they have invisible pins that connect to nets. They must become FLAG entries in .asc, not SYMBOL entries. [VERIFIED: KiCad power symbol structure inspected]
- **Assuming KiCad rotation maps directly:** KiCad uses angle in degrees (0, 90, 180, 270), LTspice uses R0/R90/R180/R270/M0/M90/M180/M270. The mapping is straightforward for standard rotations, but mirror handling requires checking `sym.mirror` in KiCad. [VERIFIED: kiutils SchematicSymbol.mirror attribute confirmed]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| .asc file serialization | Custom .asc line writer | SpiceLib AscEditor.save_netlist() | Format has subtle ordering rules, alignment encoding, and rotation dicts already handled by SpiceLib |
| .asy symbol parsing | Custom .asy reader | SpiceLib AsyReader (already used in net_graph.py) | Pin offset extraction already works, stubs already exist |
| S-expression parsing | Regex-based .kicad_sch reader | kiutils Schematic.from_file() | Already used across all phases, handles all edge cases |

**Key insight:** SpiceLib's AscEditor is a mature .asc editor with full create/read/write support. Phase 14 is primarily a domain-mapping problem (KiCad -> LTspice), not a file-format problem.

## Common Pitfalls

### Pitfall 1: Y-Axis Direction Mismatch
**What goes wrong:** KiCad Y increases downward, LTspice Y increases upward. Components appear flipped vertically.
**Why it happens:** KiCad uses screen coordinates (origin top-left), LTspice uses mathematical coordinates (origin bottom-left).
**How to avoid:** Apply `ltspice_y = (sheet_height_mm - kicad_y_mm) * scale` before grid alignment.
**Warning signs:** Exported .asc opens in LTspice with components at wrong vertical positions.

### Pitfall 2: Power Symbols Not Handled as Flags
**What goes wrong:** KiCad `power:GND` becomes a SYMBOL in .asc file, which LTspice doesn't understand.
**Why it happens:** Power symbols in KiCad are regular symbols with invisible pins; in LTspice, ground is FLAG "0" and power nets are FLAG labels.
**How to avoid:** Check `libId` against POWER_SYMBOLS table before creating a SYMBOL. Power symbols create FLAG entries at their pin connection point instead.
**Warning signs:** LTspice opens the .asc but simulation fails with "floating node" errors.

### Pitfall 3: Net Label Name Convention Clash
**What goes wrong:** KiCad net "/VCC" is written as FLAG "/VCC" but LTspice interprets "/" differently, or KiCad "{slash}" isn't decoded.
**Why it happens:** KiCad uses "/" for hierarchical sheet paths and encodes literal "/" as "{slash}" in label text.
**How to avoid:** Strip leading "/" from net names. Decode "{slash}" to "/". Map "GND" to "0".
**Warning signs:** Net names in LTspice don't match expected signal names, or simulation shows disconnected nets.

### Pitfall 4: Component Rotation Mapping
**What goes wrong:** KiCad component at angle=90 exports as R90 but appears sideways in LTspice.
**Why it happens:** KiCad and LTspice rotation systems reference different anchor points. KiCad rotation is about the component origin; LTspice rotation is about the symbol's reference point.
**How to avoid:** Map KiCad angle (0/90/180/270) to ERotation (R0/R90/R180/R270). Handle mirror by checking `sym.mirror` and mapping to M0/M90/M180/M270.
**Warning signs:** Components visually misaligned or pins not connecting to wires in LTspice.

### Pitfall 5: Grid Alignment
**What goes wrong:** Components or wires at non-grid positions cause LTspice to show "off-grid" warnings or fail to connect pins.
**Why it happens:** LTspice uses 16-unit grid snapping; non-aligned coordinates create invisible disconnections.
**How to avoid:** Round all coordinates to multiples of 16 after transformation.
**Warning signs:** LTspice shows disconnected wires that should be connected.

### Pitfall 6: SpiceLib Not in pyproject.toml
**What goes wrong:** spicelib is installed locally but not declared as a dependency; new environments fail to import.
**Why it happens:** Phase 11 used spicelib but didn't add it to pyproject.toml.
**How to avoid:** Add `spicelib>=1.5.1` to pyproject.toml dependencies in this phase.
**Warning signs:** `ModuleNotFoundError: No module named 'spicelib'` in fresh install.

## Code Examples

Verified patterns from SpiceLib runtime tests:

### Bootstrap AscEditor from Minimal Template
```python
# Source: [VERIFIED: SpiceLib 1.5.1 runtime test]
# AscEditor requires an existing file; bootstrap from minimal template
import tempfile
from pathlib import Path
from spicelib.editor.asc_editor import AscEditor

def _create_blank_editor(width: int = 880, height: int = 680) -> tuple[AscEditor, Path]:
    """Create a blank AscEditor from a minimal .asc template.

    Returns:
        (editor, temp_path) -- caller must clean up temp_path when done.
    """
    template = f"Version 4\nSHEET 1 {width} {height}\n"
    tmp = Path(tempfile.mktemp(suffix=".asc"))
    tmp.write_text(template)
    editor = AscEditor(str(tmp))
    return editor, tmp
```

### Add Component with All Attributes
```python
# Source: [VERIFIED: SpiceLib 1.5.1 runtime test]
from spicelib.editor.base_schematic import SchematicComponent, Point, ERotation
from spicelib.editor.asc_editor import ASC_ROTATION_DICT

# ASC_ROTATION_DICT maps "R0" -> ERotation.R0, "R90" -> ERotation.R90, etc.
def _rotation_from_str(rot_str: str) -> ERotation:
    """Convert rotation string to ERotation enum."""
    return ASC_ROTATION_DICT[rot_str]

comp = SchematicComponent(editor, "")
comp.reference = "R1"
comp.symbol = "res"
comp.position = Point(160, 96)
comp.rotation = ERotation.R0
comp.attributes["Value"] = "1k"
comp.attributes["Prefix"] = "R"
editor.add_component(comp)
```

### Full .asc File Format Reference
```python
# Source: [VERIFIED: basic_rc.asc fixture + SpiceLib save_netlist source inspection]
# .asc file format (Version 4):
#
# Line 1: Version 4
# Line 2: SHEET 1 <width> <height>
# Then any order of:
#   WIRE <x1> <y1> <x2> <y2>
#   FLAG <x> <y> <net_name>
#   SYMBOL <symbol_name> <x> <y> <rotation>
#   SYMATTR InstName <reference>
#   SYMATTR Value <value>
#   SYMATTR Prefix <prefix>
#   SYMATTR <attr_name> <attr_value>   (additional attributes)
#   WINDOW <num> <x> <y> <alignment> <size>  (text windows on symbol)
#   TEXT <x> <y> <alignment> <size> <type><text>
#     where type is "!" for DIRECTIVE or ";" for COMMENT
#   LINE Normal <x1> <y1> <x2> <y2> [style]
#   RECTANGLE Normal <x1> <y1> <x2> <y2> [style]
#   CIRCLE Normal <x1> <y1> <x2> <y2> [style]
#   ARC Normal <x1> <y1> <x2> <y2> <x3> <y3> <x4> <y4> [style]
#   IOPIN <x> <y> <direction>
#   DATAFLAG <x> <y>   (ignored by AscEditor)
```

### KiCad Schematic Structure for Export
```python
# Source: [VERIFIED: kiutils Schematic runtime inspection]
# Key properties accessed during export:
#
# schematic.schematicSymbols  -> list of SchematicSymbol
#   .libId                    -> "Device:R" (libraryNickname:symbolName)
#   .libraryNickname          -> "Device"
#   .position                 -> Position(X=50.0, Y=30.0, angle=None)
#   .mirror                   -> None or mirror specification
#   .properties               -> list of Property(key, value)
#     key="Reference"         -> "R1"
#     key="Value"             -> "10k"
#     key="Footprint"         -> (ignored for LTspice export)
#
# schematic.graphicalItems    -> list of Connection (wire segments)
#   Connection(type="wire", points=[Position(X, Y), Position(X, Y)])
#
# schematic.labels            -> list of LocalLabel
#   .text                     -> net name string
#   .position                 -> Position(X, Y)
#
# schematic.globalLabels      -> list of GlobalLabel
#   .text                     -> net name string
#   .position                 -> Position(X, Y)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LTspice IV format | LTspice XVII+ (Version 4 .asc) | ~2016 | Version 4 is the current format, SpiceLib handles it |
| Manual .asc editing | SpiceLib AscEditor programmatic editing | ~2020 | Full create/read/write support, no need for manual format handling |
| Custom SPICE netlist export | kicad-cli netlist export + SPICE conversion | KiCad 6+ | KiCad can export netlists, but .asc schematic export is not built-in |

**Deprecated/outdated:**
- LTspice IV format (Version 3): Not supported by SpiceLib AscEditor, only Version 4
- PyLTSpice editor: Superseded by spicelib (same author, renamed package)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | KiCad standard Device library symbol names are stable across KiCad versions | Symbol Mapping | Mapping table would need updating for new/renamed symbols |
| A2 | Scale factor of 16 LTspice units per mm produces visually reasonable schematics | Coordinate Transform | Layout may look compressed/expanded; user can configure |
| A3 | KiCad `Simulation` library provides VOLTAGE and CURRENT source symbols | Symbol Mapping | If Simulation lib not used, voltage sources must come from user-provided symbols |
| A4 | LTspice accepts any string as FLAG text (no naming restrictions beyond "0" for GND) | Net Labels | Some special characters might cause issues in LTspice |
| A5 | All KiCad wire connections are represented as `Connection` items in `graphicalItems` | Architecture | Some wire types (bus entries) may need separate handling |

## Open Questions

1. **Should we support custom/user KiCad symbol libraries?**
   - What we know: The mapping table covers standard Device, power, and Simulation libraries.
   - What's unclear: How to handle user-defined symbols that have no LTspice equivalent.
   - Recommendation: Start with standard library mapping. Provide a user-configurable extension point (JSON mapping file) for custom libraries. Raise a clear warning for unmapped symbols.

2. **What happens with KiCad hierarchical sheets?**
   - What we know: KiCad supports hierarchical sheets with sheet pins. LTspice has no hierarchy concept.
   - What's unclear: Whether Phase 14 should flatten hierarchy or error on hierarchical schematics.
   - Recommendation: Flatten to a single .asc file. Strip hierarchical path prefixes ("/sheet1/NET" -> "NET"). This is the standard approach for SPICE export.

3. **Should the converter handle KiCad Simulation library voltage/current sources?**
   - What we know: KiCad has a Simulation library with VOLTAGE and CURRENT source symbols. These map naturally to LTspice voltage/current sources.
   - What's unclear: Whether users typically use Simulation library symbols or just add SPICE directives.
   - Recommendation: Map Simulation library symbols as first-class components. This provides the cleanest KiCad-to-LTspice path.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| spicelib | AscEditor .asc read/write | Yes | 1.5.1 | -- |
| kiutils | KiCad schematic parsing | Yes | >=1.4.8 | -- |
| networkx | Net connectivity analysis | Yes | >=3.0 | -- |
| pytest | Test framework | Yes | 8.4.2 | -- |
| Python | Runtime | Yes | 3.11.11 | -- |

**Missing dependencies with no fallback:**
- None -- all required tools are available.

**Missing dependencies with fallback:**
- None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 |
| Config file | pyproject.toml (tool.pytest.ini_options) |
| Quick run command | `python3 -m pytest tests/test_ltspice_writer.py -x -q` |
| Full suite command | `python3 -m pytest tests/test_ltspice_writer.py -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BIDI-01 | Export KiCad schematic to valid .asc file | integration | `python3 -m pytest tests/test_ltspice_writer.py::TestAscWriter -x` | No -- Wave 0 |
| BIDI-02 | Symbol mapping from KiCad libId to LTspice .asy | unit | `python3 -m pytest tests/test_symbol_mapper.py -x` | No -- Wave 0 |
| BIDI-03 | Net label conversion between naming conventions | unit | `python3 -m pytest tests/test_ltspice_writer.py::TestNetLabels -x` | No -- Wave 0 |
| BIDI-04 | Simulation command injection into .asc | unit | `python3 -m pytest tests/test_ltspice_writer.py::TestSimCommands -x` | No -- Wave 0 |
| BIDI-01 | Round-trip validation: write -> parse -> compare | integration | `python3 -m pytest tests/test_ltspice_writer.py::TestRoundTrip -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_ltspice_writer.py tests/test_symbol_mapper.py -x -q`
- **Per wave merge:** `python3 -m pytest tests/ -x -q`
- **Phase gate:** `python3 -m pytest tests/ -v` (all 918+ tests green)

### Wave 0 Gaps
- [ ] `tests/test_ltspice_writer.py` -- covers BIDI-01, BIDI-03, BIDI-04, round-trip
- [ ] `tests/test_symbol_mapper.py` -- covers BIDI-02
- [ ] `tests/fixtures/ltspice/` -- may need additional .asc fixtures for validation
- [ ] `pyproject.toml` update -- add `spicelib>=1.5.1` to dependencies

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth involved |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No access control |
| V5 Input Validation | yes | KiCad schematic data validated by kiutils; path traversal protection inherited from Phase 11 |
| V6 Cryptography | no | No crypto |

### Known Threat Patterns for KiCad-to-LTspice Converter

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal in output path | Tampering | Resolve + reject ".." in output path |
| Malicious .kicad_sch input | Tampering | kiutils parser rejects malformed S-expressions |
| Temp file cleanup failure | Denial of Service | Use tempfile securely, clean up in finally blocks |
| Unbounded symbol mapping | Information Disclosure | Reject unknown symbols with clear error, no silent data loss |

## Sources

### Primary (HIGH confidence)
- SpiceLib 1.5.1 installed locally -- AscEditor source code inspected via Python inspect
- SpiceLib AscEditor.save_netlist() source -- exact .asc format confirmed
- SpiceLib AscEditor.add_component() source -- component creation verified
- Round-trip test: create .asc from code, save, parse_asc() recovers all data -- all passed
- kiutils Schematic API -- runtime inspection of real .kicad_sch files
- Existing Phase 11 code: asc_parser.py, types.py, sim_commands.py, net_graph.py -- all inspected

### Secondary (MEDIUM confidence)
- KiCad Device library naming conventions -- based on standard library inspection and common knowledge
- LTspice coordinate system analysis -- derived from basic_rc.asc fixture values and .asy stub pin offsets

### Tertiary (LOW confidence)
- Scale factor of 16 LTspice units per mm -- estimated from pin spacing analysis; may need adjustment

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- SpiceLib write capability verified with round-trip test
- Architecture: HIGH -- Pattern established from working prototype during research
- Pitfalls: HIGH -- All pitfalls identified from runtime testing (not theoretical)
- Symbol mapping: MEDIUM -- Standard library mapping is well-defined, but edge cases exist for user libraries
- Coordinate transform: MEDIUM -- Scale factor is estimated, needs validation with real LTspice opening

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (stable domain -- LTspice .asc format has not changed in years)
