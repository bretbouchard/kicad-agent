# Feature Gap Research: v2.2 complete-ops

**Domain:** KiCad 10+ automation agent (AI-safe structural editing)
**Researched:** 2026-05-29
**Confidence:** HIGH
**Scope:** 5 feature gaps for milestone v2.2

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Feature Gap Overview](#feature-gap-overview)
3. [Gap 1: Hierarchical Sheet Operations](#gap-1-hierarchical-sheet-operations)
4. [Gap 2: Remove Operations](#gap-2-remove-operations-wire-label-junction)
5. [Gap 3: Footprint Creation](#gap-3-footprint-creation-create_footprint)
6. [Gap 4: Connectivity Query](#gap-4-connectivity-query-operation)
7. [Gap 5: Cross-File Atomic Wiring](#gap-5-cross-file-atomic-wiring)
8. [Feature Classification](#feature-classification)
9. [Dependencies and Ordering](#dependencies-and-ordering)
10. [MVP Recommendation](#mvp-recommendation)

---

## Executive Summary

This document covers five feature gaps identified in the Council of Ricks audit (Phase 24) as blocking for the v2.2 milestone. Each gap represents an operation class that real-world KiCad projects require but kicad-agent does not yet expose through its operation API.

Four of the five features have substantial existing infrastructure in the codebase -- the gaps are primarily about wiring, not building from scratch. Only footprint creation requires significant new code. The hierarchical sheet operations can leverage the existing root_sheet.py navigation logic. Remove operations follow the same pattern as remove_component.py. The connectivity query wraps analysis/connectivity.py. Cross-file wiring connects crossfile/atomic.py to the executor.

The recommended implementation order is: remove operations (simplest, pattern exists) -> connectivity query (wrapping existing code) -> cross-file wiring (infrastructure exists) -> footprint creation (most new code) -> hierarchical sheets (most complex, highest value).

---

## Feature Gap Overview

| Gap | Feature | Category | Complexity | Existing Infra | Dependencies |
|-----|---------|----------|------------|----------------|--------------|
| 1 | Hierarchical sheet ops (add_sheet, add_sheet_pin, navigate) | Table Stakes | HIGH | root_sheet.py, hlabel_guard.py | None |
| 2 | Remove operations (remove_wire, remove_label, remove_junction) | Table Stakes | LOW | remove_component.py pattern, IR query methods | None |
| 3 | Footprint creation (create_footprint) | Differentiator | MEDIUM | create_symbol handler, FootprintIR | kiutils Footprint API |
| 4 | Connectivity query (netlist/graph query as operation) | Table Stakes | LOW | analysis/connectivity.py, NetGraph | None |
| 5 | Cross-file atomic wiring (wire crossfile/atomic.py to executor) | Differentiator | MEDIUM | crossfile/atomic.py, AtomicOperation | None |

---

## Gap 1: Hierarchical Sheet Operations

### What This Is

Hierarchical sheets let KiCad designers break a large schematic into multiple sub-sheets, each stored as a separate .kicad_sch file. A parent sheet contains a `sheet` S-expression that references a child file. Communication between sheets happens through **hierarchical labels** (in the child) and **sheet pins** (on the sheet symbol in the parent). This is how most real KiCad projects are organized.

### How It Works in KiCad

**S-expression format (parent sheet):**
```
(sheet (at 50.8 38.1) (size 25.4 12.7)
  (fields_autoplaced)
  (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
  (property "Sheetname" "Power Supply" (at 50.8 36.83 0)
    (effects (font (size 1.27 1.27)) (justify left bottom)))
  (property "Sheetfile" "power_supply.kicad_sch" (at 50.8 51.562 0)
    (effects (font (size 1.27 1.27)) (justify left top)))
  (pin "VCC" input (at 50.8 43.18 180)
    (effects (font (size 1.27 1.27)) (justify right)))
  (pin "GND" passive (at 76.2 43.18 0)
    (effects (font (size 1.27 1.27)) (justify left)))
  (instances
    (project "my_project"
      (path "/root-uuid/sheet-uuid"
        (reference "1"))))
)
```

**S-expression format (child sheet hierarchical label):**
```
(hierarchical_label "VCC" shape input (at 25.4 10.16 0)
  (effects (font (size 1.27 1.27))))
```

**Key rules:**
1. Each sheet instance has a UUID-based path: `/root-uuid/sheet-uuid`. This path is used for symbol instance tracking (e.g., `/root-uuid/sheet-uuid/component-uuid`).
2. Sheet pin names must exactly match hierarchical label names in the referenced sub-sheet. A sheet pin named "VCC" connects to the hierarchical label "VCC" in the child file.
3. Sheet pin connection types (input/output/bidirectional/tri_state/passive) must match the hierarchical label shapes.
4. Sheet pins appear on the sheet symbol boundary (the rectangle defined by position + size in the parent).
5. The `fileName` property must point to a valid .kicad_sch file, resolved relative to the parent sheet's directory.
6. `instances` tracks which project uses this sheet and the path for reference propagation.

### kiutils API

```python
from kiutils.items.schitems import HierarchicalSheet, HierarchicalPin

# HierarchicalSheet fields:
#   position (Position), width (float), height (float)
#   fieldsAutoplaced (bool), stroke (Stroke), fill (Fill)
#   uuid (str), sheetName (Property), fileName (Property)
#   properties (list), pins (list[HierarchicalPin]), instances (list)

# HierarchicalPin fields:
#   name (str), connectionType (str)  # "input"/"output"/"bidirectional"/"tri_state"/"passive"
#   position (Position), effects (Effects), uuid (str)
```

### Operations Needed

**1. `add_sheet` -- Add a hierarchical sheet instance to a schematic**

Schema fields:
- `target_file`: Parent schematic file path
- `sheet_name`: Display name (e.g., "Power Supply")
- `file_name`: Relative path to child schematic (e.g., "power_supply.kicad_sch")
- `position`: PositionSpec for sheet symbol placement
- `width`: Sheet symbol width in mm (default 25.4)
- `height`: Sheet symbol height in mm (default 12.7)

Implementation:
1. Validate `file_name` is a valid .kicad_sch path (TargetFile validation)
2. Create a new HierarchicalSheet kiutils object with position, size, sheetName, fileName
3. Generate UUID for the sheet instance
4. If the child file exists, parse it and auto-generate sheet pins from its hierarchical labels
5. Append to `sch.sheets` list in the parent schematic
6. Serialize parent

**2. `add_sheet_pin` -- Add a pin to an existing hierarchical sheet**

Schema fields:
- `target_file`: Parent schematic file path
- `sheet_file_name`: The fileName property of the target sheet (identifies which sheet)
- `pin_name`: Pin name (must match a hierarchical label in the child sheet)
- `connection_type`: "input" | "output" | "bidirectional" | "tri_state" | "passive"
- `position`: PositionSpec for pin placement on sheet boundary

Implementation:
1. Find the target sheet in `sch.sheets` by matching `fileName` property
2. Validate pin_name matches a hierarchical label in the referenced child sheet
3. Create HierarchicalPin with name, connectionType, position, effects
4. Append to `sheet.pins`
5. Serialize parent

**3. `navigate_hierarchy` -- Query the sheet hierarchy**

Schema fields:
- `target_file`: Root schematic file path
- `depth`: How deep to traverse (0 = current sheet only, -1 = full tree)

Implementation:
1. Parse the root schematic
2. Walk `sch.sheets`, for each sheet parse the referenced child file
3. Recursively descend up to `depth` levels
4. Return a tree structure: `{name, file, sheets: [...], labels: [...], components: N}`

### Edge Cases

1. **Circular references**: A sheet that references itself or creates a cycle in the hierarchy. Must detect and reject.
2. **Missing child file**: Sheet references a file that does not exist. `add_sheet` should create the child file automatically (using CreateSchematicOp), but `navigate_hierarchy` must handle gracefully.
3. **Pin/label mismatch**: Adding a sheet pin whose name does not match any hierarchical label in the child. Must validate and reject.
4. **Relative path resolution**: `fileName` is relative to the parent sheet's directory, not the project root. Must resolve correctly when parent is in a subdirectory.
5. **UUID path uniqueness**: Each sheet instance must have a globally unique UUID. Must generate and verify uniqueness.
6. **Instance path propagation**: When adding a sheet, the `instances` block must include the project path with correct UUID chain.
7. **Empty child sheet**: Adding a sheet that references a new/empty child file. Should work -- the sheet has no pins until hierarchical labels are added to the child.
8. **Multiple sheets referencing the same file**: KiCad allows multiple sheet instances of the same file. Each instance gets its own UUID and reference numbering.

### Completeness Criteria

The feature is complete when:
- Can add a hierarchical sheet to any schematic and KiCad opens the result without errors
- Can add sheet pins that correctly link to child hierarchical labels
- Can navigate a multi-level hierarchy and return a complete tree
- Round-trip fidelity is maintained (parse -> add_sheet -> serialize -> KiCad opens clean)
- ERC passes on hierarchical designs with sheet pins

### Existing Infrastructure

- `src/kicad_agent/ops/root_sheet.py`: Already navigates hierarchy, discovers sub-sheets, parses each, extracts hierarchical labels, classifies directions, and rebuilds sheet pins. This is the primary code to refactor or reuse.
- `src/kicad_agent/ops/hlabel_guard.py`: Validates hierarchical label sets. Can validate pin/label consistency.
- `src/kicad_agent/ir/schematic_ir.py`: Has `add_label` with `label_type="hierarchical"` support.

### Complexity Assessment

**HIGH.** The S-expression format is complex, kiutils has the classes, but the UUID path management and instance tracking add significant complexity. Auto-generating pins from child labels requires cross-file coordination. This is the most valuable but most complex gap to fill.

---

## Gap 2: Remove Operations (Wire, Label, Junction)

### What This Is

The add operations for wires, labels, power symbols, no-connects, and junctions exist. The remove counterparts do not. Users can add schematic elements but cannot delete them through the operation API.

### How It Works in KiCad

KiCad schematic elements are stored in type-specific lists on the Schematic object:

| Element | kiutils List | kiutils Type | Located In |
|---------|-------------|-------------|-----------|
| Wire | `graphicalItems` (filtered by `type == "wire"`) | `Connection` | `sch.graphicalItems` |
| Local label | `labels` | `LocalLabel` | `sch.labels` |
| Global label | `globalLabels` | `GlobalLabel` | `sch.globalLabels` |
| Hierarchical label | `hierarchicalLabels` | `HierarchicalLabel` | `sch.hierarchicalLabels` |
| Junction | `junctions` | `Junction` | `sch.junctions` |
| No-connect | `noConnects` | `NoConnect` | `sch.noConnects` |

### Operations Needed

**1. `remove_wire` -- Remove a wire segment**

Schema fields:
- `target_file`: Schematic file path
- `start_x`, `start_y`: Start point coordinates (for precise match)
- `end_x`, `end_y`: End point coordinates (for precise match)
- `uuid`: Alternative -- match by UUID (more precise, no coordinate comparison)

Implementation pattern (from remove_component.py):
```python
# Find wire by UUID (preferred) or coordinate match
wires = [item for item in sch.graphicalItems
         if isinstance(item, Connection) and item.type == "wire"]
wire = find_by_uuid(wires, op.uuid) or find_by_coords(wires, op.start_x, ...)

# Remove using identity check
sch.graphicalItems = [item for item in sch.graphicalItems if item is not wire]
ir._record_mutation("remove_wire", {"uuid": wire.uuid})
```

**2. `remove_label` -- Remove a net label**

Schema fields:
- `target_file`: Schematic file path
- `name`: Label text to match
- `label_type`: "local" | "global" | "hierarchical" (determines which list to search)
- `x`, `y`: Position for disambiguation when multiple labels share a name
- `uuid`: Alternative -- match by UUID

Implementation:
```python
if label_type == "global":
    target_list = sch.globalLabels
elif label_type == "hierarchical":
    target_list = sch.hierarchicalLabels
else:
    target_list = sch.labels

label = find_by_uuid_or_name_pos(target_list, ...)
# Remove using list comprehension with identity check
```

**3. `remove_junction` -- Remove a junction dot**

Schema fields:
- `target_file`: Schematic file path
- `x`, `y`: Junction position
- `uuid`: Alternative -- match by UUID

Implementation:
```python
jct = find_by_uuid_or_pos(sch.junctions, ...)
sch.junctions = [j for j in sch.junctions if j is not jct]
ir._record_mutation("remove_junction", {"uuid": jct.uuid})
```

Also needed: `remove_no_connect` follows the same pattern for `sch.noConnects`.

### Edge Cases

1. **Multiple wires sharing endpoints**: Coordinate matching may find the wrong wire. UUID matching is unambiguous and should be the primary matching strategy.
2. **Labels with duplicate names**: Multiple local labels can share the same name (different positions). Must match by position or UUID for disambiguation.
3. **Removing a wire that other wires connect to**: KiCad does not track wire connectivity explicitly -- it is geometric. Removing a wire segment does not automatically clean up connected wires or junctions. This is expected behavior (KiCad GUI works the same way).
4. **Removing a label that is the only connection point for a net**: After removing a label, the net may become unnamed. This is valid but may break connectivity. The operation should succeed -- the user can run ERC to detect the resulting issues.
5. **UUID not found**: Must raise a clear error indicating the element does not exist (may have been already removed).
6. **Position tolerance**: When matching by coordinates, floating-point comparison must use a tolerance (e.g., 0.01mm). KiCad stores coordinates at different precisions depending on context.

### Completeness Criteria

The feature is complete when:
- Can remove wires, labels (all three types), junctions, and no-connects
- Match by UUID (primary) or by name+position (secondary)
- Round-trip fidelity maintained after removal
- ERC still runs clean on schematics where elements were removed (assuming the removal did not break connectivity)

### Existing Infrastructure

- `src/kicad_agent/ops/remove_component.py`: The exact pattern to follow. Identity-check removal, symbol instance cleanup, mutation recording.
- `src/kicad_agent/ir/schematic_ir.py`: Has `get_wire_endpoints()` and `get_label_positions()` query methods that already find wires and labels with their UUIDs and positions.
- `src/kicad_agent/ops/_schema_wire.py`: Has AddWireOp, AddLabelOp, etc. New RemoveWireOp, RemoveLabelOp, RemoveJunctionOp models go in the same file (or a new `_schema_remove.py`).

### Complexity Assessment

**LOW.** This is the simplest gap. The pattern exists in remove_component.py. The IR query methods exist. The kiutils types are well-understood. Each remove operation is ~30-50 lines following the existing pattern.

---

## Gap 3: Footprint Creation (create_footprint)

### What This Is

The `create_symbol` operation exists for creating schematic symbols in .kicad_sym files. There is no equivalent `create_footprint` operation for creating PCB footprints in .kicad_mod files. Users can create symbols programmatically but not footprints.

### How It Works in KiCad

A footprint (.kicad_mod) is a library element containing:

```
(module "MY_DIP-8" (layer "F.Cu")
  (tedit 0)
  (attr through_hole)
  (fp_text reference "REF**" (at 0 -5.08) (layer "F.SilkS")
    (effects (font (size 1 1) (thickness 0.15))))
  (fp_text value "MY_DIP-8" (at 0 5.08) (layer "F.Fab")
    (effects (font (size 1 1) (thickness 0.15))))
  (fp_line (start -3.81 -3.81) (end 3.81 -3.81) (layer "F.SilkS") (width 0.12))
  (fp_line (start 3.81 -3.81) (end 3.81 3.81) (layer "F.SilkS") (width 0.12))
  (fp_line (start 3.81 3.81) (end -3.81 3.81) (layer "F.SilkS") (width 0.12))
  (fp_line (start -3.81 3.81) (end -3.81 -3.81) (layer "F.SilkS") (width 0.12))
  (pad "1" thru_hole rect (at -2.54 3.81) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))
  (pad "2" thru_hole oval (at 0 3.81) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))
  (pad "3" thru_hole oval (at 2.54 3.81) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))
  (model "${KICAD8_3DMODEL_DIR}/Package_DIP.3dshapes/DIP-8_W7.62mm.wrl"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))))
```

**Key elements:**
1. **Text items**: Reference (`REF**`), Value, and optional user text. Placed on specific layers (SilkS, Fab, etc.)
2. **Graphic items**: Lines (fp_line), circles (fp_circle), arcs (fp_arc), polygons (fp_poly) on silkscreen/fabrication/courtyard layers
3. **Pads**: Through-hole (thru_hole), SMD (smd), or edge connector (connect). Each has number, shape (rect/roundrect/oval/circle/custom), position, size, drill parameters, and layer assignment
4. **Courtyard**: Required boundary lines on F.CrtYd/B.CrtYd for DRC
5. **3D model**: Optional STEP/WRL model reference with offset/scale/rotate transforms

### kiutils API

```python
from kiutils.footprint import Footprint
from kiutils.items.fpitems import FpLine, FpCircle, FpArc, FpText
from kiutils.items.common import Pad, Position

# Footprint constructor:
# Footprint(libraryNickname, entryName, ...)

# Pad constructor:
# Pad(number, type, shape, position, size, drill, layers, ...)

# FpLine constructor:
# FpLine(start, end, layer, width, stroke, locked, tstamp)
# NOTE: FpLine does NOT have an effects parameter (unlike other graphical items)

# FpText constructor:
# FpText(type, text, position, layer, ...)
```

### Operation Needed

**`create_footprint` -- Create a new footprint in a footprint library**

Schema fields:
- `target_file`: Footprint library file path (.kicad_mod or .pretty directory)
- `footprint_name`: Name for the footprint entry (e.g., "MY_DIP-8")
- `reference_prefix`: Reference designator prefix (default "U")
- `value`: Default value text
- `pads`: List of PadSpec objects (new type needed)
- `body_lines`: List of graphic line definitions (start, end, layer, width)
- `courtyard`: Optional courtyard outline (list of line segments on F.CrtYd)
- `model_3d`: Optional 3D model reference path
- `attributes`: Through-hole, SMD, or board-only

New schema type needed -- `PadSpec`:
```python
class PadSpec(BaseModel):
    number: str = Field(min_length=1, max_length=32)
    pad_type: Literal["smd", "thru_hole", "connect"]
    shape: Literal["rect", "roundrect", "oval", "circle", "custom"]
    position: PositionSpec
    size_x: float = Field(gt=0, le=50)
    size_y: float = Field(gt=0, le=50)
    drill_diameter: Optional[float] = Field(default=None, gt=0, le=10)
    drill_offset_x: Optional[float] = None
    drill_offset_y: Optional[float] = None
    layers: list[str] = Field(min_length=1, max_length=32)
```

Implementation (following create_symbol pattern):
1. Check if target library file exists; create if not
2. Create kiutils Footprint object with libraryNickname and entryName
3. Build reference and value text items (FpText)
4. Build pad definitions from PadSpec list
5. Build courtyard and body graphic lines (FpLine)
6. Append footprint to library
7. Serialize with `_atomic_write`

### Edge Cases

1. **Footprint library format**: KiCad 10 uses .kicad_mod files (one footprint per file) inside .pretty directories. The target_file might be either the directory or an individual file. Must handle both.
2. **Pad layer strings**: Must use canonical KiCad layer names ("F.Cu", "B.Cu", "*.Cu", "*.Mask", "F.Paste"). Invalid layer names will break DRC.
3. **Drill parameters required for thru_hole**: Through-hole pads must have drill diameter. SMD pads must not. Must validate pad_type against drill presence.
4. **Courtyard requirements**: DRC expects courtyard outlines. Footprint without courtyard will generate DRC warnings. Should auto-generate courtyard from body bounds if not explicitly provided.
5. **FpLine has no effects parameter**: Unlike other graphical items, FpLine uses start/end/layer/width/stroke. The create_symbol handler uses different kiutils constructors. Must not accidentally pass effects to FpLine.
6. **Pad number uniqueness**: Duplicate pad numbers are allowed in KiCad (for multi-pad connections) but unusual. Should warn, not reject.
7. **3D model path resolution**: `${KICAD8_3DMODEL_DIR}` variable must be preserved as-is, not resolved at creation time.

### Completeness Criteria

The feature is complete when:
- Can create a footprint with pads, graphics, and courtyard in a .kicad_mod file
- KiCad opens the created footprint library without errors
- DRC passes on a PCB using the created footprint (assuming correct courtyard)
- Round-trip: create_footprint -> open in KiCad -> save -> parse back produces equivalent data

### Existing Infrastructure

- `src/kicad_agent/ops/create_file.py`: The `create_symbol` handler is the closest pattern. Same approach: build kiutils objects from specs, append to library, serialize.
- `src/kicad_agent/ir/footprint_ir.py`: FootprintIR wraps kiutils Footprint. Has pad and graphic item access.
- `src/kicad_agent/ops/_schema_create.py`: CreateSymbolOp with PinSpec. New CreateFootprintOp goes here with PadSpec.
- `src/kicad_agent/ops/schema.py`: PinSpec model exists as reference for PadSpec design.

### Complexity Assessment

**MEDIUM.** More new code than the other gaps (new PadSpec schema, new handler, footprint-specific edge cases), but the pattern from create_symbol is well-established and kiutils has the Footprint/FpLine/Pad classes.

---

## Gap 4: Connectivity Query Operation

### What This Is

`src/kicad_agent/analysis/connectivity.py` contains a full netlist graph analysis module (NetGraph using networkx). It can answer questions like "what nets connect to this component?", "are these two pads on the same net?", and "what are the connected components of this board?". But this capability is not exposed as an operation -- users cannot query it through the operation API.

### How It Works in KiCad

Connectivity in KiCad has two layers:

**Schematic connectivity** (implicit):
- Wires connect pins that overlap geometrically
- Labels (local, global, hierarchical) name nets -- pins connected to the same label name are on the same net
- Power symbols connect pins to power nets (VCC, GND, etc.)
- Bus entry points connect bus members to individual nets

**PCB connectivity** (explicit):
- Each pad has a `net` attribute with net name and net code
- Tracks/zones connect pads on the same net
- Copper zones fill areas connecting multiple pads

The existing NetGraph in `analysis/connectivity.py` handles **PCB connectivity only**. It builds an undirected graph where nodes are (footprint_ref, pad_number) tuples and edges connect pads on the same net.

### Operations Needed

**1. `query_connectivity` -- Query the connectivity graph**

Schema fields:
- `target_file`: PCB file path (.kicad_pcb)
- `query_type`: What to ask:
  - `"connected_pads"`: Given a reference + pad, what else is on the same net?
  - `"net_stats"`: Statistics for all nets (pad count, component count)
  - `"are_connected"`: Are two specific pads on the same net?
  - `"shortest_path"`: Shortest copper path between two pads
  - `"connected_components"`: Electrically isolated sub-graphs
  - `"net_list"`: All nets with their member pads
- `reference`: Component reference (for pad-specific queries)
- `pad_number`: Pad number (for pad-specific queries)
- `reference2`, `pad_number2`: Second pad (for pair queries)
- `net_name`: Filter by net name (for net-specific queries)

Implementation:
```python
from kicad_agent.analysis.connectivity import NetGraph

def query_connectivity(op, ir):
    graph = NetGraph(ir)
    if op.query_type == "connected_pads":
        pads = graph.get_connected_pads(op.reference, op.pad_number)
        return {"pads": [(ref, pad) for ref, pad in pads]}
    elif op.query_type == "net_stats":
        return graph.get_net_stats()
    # ... etc
```

**2. Future: `query_schematic_connectivity` -- Query schematic-level connectivity**

This is more complex because schematic connectivity is implicit (geometric wire overlap + label name matching). Would require:
- Wire endpoint overlap detection
- Label-to-pin association by position
- Power symbol net injection
- Cross-sheet label propagation

Not required for v2.2, but the operation schema should accommodate it.

### Edge Cases

1. **PCB without netlist**: A fresh PCB with no schematic link has no net assignments. All pads are unconnected. NetGraph should handle gracefully (empty graph or single-node components).
2. **Unconnected pads**: Pads with no net assignment appear as isolated nodes. Queries should return empty results, not errors.
3. **Large boards**: NetGraph builds from PcbIR which parses the full PCB. For boards with 10,000+ pads, graph construction may be slow. Consider caching the graph per executor session.
4. **Net name canonicalization**: KiCad net names may have different capitalization or whitespace than user expects. Queries should be case-insensitive.
5. **Multi-unit symbols**: A symbol with multiple units (e.g., a quad op-amp) has pads spread across units. Connectivity queries must handle the reference format (e.g., "U1A" vs "U1" for unit A).

### Completeness Criteria

The feature is complete when:
- Can query PCB connectivity through the operation API
- All five query types work (connected_pads, net_stats, are_connected, shortest_path, connected_components)
- Results are structured JSON, not raw networkx objects
- Handles empty/unpopulated PCBs without errors

### Existing Infrastructure

- `src/kicad_agent/analysis/connectivity.py`: Full NetGraph implementation with networkx. Methods: `get_connected_pads`, `shortest_path`, `are_connected`, `get_connectivity_components`, `get_net_stats`. Works with PcbIR.
- The gap is purely wiring -- creating the schema model, registering in executor, and calling the existing methods.

### Complexity Assessment

**LOW.** The analysis code exists and works. The gap is a schema definition (~30 lines), an executor handler (~40 lines), and registration. The only decision is the schema design for the `query_type` discriminator.

---

## Gap 5: Cross-File Atomic Wiring

### What This Is

`src/kicad_agent/crossfile/atomic.py` implements an `AtomicOperation` class that coordinates multiple file-level transactions in an all-or-nothing pattern. `crossfile/propagation.py` has functions for updating references across files. Neither is wired to the operation executor. No operation can currently perform mutations across multiple files atomically.

### How It Works

The cross-file infrastructure provides:

**AtomicOperation** (`crossfile/atomic.py`):
- Context manager wrapping multiple Transaction objects
- Each Transaction handles one file (snapshot, mutate, commit/rollback)
- If any file's mutation fails, all files roll back to snapshots
- `commit()` writes all files; `rollback()` restores all from backups
- Returns `AtomicResult` with per-file `DiffEntry` lists

**Propagation functions** (`crossfile/propagation.py`):
- `propagate_symbol_ref`: Update symbol references across schematic files when a library symbol changes
- `propagate_footprint_ref`: Update footprint references when a footprint library entry changes

**Project discovery** (`crossfile/__init__.py`):
- `discover_project`: Find all KiCad files in a project directory
- `detect_project_root`: Walk up from a file to find the project root
- `structural_diff`: Compare two KiCad files semantically

### What Needs Wiring

1. **New executor registry**: The executor has `_SCHEMATIC_HANDLERS`, `_PCB_HANDLERS`, `_PROJECT_HANDLERS`, `_CREATE_HANDLERS`. A new `_CROSSFILE_HANDLERS` registry (or extending `_PROJECT_HANDLERS`) is needed for operations that touch multiple files.

2. **Multi-file operation dispatch**: Current dispatch is one operation -> one file -> one IR -> one transaction. Cross-file operations need: one operation -> multiple files -> multiple IRs -> one AtomicOperation.

3. **Cross-file operation schema**: Operations that touch multiple files need a different target specification. Options:
   - `target_project`: Path to .kicad_pro file, discover all related files
   - `target_files`: List of TargetFile paths
   - `target_directory`: Project root directory

4. **Operations that need cross-file support** (initial set):
   - `propagate_symbol_change`: When a symbol library entry changes, update all schematics that use it
   - `propagate_footprint_change`: When a footprint library entry changes, update all PCBs that use it
   - `sync_schematic_pcb`: Push schematic changes (netlist, component changes) to the PCB
   - `full_annotate`: Annotate references across all sheets in a hierarchical design

### Edge Cases

1. **Partial failure**: If 3 of 5 files mutate successfully but the 4th fails, all must roll back. The AtomicOperation context manager handles this, but the executor must use it correctly.
2. **File locking**: Multiple transactions may try to lock the same file. fcntl locking is per-process on some systems. Must handle lock contention.
3. **Circular dependencies**: Propagation might trigger cascading updates (symbol change -> schematic update -> PCB update). Must detect and limit depth.
4. **Project discovery**: If the project structure is non-standard (files in unusual directories), discovery may miss files. Must be explicit about which files to touch.
5. **Race conditions**: If another process (KiCad GUI) modifies a file between snapshot and commit, the transaction is based on stale data. File locking mitigates but does not eliminate this.
6. **Large projects**: Atomic snapshots of many large files consume disk space and time. For a 50-sheet hierarchical design with a large PCB, snapshotting all files could take seconds.

### Completeness Criteria

The feature is complete when:
- At least one cross-file operation works end-to-end (propagate_symbol_change is the simplest)
- Atomic rollback works: if any file fails, all files restore to pre-operation state
- Executor dispatch supports multi-file operations alongside single-file operations
- Project discovery works for standard KiCad project layouts

### Existing Infrastructure

- `src/kicad_agent/crossfile/atomic.py`: AtomicOperation, AtomicResult, full all-or-nothing transaction logic.
- `src/kicad_agent/crossfile/propagation.py`: propagate_symbol_ref, propagate_footprint_ref.
- `src/kicad_agent/crossfile/__init__.py`: Project discovery, structural diff.
- `src/kicad_agent/ir/transaction.py`: Per-file transaction with snapshot, commit, rollback, file locking.

The gap is entirely wiring: schema models, executor registration, and handler functions that compose existing infrastructure.

### Complexity Assessment

**MEDIUM.** The infrastructure is complete. The complexity is in the executor integration -- the current dispatch pattern assumes one file per operation. Supporting multi-file operations requires either a new dispatch path or a wrapper that creates multiple single-file operations inside an AtomicOperation. The design decision here affects future operations.

---

## Feature Classification

### Table Stakes (Missing = Product Feels Incomplete)

| Feature | Why Expected | Complexity | Dependencies |
|---------|--------------|------------|--------------|
| Hierarchical sheet operations | Real KiCad projects use hierarchy. An agent that cannot navigate or create sub-sheets cannot handle production designs. | HIGH | None (root_sheet.py provides foundation) |
| Remove operations (wire, label, junction) | Add-only API feels broken. Users expect symmetric add/remove. If you can add a wire, you must be able to remove it. | LOW | None (pattern exists) |
| Connectivity query | Users need to ask "what connects to what?" The analysis code exists; not exposing it is a gap. | LOW | None (analysis/connectivity.py exists) |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Dependencies |
|---------|-------------------|------------|--------------|
| Footprint creation | No other KiCad automation tool lets you create footprints through a JSON operation schema. Enables full programmable footprint generation. | MEDIUM | kiutils Footprint API |
| Cross-file atomic operations | True multi-file atomic transactions are unique. KiBot and kicad-python do not provide this. Enables safe project-wide mutations. | MEDIUM | crossfile/atomic.py exists |

### Anti-Features (Explicitly Not Building)

| Feature | Why Avoid | What to Do Instead |
|---------|-----------|-------------------|
| Auto-generated hierarchical pin/label sync | Automatically creating/deleting pins when labels change is fragile and surprises users. | Explicit add_sheet_pin operation. User controls pin creation. |
| Remove-by-pattern (wildcard removal) | "Remove all wires in region X" is dangerous in AI hands. One bad intent could delete an entire schematic. | Single-element removal by UUID or precise coordinates only. |
| Schematic connectivity graph | Building connectivity from geometric wire overlap is complex and error-prone. Not needed for v2.2. | PCB connectivity query only (explicit net assignments). Defer schematic connectivity. |
| Footprint wizard (parameterized generators) | "Create a DIP-8 footprint" with auto-calculated pad positions is valuable but scope-creeping. | Explicit pad position specification. Parameterized generators are a future extension. |

---

## Dependencies and Ordering

```
[Remove Operations]           -- no deps, simplest, pattern exists
        |
        v
[Connectivity Query]          -- no deps, wraps existing code
        |
        v
[Cross-File Wiring]           -- no deps, wires existing infra
        |
        v
[Footprint Creation]          -- no deps, most new code
        |
        v
[Hierarchical Sheet Ops]      -- most complex, highest value
        |
        v
(Cross-file + hierarchy combined -- future phase)
```

**Why this order:**

1. **Remove operations first**: Lowest risk, clearest pattern. Validates the add/remove symmetry. Three operations in ~150 lines of handler code total.

2. **Connectivity query second**: Wraps existing code. Exercises the schema -> executor -> IR path for read-only operations (no mutation). Good warm-up for more complex operations.

3. **Cross-file wiring third**: Medium complexity but the infrastructure is complete. The design decision here (how to extend the executor) affects future operations, so doing it before the complex features lets the pattern settle.

4. **Footprint creation fourth**: Most new code. Requires new PadSpec schema type. Benefits from having the executor extension pattern established by cross-file wiring.

5. **Hierarchical sheets last**: Highest complexity, highest value. The root_sheet.py code provides navigation, but creating new sheets with correct UUID paths and instance tracking is the hardest part. Doing it last means the operation patterns are well-established.

---

## MVP Recommendation

### v2.2 Must-Have (All 5 Gaps)

All five gaps are in the milestone scope. Recommended implementation order:

1. **Remove operations** (3 ops: remove_wire, remove_label, remove_junction) -- 1-2 days
2. **Connectivity query** (1 op: query_connectivity) -- 0.5-1 day
3. **Cross-file wiring** (1 op: propagate_symbol_change, executor extension) -- 2-3 days
4. **Footprint creation** (1 op: create_footprint, PadSpec schema) -- 2-3 days
5. **Hierarchical sheets** (3 ops: add_sheet, add_sheet_pin, navigate_hierarchy) -- 3-5 days

### Defer to Later

- `remove_no_connect`: Follows the same pattern as remove_junction. Not blocking.
- `remove_power_symbol`: Removing power symbols is just remove_component with a power: prefix. Not a separate operation.
- Schematic connectivity graph: Requires geometric wire overlap analysis. Not needed for v2.2.
- Footprint wizard/parameterized generators: Explicit positions only for now.

---

## Sources

- `src/kicad_agent/ops/schema.py` -- 47+ operation schemas, discriminated union pattern
- `src/kicad_agent/ops/remove_component.py` -- Remove operation pattern
- `src/kicad_agent/ops/create_file.py` -- Create operation pattern (create_symbol)
- `src/kicad_agent/ops/root_sheet.py` -- Hierarchical navigation logic
- `src/kicad_agent/ops/hlabel_guard.py` -- Hierarchical label validation
- `src/kicad_agent/ir/schematic_ir.py` -- SchematicIR with add/remove/query methods
- `src/kicad_agent/ir/footprint_ir.py` -- FootprintIR for PCB footprint access
- `src/kicad_agent/ir/transaction.py` -- Per-file transaction with rollback
- `src/kicad_agent/crossfile/atomic.py` -- Multi-file atomic operation
- `src/kicad_agent/crossfile/propagation.py` -- Cross-file reference propagation
- `src/kicad_agent/analysis/connectivity.py` -- NetGraph with networkx
- `src/kicad_agent/ops/_schema_wire.py` -- Wire/label/junction add schemas
- `src/kicad_agent/ops/_schema_create.py` -- Create operation schemas
- `src/kicad_agent/ops/executor.py` -- Operation dispatch and handler registries
- `KNOWN_LIMITATIONS.md` -- H-1, M-1, M-3, M-4, M-6 gap documentation
- kiutils API inspection -- HierarchicalSheet, HierarchicalPin, Footprint, Pad, FpLine constructors
- KiCad S-expression file format specification (dev-docs.kicad.org)

---
*Feature gap research for: kicad-agent v2.2 complete-ops milestone*
*Researched: 2026-05-29*
*Confidence: HIGH*
