# Phase 38: Schematic Routing Engine

**Status:** PLANNING
**Requirements:** SCH-ROUTE-01, SCH-ROUTE-02, SCH-ROUTE-03, SCH-ROUTE-04
**Depends on:** Phase 25 (remove operations), Phase 32 (executor batch), Phase 35 (remaining ops gaps)
**Context:** See `38-CONTEXT.md` for real-world pain points, test cases, and implementation notes from hands-on schematic wiring work.

## Goal

Give kicad-agent the ability to route schematic wires with the same intelligence as its PCB auto-router. Today, schematic wiring requires manual Python scripts — resolve pin positions, avoid collisions, generate wires and labels. After this phase, it should be: `connect_pins(file, "VCA_IN", [("R56", 2), ("U22", "VCA_IN")])`.

## Plans

### Plan 38-01: Pin Position Resolution (SCH-ROUTE-01)

**Goal:** Add `resolve_pin_positions` operation that returns absolute coordinates for every pin of any component.

**Schema:**
```python
class ResolvePinPositionsOp(OpBase):
    op_type: Literal["resolve_pin_positions"] = "resolve_pin_positions"
    target_file: TargetFile
    reference: str  # Component reference (e.g., "U21", "R55")
```

**Returns:**
```python
{
    "reference": "U21",
    "lib_id": "CD4066BE",
    "units": {
        "1": {"position": [69.85, 69.85], "rotation": 0, "pins": {"1": [62.23, 69.85], "2": [77.47, 69.85], "13": [69.85, 74.93]}},
        "5": {"position": [85.09, 69.85], "rotation": 0, "pins": {"7": [85.09, 77.47], "14": [85.09, 62.23]}}
    },
    "all_pins": {"1": [62.23, 69.85], "2": [77.47, 69.85], "7": [85.09, 77.47], "13": [69.85, 74.93], "14": [85.09, 62.23]},
    "named_pins": {}  # Only populated for symbols with named pins (e.g., THAT4301)
}
```

**Implementation steps:**
1. Parse `lib_symbols` section to extract pin offsets per unit per symbol
2. Parse symbol instances to get unit positions and rotations
3. Calculate absolute positions using rotation transform
4. Handle special cases:
   - Multi-unit symbols (units at different positions)
   - Named pins (THAT4301 style: `VCA_IN`, `EC_SPAN`)
   - Numbered pins (CD4066BE style: pin 1, 2, 13, 14)
   - R/C passives (Device:R, Device:C — pin 1 top, pin 2 bottom, ±3.81mm offset)
   - Rotation transforms (0°, 90°, 180°, 270°)
   - Power symbols (#PWR — single pin at placement position)

**Tests:**
- Unit test: known pin positions for CD4066BE multi-unit
- Unit test: named pins for THAT4301
- Unit test: R/C passive pin positions
- Unit test: rotated component pin positions
- Integration test: resolve all pins for compressor-stage schematic

---

### Plan 38-02: Collision Detection + Pin Overlap Detection (SCH-ROUTE-02)

**Goal:** Add `detect_routing_collisions` and `detect_pin_overlaps` operations.

**Schema:**
```python
class DetectRoutingCollisionsOp(OpBase):
    op_type: Literal["detect_routing_collisions"] = "detect_routing_collisions"
    target_file: TargetFile
    route_x_ranges: Optional[list[tuple[float, float]]] = None  # Auto-detect if not provided

class DetectPinOverlapsOp(OpBase):
    op_type: Literal["detect_pin_overlaps"] = "detect_pin_overlaps"
    target_file: TargetFile
```

**`detect_routing_collisions` returns:**
```python
{
    "collision_zones": [
        {
            "x_range": [95.0, 95.5],
            "pins_in_zone": [
                {"ref": "U22", "pin": "GND", "position": [95.25, 80.01]},
                {"ref": "U22", "pin": "OUTPUT", "position": [95.25, 77.47]},
                # ... 6 more
            ],
            "severity": "error",
            "note": "Vertical wire at x=95.25 would short 8 pins"
        }
    ],
    "safe_routes": 42,
    "blocked_routes": 8
}
```

**`detect_pin_overlaps` returns:**
```python
{
    "overlaps": [
        {
            "position": [59.69, 78.74],
            "pins": [
                {"ref": "R55", "pin": 2, "net": "to_switch"},
                {"ref": "R56", "pin": 1, "net": "COMP_BYPASS_SIG"}
            ],
            "same_net": false,
            "severity": "error"
        }
    ]
}
```

**Auto-detection algorithm for collision zones:**
1. Resolve all pin positions for all components
2. Group pins by x-coordinate (within 0.5mm tolerance)
3. For each x-column with 3+ pins, check if any vertical wire range would intersect multiple pins
4. Flag as collision zone if pins are from different nets

**Tests:**
- Unit test: U22 pin column detection (x=95.25, x=105.41)
- Unit test: R/C column overlap detection (x=59.69)
- Unit test: Pin overlap between adjacent R/C components
- Integration test: full collision map for compressor-stage

---

### Plan 38-03: `connect_pins` Operation (SCH-ROUTE-03)

**Goal:** The core primitive — connect a list of pins into a net with intelligent routing.

**Schema:**
```python
class ConnectPinsOp(OpBase):
    op_type: Literal["connect_pins"] = "connect_pins"
    target_file: TargetFile
    net_name: str
    pins: list[PinRef]  # [("R55", 2), ("U21", 1)] or [("U22", "VCA_IN")]
    strategy: Literal["wire_first", "label_only", "hybrid"] = "hybrid"
    label_size: float = 0.75
    max_wire_length: float = 40.0
    collision_zones: Optional[list[tuple[float, float]]] = None  # Auto-detect if not provided

class PinRef(BaseModel):
    reference: str
    pin: Union[int, str]  # pin number or pin name
```

**Strategy behavior:**
- `wire_first`: Try L-shaped wires first, fall back to labels for collision zones
- `label_only`: No wires, just net labels at every pin (most reliable)
- `hybrid`: Generate wires for short/clean routes, labels everywhere (recommended default)

**Wire routing algorithm:**
1. Resolve all pin positions
2. Detect collision zones (auto or provided)
3. For each pair of connected pins:
   a. If either endpoint is in a collision zone → label only
   b. If Manhattan distance > max_wire_length → label only
   c. If route passes through a collision zone → label only
   d. Otherwise → generate L-shaped wire (horizontal then vertical) + label at both endpoints
4. Always generate net labels at every pin position (belt + suspenders)

**Returns:**
```python
{
    "net_name": "COMP_IN",
    "pins_connected": 2,
    "wires_generated": 1,
    "labels_generated": 2,
    "routes_skipped": 0,
    "collisions_avoided": 0,
    "notes": []
}
```

**Tests:**
- Unit test: simple 2-pin connection (wire + labels)
- Unit test: multi-pin star topology
- Unit test: collision zone avoidance (U22 column)
- Unit test: label-only strategy
- Unit test: max_wire_length filter
- Integration test: connect all pins for a THAT4301 VCA circuit

---

### Plan 38-04: `batch_connect` + `regenerate_wiring` Operations (SCH-ROUTE-04)

**Goal:** High-level operations for full schematic wiring — batch net connection and complete rewire.

**Schema:**
```python
class BatchConnectOp(OpBase):
    op_type: Literal["batch_connect"] = "batch_connect"
    target_file: TargetFile
    nets: list[NetDefinition]
    global_labels: Optional[list[GlobalLabelDef]] = None
    no_connects: Optional[list[Position]] = None
    strategy: Literal["wire_first", "label_only", "hybrid"] = "hybrid"
    collision_zones: Optional[list[tuple[float, float]]] = None

class NetDefinition(BaseModel):
    name: str
    pins: list[PinRef]

class GlobalLabelDef(BaseModel):
    name: str
    position: tuple[float, float]
    rotation: int = 0
    shape: str = "bidirectional"  # input, output, bidirectional, tri_state, passive

class RegenerateWiringOp(OpBase):
    op_type: Literal["regenerate_wiring"] = "regenerate_wiring"
    target_file: TargetFile
    nets: list[NetDefinition]
    global_labels: list[GlobalLabelDef]
    no_connects: Optional[list[Position]] = None
    keep_components: bool = True  # Keep existing components
    strategy: Literal["wire_first", "label_only", "hybrid"] = "hybrid"
    run_erc: bool = True  # Run ERC after regeneration
```

**`regenerate_wiring` algorithm:**
1. Remove all wires, labels, no_connects (keep components and power symbols)
2. Auto-detect collision zones from remaining component pin positions
3. For each net in `nets`: call `connect_pins` logic
4. Place global labels at specified positions
5. Place no_connects at specified positions
6. If `run_erc`: execute `kicad-cli sch erc` and include results

**Returns:**
```python
{
    "removed": {"wires": 124, "labels": 0, "no_connects": 0},
    "generated": {"wires": 21, "net_labels": 82, "global_labels": 23, "no_connects": 0},
    "erc_result": {"errors": 8, "warnings": 25},
    "pin_overlaps_detected": 1,
    "collision_zones_found": 2
}
```

**Tests:**
- Integration test: batch connect 5 nets on a simple schematic
- Integration test: regenerate wiring for compressor-stage schematic
  - File: `analog-ecosystem/hardware/network-io/channel-strip/compressor-stage.kicad_sch`
  - Target: 33 violations (8 errors pre-existing, 25 warnings)
  - Must not exceed 33 violations (no regression from manual script)
- End-to-end test: full regenerate → ERC → verify violation count

---

## Success Criteria

1. `resolve_pin_positions` correctly resolves all pins for multi-unit ICs (CD4066BE, NE5532), named-pin ICs (THAT4301), R/C passives, and power symbols
2. `detect_pin_overlaps` finds the R55/R56 overlap in compressor-stage at position (59.69, 78.74)
3. `detect_routing_collisions` identifies U22 pin columns (x=95.25, x=105.41) as collision zones
4. `connect_pins` generates wires with collision avoidance and net labels for guaranteed connectivity
5. `batch_connect` processes 45 nets for compressor-stage without error
6. `regenerate_wiring` produces a schematic with ≤33 ERC violations (matching manual script result)
7. Parent schematic ERC does not regress (≤209 violations for analog-board)

## Real-World Test Files

Primary: `analog-ecosystem/hardware/network-io/channel-strip/compressor-stage.kicad_sch`
Reference: `analog-ecosystem/hardware/dumb-cartridges/compressor/schematic/left-channel-compressor.kicad_sch`
Expected result: 33 violations (8 errors all pre-existing, 25 warnings)
