# Domain Pitfalls -- Milestone v2.2 complete-ops

**Domain:** Adding hierarchical sheets, remove operations, footprint creation, connectivity query, and cross-file wiring to kicad-agent
**Researched:** 2026-05-29
**Context:** Mature project (24 phases, 1567 tests, security-hardened). This document covers pitfalls SPECIFIC to adding these five feature groups.
**Confidence:** HIGH (verified against kiutils 1.4.8 source, existing codebase patterns, Council review findings, KiCad file format docs)

---

## Critical Pitfalls

Mistakes that cause rewrites or major issues.

---

### Pitfall 1: Sheet Pin Names Must Match Hierarchical Labels Exactly -- Case-Sensitive, No Fuzzy Matching

**What goes wrong:**
A sheet pin named "SDA" in the parent sheet will not connect to a hierarchical label named "sda" or " SDA" in the child sheet. KiCad's electrical connectivity between parent and child sheets depends on EXACT string match between `HierarchicalPin.name` and the child's `HierarchicalLabel.text`. The ERC will report "Pin not connected" and the netlist will show an open circuit.

**Why it happens:**
The developer assumes KiCad does case-insensitive matching or trims whitespace. It does not. The S-expression format stores both strings as quoted values with no normalization. The `root_sheet.py` module already has this pattern correct (line 98-99 reads `label.text` directly) but the `add_sheet_pin` operation will receive the pin name from LLM JSON, which may not exactly match the child's hierarchical labels.

**Consequences:**
- Silent connectivity breaks -- ERC may not catch a mismatched pin if both the pin and label exist independently (pin is "connected" to nothing, label is "unconnected")
- Netlist differs from visual intent
- Debugging requires opening both files and comparing strings manually

**Prevention:**
1. `add_sheet_pin` MUST validate that the pin name matches an existing hierarchical label in the child sheet file before accepting the operation
2. Use exact `==` comparison, never `.lower()` or `.strip()`
3. Test: create a sub-sheet with hierarchical label "VCC", attempt `add_sheet_pin` with name "vcc" -- must fail with descriptive error

**Detection:**
ERC on parent sheet will report unconnected sheet pins. But only if the child sheet is also ERC'd.

---

### Pitfall 2: Sheet fileName Property Must Be Relative to Parent -- Not to Project Root

**What goes wrong:**
The `HierarchicalSheet.fileName` property stores the sub-sheet file path relative to the PARENT schematic's directory, NOT relative to the project root. In a flat project structure this distinction is invisible. In a hierarchical project with nested sub-sheets (e.g., `power/power_supply.kicad_sch` referenced from `root.kicad_sch`), using the wrong base directory produces a path that looks correct but resolves to a nonexistent file.

**Why it happens:**
`root_sheet.py` line 77 already handles this correctly (`root_sch_path.resolve().parent / sheet_file_name`). But `add_sheet` is a CREATE operation -- it must generate this path. The LLM may provide a project-root-relative path when the parent is in a subdirectory, or the developer may use `base_dir` instead of `parent_file_dir` when resolving.

**Consequences:**
- Sheet reference in the S-expression points to a nonexistent file
- KiCad opens the project but the sub-sheet is "missing"
- Subsequent operations that try to parse the sub-sheet fail with FileNotFoundError
- The `root_sheet.py` rebuild_root_sheet operation will skip the sheet with a warning (line 80-82)

**Prevention:**
1. `add_sheet` operation must accept a relative file path and resolve it relative to the PARENT file's directory, not `base_dir`
2. Validate that the referenced file either exists or will be created in the same operation
3. Test with nested hierarchy: root -> subdir/child -> subdir/subsubdir/grandchild
4. Document the resolution rule clearly in the Pydantic model docstring

**Detection:**
After `add_sheet`, verify the resolved path exists. If it does not, the operation should either fail or be paired with `create_schematic` for the child.

---

### Pitfall 3: Sheet Instances Must Be Updated When Adding/Removing Sheets

**What goes wrong:**
Every hierarchical sheet in a KiCad schematic has a corresponding entry in the `sheetInstances` list of the root schematic. Adding a sheet without adding a sheet_instance entry, or removing a sheet without cleaning up the instance, causes KiCad to report "Sheet instance not found" or duplicate page numbers.

**Why it happens:**
The `remove_component.py` pattern (line 64-69) correctly cleans up `symbolInstances`. But the executor does NOT have an analogous pattern for `sheetInstances`. The existing `root_sheet.py` rebuilds pins but does NOT touch `sheetInstances`. A new `add_sheet` operation must add both the `HierarchicalSheet` object AND a `HierarchicalSheetInstance` with the correct path and page number.

**Consequences:**
- KiCad crashes or shows "Error loading schematic" when opening the project
- Page numbering becomes inconsistent
- ERC may skip checking sub-sheets

**Prevention:**
1. `add_sheet` handler must append to BOTH `schematic.sheets` AND `schematic.sheetInstances`
2. `remove_sheet` (if implemented) must remove from both lists
3. Page numbers must be unique -- auto-assign the next available page number
4. Test: add a sheet, serialize, open in KiCad, verify page numbering is correct

**Detection:**
Parse the serialized file back and verify sheet count matches sheet_instances count.

---

### Pitfall 4: Remove Wire/Label/Junction Must Clean Up Adjacent Wire Segments

**What goes wrong:**
Removing a wire segment that is part of a multi-segment path (L-shaped, zigzag) without checking if other wire segments terminate at the same point leaves dangling wire endpoints. A wire ending at coordinates that have no pin, no junction, and no other wire is an ERC error. Similarly, removing a label without checking if it was the only thing connecting two wire segments breaks the net.

**Why it happens:**
The existing `add_wire` operation (schematic_ir.py line 392-427) only appends to `graphicalItems` with no connectivity tracking. There is no adjacency index. A `remove_wire` operation that simply filters the wire out of `graphicalItems` (like `remove_component` filters from `schematicSymbols`) will not check for orphaned neighbors.

**Consequences:**
- ERC reports "Pin not connected" or "Wire dangling"
- Visual artifacts in KiCad (wire stubs going nowhere)
- Downstream operations that rely on connectivity (like `repair_schematic`) may misbehave

**Prevention:**
1. Before removing a wire segment, check if other wires share an endpoint with it
2. If removing the wire would leave a dangling endpoint, either refuse the operation (with a clear error message listing the orphaned segments) or offer to cascade-remove the entire connected chain
3. Removing a local label must check if the label was the sole net name source for its wires. If yes, the wires become unnamed and effectively disconnected
4. Removing a junction at an intersection must verify that the remaining wires still connect properly
5. The `repair_schematic` operation already handles orphan cleanup, but it should not be a substitute for correct remove semantics

**Detection:**
Run ERC after every remove operation. Test: create a T-junction of three wires, remove the stem -- the two cross wires should still connect at the junction point.

---

### Pitfall 5: Footprint Creation Must Generate Pad Numbers Matching Symbol Pin Numbers for verify_pin_map

**What goes wrong:**
`verify_pin_map` (schematic_ir.py line 315-363) compares symbol pin numbers against footprint pad numbers. If the `create_footprint` operation generates pads with numbers like "1", "2", "3" but the corresponding symbol has pin numbers like "A1", "A2", "B1", the pin map verification fails. The operation succeeds but the resulting component cannot be used without footprint assignment errors.

**Why it happens:**
The existing `create_symbol` operation (create_file.py line 234-335) uses `PinSpec.number` from the schema. The `create_footprint` operation will use a similar `PadSpec`. But there is no cross-validation between the two. The LLM generating the JSON operation may not know the symbol's pin numbering scheme when creating the footprint.

**Consequences:**
- `verify_pin_map` returns `match: false` with `missing_in_footprint` entries
- KiCad shows "No footprint" or "Pin mismatch" errors
- User must manually fix pad numbering after creation

**Prevention:**
1. The `create_footprint` operation schema should accept pad numbers as explicit strings (not auto-generated integers)
2. If a `reference_symbol` parameter is provided, validate that the pad number set covers all pin numbers from the symbol
3. Test: create a symbol with pins numbered "A1", "A2", create a footprint with pads numbered "1", "2" -- verify_pin_map should fail with clear mismatch message
4. Test: create a symbol and matching footprint with identical pin/pad numbers -- verify_pin_map should pass

**Detection:**
After `create_footprint`, run `verify_pin_map` against the target symbol. This should be documented as a required step in the operation's result message.

---

### Pitfall 6: Connectivity Query Must Not Mutate State -- The IR Is Shared

**What goes wrong:**
A connectivity query operation (exposing `analysis/connectivity.py` `NetGraph.from_pcb_ir()`) parses the PCB IR and builds a networkx graph. If the query operation accidentally mutates the IR (e.g., by modifying footprints during traversal, or by caching the NetGraph on the IR object), subsequent operations on the same file will see corrupted state.

**Why it happens:**
The existing `analysis/connectivity.py` accesses `pcb_ir.footprints` and reads `fp.properties`, `pad.net`. All reads, no writes. But the `from_pcb_ir` classmethod is currently only called from test code. When wired as an operation, it will be called inside the executor's `_execute_pcb` method, which wraps everything in a Transaction. If NetGraph builds any caches or indexes that reference mutable IR objects, those references become stale after the Transaction commits and the IR is discarded.

**Consequences:**
- Silent data corruption if the NetGraph holds references to IR objects that are later mutated
- Test failures that are timing-dependent (pass in isolation, fail in batch)
- Security concern: read-only query should never trigger Transaction commit

**Prevention:**
1. The connectivity query operation should use the READ-ONLY path in the executor -- it should NOT be registered as a PCB handler (which triggers Transaction wrapping). Instead, register it as a new handler category (e.g., `_QUERY_HANDLERS`) that parses the file, builds the graph, serializes nothing, and returns results
2. NetGraph must not store references to mutable IR objects -- extract all needed data during construction (it already does this correctly via `_net_index`)
3. Test: run connectivity query, then immediately run a mutation operation on the same file, verify the mutation succeeds and the query results are unchanged
4. Verify no file is written after a connectivity query (check file mtime before and after)

**Detection:**
Check file modification timestamp before and after query operation. If the file was modified, the query is not truly read-only.

---

### Pitfall 7: Cross-File Wiring Partial Failure Leaves Files Inconsistent

**What goes wrong:**
A cross-file wiring operation (e.g., add a hierarchical label in a sub-sheet AND add a matching sheet pin in the parent) involves two files. If the first file's mutation succeeds but the second fails, the project is left in an inconsistent state: the sub-sheet has a label "DATA" but the parent has no corresponding pin.

**Why it happens:**
The `crossfile/atomic.py` AtomicOperation class handles rollback correctly at the file level -- if the second file's Transaction fails, both files are rolled back. But the current executor (`_execute_schematic`, `_execute_pcb`) processes ONE file per operation. Cross-file operations must use the AtomicOperation coordinator, which exists but is NOT wired to any operation (KNOWN_LIMITATIONS.md M-1).

**Consequences:**
- One file is modified, the other is not
- ERC on the modified file passes, but cross-file ERC fails
- Repairing the inconsistency requires manual editing or knowing which operation partially applied

**Prevention:**
1. Cross-file operations MUST use `AtomicOperation` from `crossfile/atomic.py` for multi-file Transaction coordination
2. Each cross-file operation must define ALL files it will modify upfront (the AtomicOperation constructor validates all paths exist before opening Transactions)
3. The operation handler must be structured as: parse all files -> validate all mutations -> apply all mutations -> commit all Transactions
4. If any validation fails, NO Transaction is opened -- fail fast before side effects
5. Test: simulate a failure on the second file (e.g., invalid mutation parameter) and verify BOTH files are unchanged

**Detection:**
After any cross-file operation (success or failure), verify all involved files have consistent state. For wiring operations: run ERC on both files and verify no new errors were introduced.

---

## Moderate Pitfalls

---

### Pitfall 8: kiutils Drops UUIDs from Footprint Files -- create_footprint Must Use Raw S-expression for Serialization

**What goes wrong:**
kiutils 1.4.8 drops all UUID tokens from footprint files during parse/serialize. The existing `FootprintIR.__post_init__` enforces `_uuid_map is not None` to prevent this. But `create_footprint` is a CREATE operation -- it uses the `_CREATE_HANDLERS` registry which bypasses IR construction entirely. If the handler uses `kiutils.Footprint.to_file()` directly (like `create_symbol` does with `SymbolLib.to_file()`), the resulting .kicad_mod file will be missing all UUIDs, which makes it incompatible with board files that reference footprints by UUID.

**Why it happens:**
The `create_symbol` operation (create_file.py line 327-328) calls `lib.to_file()` directly and it works because symbol libraries use `tstamp` (not `uuid`). But footprints use `uuid` tokens extensively (pads, graphics, zones). The PCB IR already has the `_raw_written` escape hatch (executor.py line 729) for cases where kiutils serialization loses data.

**Consequences:**
- Created footprints work in isolation but fail when imported into a board
- DRC reports "Missing UUID" warnings
- Round-trip tests fail because the serialized file is missing tokens

**Prevention:**
1. `create_footprint` should construct the footprint using kiutils, then use the raw S-expression serializer (`serializer/footprint_ser.py`) to preserve UUIDs
2. Alternatively, generate the S-expression string directly (like some PCB IR methods do) bypassing kiutils serialization entirely
3. Test: create a footprint, parse it back with `parse_footprint`, verify all UUIDs are present in the raw content
4. This is the same pattern as FootprintIR -- learn from its UUID map requirement

**Detection:**
Parse the created .kicad_mod file and count `(uuid` tokens. If fewer than expected (one per pad + one per graphic item), the serialization lost UUIDs.

---

### Pitfall 9: Sheet UUID Must Be Unique Across the Entire Project

**What goes wrong:**
Each `HierarchicalSheet` object has a `uuid` field. If two sheets in the same project share a UUID (e.g., because `uuid.uuid4()` was called but a race condition produced a collision, or more likely because the developer copied a sheet object without regenerating its UUID), KiCad will show "Duplicate UUID" errors and may silently drop one of the sheets.

**Why it happens:**
The existing `add_component` and `create_schematic` operations generate UUIDs correctly using `str(uuid.uuid4())`. But `add_sheet` creates multiple objects that all need UUIDs: the sheet itself, each sheet pin, and the sheet_instance. If any of these reuse a UUID from another object in the same file, KiCad rejects the file.

**Consequences:**
- KiCad refuses to load the schematic
- UUID collision detection is not part of the current validation pipeline
- Extremely hard to debug -- the error message just says "duplicate UUID" without specifying which objects

**Prevention:**
1. Generate a fresh UUID for every object: sheet, each pin, each instance
2. After construction, verify all UUIDs in the file are unique (a simple set-length check)
3. The `uuid_extractor.py` module already extracts UUIDs from raw content -- use it to validate uniqueness after creation
4. Test: add two sheets in sequence, verify their UUIDs are different

**Detection:**
After any sheet-adding operation, extract all UUIDs from the serialized file and verify no duplicates.

---

### Pitfall 10: Remove Operations Need UUID Cleanup in symbolInstances/sheetInstances

**What goes wrong:**
Removing a wire, label, or junction leaves its UUID behind in instance tables if those tables track graphical items. While KiCad 10+ does not track wire/label/junction UUIDs in instance tables (only component UUIDs are tracked in `symbolInstances`), the remove operation must still ensure the UUID does not appear in any cross-reference structure.

**Why it happens:**
The `remove_component` handler (remove_component.py line 63-69) correctly cleans `symbolInstances`. But `remove_wire` operates on `graphicalItems` which is not tracked in instance tables. The pitfall is assuming this cleanup is unnecessary and then discovering that a future KiCad version or a third-party tool does track these UUIDs.

**Consequences:**
- No immediate breakage in KiCad 10, but forward-compatibility risk
- If the codebase later adds net tracking that uses wire UUIDs, old remove operations will leave phantom references

**Prevention:**
1. For `remove_wire`: filter from `graphicalItems` using identity check (like remove_component does for schematicSymbols)
2. For `remove_label`: remove from the correct list (`labels`, `globalLabels`, or `hierarchicalLabels`) -- the label type determines which list
3. For `remove_junction`: remove from `junctions` list
4. Verify the removed UUID does not appear anywhere else in the file content (belt-and-suspenders check)
5. Each remove operation must record the mutation for audit trail

**Detection:**
After remove, search the serialized file for the removed object's UUID string. It should not appear.

---

### Pitfall 11: Hierarchical Sheet Pin Position Must Be on Sheet Boundary -- Not Inside or Outside

**What goes wrong:**
A hierarchical sheet pin must be positioned exactly on the boundary of the sheet rectangle (defined by `sheet.position`, `sheet.width`, `sheet.height`). Pins placed inside the sheet rectangle are invisible. Pins placed outside the rectangle are shown but do not connect to the sheet's internal wiring. KiCad does not validate this during file load -- the error only shows when trying to wire to the pin.

**Why it happens:**
The `root_sheet.py` module (lines 121-149) correctly places left pins at `sheet_x` and right pins at `sheet_x + sheet_w`. But `add_sheet_pin` receives coordinates from the LLM JSON, which may not account for the sheet's boundary geometry.

**Consequences:**
- Sheet pin appears misplaced in the GUI
- Cannot connect wires to the pin
- ERC may not catch this specific error

**Prevention:**
1. `add_sheet_pin` must validate that the pin position lies on the sheet boundary:
   - X matches `sheet.position.X` (left edge) or `sheet.position.X + sheet.width` (right edge), OR
   - Y matches `sheet.position.Y` (top edge) or `sheet.position.Y + sheet.height` (bottom edge)
2. Within a small tolerance (e.g., 0.01mm) for floating-point comparison
3. If the position is not on the boundary, snap to the nearest boundary edge with a warning
4. Test: place a pin at sheet center -- must fail or snap to nearest edge

**Detection:**
Visual inspection in KiCad, or automated check of pin coordinates against sheet geometry.

---

### Pitfall 12: Connectivity Query for Schematics Requires Wire Tracing -- Not Just Net Names

**What goes wrong:**
The existing `NetGraph` (analysis/connectivity.py) only works for PCB files -- it reads pad net assignments. A schematic connectivity query must TRACE WIRES to determine which pins are connected. Two pins with the same net label are connected even if no wire physically joins them (KiCad implicit connection via labels). Two pins connected by a wire but with different labels are shorted. The query must handle both cases.

**Why it happens:**
The developer assumes schematic connectivity can reuse the PCB NetGraph by reading label names instead of pad nets. This works for label-based connections but misses wire-based connections between pins that have no labels. The existing `ops/repair.py:202-208` has a DEAD CODE loop body (`pass`) for wire propagation (Council finding H-08), meaning wire-based connectivity tracing was attempted but never implemented.

**Consequences:**
- Query reports "SDA is connected to U1 pin 5 and R2 pin 1" when in fact R2 pin 1 is on a different net that happens to pass through the same position
- Missing connections that are wire-only (no labels)
- Incorrect connectivity graph leads to incorrect DRC results

**Prevention:**
1. Schematic connectivity query must implement proper wire tracing: build a graph where nodes are pin positions, label positions, and wire endpoints; edges are wire segments connecting positions
2. Labels at the same position implicitly connect all wires/pins at that position
3. This is a non-trivial graph algorithm -- do not underestimate it
4. Consider using networkx (already a dependency) for the graph
5. Test: create a schematic with two components connected by wire only (no labels), verify the query reports them as connected
6. Test: create a schematic with two components connected only by sharing a label name at different positions, verify the query reports them as connected

**Detection:**
Compare query results against KiCad's netlist export. Discrepancies indicate bugs.

---

### Pitfall 13: Cross-File Operation Must Resolve Paths Relative to Project Root, Not CWD

**What goes wrong:**
When a cross-file operation modifies `power_supply.kicad_sch` and `root.kicad_sch`, it must resolve both file paths relative to the project's `base_dir`. But the executor currently resolves `target_file` relative to `base_dir` for single-file operations (executor.py line 621). Cross-file operations will receive multiple target_file values, and if any is resolved relative to CWD instead of base_dir, the AtomicOperation will open a Transaction on the wrong file.

**Why it happens:**
The `crossfile/project_context.py` `detect_project_root` function walks upward to find `.kicad_pro`, which gives the project root. But the cross-file operation handler must use this root (or `base_dir`) to resolve ALL file paths, not just the primary target.

**Consequences:**
- Transaction opened on wrong file path
- Path confinement check (executor.py line 626) may pass for the correct path but the AtomicOperation opens the wrong file
- File corruption if the wrong file is modified and committed

**Prevention:**
1. All file paths in cross-file operations must be relative to `base_dir`
2. The `TargetFile` validator already rejects absolute paths and `..` traversal
3. The cross-file handler must resolve each path as `base_dir / target_file` (same pattern as single-file executor)
4. Test: run a cross-file operation with CWD different from the project root, verify correct files are modified

**Detection:**
Log the resolved absolute paths at the start of every cross-file operation. Compare against expected paths.

---

## Minor Pitfalls

---

### Pitfall 14: create_footprint Must Be Added to _CREATE_OP_TYPES Set

**What goes wrong:**
The executor checks `_CREATE_OP_TYPES` (executor.py line 632) to decide whether a file must exist before the operation runs. If `create_footprint` is not in this set, the executor will raise `FileNotFoundError` because the target `.kicad_mod` file does not exist yet.

**Why it happens:**
The developer adds the `@register_create("create_footprint")` decorator and handler but forgets to update the `_CREATE_OP_TYPES` set on line 50.

**Consequences:**
- Operation fails immediately with FileNotFoundError for new footprint files
- Works for appending to existing footprint libraries (confusing -- appears to work sometimes)

**Prevention:**
1. Add `"create_footprint"` to `_CREATE_OP_TYPES` set on executor.py line 50
2. Test: create a footprint in a new file, verify it succeeds
3. Add a CI check: grep for `@register_create` decorators and verify all op_types are in `_CREATE_OP_TYPES`

**Detection:**
If the operation works for existing files but fails for new files, the `_CREATE_OP_TYPES` set is missing the entry.

---

### Pitfall 15: Schema Field Names Must Match prompt.md Exactly

**What goes wrong:**
The Phase 24 Council audit (finding H-6) found prompt-to-schema field name mismatches: `grid_size` in prompt vs `grid_mm` in schema, `erc_report_path` documented but not in schema. Adding new operations repeats this mistake if the prompt.md documentation and Pydantic schema are written by different agents or at different times.

**Why it happens:**
The LLM reads prompt.md to generate JSON operations. If prompt.md says `file_name` but the Pydantic model has `filename`, validation fails. The schema is the source of truth but prompt.md is what the LLM reads.

**Consequences:**
- LLM generates operations that fail Pydantic validation
- User frustration -- the documented fields do not work
- Same pattern that was already identified and "fixed" in Phase 24

**Prevention:**
1. For each new operation, write the Pydantic schema FIRST, then generate prompt.md FROM the schema
2. Use `model_json_schema()` to auto-generate the field documentation
3. Add a test: for each operation type, verify the prompt.md examples pass Pydantic validation
4. This is a KNOWN repeating pattern -- the Council already flagged it once

**Detection:**
Run the prompt.md example JSON through `Operation.model_validate()`. If it fails, there is a mismatch.

---

### Pitfall 16: Remove Wire by UUID, Not by Coordinates

**What goes wrong:**
Removing a wire by matching start/end coordinates fails when two wires share an endpoint (which is common -- T-junctions, bus entries). The coordinate-based match removes the wrong wire or multiple wires.

**Why it happens:**
The developer follows the pattern of `remove_component` (which matches by unique reference string) but uses coordinates as the identifier for wires. Coordinates are NOT unique identifiers for wires.

**Consequences:**
- Wrong wire removed
- Multiple wires removed when only one was intended
- Connectivity broken at the removed location

**Prevention:**
1. Remove wire MUST use UUID as the identifier, not coordinates
2. The schema should have a `wire_uuid` field, not `start_x/start_y/end_x/end_y`
3. The handler looks up the UUID in `graphicalItems` and removes by identity
4. For user convenience, provide a `find_wires_at_position` query that returns UUIDs at given coordinates
5. Test: create two wires sharing an endpoint, remove one by UUID, verify the other remains

**Detection:**
Count wires before and after removal. If more than one wire was removed, the matching is too broad.

---

### Pitfall 17: Hierarchical Sheet Discovery for Connectivity Query Must Follow Nested References

**What goes wrong:**
A connectivity query on the root schematic must recursively discover all sub-sheets, sub-sub-sheets, etc. to build the complete connectivity graph. If the discovery only goes one level deep, nets that cross through intermediate sub-sheets are missed.

**Why it happens:**
`root_sheet.py` iterates `sch.sheets` but does not recurse into sub-sheets' sheets. For the rebuild_root_sheet operation this is fine (it only processes immediate children). For a connectivity query, all levels must be traversed.

**Consequences:**
- Incomplete connectivity graph
- Nets that cross sub-sheet boundaries are not traced
- Query reports incorrect connectivity for multi-level hierarchies

**Prevention:**
1. Implement recursive sheet discovery with a max depth limit (e.g., 20 levels to match the `_MAX_WALK_LEVELS` constant in project_context.py)
2. Detect circular references (sheet A references sheet B references sheet A) and fail with a clear error
3. Cache parsed sub-sheets to avoid re-parsing the same file multiple times
4. Test: create a 3-level hierarchy (root -> child -> grandchild), verify the query discovers all three levels

**Detection:**
Compare discovered sheet count against the project's actual .kicad_sch file count. If fewer sheets are discovered, the recursion is incomplete.

---

### Pitfall 18: Footprint Pad Layers Must Be Valid KiCad Layer Names

**What goes wrong:**
KiCad pad layer names are specific strings like "F.Cu", "B.Cu", "*.Cu", "F.Mask", "F.Paste". Passing invalid layer names (e.g., "Top", "Bottom", "copper_top") causes KiCad to silently ignore the pad or show "Unknown layer" errors.

**Why it happens:**
The `create_symbol` operation does not deal with layers (symbols are layer-agnostic). Footprints are fundamentally layer-aware. The LLM may generate layer names from its training data that do not match KiCad's naming convention.

**Consequences:**
- Created footprint has pads on wrong layers or no layers
- DRC reports pad errors
- Footprint appears correct in the library editor but fails when placed on a board

**Prevention:**
1. Define a `Literal` type for valid KiCad layer names in the schema (like `PinSpec.electrical_type` uses Literal)
2. At minimum: "F.Cu", "B.Cu", "*.Cu", "F.Mask", "B.Mask", "F.Paste", "B.Paste", "F.SilkS", "B.SilkS", "Edge.Cuts"
3. Validate layer names in the Pydantic schema
4. Test: create a footprint with an invalid layer name -- must fail validation

**Detection:**
Parse the created footprint with kiutils and verify pad layers are recognized.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation | Phase to Address |
|-------------|---------------|------------|-----------------|
| Hierarchical sheet add | Sheet path resolution relative to parent (Pitfall 2) | Resolve relative to parent file dir, not project root | First phase implementing sheets |
| Hierarchical sheet add | Sheet instances not updated (Pitfall 3) | Add to both sheets list AND sheetInstances | First phase implementing sheets |
| Hierarchical sheet pin add | Pin name mismatch with child labels (Pitfall 1) | Validate against child sheet labels | First phase implementing sheets |
| Hierarchical sheet pin add | Pin position off sheet boundary (Pitfall 11) | Snap to nearest boundary edge | First phase implementing sheets |
| Remove wire/label/junction | Dangling wire segments after remove (Pitfall 4) | Check adjacency before remove, cascade or refuse | Remove operations phase |
| Remove wire | Coordinate-based matching removes wrong wire (Pitfall 16) | Use UUID as identifier, not coordinates | Remove operations phase |
| Remove wire/label/junction | UUID cleanup in instance tables (Pitfall 10) | Verify UUID not in file after remove | Remove operations phase |
| create_footprint | kiutils drops UUIDs during serialization (Pitfall 8) | Use raw S-expression serializer, not kiutils to_file | Footprint creation phase |
| create_footprint | Pad numbering mismatches symbol pins (Pitfall 5) | Cross-validate with target symbol pin numbers | Footprint creation phase |
| create_footprint | Missing from _CREATE_OP_TYPES (Pitfall 14) | Add to set, add CI check | Footprint creation phase |
| create_footprint | Invalid pad layer names (Pitfall 18) | Use Literal type for layer names | Footprint creation phase |
| Connectivity query | Query mutates IR state (Pitfall 6) | Use read-only executor path, no Transaction | Connectivity query phase |
| Connectivity query (schematic) | Wire tracing not implemented (Pitfall 12) | Implement graph-based wire tracing with networkx | Connectivity query phase |
| Connectivity query | Nested sheet discovery incomplete (Pitfall 17) | Recursive discovery with depth limit and cycle detection | Connectivity query phase |
| Cross-file wiring | Partial failure leaves files inconsistent (Pitfall 7) | Use AtomicOperation for multi-file transactions | Cross-file wiring phase |
| Cross-file wiring | Path resolution relative to CWD (Pitfall 13) | Resolve all paths relative to base_dir | Cross-file wiring phase |
| All new operations | Schema-prompt field name mismatch (Pitfall 15) | Generate prompt from schema, validate examples | Every phase |

## Recommended Implementation Order

Based on pitfall dependencies:

1. **Remove operations first** -- standalone, no cross-file complexity, exercises the remove pattern that cross-file wiring will also need
2. **Footprint creation** -- standalone create operation, tests the _CREATE_OP_TYPES pattern and UUID serialization
3. **Connectivity query** -- read-only, no mutation risk, but requires wire tracing implementation
4. **Hierarchical sheet add** -- most complex single-file operation, multiple sub-pitfalls
5. **Cross-file wiring** -- depends on AtomicOperation (already built), sheet operations (preceding phase), and remove operations (for cleanup)

## Sources

- kiutils 1.4.8 source: HierarchicalSheet, HierarchicalPin, Pad, Footprint classes (verified via inspect)
- Council of Ricks All-Hands Audit (COUNCIL-REVIEW.md): Findings H-1, H-6, H-8, M-1, M-3, M-4, M-6, M-8
- KNOWN_LIMITATIONS.md: Gaps H-1, M-1, M-3, M-4, M-6
- Existing codebase: executor.py dispatch pattern, remove_component.py cleanup pattern, root_sheet.py sheet handling, create_file.py create_symbol pattern, crossfile/atomic.py multi-file transaction, analysis/connectivity.py NetGraph
- KiCad S-expression format documentation (dev-docs.kicad.org)
- kiutils GitHub issues for UUID serialization limitations
