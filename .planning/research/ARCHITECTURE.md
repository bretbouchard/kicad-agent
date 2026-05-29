# Architecture: complete-ops Milestone (v2.2)

**Domain:** Integration architecture for 5 feature gaps in existing kicad-agent
**Researched:** 2026-05-29
**Confidence:** HIGH (direct codebase analysis, no external dependencies)

## Executive Summary

The existing kicad-agent follows a strict pipeline: **Parser -> IR -> Operation Handler -> Serializer -> Transaction**. Every operation flows through the executor, which dispatches by `op_type` to registered handlers using one of four registries (`_SCHEMATIC_HANDLERS`, `_PCB_HANDLERS`, `_PROJECT_HANDLERS`, `_CREATE_HANDLERS`). Each handler receives the appropriate IR object and returns a dict. All mutations are wrapped in `Transaction` for rollback safety.

The 5 new features fit into this pipeline with varying degrees of disruption. Two features (remove operations, connectivity query) are straightforward additions to existing registries. Two features (hierarchical sheets, footprint creation) require new schema sub-modules and handler modules but no pipeline changes. One feature (cross-file wiring) is the most complex because it requires a new execution path in the executor that coordinates multiple files atomically.

No new IR layer is needed for any feature. The existing `SchematicIR` already wraps kiutils `Schematic` which has `sheets` and `sheetInstances` attributes. The existing `FootprintIR` wraps kiutils `Footprint`. The existing `PcbIR` and `NetGraph` provide everything connectivity queries need.

## Recommended Architecture

### Data Flow (Unchanged Pipeline)

```
LLM JSON -> Operation (Pydantic validate) -> OperationExecutor.execute()
    -> [branch by file type]
    -> Parse file -> Build IR -> Transaction wraps handler call
    -> Handler mutates IR -> Serialize -> Normalize -> Commit
```

No pipeline changes needed for any of the 5 features. The executor's existing 4-registry dispatch pattern accommodates all of them.

### Component Boundaries

| Component | Responsibility | Status |
|-----------|---------------|--------|
| `ops/_schema_sheet.py` | NEW: Pydantic models for sheet ops (add_sheet, add_sheet_pin) | Must create |
| `ops/sheet_ops.py` | NEW: Handler implementations for sheet operations | Must create |
| `ops/_schema_wire.py` | MODIFIED: Add RemoveWireOp, RemoveLabelOp, RemoveJunctionOp | Extend existing |
| `ops/_schema_create.py` | MODIFIED: Add CreateFootprintOp | Extend existing |
| `ops/create_file.py` | MODIFIED: Add create_footprint handler | Extend existing |
| `ops/_schema_query.py` | NEW: Pydantic model for connectivity query | Must create |
| `ops/connectivity_query.py` | NEW: Handler that wraps NetGraph.from_pcb_ir | Must create |
| `ops/executor.py` | MODIFIED: Wire new handlers, add _CROSS_FILE_OPS path | Extend existing |
| `ops/schema.py` | MODIFIED: Import and re-export new Op classes | Extend existing |
| `ir/schematic_ir.py` | MODIFIED: Add remove_wire, remove_label, remove_junction methods | Extend existing |
| `crossfile/atomic.py` | UNCHANGED: Already built, just needs wiring | Wire, don't modify |
| `analysis/connectivity.py` | UNCHANGED: Already built, just needs operation exposure | Wire, don't modify |

## Feature Integration Plans

### Feature 1: Hierarchical Sheet Operations

**What:** `add_sheet` and `add_sheet_pin` operations to create and modify hierarchical schematic sheets.

**KiCad Representation:**
Sheets in `.kicad_sch` are `HierarchicalSheet` objects stored in `Schematic.sheets` (a list). Each sheet has:
- `position` (Position), `width` (float), `height` (float)
- `sheetName` (Property with key "Sheet name")
- `fileName` (Property with key "Sheet file") -- the referenced `.kicad_sch` file
- `pins` (list of `HierarchicalPin`) -- the connection points on the sheet symbol
- `uuid`, `stroke`, `fill`, `properties`, `instances`

**Integration approach:**

1. **New schema module:** `ops/_schema_sheet.py`
   - `AddSheetOp(BaseModel)`: op_type="add_sheet", target_file, sheet_name, file_name, position, width, height
   - `AddSheetPinOp(BaseModel)`: op_type="add_sheet_pin", target_file, sheet_name (or sheet_uuid), pin_name, connection_type, position

2. **New handler module:** `ops/sheet_ops.py`
   - `add_sheet(op, ir, file_path)`: Creates a `HierarchicalSheet` via kiutils, appends to `ir.schematic.sheets`, creates the referenced sub-sheet file if it doesn't exist
   - `add_sheet_pin(op, ir, file_path)`: Finds sheet by name, creates `HierarchicalPin`, appends to sheet.pins

3. **Registry:** Both register as `_SCHEMATIC_HANDLERS`

4. **SchematicIR additions:** None needed -- kiutils `Schematic.sheets` is already accessible via `ir.schematic`

5. **Sub-sheet file creation:** `add_sheet` should auto-create the referenced `.kicad_sch` file using the existing `create_schematic()` from `create_file.py`. This is a cross-file concern but within the same project, so path resolution via `file_path.parent` suffices.

**No new IR layer needed.** The kiutils `HierarchicalSheet` object is fully typed. The existing `SchematicIR.schematic` property provides direct access to `schematic.sheets`.

**Dependencies:** None. Can be built independently.

```
add_sheet flow:
  Executor -> _dispatch("add_sheet") -> sheet_ops.add_sheet()
    -> kiutils HierarchicalSheet(position, width, height, sheetName, fileName)
    -> ir.schematic.sheets.append(sheet)
    -> create_file.create_schematic(sub_sheet_path)  # auto-create sub-sheet
    -> return {"sheet_name", "file_name", "pins": []}
```

### Feature 2: Remove Operations (Wire, Label, Junction)

**What:** `remove_wire`, `remove_label`, `remove_junction` operations -- the inverse of existing add operations.

**Integration approach:**

1. **Extend schema:** `ops/_schema_wire.py`
   - `RemoveWireOp(BaseModel)`: op_type="remove_wire", target_file, start_x, start_y, end_x, end_y (match by coordinates) OR uuid
   - `RemoveLabelOp(BaseModel)`: op_type="remove_label", target_file, name, label_type, position
   - `RemoveJunctionOp(BaseModel)`: op_type="remove_junction", target_file, position

2. **SchematicIR additions:**
   - `remove_wire(start_x, start_y, end_x, end_y)`: Find Connection with type="wire" in `graphicalItems`, remove matching entry. Match by coordinates (within tolerance) or by UUID.
   - `remove_label(name, label_type, x, y)`: Remove from appropriate list (`labels`, `globalLabels`, `hierarchicalLabels`)
   - `remove_junction(x, y)`: Remove from `junctions` by position match

3. **Registry:** All three register as `_SCHEMATIC_HANDLERS`

4. **Matching strategy:** Position-based matching with tolerance (0.01mm grid snap). UUID matching as optional alternative for unambiguous removal.

**Dependencies:** None. Can be built independently.

```
remove_wire flow:
  Executor -> _dispatch("remove_wire") -> handler calls ir.remove_wire()
    -> iterate graphicalItems, find Connection with type="wire"
    -> match by coordinates (within tolerance) or UUID
    -> remove from list, record mutation
    -> return {"removed": true, "start": [...], "end": [...]}
```

### Feature 3: Footprint Creation

**What:** `create_footprint` operation -- mirrors existing `create_symbol` but for `.kicad_mod` files.

**KiCad Representation:**
Footprints are stored as individual `.kicad_mod` files (one footprint per file) OR within `.kicad_sym`-style library collections. The kiutils `Footprint` dataclass has fields: `libraryNickname`, `entryName`, `layer`, `position`, `properties` (dict), `pads`, `graphicItems`, `zones`, `models`, etc.

**Integration approach:**

1. **Extend schema:** `ops/_schema_create.py`
   - `CreateFootprintOp(BaseModel)`: op_type="create_footprint", target_file, footprint_name, pads (list of PadSpec), courtyards, reference_prefix, value
   - New `FootprintPadSpec` for footprint pads (different fields than symbol pins): number, shape, size_x, size_y, drill_diameter, pad_type, layer_set

2. **Extend create handler:** `ops/create_file.py`
   - `create_footprint(op, file_path)`: Create kiutils `Footprint`, set properties, add pads, write to file
   - Follow same pattern as `create_symbol`: if file exists, check for duplicate name; if not, create fresh

3. **Registry:** Register in `_CREATE_HANDLERS`, add "create_footprint" to `_CREATE_OP_TYPES`

4. **Serializer:** Already exists in `serializer/footprint_ser.py` for footprint files

**Important distinction from create_symbol:** Footprint pads have physical properties (drill size, copper layers, pad shape) that symbol pins do not. The PadSpec for footprints needs different fields.

**Dependencies:** None. Can be built independently.

```
create_footprint flow:
  Executor -> _execute_create(op, file_path)
    -> create_file.create_footprint(op, file_path)
    -> kiutils Footprint(libraryNickname, entryName, layer="F.Cu")
    -> Add Reference/Value properties
    -> Build pads from op.pads
    -> Footprint.to_file()
    -> return {"footprint_name", "pad_count"}
```

### Feature 4: Connectivity Query

**What:** Read-only operation to query net connectivity. Exposes existing `NetGraph` from `analysis/connectivity.py`.

**Integration approach:**

1. **New schema module:** `ops/_schema_query.py`
   - `QueryConnectivityOp(BaseModel)`: op_type="query_connectivity", target_file (must be .kicad_pcb), query_type (one of: "net_pads", "path", "components", "stats"), parameters (query-specific: net_name, source_pad, target_pad)

2. **New handler module:** `ops/connectivity_query.py`
   - Build `NetGraph.from_pcb_ir(ir)` inside handler
   - Dispatch by query_type:
     - "net_pads": `graph.get_connected_pads(net_name)`
     - "path": `graph.shortest_path(source, target)`
     - "components": `graph.get_connectivity_components()`
     - "stats": `graph.get_net_stats()`

3. **Registry:** Register in `_PCB_HANDLERS` (targets .kicad_pcb files)

4. **Read-only semantics:** This operation does NOT mutate the IR. No `_record_mutation()` call. The Transaction still wraps it (executor pattern), but the commit just cleans up the snapshot without changes.

**Why not a separate read-only registry:** Adding a 5th registry for read-only ops would add complexity for no benefit. The existing Transaction pattern handles non-mutations correctly -- the snapshot is taken and discarded on commit, which is a clean no-op. Keeping it in `_PCB_HANDLERS` follows the established pattern.

**Dependencies:** None. Can be built independently.

```
query_connectivity flow:
  Executor -> _execute_pcb(op, file_path)
    -> parse_pcb, build PcbIR
    -> Transaction wraps (no mutation will occur)
    -> connectivity_query.handle(op, ir, file_path)
      -> NetGraph.from_pcb_ir(ir)
      -> dispatch by query_type
      -> return results dict
    -> serialize (no-op, no changes)
    -> Transaction.commit()
```

### Feature 5: Cross-file Wiring

**What:** Wire `crossfile/atomic.py` to the executor so operations can atomically modify multiple files.

**The core problem:** The executor currently handles one file per operation. `AtomicOperation` already exists and handles multi-file transactions, but no operation uses it. The wiring requires a new execution path.

**Integration approach:**

1. **New execution path in executor:** `_execute_cross_file()`
   - Triggered by operations with `op_type` in a new `_CROSS_FILE_OP_TYPES` set
   - Coordinates parsing multiple files, building IRs, calling handlers, serializing all files
   - Uses `AtomicOperation` for rollback coordination

2. **New handler registry:** `_CROSS_FILE_HANDLERS`
   - Handlers receive `dict[Path, BaseIR]` instead of single IR
   - Handler signature: `(op, ir_map, base_dir) -> dict`

3. **New schema:** `ops/_schema_crossfile.py`
   - `SyncSchematicPcbOp`: op_type="sync_schematic_pcb", schematic_file, pcb_file -- sync net names between schematic and PCB
   - `PropagateLibRefOp`: op_type="propagate_lib_ref", target_files, old_ref, new_ref -- propagate a library reference change across files

4. **Executor changes:**
   ```python
   _CROSS_FILE_OP_TYPES = {"sync_schematic_pcb", "propagate_lib_ref"}

   def execute(self, op):
       # ... existing path confinement ...
       if root.op_type in _CROSS_FILE_OP_TYPES:
           return self._execute_cross_file(op, file_path)
       # ... rest of existing logic ...
   ```

5. **_execute_cross_file implementation:**
   ```python
   def _execute_cross_file(self, op, file_path):
       # 1. Determine file paths from operation
       file_paths = self._resolve_cross_file_paths(op)
       # 2. Parse all files, build IR map
       ir_map = {}
       for fp in file_paths:
           parse_result = parse_schematic(fp) or parse_pcb(fp)
           ir_map[fp] = build_ir(parse_result)
       # 3. Open AtomicOperation for all files
       with AtomicOperation(file_paths) as atomic:
           details = handler(op, ir_map, self._base_dir)
           # Serialize all modified IRs
           for fp, ir in ir_map.items():
               if ir.dirty:
                   serialize(ir, fp)
           result = atomic.commit()
       return {...}
   ```

6. **Wire existing propagation functions:** `crossfile/propagation.py` already has `propagate_symbol_ref()` and `propagate_footprint_ref()`. These become the handler implementations for `propagate_lib_ref`.

**Dependencies:** This is the most complex feature. It depends on `crossfile/atomic.py` (built), `crossfile/propagation.py` (built), and requires executor modifications. It should be built LAST.

```
propagate_lib_ref flow:
  Executor -> _execute_cross_file(op)
    -> resolve file paths (schematic + pcb)
    -> parse both files, build ir_map
    -> AtomicOperation wraps both files
    -> handler calls propagate_symbol_ref() + propagate_footprint_ref()
    -> serialize both files if dirty
    -> AtomicOperation.commit()
    -> return {"schematic_updated": N, "pcb_updated": M}
```

## Patterns to Follow

### Pattern 1: Schema Sub-module Extension
**What:** Each operation domain gets its own `_schema_*.py` file imported by `schema.py`
**When:** Adding any new operation type
**Example:**
```python
# ops/_schema_sheet.py
class AddSheetOp(BaseModel):
    op_type: Literal["add_sheet"] = "add_sheet"
    target_file: TargetFile
    sheet_name: str = Field(min_length=1, max_length=128)
    file_name: str = Field(min_length=1, max_length=256)
    position: PositionSpec
    width: float = Field(default=30.0, gt=0, le=500)
    height: float = Field(default=20.0, gt=0, le=500)
```

### Pattern 2: Handler Registration
**What:** Decorator-based registration in executor.py
**When:** Adding any new operation handler
**Example:**
```python
@register_schematic("add_sheet")
def _handle_add_sheet(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.sheet_ops import add_sheet
    return add_sheet(op, ir, file_path)
```

### Pattern 3: IR Mutation Method
**What:** All mutations go through IR methods that call `_record_mutation()`
**When:** Adding any data-modifying capability
**Example:**
```python
def remove_wire(self, start_x, start_y, end_x, end_y) -> dict[str, Any]:
    # ... find and remove matching wire ...
    self._record_mutation("remove_wire", {"start": [...], "end": [...]})
    return {"removed": True, ...}
```

### Pattern 4: Lazy Import in Handlers
**What:** Handler functions use lazy imports for their implementation modules
**When:** Always (avoids circular imports, keeps executor lightweight)
**Example:** `from kicad_agent.ops.sheet_ops import add_sheet` inside the handler function body

## Anti-Patterns to Avoid

### Anti-Pattern 1: New IR Layer for Sheets
**What:** Creating a SheetIR class separate from SchematicIR
**Why bad:** kiutils `HierarchicalSheet` is a child of `Schematic`, not a separate file type. Sheets are stored within `.kicad_sch` files. A separate IR would break the one-IR-per-ParseResult invariant enforced by `BaseIR.__post_init__`.
**Instead:** Access sheets through `SchematicIR.schematic.sheets` property, add mutation methods to SchematicIR.

### Anti-Pattern 2: Cross-file Operations Without AtomicOperation
**What:** Having handlers directly call propagation functions without atomic coordination
**Why bad:** If the schematic update succeeds but the PCB update fails, references are inconsistent with no rollback.
**Instead:** Always use `crossfile.AtomicOperation` for multi-file operations. The infrastructure is already built.

### Anti-Pattern 3: Separate Read-only Executor Path
**What:** Adding a `_READ_ONLY_HANDLERS` registry that skips Transaction wrapping
**Why bad:** Creates two execution paths for no real benefit. Transaction on a non-mutated file is a clean no-op (snapshot created and discarded). The existing path handles it correctly.
**Instead:** Register read-only operations in the appropriate existing registry (`_PCB_HANDLERS` for connectivity).

### Anti-Pattern 4: Footprint Pads Reusing Symbol PinSpec
**What:** Using the existing `PinSpec` from schema.py for footprint pad definitions
**Why bad:** Symbol pins have electrical_type and graphical_style. Footprint pads have shape (SMD/Thru-Hole/Connect), drill diameter, copper layers, and pad-to-net assignments. The fields are fundamentally different.
**Instead:** Create a new `FootprintPadSpec` in `_schema_create.py` with pad-specific fields.

## Scalability Considerations

| Concern | Current | After complete-ops | Impact |
|---------|---------|-------------------|--------|
| Operation count | 47 types | ~54 types (+7) | Minimal -- dict dispatch is O(1) |
| Executor imports | ~20 lazy imports | ~27 lazy imports | No performance impact (all lazy) |
| Schema union size | ~35 Op variants | ~42 Op variants | Pydantic union discrimination still fast |
| Cross-file ops | 0 | 2-3 | New execution path but isolated |

## Build Order (Dependency-Aware)

The build order respects the constraint that cross-file wiring requires executor modifications and should come last. The other four features are independent and can be built in any order.

```
Phase A (independent, any order):
  1. Remove operations (wire, label, junction)
     - Extend _schema_wire.py
     - Add methods to SchematicIR
     - Register in executor
     - Tests

  2. Footprint creation
     - Add FootprintPadSpec to _schema_create.py
     - Add create_footprint to create_file.py
     - Register in executor, add to _CREATE_OP_TYPES
     - Tests

  3. Connectivity query
     - Create _schema_query.py
     - Create connectivity_query.py handler
     - Register in executor as PCB handler
     - Tests (NetGraph already tested)

  4. Hierarchical sheet operations
     - Create _schema_sheet.py
     - Create sheet_ops.py handler
     - Register in executor
     - Tests

Phase B (depends on executor being stable):
  5. Cross-file wiring
     - Create _schema_crossfile.py
     - Add _execute_cross_file() to executor
     - Create cross-file handlers using AtomicOperation + propagation
     - Integration tests
```

**Rationale for ordering:**
- Remove operations and footprint creation are the simplest (extend existing modules)
- Connectivity query is simple but creates a new schema module
- Sheet operations are the most complex of the independent features (new module + auto-create sub-sheets)
- Cross-file wiring touches the executor core and must come last

## Impact on Existing Code

| File Modified | Lines Changed (est.) | Risk |
|---------------|----------------------|------|
| `ops/executor.py` | +50 (new handlers, cross-file path) | LOW (additive, no existing code changes) |
| `ops/schema.py` | +30 (imports, union variants, __all__) | LOW (additive) |
| `ops/_schema_wire.py` | +50 (3 new Op classes) | LOW (additive) |
| `ops/_schema_create.py` | +40 (1 new Op class + PadSpec) | LOW (additive) |
| `ir/schematic_ir.py` | +60 (3 remove methods) | LOW (additive, no existing method changes) |
| **Total modified** | ~230 lines across 5 files | **LOW risk** |
| **Total new** | ~400 lines across 5 new files | **No risk to existing** |

## Sources

- Direct codebase analysis of all files in `src/kicad_agent/`
- kiutils `HierarchicalSheet` dataclass fields (verified via Python introspection)
- kiutils `Footprint` dataclass fields (verified via Python introspection)
- KNOWN_LIMITATIONS.md from Council audit (H-1, M-1, M-3, M-4, M-6)
