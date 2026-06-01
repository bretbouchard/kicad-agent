# Phase 58: Eagle + OpenWater

**Status:** PLANNING
**Requirements:** FORMAT-04
**Depends on:** Phase 55 (Abstract AST), specifically 55-02 (KiCad adapter proven)
**Milestone:** v3.0

## Goal

Add Autodesk Eagle XML format support and create the Format Registry that unifies all format adapters into a single discoverable system. Eagle is the second-most-common EDA format after KiCad in the maker/education space, and its XML format is fully documented by Autodesk.

The Format Registry is the capstone of the multi-format expansion: it provides auto-detection, unified CLI conversion, and a capability matrix that tells users exactly what each format supports.

## Context

Eagle uses well-documented XML files with `.sch` (schematic) and `.brd` (board) extensions. The format is human-readable and well-understood -- there are multiple open-source Eagle parsers (e.g., in KiCad's own importer). Eagle symbols use a gate-based model (one symbol can have multiple gates, each with a subset of pins), which differs from KiCad's single-symbol model but maps cleanly to Abstract AST.

OpenWater is an open-source EDA tool. If its format is accessible, a proof-of-concept adapter demonstrates the registry's extensibility -- adding a new format should require only a parser, a writer, and a registry entry.

## Architecture

```
                    FormatRegistry
                    ┌─────────────────────────────────────┐
                    │ detect_format(path) -> FormatType    │
                    │ get_parser(fmt) -> Parser            │
                    │ get_writer(fmt) -> Writer            │
                    │ capability_matrix() -> dict          │
                    └──────────┬──────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   EagleAdapter         KiCadAdapter         OpenWaterAdapter
   (58-01)              (55-02)              (58-02)
```

## Plans

### Plan 58-01: Eagle XML Parser + Writer (FORMAT-04)

**Goal:** Parse Eagle XML schematics into AbstractCircuit and write AbstractCircuit back to Eagle XML.

**Eagle XML structure (schematic):**
```xml
<eagle>
  <drawing>
    <schematic>
      <libraries>
        <library name="..."> <symbols> <symbol name="..."> <pins>... </symbol> </symbols> </library>
      </libraries>
      <parts>
        <part name="U1" library="..." deviceset="..." device="..." value="NE5532"/>
      </parts>
      <sheets>
        <sheet>
          <instances> <instance part="U1" gate="G$1" x="..." y="..."/> </instances>
          <nets>
            <net name="VCC" class="0">
              <segment> <wire x1="..." y1="..." x2="..." y2="..."/> <label .../> </segment>
            </net>
          </nets>
        </sheet>
      </sheets>
    </schematic>
  </drawing>
</eagle>
```

**Classes:**
```python
class EagleParser:
    def parse(self, eagle_path: str | Path) -> AbstractCircuit: ...

class EagleWriter:
    def write(self, circuit: AbstractCircuit, output_path: str | Path) -> None: ...
```

**Eagle-specific handling:**
- Gate-based symbols: map to AbstractComponent with all gates merged
- Package variants: capture in component properties dict
- Net segments + junctions: map to AbstractNet with wire segments
- Bus definitions: capture bus membership in net metadata

**Tests:**
- Parse minimal Eagle XML fixture -> verify AbstractCircuit
- Write AbstractCircuit -> verify valid Eagle XML
- Round-trip: Eagle -> Abstract -> Eagle -> compare structural equivalence
- Gate-based symbol handling (multi-gate components like NE5532 dual opamp)

---

### Plan 58-02: OpenWater + Format Registry (FORMAT-04, capstone)

**Goal:** Create the Format Registry that unifies all format adapters and add OpenWater as a proof-of-concept for registry extensibility.

**Format Registry:**
```python
class FormatRegistry:
    _adapters: dict[FormatType, FormatAdapter] = {}

    @classmethod
    def detect_format(cls, path: str | Path) -> FormatType: ...

    @classmethod
    def get_parser(cls, fmt: FormatType) -> type[BaseParser]: ...

    @classmethod
    def get_writer(cls, fmt: FormatType) -> type[BaseWriter]: ...

    @classmethod
    def capability_matrix(cls) -> dict[FormatType, FormatCapabilities]: ...

    @classmethod
    def register(cls, adapter: FormatAdapter) -> None: ...
```

**Format capabilities:**
```python
class FormatCapabilities(BaseModel):
    read: bool
    write: bool
    round_trip: bool
    schematic: bool
    pcb: bool
    hierarchy: bool        # Multi-sheet support
    component_libs: bool   # Library access
```

**Auto-detection logic:**
- `.kicad_sch` / `.kicad_pcb` -> KiCad (S-expression)
- `.json` with EasyEDA head.docType -> EasyEDA
- `.SchDoc` / `.PcbDoc` (OLE container) -> Altium
- `.sch` / `.brd` with XML header -> Eagle
- Fallback: content-based detection (magic bytes, XML root element)

**Unified CLI:**
```bash
kicad-agent convert --from eagle --to kicad input.sch output.kicad_sch
kicad-agent convert --from easyeda --to kicad project.json output.kicad_sch
kicad-agent convert --from altium --to kicad design.SchDoc output.kicad_sch
kicad-agent formats  # List supported formats and capabilities
```

**OpenWater proof-of-concept:**
- If OpenWater format is accessible: minimal parser that registers with FormatRegistry
- Purpose: prove that adding a new format requires only parser + writer + registry entry
- Tests: register OpenWater adapter, detect format, verify capability matrix update

## Estimated Effort

- 58-01: ~5 hours (Eagle parser + writer + XML handling)
- 58-02: ~4 hours (Format Registry + CLI + OpenWater PoC)
- Total: ~9 hours
