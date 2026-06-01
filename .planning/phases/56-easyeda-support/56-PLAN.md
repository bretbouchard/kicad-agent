# Phase 56: EasyEDA Support

**Status:** PLANNING
**Requirements:** FORMAT-02
**Depends on:** Phase 55 (Abstract AST)
**Milestone:** v3.0

## Goal

Add EasyEDA as the first non-KiCad format supported through the Abstract AST layer. EasyEDA is the highest-value target for multi-format expansion because it has a well-documented public JSON format, deep JLCPCB/LCSC integration, and a large maker/professional user base that kicad-agent does not currently serve.

## Context

EasyEDA uses a JSON-based schematic/PCB format with publicly documented schema. Components are shape-based (rectangles with pins rather than KiCad's symbol+footprint model). Wire routing uses path arrays. Net names come from labels attached to wire junctions. The LCSC component library (built into EasyEDA) provides part numbers that map to JLCPCB assembly -- this is the single most requested integration from the JLCPCB-focused community.

The existing `EasyEdaClient` in `mcp/server.py` already wraps LCSC API calls for component search. Phase 56-02 builds on this existing integration to provide BOM export and component mapping.

## Architecture

```
EasyEDA JSON ──> EasyEdaParser ──> AbstractCircuit ──> EasyEdaWriter ──> EasyEDA JSON
                                      │
                                      ├──> KiCadAdapter ──> .kicad_sch  (cross-format)
                                      ├──> AltiumAdapter  ──> .SchDoc   (future)
                                      └──> EagleAdapter   ──> .sch      (future)
```

## Plans

### Plan 56-01: EasyEDA Parser + Writer (FORMAT-02)

**Goal:** Parse EasyEDA JSON into AbstractCircuit and write AbstractCircuit back to EasyEDA JSON.

**EasyEDA JSON structure:**
```json
{
  "head": { "docType": "1", "editorVersion": "6.5.x" },
  "canvas": "CA~1000~1000~...",
  "shape": [
    "LIB~0~356~package~lcsc_part~...~THAT4301~...",
    "W~100~200~300~200~...",
    "L~100~200~net_name~...",
    "J~300~200~..."
  ]
}
```

- Components: `LIB~` entries in shape array with LCSC part numbers
- Wires: `W~` entries with coordinate sequences
- Labels: `L~` entries with net names at positions
- Junctions: `J~` entries at wire intersections

**Classes:**
```python
class EasyEdaParser:
    def parse(self, json_path: str | Path) -> AbstractCircuit: ...

class EasyEdaWriter:
    def write(self, circuit: AbstractCircuit, output_path: str | Path) -> None: ...
```

**Tests:**
- Parse minimal EasyEDA JSON fixture -> verify AbstractCircuit fields
- Write AbstractCircuit -> verify valid EasyEDA JSON output
- Round-trip: EasyEDA -> Abstract -> EasyEDA -> compare structural equivalence
- LCSC part number preservation through round-trip

---

### Plan 56-02: EasyEDA API Integration (FORMAT-02, LCSC/JLCPCB)

**Goal:** Connect EasyEDA format support with LCSC component library and JLCPCB manufacturing.

**Features:**
1. LCSC component search via existing `EasyEdaClient`
2. JLCPCB BOM format export from AbstractCircuit
3. Component mapping: LCSC part -> KiCad symbol/footprint equivalents
4. EasyEDA project push/pull (if API is available and documented)

**Classes:**
```python
class LcscComponentMapper:
    def lcsc_to_kicad(self, lcsc_part: str) -> tuple[str, str]: ...  # (symbol, footprint)
    def kicad_to_lcsc(self, symbol: str, footprint: str) -> str: ...

class JlcpcbBomExporter:
    def export(self, circuit: AbstractCircuit, output_path: str | Path) -> None: ...
```

## Estimated Effort

- 56-01: ~5 hours (parser + writer + EasyEDA-specific quirks)
- 56-02: ~4 hours (API integration + BOM export + component mapping)
- Total: ~9 hours
