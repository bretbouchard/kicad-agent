# Stack Research -- Milestone v2.2 complete-ops

**Domain:** KiCad 10+ automation agent -- new operation capabilities
**Researched:** 2026-05-29
**Confidence:** HIGH

## Executive Summary

All five new capabilities (hierarchical sheets, remove operations, footprint creation, connectivity query, cross-file wiring) can be built entirely with the **existing stack**. No new dependencies are required. The work is integration, not invention -- kiutils already provides `HierarchicalSheet`, `HierarchicalPin`, `Footprint.create_new()`, and `Pad` classes; `crossfile/atomic.py` is already built; `analysis/connectivity.py` already has the `NetGraph`. The gap is wiring these to the operation executor.

## Existing Stack (No Changes Needed)

| Technology | Version | Status | Role in New Features |
|------------|---------|--------|---------------------|
| kiutils | 1.4.8 | INSTALLED | Provides `HierarchicalSheet`, `HierarchicalPin`, `Footprint`, `Pad`, `Schematic.sheets` -- all needed APIs verified present |
| pydantic | 2.12.5 | INSTALLED | New operation schemas follow existing `_schema_*.py` pattern |
| networkx | 3.6.1 | INSTALLED | `NetGraph` in `analysis/connectivity.py` already built on networkx |
| sexpdata | 1.0.0 | INSTALLED | Fallback if kiutils gaps found (unlikely for these features) |

**Verdict: Zero new pip installs.** The entire milestone is wiring existing infrastructure to the executor.

---

## Feature-by-Feature Stack Analysis

### 1. Hierarchical Sheet Operations (add_sheet, add_sheet_pin, sheet navigation)

**kiutils API verified present:**

| Class | Module | Constructor Fields |
|-------|--------|-------------------|
| `HierarchicalSheet` | `kiutils.items.schitems` | `position`, `width`, `height`, `sheetName`, `fileName`, `properties`, `pins` (list of HierarchicalPin), `instances` |
| `HierarchicalPin` | `kiutils.items.schitems` | `name`, `connectionType` (str: "input"/"output"/"bidirectional"/"passive"/"tri_state"), `position`, `effects`, `uuid` |

**Access pattern on Schematic object:**
```python
sch = Schematic.create_new()
sch.sheets          # list[HierarchicalSheet] -- sheet instances on root
sch.sheetInstances  # list[HierarchicalSheetInstance] -- instance tracking
```

**Existing precedent:** `root_sheet.py` already demonstrates sheet iteration (`for sheet in sch.sheets`), pin creation via `HierarchicalPin`, and pin rebuilding via `_rebuild_sheet_pins()`. The `rebuild_root_sheet` operation already works -- the new operations add/create/navigate instead of rebuild.

**What to build:**
- `AddSheetOp` schema -- target_file, sheet_name, file_name, position, width, height
- `AddSheetPinOp` schema -- target_file, sheet_index (or sheet_file_name), pin_name, connection_type, side ("left"/"right"), pin_index
- `NavigateSheetsOp` schema -- target_file (returns sheet hierarchy)
- Handler implementations using kiutils `HierarchicalSheet` / `HierarchicalPin` constructors
- Sheet file creation: when adding a sheet, also create the referenced `.kicad_sch` via existing `create_schematic` pattern

**Confidence: HIGH** -- kiutils API is complete, existing code demonstrates the pattern.

### 2. Remove Operations (remove_wire, remove_label, remove_junction, remove_no_connect)

**kiutils access points:**
```python
# Wires: Connection objects in graphicalItems with type="wire"
sch.graphicalItems    # list -- filter for Connection(type="wire")
# Labels: separate lists per type
sch.labels            # list[LocalLabel]
sch.globalLabels      # list[GlobalLabel]
sch.hierarchicalLabels # list[HierarchicalLabel]
# Junctions
sch.junctions         # list[Junction]
# No-connects
sch.noConnects        # list[NoConnect]
```

**Existing precedent:** `add_wire`, `add_label`, `add_junction`, `add_no_connect` all exist in `SchematicIR` and are registered in the executor. The remove operations are the symmetric inverse -- find by UUID or position, remove from the list.

**Removal strategy:**
- By UUID (preferred): each element has a `uuid` field. Filter the list, remove matching.
- By position (fallback): match on `(x, y)` coordinates with tolerance.
- By name (for labels): match on `text` field.

**What to build:**
- `RemoveWireOp` schema -- target_file, uuid OR (start_x, start_y, end_x, end_y with tolerance)
- `RemoveLabelOp` schema -- target_file, name, label_type (optional filter)
- `RemoveJunctionOp` schema -- target_file, uuid OR (x, y with tolerance)
- `RemoveNoConnectOp` schema -- target_file, uuid OR (x, y with tolerance)
- Handler implementations: filter list, remove match, record mutation

**Confidence: HIGH** -- pure list manipulation on kiutils objects. No API gaps.

### 3. Footprint Creation (create_footprint)

**kiutils API verified present:**

| Class | Module | Key Fields |
|-------|--------|-----------|
| `Footprint` | `kiutils.footprint` | `libraryNickname`, `entryName`, `pads` (list of `Pad`), `graphicItems`, `description`, `tags`, `layer` |
| `Pad` | `kiutils.footprint` | `number`, `type` ("smd"/"thru_hole"/"connect"/"np_thru_hole"), `shape` ("rect"/"circle"/"oval"/...), `position`, `size`, `drill`, `layers`, `net` |

**Footprint.create_new()** signature:
```python
Footprint.create_new(library_id, value, type="other", reference="REF**")
```

**Existing precedent:** `create_symbol` in `create_file.py` demonstrates the exact pattern: create via kiutils constructor, build child objects (pins/pads), set properties, write to file, normalize output. `create_footprint` follows the same structure with `Footprint` + `Pad` instead of `Symbol` + `SymbolPin`.

**Target file type:** `.kicad_mod` -- already in `TargetFile` valid extensions (verified in `schema.py:153`).

**What to build:**
- `CreateFootprintOp` schema -- target_file (.kicad_mod), footprint_name, pads list (PadSpec reuse), description, graphic body items
- `PadSpec` reuse: the existing `PinSpec` in `schema.py` is symbol-specific. Need a new `FootprintPadSpec` with `number`, `type` (smd/thru_hole/connect/np_thru_hole), `shape`, `position`, `size`, `drill_diameter`, `layers`
- Handler: `Footprint.create_new()`, add pads, write to file, normalize

**Key difference from create_symbol:** Footprints need pad drill specification (for thru-hole), layer assignment, and courtyard/assembly outline. The schema must capture these.

**Confidence: HIGH** -- kiutils `Footprint` and `Pad` are complete. Pattern follows `create_symbol` exactly.

### 4. Connectivity/Netlist Query Operation

**Existing infrastructure (already built, not wired):**

```python
# analysis/connectivity.py -- fully functional NetGraph
graph = NetGraph.from_pcb_ir(pcb_ir)
connected = graph.get_connected_pads("GND")
path = graph.shortest_path(("J1", "1"), ("U1", "5"))
components = graph.are_connected(("R1", "1"), ("R2", "2"))
islands = graph.get_connectivity_components()
stats = graph.get_net_stats()
```

**What to build:**
- `QueryConnectivityOp` schema -- target_file (.kicad_pcb), query_type ("net_pads"/"shortest_path"/"are_connected"/"components"/"stats"), query_params (net_name, source_pad, target_pad depending on query_type)
- Handler: parse PCB, build PcbIR, create NetGraph, run query, return results
- Registration: PCB handler in executor (like `auto_route` which also creates analysis objects)

**Confidence: HIGH** -- `NetGraph` is already built and tested. Just needs schema + handler + registration.

### 5. Cross-file Atomic Operations Wiring

**Existing infrastructure (already built, not wired):**

```python
# crossfile/atomic.py -- fully functional AtomicOperation
with AtomicOperation([schematic_path, pcb_path]) as atomic:
    # ... perform mutations on both files ...
    result = atomic.commit()
```

**What to build:**
- Cross-file operation schemas that accept multiple target files
- Handler that instantiates `AtomicOperation`, parses each file, creates IRs per file, dispatches sub-operations, commits
- Registration: new handler category in executor (or extension of existing pattern)

**Key integration point:** The executor currently handles one file per operation (`D-03: Single file per operation`). Cross-file ops break this constraint. Two approaches:
1. **New handler category** (recommended): Add `_CROSSFILE_HANDLERS` registry alongside existing `_SCHEMATIC_HANDLERS`/`_PCB_HANDLERS`/`_CREATE_HANDLERS`. Cross-file ops bypass single-file constraint.
2. **Compound operation wrapper**: Wrap multiple operations in a single cross-file envelope.

Approach 1 is cleaner -- it extends the existing decorator pattern without modifying the atomic operation constraint.

**Confidence: MEDIUM** -- the `AtomicOperation` infrastructure works, but the executor routing needs careful design to maintain the single-file security model while allowing multi-file atomicity. The path confinement checks (T-24-01) must be applied to each file individually.

---

## New Schema Files Needed

| File | Operations | Pattern Follows |
|------|-----------|----------------|
| `_schema_sheet.py` | `AddSheetOp`, `AddSheetPinOp`, `NavigateSheetsOp` | `_schema_create.py` (has CreateSchematicOp) |
| `_schema_remove.py` | `RemoveWireOp`, `RemoveLabelOp`, `RemoveJunctionOp`, `RemoveNoConnectOp` | `_schema_wire.py` (symmetric inverse) |
| `_schema_create.py` (extend) | `CreateFootprintOp` | Existing `CreateSymbolOp` pattern |
| `_schema_connectivity.py` | `QueryConnectivityOp` | `_schema_validation.py` (query-only ops) |
| `_schema_crossfile.py` | Cross-file compound operations | New pattern (multi-target_file) |

## New Handler Files Needed

| File | Registration Type | Notes |
|------|------------------|-------|
| `ops/sheet_ops.py` | `register_schematic` | Sheet/pin creation and navigation |
| `ops/remove_ops.py` | `register_schematic` | Wire/label/junction/no-connect removal |
| `ops/create_file.py` (extend) | `register_create` | Add `create_footprint` to existing file |
| `ops/connectivity_query.py` | `register_pcb` | NetGraph query wrapper |
| `ops/crossfile_ops.py` | New `_CROSSFILE_HANDLERS` | Multi-file atomic operations |

## What NOT to Add

| Avoid | Why |
|-------|-----|
| Any new pip dependency | All five features use existing kiutils, networkx, pydantic APIs. No gaps found. |
| New parser layer | kiutils handles all needed file types. No raw sexpdata needed. |
| Custom footprint library format | kiutils `Footprint` produces standard `.kicad_mod` files. No custom format. |
| Graph database for connectivity | networkx `NetGraph` is already built and sufficient for query operations. |
| Separate microservice for cross-file ops | `AtomicOperation` runs in-process. No network overhead needed. |
| New validation engine | ERC/DRC via kicad-cli covers validation. Cross-file ops use same gates per file. |
| KiCad Python API (pcbnew module) | Requires KiCad runtime. kiutils is standalone. |

---

## Version Verification

| Package | Version | Required For | Status |
|---------|---------|-------------|--------|
| kiutils | 1.4.8 | HierarchicalSheet, HierarchicalPin, Footprint, Pad | Verified -- all APIs present |
| pydantic | 2.12.5 | New operation schemas | Verified -- discriminated union pattern works |
| networkx | 3.6.1 | NetGraph connectivity queries | Verified -- already in analysis/connectivity.py |
| sexpdata | 1.0.0 | Fallback parser | Not needed for these features |
| kicad-cli | 10.0.1 | Post-edit validation | Already used for ERC/DRC gates |

## Integration Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| kiutils HierarchicalSheet serialization differs from KiCad's format | MEDIUM | Round-trip test: create sheet, write, read back, compare. `root_sheet.py` already does this successfully. |
| Footprint.create_new() output missing courtyard | LOW | Add courtyard outline as graphic items. Standard KiCad practice. |
| Cross-file ops break executor's single-file security model | MEDIUM | New handler category with per-file path confinement checks. |
| Remove-by-position fails with floating-point precision | LOW | Use UUID-based removal as primary, position as fallback with tolerance. |
| NetGraph query on large PCBs is slow | LOW | networkx handles thousands of nodes efficiently. Add caching if needed. |

---

## Confidence Assessment

| Feature | Confidence | Reason |
|---------|------------|--------|
| Hierarchical sheets | HIGH | kiutils API verified, existing root_sheet.py demonstrates the pattern |
| Remove operations | HIGH | Symmetric inverse of existing add operations, pure list manipulation |
| Footprint creation | HIGH | kiutils Footprint+Pad API verified, follows create_symbol pattern exactly |
| Connectivity query | HIGH | NetGraph already built, just needs schema+handler wiring |
| Cross-file wiring | MEDIUM | AtomicOperation works, but executor routing needs design care |

## Sources

- Live Python inspection of kiutils 1.4.8: `HierarchicalSheet`, `HierarchicalPin`, `Footprint`, `Pad`, `Schematic.sheets` APIs
- Existing codebase: `executor.py` (handler registration pattern), `schema.py` (Pydantic schema pattern), `create_file.py` (create_symbol precedent), `root_sheet.py` (sheet iteration precedent), `schematic_ir.py` (add_wire/label/junction pattern), `crossfile/atomic.py` (atomic operation infrastructure), `analysis/connectivity.py` (NetGraph infrastructure)
- KNOWN_LIMITATIONS.md: H-1, M-1, M-3, M-4, M-6 -- documented gaps this milestone addresses

---
*Stack research for: kicad-agent milestone v2.2 complete-ops*
*Researched: 2026-05-29*
