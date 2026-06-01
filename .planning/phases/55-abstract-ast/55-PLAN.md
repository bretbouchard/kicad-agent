# Phase 55: Abstract AST (Format-Neutral Internal Representation)

**Status:** PLANNING
**Requirements:** FORMAT-01
**Depends on:** Phase 40 (ERC root cause -- validates circuit semantics understanding)
**Milestone:** v3.0

## Goal

Extract a format-agnostic circuit representation from kicad-agent's existing IR layer. The Abstract AST is the keystone that enables multi-format expansion: every new format (EasyEDA, Altium, Eagle) converts to and from this single representation, rather than requiring N-squared format-to-format adapters.

## Context

kicad-agent currently speaks only KiCad. The IR layer (`src/kicad_agent/ir/`) wraps kiutils objects with mutation tracking, but it is tightly coupled to KiCad's S-expression data model. The parser/serializer layer handles KiCad 5/6/10 format differences, but there is no format-neutral representation.

The LTSpice integration (`src/kicad_agent/ltspice/`) proved cross-format viability with `asc_parser.py` and `symbol_mapper.py`, but it directly maps LTSpice to KiCad rather than going through an intermediate representation. This approach does not scale to 4+ formats.

What is needed: a **Format-agnostic Abstract Syntax Tree** that captures circuit semantics (components, pins, nets, hierarchy) without any format-specific baggage. Every format adapter converts to Abstract AST on read and from Abstract AST on write. Operations (ERC, routing, BOM generation) work against Abstract AST, making them format-portable.

## Design Principles

1. **Lossless round-trip for supported fields.** KiCad to Abstract AST and back must preserve all circuit semantics that kicad-agent operations use.
2. **Pydantic models for validation.** Every Abstract AST node is a Pydantic model with strict validation. Invalid circuits fail at conversion time, not during operations.
3. **Pin-first connectivity.** Nets are defined by pin-pin connections (AbstractNet.pin_refs), not by wire geometry. Wire segments are optional visual data.
4. **Format adapters are isolated.** Each format (KiCad, EasyEDA, Altium, Eagle) gets its own adapter module. No format-specific logic leaks into Abstract AST models.

## Architecture

```
                    ┌──────────────────┐
                    │  AbstractCircuit  │
                    │  (format-neutral) │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────┴────┐  ┌─────┴─────┐  ┌─────┴─────┐
     │ KiCadAdapter│  │EasyEdaAdpt│  │EagleAdptr │  ...
     │ (55-02)     │  │ (56-01)   │  │ (58-01)   │
     └──────┬──────┘  └───────────┘  └───────────┘
            │
    ┌───────┴───────┐
    │ SchematicIR   │
    │ (existing)    │
    └───────────────┘
```

## Plans

### Plan 55-01: Abstract Circuit Model (FORMAT-01)

**Goal:** Define format-neutral Pydantic models for circuit representation with validation.

**Models:**
```python
class PinType(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    BIDI = "bidi"
    PASSIVE = "passive"
    POWER_IN = "power_in"
    POWER_OUT = "power_out"
    UNSPECIFIED = "unspecified"
    NO_CONNECT = "no_connect"

class AbstractPin(BaseModel):
    number: str
    name: str
    pin_type: PinType
    position: Optional[RelativePosition] = None  # Relative to component origin

class AbstractComponent(BaseModel):
    ref: str                                    # "U1", "R3"
    lib_id: str                                 # "THAT4301" or "Device:R"
    value: str                                  # "10k", "NE5532"
    footprint: Optional[str] = None             # "Package_DIP:DIP-8_W7.62mm"
    position: Optional[Position] = None         # Absolute on sheet
    rotation: float = 0.0
    pins: list[AbstractPin] = []
    properties: dict[str, str] = {}             # Format-specific extras

class WireSegment(BaseModel):
    start: Position
    end: Position

class AbstractNet(BaseModel):
    name: str
    pin_refs: list[tuple[str, str]]             # [(ref, pin_number), ...]
    wire_segments: list[WireSegment] = []
    labels: list[str] = []

class AbstractSheet(BaseModel):
    name: str
    file_path: Optional[str] = None
    components: list[AbstractComponent] = []
    nets: list[AbstractNet] = []
    hierarchical_labels: list[str] = []

class AbstractCircuit(BaseModel):
    name: str = ""
    components: list[AbstractComponent] = []
    nets: list[AbstractNet] = []
    sheets: list[AbstractSheet] = []
    metadata: dict[str, Any] = {}
```

**Validation rules:**
- Component references must be unique within a circuit/sheet
- Pin refs in nets must reference existing component pins
- Net pin_refs must not contain duplicates
- Pin numbers must be unique within a component

**Tests:**
- Schema validation for all models (valid/invalid cases)
- Unique ref validation
- Pin connectivity validation (no dangling pin refs)
- Net consistency (all referenced components/pins exist)
- Round-trip invariant: AbstractCircuit serialized and deserialized is identical

---

### Plan 55-02: KiCad Adapter (FORMAT-01, bidirectional)

**Goal:** Prove KiCad to Abstract AST round-trip with the existing IR layer.

**Classes:**
```python
class KiCadAdapter:
    @staticmethod
    def schematic_ir_to_abstract(ir: SchematicIR) -> AbstractCircuit:
        """Extract components, pins (from lib_symbols), nets (from wires + labels), sheets."""

    @staticmethod
    def abstract_to_schematic_ir(circuit: AbstractCircuit) -> SchematicIR:
        """Generate SchematicIR from AbstractCircuit (new file)."""
```

**Conversion details:**
- Components: SchematicSymbol -> AbstractComponent (ref, lib_id, value, footprint, position, rotation)
- Pins: Extract from lib_symbols pin definitions (not just stub instances)
- Nets: Derived from wire connectivity graph + labels (trace which pins share nets)
- Sheets: Hierarchical sheet instances become AbstractSheet entries
- Loss accounting: Document what IS preserved (all circuit semantics) and ISN'T (graphical elements, annotations)

**Tests:**
- Parse a real .kicad_sch -> AbstractCircuit -> verify component/net counts match
- Round-trip: KiCad -> Abstract -> KiCad -> compare S-expression equivalence
- Loss accounting test: known invariants survive round-trip

## Dependencies

- Phase 40 (ERC root cause) -- validates that kicad-agent understands circuit semantics deeply enough to define an abstract model
- The Abstract AST is a prerequisite for ALL multi-format work (phases 56-58)

## Estimated Effort

- 55-01: ~3 hours (model definition + validation + tests)
- 55-02: ~4 hours (KiCad adapter + round-trip testing)
- Total: ~7 hours
