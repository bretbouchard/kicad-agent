# Phase 38 Context: Schematic Routing Engine

**Source:** Bret Bouchard (analog-ecosystem project), based on 3+ sessions of manual schematic wiring
**Date:** 2026-05-31
**Why this phase exists:** I spent hours writing Python scripts to do what kicad-agent should do natively — resolve pin positions, route wires with collision avoidance, and connect nets from a topology definition. Every task below comes from real pain points encountered while regenerating a THAT4301 compressor schematic with 43 components and 45 nets.

---

## Pain Point 1: Pin Position Resolution

### What I had to do manually
For every component, I manually:
1. Read the `lib_symbols` section of the `.kicad_sch` file
2. Found each pin's `(at lx ly rotation)` offset within its symbol unit
3. Found each symbol unit's `(at cx cy rotation)` placement in the schematic
4. Calculated absolute positions: `sch_x = cx + lx`, `sch_y = cy - ly` (y-negation for rotation=0)
5. Handled multi-unit components (CD4066BE has 5 units A-E at different positions; NE5532 has 3 units A-C)
6. Handled pin numbering vs pin naming (THAT4301 uses named pins: `VCA_IN`, `EC_SPAN`, etc.)

### Example that broke me
```python
# CD4066BE has unit A at (69.85, 69.85) and unit E (power) at (85.09, 69.85)
# Pin 14 (VDD) is in unit E with offset (0, 7.62)
# Absolute: pp(85.09, 69.85, 0, 7.62) = (85.09, 62.23)
# If you use unit A's position: pp(69.85, 69.85, 0, 7.62) = (69.85, 62.23) — WRONG
```

### What kicad-agent needs
```
resolve_pin_positions(file, ref) → {
  ref: "U21",
  lib_id: "CD4066BE",
  units: {
    "1": { position: (69.85, 69.85), pins: {1: (62.23, 69.85), 2: (77.47, 69.85), 13: (69.85, 74.93)} },
    "5": { position: (85.09, 69.85), pins: {7: (85.09, 77.47), 14: (85.09, 62.23)} }
  },
  all_pins: {1: (62.23, 69.85), 2: (77.47, 69.85), 7: (85.09, 77.47), 13: (69.85, 74.93), 14: (85.09, 62.23)}
}
```

Must handle:
- Multi-unit symbols (units at different positions)
- Pin numbering (CD4066BE pin 1, 2, 7, 13, 14)
- Pin naming (THAT4301 pin VCA_IN, EC_SPAN, etc.)
- Rotation transforms (rotation=0 is common but rotation=90/180/270 occur)
- Body style variations
- R/C passives (Device:R, Device:C have pin 1 at top, pin 2 at bottom, offset 3.81mm)

---

## Pain Point 2: Net-Based Wire Routing

### What I had to do manually
The PCB auto-router exists and works great. For schematics, there's only `add_wire` — a single segment. I had to write a full routing engine:

```python
def make_wire(x1, y1, x2, y2):
    """L-shaped: horizontal then vertical."""
    if x1 == x2 or y1 == y2:
        return [single_segment]
    else:
        return [horizontal_segment, vertical_segment]
```

### Collision avoidance I had to implement manually
1. **IC pin columns**: THAT4301 has 8 pins on each side at x=95.25 and x=105.41. Any vertical wire in these columns shorts ALL 8 pins together. Had to filter: `if 95.0 < x < 95.5 or 105.0 < x < 105.9: skip`
2. **R/C component columns**: Multiple resistors at x=59.69 (R55-R58, C45-C48). Vertical wires in this column overlap between nets, creating unintended connections.
3. **Long-distance routes**: Wires >40mm tend to cross many other nets. Better to use net labels.

### What I discovered about wire connectivity
**CRITICAL**: In KiCad 10, programmatically generated wires DON'T reliably connect to component pins even when coordinates match exactly. I verified coordinates against lib_symbols, component positions, and ERC reports — all correct. But KiCad reports "unconnected_wire_endpoint" for them anyway.

**Workaround**: Net labels at every pin position provide guaranteed connectivity via name matching. Wires are cosmetic/at best.

### What kicad-agent needs
```
connect_pins(file, net_name, pins, strategy="hybrid") → {
    net_name: "COMP_IN",
    wires_generated: 2,  # or 0 if strategy="label_only"
    labels_generated: 3,
    collisions_avoided: 1,
    notes: ["Wire at x=59.69 skipped — vertical column with 4 overlapping nets"]
}
```

Strategies:
- `wire_first`: Generate wires, add labels only at pin positions not reached by wires
- `label_only`: No wires, just net labels at every pin position (most reliable)
- `hybrid`: Generate wires for short/clean routes, labels for everything else (recommended)

---

## Pain Point 3: Batch Net Definition

### What I had to do manually
I defined 45 nets manually as Python tuples:
```python
NETS = [
    ('COMP_IN',     [('TP8', 1), ('C45', 1)]),
    ('input_rc',    [('C45', 2), ('R55', 1)]),
    ('to_switch',   [('R55', 2), ('U21', 1)]),
    # ... 42 more
]
```

Each net required knowing which pins to connect. For a THAT4301 compressor circuit, this meant understanding the IC datasheet and reference circuit topology.

### What kicad-agent needs
```
batch_connect(file, nets, options) → {
    nets_processed: 45,
    wires_generated: 21,
    labels_generated: 82,
    global_labels_generated: 23,
    collisions_detected: 3,
    pin_overlaps_detected: 1
}
```

Options:
- `global_labels`: List of (name, position, rotation, shape) for interface nets
- `no_connects`: List of positions for unused pins
- `collision_zones`: List of x-ranges or rectangular regions to avoid routing through
- `label_size`: Font size for net labels (default 0.75mm)
- `max_wire_length`: Skip wires longer than this (default 40mm)

---

## Pain Point 4: Component Pin Overlap Detection

### The bug I found
R55 (at y=74.93) and R56 (at y=82.55) are stacked vertically. R55 pin2 is at (59.69, 78.74) and R56 pin1 is ALSO at (59.69, 78.74). They share the same position but are on different nets (separated by a CD4066BE bypass switch). Any label or wire at that position applies to both pins, creating an unintended short.

This is a layout bug that no current operation detects. I found it through ERC `multiple_net_names` warnings after the fact.

### What kicad-agent needs
```
detect_pin_overlaps(file) → [
    {
        position: (59.69, 78.74),
        pins: [
            {ref: "R55", pin: 2, net: "to_switch"},
            {ref: "R56", pin: 1, net: "COMP_BYPASS_SIG"}
        ],
        severity: "error",
        note: "Pins from different nets share position — unintended short"
    }
]
```

---

## Pain Point 5: Regenerate Wiring from Netlist

### The big picture operation
The entire reason this phase exists. I had to write a 300-line Python script (`regenerate_compressor_wiring.py`) that:

1. Reads the schematic
2. Removes ALL wires, labels, no_connects (keeping components and power symbols)
3. Defines the complete net topology
4. Generates wires with collision avoidance
5. Generates net labels at every pin position
6. Generates global labels at interface points
7. Writes the result
8. Runs ERC to verify

Result: 60 → 33 violations (45% reduction), parent schematic 221 → 209 (no regression).

### What kicad-agent needs
```
regenerate_wiring(file, netlist, labels, options) → {
    removed: {wires: 124, labels: 0, no_connects: 0},
    generated: {wires: 21, net_labels: 82, global_labels: 23, no_connects: 0},
    erc_result: {errors: 8, warnings: 25},
    notes: ["5 power_pin_not_driven errors are library-level issues"]
}
```

---

## Real-World Test Case

The compressor-stage schematic in the analog-ecosystem project is the perfect integration test:

- **43 components**: U21-U24 (CD4066BE×2, THAT4301, NE5532), R55-R69, C45-C51, TP8-TP9, 12 power symbols
- **45 nets**: Audio signal path, sidechain, bypass switching, power distribution
- **Multi-unit ICs**: CD4066BE (5 units), NE5532 (3 units), THAT4301 (1 unit, 16 named pins)
- **Known collision zones**: U22 pin columns, R/C component column
- **Known layout bug**: R55/R56 pin overlap
- **Pre-existing ERC issues**: power_pin_not_driven (library), orphaned #PWR symbols

File: `hardware/network-io/channel-strip/compressor-stage.kicad_sch` in the analog-ecosystem project.
Reference circuit: `hardware/dumb-cartridges/compressor/schematic/left-channel-compressor.kicad_sch`

---

## Implementation Notes for the Cicada Team

### Pin position calculation (verified formula)
```python
def resolve_pin_position(unit_pos, pin_offset, rotation=0):
    """Calculate absolute pin position from unit placement + pin offset."""
    cx, cy = unit_pos  # (at cx cy rotation) from symbol instance
    lx, ly = pin_offset  # (at lx ly rot) from lib_symbol pin definition

    if rotation == 0:
        return (cx + lx, cy - ly)  # y-negation for schematic coords
    elif rotation == 90:
        return (cx - ly, cy - lx)  # 90° clockwise
    elif rotation == 180:
        return (cx - lx, cy + ly)
    elif rotation == 270:
        return (cx + ly, cy + lx)
```

### KiCad Device:R/C pin mapping (standard)
```python
def rc_pin_positions(component_pos):
    """Device:R and Device:C always have pin1=top, pin2=bottom."""
    x, y = component_pos
    return {
        1: (x, y - 3.81),   # TOP (y-negated)
        2: (x, y + 3.81)    # BOTTOM
    }
```

### Wire routing collision zones (learned from 60+ iterations)
```python
COLLISION_ZONES = [
    # (x_range, description)
    (95.0, 95.5, "U22 left pin column — 8 pins at x=95.25"),
    (105.0, 105.9, "U22 right pin column — 8 pins at x=105.41"),
]
# Also check: if two pins at same x have overlapping y-ranges, that column is a collision zone
```

### Net label format (verified working)
```
(label "NET_NAME"
    (at X Y ROT)
    (effects
        (font
            (size 0.75 0.75)
        )
    )
    (uuid "UUID")
)
```

### Wire format (verified working)
```
(wire
    (pts
        (xy X1 Y1) (xy X2 Y2)
    )
    (stroke
        (width 0)
        (type default)
    )
    (uuid "UUID")
)
```

### Key insight: net labels > wires
In practice, net labels provide more reliable connectivity than wires for programmatically generated schematics. The recommended strategy is:
1. Generate net labels at EVERY pin position (guaranteed connectivity)
2. Generate wires for short, clean routes (aesthetic value)
3. Skip wires in collision zones (label-only)
4. Use global labels for interface nets (cross-sheet connectivity)
