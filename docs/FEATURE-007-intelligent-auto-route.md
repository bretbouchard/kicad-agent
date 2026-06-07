# FEATURE-007: Intelligent Auto-Routing with Obstacle Awareness

**Issue:** kicad-agent-7
**Priority:** P0 — blocks Phase 21.5 channel-strip-pcb completion
**Date:** 2026-06-05
**Status:** OPEN

---

## Problem Statement

The `auto_route` operation exists with full infrastructure (A* pathfinding, multi-layer support, impedance control, length matching, KiCad S-expression bridge) but produces near-zero useful results on real PCBs because it has **no obstacle awareness**.

Test on channel-strip analog-board (197 footprints, 213 nets):
- 3 nets routed, 200 failed (1.5% success rate)
- Root cause: `build_routing_graph()` is called with **empty obstacles list**
- Paths can route through component bodies, pads, and silkscreen
- Most nets fail because A* cannot navigate around densely packed components

The routing engine is architecturally sound — it just needs the spatial data that already exists in the PCB file.

---

## What We Have (Working Infrastructure)

### Routing Engine (`routing/`)
- **`pathfinder.py`**: A* with networkx, nearest-neighbor multi-pin routing, 2D/3D coordinates
- **`graph.py`**: Grid-based routing graph with DRC-aware edge costs, STRtree obstacle checking
- **`constraints.py`**: RoutingConstraints frozen dataclass (clearance, grid, trace width, via size)
- **`bridge.py`**: TrackSegment/ViaSegment with `to_sexpr()` — outputs valid KiCad `(segment ...)` and `(via ...)`
- **`impedance.py`**: Microstrip/stripline impedance solver
- **`length_matching.py`**: Sawtooth pattern for differential pairs
- **`multi_pass.py`**: 3-pass strategy with progressive obstacle blocking

### Spatial Engine (`spatial/`)
- **`pcb_model.py`**: PcbSpatialModel with Shapely geometries, STRtree spatial indexing
- **`query.py`**: Proximity, containment, clearance queries
- **`primitives.py`**: SpatialBox, SpatialPoint primitives

### PcbIR (`ir/pcb_ir.py`)
- **`extract_netlist()`**: Returns `{net_name: [(x, y), ...]}` — pad positions with absolute coords
- **`get_board_bounds()`**: Extracts board outline bounds
- **`insert_track_segments()`**: Writes S-expression segments into PCB via PcbRawWriter

### Bridge to KiCad Format
```lisp
(segment
  (start 45.5000 52.2500)
  (end 67.7500 52.2500)
  (width 0.2500)
  (layer "F.Cu")
  (net 42 "I2C_SDA")
)

(via
  (at 55.0000 52.0000)
  (size 0.8000)
  (drill 0.4000)
  (layers "F.Cu" "In1.Cu")
  (net 42 "I2C_SDA")
)
```

---

## What's Missing (The Gap)

### Gap 1: No Obstacle Extraction from PCB
The routing graph accepts `obstacles: list[SpatialBox]` but the handler never provides them. It calls:
```python
routing_graph = build_routing_graph(bounds, constraints=constraints, layers=active_layers)
# obstacles defaults to [] — the entire board is treated as free space
```

**Fix:** Extract SpatialBox obstacles from placed footprints. Each footprint's bounding box (including pads, courtyard, silkscreen) is a forbidden routing zone.

### Gap 2: No Pad-to-Grid Snapping
KiCad pads are placed at arbitrary mm positions. With 0.5mm grid resolution, many pads land between grid nodes. A* can only route TO grid nodes, so pads not on the grid are unreachable.

**Fix:** When constructing the routing graph, snap each pad position to the nearest grid node and add it as a routing target. Use `graph.add_target_node(pad_x, pad_y, net_name)` or similar.

### Gap 3: No Via Penalties for Power Nets
Power nets (+9V, -9V, +3V3, +5V, GND) should use internal copper planes, not routed traces. The current router treats them identically to signal nets.

**Fix:** Skip power/ground nets in auto_route (they're handled by copper zones). Or add a `zone_fill` operation that creates copper pour zones instead of traces for power nets.

### Gap 4: No Sequential Routing with Rip-Up
Nets routed early can block nets routed later. The multi_pass router exists but only does 3 passes with increasing relaxation — it doesn't do ordered rip-up based on net priority.

**Fix:** Route nets in priority order: power planes first (as zones), then critical signals (diff pairs, audio), then remaining signals. Failed nets get rip-up and re-routed with updated obstacles from previously routed nets.

### Gap 5: No Copper Zone Generation
After routing, copper zones (ground/power planes) must be filled. `AddCopperZoneOp` exists but lacks polygon outline specification (L-13 in KNOWN_LIMITATIONS).

**Fix:** Auto-generate zone polygons from board outline minus clearance from routed traces and pads.

---

## Proposed Architecture

### Phase A: Obstacle-Aware Routing (Minimal — Unblocks Channel Strip)

**Goal:** Get auto_route from 1.5% to 80%+ success rate on real PCBs.

**A1: Extract footprint bounding boxes as obstacles**
```python
def extract_obstacles(ir: PcbIR) -> list[SpatialBox]:
    """Extract SpatialBox obstacles from all placed footprints.

    For each footprint:
    1. Get footprint position (at X Y)
    2. Get courtyard bounds (if defined)
    3. Fallback: compute bounding box from all pads + margin
    4. Return SpatialBox with absolute coordinates
    """
```

Data already available in PcbIR. Courtyard data is in the PCB file as `(gr_rect (start X Y) (end X Y) (layer "F.CrtYd"))` inside each footprint block.

**A2: Pad-to-grid snapping**
```python
def snap_pad_to_grid(pad_x: float, pad_y: float, grid_res: float) -> tuple[float, float]:
    """Snap pad position to nearest grid node."""
    return (round(pad_x / grid_res) * grid_res, round(pad_y / grid_res) * grid_res)
```

**A3: Wire obstacles in handler**
```python
# In _handle_auto_route:
obstacles = ir.extract_obstacles()  # NEW
routing_graph = build_routing_graph(bounds, obstacles=obstacles, ...)
```

**A4: Filter power/ground nets**
```python
# Skip power and ground — they get copper zones instead
skip_nets = {n for n in netlist if n.startswith('+') or n.startswith('GND') or n == 'AGND'}
route_nets = {n: pins for n, pins in netlist.items() if n not in skip_nets}
```

**A5: Route in priority order**
```python
# 1. Differential pairs (length-matched)
# 2. Audio signal nets (critical path)
# 3. Digital control nets (I2C, SPI)
# 4. General purpose nets
# After each batch: add routed segments as obstacles for next batch
```

**Estimated effort:** 200-300 lines of code changes to existing files.

### Phase B: AI-Guided Routing Strategy

**Goal:** Use LLM to decide routing strategy, not just paths.

The LLM doesn't draw individual traces — it decides the high-level strategy that the A* pathfinder executes:

**B1: Route planning via LLM**
```python
def plan_routing_strategy(ir: PcbIR, constraints: RoutingConstraints) -> RoutingPlan:
    """LLM analyzes the PCB and returns a routing plan.

    Input to LLM:
    - Board dimensions, layer stackup
    - Net list with pin counts, net classes
    - Component zones (audio section, digital section, power section)
    - Critical nets (diff pairs, impedance-controlled)
    - Design rules

    Output from LLM:
    - Layer assignment per net class (audio on F.Cu, digital on In1.Cu, etc.)
    - Routing order priority
    - Which nets need zones vs traces
    - Via strategy (where layer transitions should happen)
    - Keep-out zones (audio/digital separation)
    """
```

**B2: Zone-aware routing**
After traces are routed, generate copper zone outlines:
```python
def generate_zone_outlines(ir: PcbIR, routed_segments: list, net_name: str) -> list[tuple[float, float]]:
    """Generate polygon outline for a copper zone.

    1. Start with board outline
    2. Subtract clearance around all obstacles
    3. Subtract clearance around routed traces on other nets
    4. Return polygon points for (zone (polygon (pts ...)))
    """
```

**B3: Iterative DRC feedback loop**
```python
def route_with_drc_feedback(ir: PcbIR, constraints):
    """Route -> DRC -> Feed violations back -> Re-route failed nets."""
    for iteration in range(5):
        results = auto_route(ir, constraints)
        violations = run_drc(ir)
        if not violations:
            break
        # Add violation locations as new obstacles
        constraints.obstacles.extend(violation_boxes)
```

**Estimated effort:** 400-600 lines, new file `routing/planner.py`.

### Phase C: Visual Rendering for AI Feedback

**Goal:** Render PCB state as images so vision models can verify routing.

**C1: PCB layer renderer**
Render each copper layer as an image with:
- Component outlines (footprint bounding boxes)
- Placed pads (circles colored by net)
- Routed traces (lines colored by net)
- Board outline

This feeds into the pcb-vision-rick infrastructure for coordinate-grounded visual inspection.

**Estimated effort:** 300-400 lines, extends `spatial/renderer.py`.

---

## Data Format: What the AI Receives

### Board State JSON (input to routing plan)
```json
{
  "board": {
    "width_mm": 120.0,
    "height_mm": 80.0,
    "layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
    "stackup": "1.6mm 4-layer"
  },
  "components": [
    {
      "ref": "U25",
      "footprint": "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
      "position": [97.575, 99.69],
      "layer": "F.Cu",
      "zone": "audio"
    }
  ],
  "nets": {
    "I2C_SDA": {
      "pins": [
        {"ref": "U37", "pad": "30", "pos": [75.2, 62.8]},
        {"ref": "U39", "pad": "14", "pos": [88.5, 45.0]}
      ],
      "class": "signal",
      "clearance_mm": 0.2,
      "width_mm": 0.25
    },
    "GND": {
      "pin_count": 150,
      "class": "power",
      "strategy": "zone"
    }
  },
  "design_rules": {
    "clearance_mm": 0.2,
    "trace_width_mm": 0.25,
    "via_diameter_mm": 0.8,
    "via_drill_mm": 0.4
  }
}
```

### Routing Output Format (from A* pathfinder)
```json
{
  "I2C_SDA": {
    "success": true,
    "path": [
      [75.0, 62.5, "F.Cu"],
      [76.0, 62.5, "F.Cu"],
      [78.0, 62.5, "F.Cu"],
      [78.0, 45.0, "F.Cu"],
      [88.5, 45.0, "F.Cu"]
    ],
    "length_mm": 16.5,
    "vias": 0
  }
}
```

---

## Channel Strip Test Case

### Analog Board
- **Board:** 120 x 80mm, 4-layer (F.Cu/In1.Cu/In2.Cu/B.Cu)
- **Components:** 197 footprints, 709 pads
- **Nets:** 213 (11 power/ground, 202 signal)
- **Routing nodes:** 560
- **Grid:** 0.5mm resolution = 38,801 nodes/layer

### Routing Strategy
1. **Copper zones** for GND (B.Cu), +3V3 (In1.Cu), +5V (In1.Cu), +9V/-9V (In2.Cu)
2. **Differential pairs:** None on analog board
3. **Audio signal path:** F.Cu — input stage → preamp → compressor → EQ → output
4. **Digital control:** In1.Cu — I2C to GPIO expanders, SPI to digipots
5. **Codec TDM:** F.Cu with impedance-controlled traces to U37

### Digital Board
- **Components:** 48 footprints, 165 pads
- **Nets:** 86 (4 power, 82 signal)
- **Key constraints:** USB 90-ohm diff pair, Ethernet 100-ohm diff pair
- **Routing strategy:** USB diff pair on F.Cu, Ethernet diff pair on F.Cu/In1.Cu

---

## Implementation Order

### Sprint 1: Phase A (Obstacle Awareness) — P0
Files to modify:
- `ir/pcb_ir.py` — add `extract_obstacles()` method
- `ops/handlers/pcb.py` — pass obstacles to routing graph, filter power nets, priority ordering
- `routing/graph.py` — ensure grid snapping of pad positions
- `routing/pathfinder.py` — add routed-path-as-obstacle for sequential routing

### Sprint 2: Zone Generation — P1
Files to modify/create:
- `ops/handlers/pcb.py` — auto-generate zones after routing
- `routing/zones.py` (new) — polygon outline generation from board outline minus obstacles
- `ops/_schema_pcb.py` — update AddCopperZoneOp with polygon pts field

### Sprint 3: AI Strategy Planner — P2
Files to create:
- `routing/planner.py` (new) — LLM-driven routing strategy

### Sprint 4: Visual Feedback — P3
Files to create/modify:
- `spatial/renderer.py` — PCB layer rendering for visual inspection

---

## Success Criteria

1. **80%+ net routing success** on analog-board (up from 1.5%)
2. **95%+ net routing success** on digital-board
3. **DRC passes** with 0 errors after routing + zone fill
4. **KiCad GUI opens** the routed PCB without corruption
5. **Gerber export** produces valid manufacturing files

---

## Dependencies

- `shapely` (already in use)
- `networkx` (already in use)
- No new external dependencies required for Sprint 1

## Risks

| Risk | Mitigation |
|------|------------|
| Grid resolution too coarse (0.5mm) for fine-pitch ICs | Reduce to 0.25mm for dense areas, use adaptive grid |
| A* pathfinding slow on large boards (155K nodes) | Use hierarchical routing: coarse global + fine local |
| KiCad S-expression corruption on segment insert | Already solved: PcbRawWriter uses raw S-expression manipulation |
| Footprint courtyard data missing from some footprints | Fallback: compute bounding box from pads + clearance margin |
| Power plane via traces instead of zones | Explicitly route power nets to zone generation, not A* |

---

## Related Issues

- KNOWN_LIMITATIONS M-5: Auto-router single-layer only (FIXED — multi-layer exists)
- KNOWN_LIMITATIONS L-13: Copper zone has no polygon outline (addressed in Sprint 2)
- kicad-agent-6: update_pcb_from_schematic (CLOSED — provides net sync for routing input)

---

*Feature request authored by kicad-agent team for analog-ecosystem Phase 21.5.*
