# Phase 9 Context: GRPO Spatial Reasoning Training

## Existing Infrastructure (from Phase 8)

### Maze Generator (`src/kicad_agent/spatial/maze_generator.py`)
- `generate_maze_board()` produces KiCad PCB files with obstacles, source/target vias, and BFS-computed solutions
- `MazeBoard` dataclass: pcb_path, dimensions, obstacles (SpatialBox), source/target points, solution_path, clearance_mm
- BFS solver returns shortest path through grid
- Configurable: board size (1-500mm), grid cell size (>=1mm), obstacle density (~40%), random seed
- Safety: max 10k grid cells, max 500mm board dims

### Reasoning Chains (`src/kicad_agent/spatial/reasoning_chains.py`)
- `ReasoningStep` (frozen): step_type, content, coordinates, metadata
- `ReasoningChain` (frozen): violation_type, description, severity, steps tuple, spatial_primitives, chain_id
- `synthesize_chain()` builds 5-step chains: observation → spatial_context → coordinate_reference → diagnosis → recommendation
- `synthesize_chains()` processes DRC/ERC violation lists
- `_DIAGNOSIS_MAP` and `_RECOMMENDATION_MAP` for 9 violation types

### Spatial Primitives (`src/kicad_agent/spatial/primitives.py`)
- `SpatialPoint(x, y, entity_type, entity_id, layer, net)` — pins, vias, pads
- `SpatialBox(x1, y1, x2, y2, entity_type, entity_id, layer, reference)` — components, footprints
- `SpatialPath(points, entity_type, entity_id, layer, net, width)` — traces, wires
- `SpatialRegion(boundary, entity_type, entity_id, layer, net, region_type)` — zones, keepouts
- All frozen dataclasses with `to_json()` and `to_shapely()` methods

### Spatial Query Engine (`src/kicad_agent/spatial/query.py`)
- `SpatialQueryEngine` backed by Shapely STRtree
- Methods: `proximity()`, `containment()`, `clearance()`, `find_by_entity_id()`, `find_by_net()`, `find_by_layer()`
- Two-phase query: STRtree bounding-box filter → exact Shapely check

### Extractor (`src/kicad_agent/spatial/extractor.py`)
- `extract_primitives(pcb_ir)` returns list of all spatial primitives from a PcbIR
- Handles absolute pad positioning: footprint.position + rotate(pad.position, footprint.angle)

### Rick Integration (`src/kicad_agent/spatial/rick_integration.py`)
- `RickDomain` enum: SI, PI, EMC, DFM
- Domain analyzers produce `RickFinding` tuples with coordinate grounding

## Available ML Dependencies

- **PyTorch 2.10** (nightly) — model training, GPU support
- **Transformers 4.56** — model loading, tokenization
- **Accelerate 1.10** — distributed training
- **Shapely 2.1** — spatial geometry (already used)
- **kiutils 1.4+** — KiCad file parsing

## Project Structure
```
src/kicad_agent/
├── spatial/
│   ├── __init__.py          # barrel exports
│   ├── primitives.py        # SpatialPoint/Box/Path/Region
│   ├── extractor.py         # PcbIR → primitives
│   ├── maze_generator.py    # MazeBoard + BFS solver
│   ├── reasoning_chains.py  # Chain synthesis
│   ├── query.py             # SpatialQueryEngine
│   ├── renderer.py          # PCB image rendering
│   └── rick_integration.py  # Domain analyzers
├── training/                # NEW — Phase 9 module
├── parser/                  # Phase 1
├── ir/                      # Phase 2
├── validation/              # Phase 3
├── ops/                     # Phase 4-5
└── ...
```

## Key Design Decisions

1. Maze generator uses BFS for verified solutions (shortest path guarantee)
2. Reasoning chains use 5-step pattern (observation → recommendation)
3. Spatial primitives are frozen dataclasses with Shapely conversion
4. All coordinates in mm, Y-axis downward (KiCad convention)
5. No external ML framework dependencies yet — training/ module is new

## Constraints

- Must not break existing 568+ tests
- Training module should be optional (import guard for PyTorch)
- Synthetic data must be reproducible (seed-based)
- Must work on CPU (GPU optional for acceleration)
