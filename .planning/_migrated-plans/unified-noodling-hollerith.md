# Plan: Add Schematic Spatial Extraction

## Context

The merged training dataset has 10,008 board graph samples, but 2,903 (29%) are schematic-only records with zero spatial data (`box_count=0, path_count=0`). The spatial extractor in `src/kicad_agent/spatial/extractor.py` only handles `PcbIR` — it skips schematics entirely. KiCad schematics DO have spatial data (symbol positions, pin positions, wire endpoints, label positions) already exposed via `SchematicIR` methods. We need to add schematic spatial extraction so all 10K samples are usable for spatial reasoning training.

## Changes

### 1. Add `extract_schematic_points()` to `src/kicad_agent/spatial/extractor.py`

Uses `SchematicIR.get_pin_positions()` + `get_label_positions()` to create `SpatialPoint` instances.

- Pin positions → `entity_type="pin"`, `entity_id="{ref}.{pin_number}"`, `net=pin_name`
- Label positions → `entity_type="label"`, `entity_id=label_name`, `net=net_name`
- Component symbol positions (no pins) → `entity_type="symbol"`, `entity_id=ref`

### 2. Add `extract_schematic_boxes()` to `src/kicad_agent/spatial/extractor.py`

Computes bounding boxes for schematic symbols from their pin positions. Group pins by reference, compute min/max x,y, add small margin (1.0mm like PCB extractor).

- Boxes computed from pin positions per reference
- Symbols with no pins get a default 2mm×2mm box at symbol position
- `entity_type="symbol"`, `reference=ref`

### 3. Add `extract_schematic_paths()` to `src/kicad_agent/spatial/extractor.py`

Uses `SchematicIR.get_wire_endpoints()` to create `SpatialPath` instances.

- Each wire segment → `SpatialPath(points=((start_x,start_y),(end_x,end_y)))`, `entity_type="wire"`
- Multi-point wires (polyline connections) → single path with all vertices

### 4. Add `extract_schematic_all()` to `src/kicad_agent/spatial/extractor.py`

Wrapper function mirroring `extract_all()` but for `SchematicIR`. Returns `{"points": [...], "boxes": [...], "paths": [...]}`. No regions (schematics don't have zones).

### 5. Wire schematic extraction into `build_board_graph()` in `src/kicad_agent/training/graph_builder.py`

Currently at line 314: `spatial_data = extract_all(pcb_ir)` only extracts from PCB. Add schematic spatial extraction and merge results. Also add spatial attributes (x_mm, y_mm) to component nodes from schematic symbol positions (lines 357-386 only use PCB footprint positions — components without PCB footprints get no position).

Changes:
- After `extract_all(pcb_ir)`, also call `extract_schematic_all(sch_ir)`
- Merge: combine points, boxes, paths from both sources
- For component nodes missing `x_mm`/`y_mm` (no PCB footprint), use schematic symbol position from `sch_ir.get_component_positions()` or iterate `sch.components` for position data

### 6. Re-run `process_pairs.py` on schematic-only records

After the code changes, re-process the 2,903 schematic-only records from `training_data_merged/train.jsonl` to add spatial data. This can be a targeted script that:
- Reads each schematic record
- Re-runs graph builder with updated extraction
- Updates the spatial_summary_json and graph_json

## Critical Files

- `src/kicad_agent/spatial/extractor.py` — add 3 extraction functions + 1 wrapper
- `src/kicad_agent/spatial/primitives.py` — no changes needed (existing types work)
- `src/kicad_agent/ir/schematic_ir.py` — no changes needed (methods already exist)
- `src/kicad_agent/training/graph_builder.py` — wire schematic extraction into build flow (lines 314, 357-386, 393)
- `scripts/process_pairs.py` — run targeted re-processing of schematic records

## Verification

1. `python3 -c "from kicad_agent.spatial.extractor import extract_schematic_all"` — imports work
2. Run on a test schematic from staging: verify non-zero box_count, path_count, point_count
3. Re-process 2,903 schematic records: confirm all get spatial data
4. Final dataset check: all 10,008 records should have `box_count > 0` or `path_count > 0`
