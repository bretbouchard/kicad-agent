# Phase 57: Altium Support

**Status:** PLANNING
**Requirements:** FORMAT-03
**Depends on:** Phase 55 (Abstract AST), specifically 55-02 (KiCad adapter proven)
**Milestone:** v3.0

## Goal

Add Altium Designer format support (SchDoc/PcbDoc) through the Abstract AST layer. Altium is the dominant enterprise EDA tool with the highest willingness-to-pay user base. Even read-only support (parse Altium -> AbstractCircuit -> KiCad migration) delivers significant value for users transitioning away from Altium.

## Context

Altium SchDoc/PcbDoc files are OLE compound documents (Microsoft Structured Storage) containing binary streams with S-expression-like sections. The format is not publicly documented by Altium, but the community has reverse-engineered significant portions. The `olefile` Python library provides OLE container access.

Altium's dominance in enterprise means:
- Many engineering teams have legacy Altium designs they want to migrate
- Altium COM API provides automation on Windows (secondary approach)
- Even partial read support (component extraction, netlist) enables migration workflows
- Writing Altium format is significantly harder than reading -- start read-only

## Architecture

```
.SchDoc (OLE) ──> olefile ──> binary streams ──> AltiumParser ──> AbstractCircuit
                                                                        │
                                        ┌───────────────────────────────┤
                                        │                               │
                              KiCadAdapter ──> .kicad_sch      AltiumWriter? (57-02)
```

## Plans

### Plan 57-01: Altium SchDoc Parser (FORMAT-03, read-only)

**Goal:** Parse Altium .SchDoc files into AbstractCircuit for read-only access and KiCad migration.

**Technical approach:**
1. Use `olefile` to open .SchDoc as OLE compound document
2. Extract the `FileHeader` stream (contains schematic records)
3. Parse binary record structure: record type headers + parameter blocks
4. Map Altium record types to Abstract AST models

**Altium record types to handle:**
- `Component` (Designator, Part Description, Lib Reference)
- `Pin` (Name, Number, Electrical type, Position)
- `Wire` (Start/End coordinates)
- `NetLabel` (Text, Position)
- `PowerObject` (Text, Style)
- `SheetSymbol` (hierarchical sheet references)

**Classes:**
```python
class AltiumParser:
    def parse(self, schdoc_path: str | Path) -> AbstractCircuit: ...

class AltiumSymbolMapper:
    def altium_to_abstract_pin_type(self, altium_electrical_type: int) -> PinType: ...
```

**Tests:**
- Parse minimal .SchDoc fixture -> verify AbstractCircuit extraction
- Pin type mapping table (Altium electrical type codes -> PinType enum)
- Component extraction with designator/value/lib_reference
- Net extraction from wires + net labels
- OLE container security validation

---

### Plan 57-02: Altium Writer + Round-Trip (FORMAT-03, feasibility-dependent)

**Goal:** Evaluate and (if feasible) implement Altium .SchDoc writing.

**Approach:**
1. Evaluate OLE compound document creation feasibility
2. If feasible: implement `AltiumWriter` class
3. If not feasible: enhance read support with more complete record coverage + build Altium-to-KiCad migration CLI tool

**Altium COM API bridge (optional, Windows-only):**
- Use `pywin32` to drive Altium via COM automation
- Enables round-trip on Windows without binary format reverse-engineering
- Consider as fallback if direct binary writing proves unreliable

**Deliverables:**
- Feasibility assessment document
- Enhanced read support (more record types, better error handling)
- Altium-to-KiCad migration tool (works regardless of write feasibility)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OLE binary format undocumented | Medium | High | Start with read-only, use community knowledge |
| Altium record format changes across versions | Medium | Medium | Version detection, test with multiple fixtures |
| Binary parsing security (malformed OLE) | Low | High | olefile handles malformed containers; add input validation |
| COM API only works on Windows | High | Low | Optional path; direct parsing is primary |

## Estimated Effort

- 57-01: ~6 hours (OLE parsing + binary record extraction + tests)
- 57-02: ~4-6 hours (feasibility study + enhanced read or basic write)
- Total: ~10-12 hours
