# Project Research Summary

**Project:** kicad-agent milestone v2.2 complete-ops
**Domain:** KiCad 10+ EDA automation -- operation API gap-filling
**Researched:** 2026-05-29
**Confidence:** HIGH

## Executive Summary

The v2.2 complete-ops milestone fills five operation gaps in kicad-agent: hierarchical sheet operations, remove operations (wire/label/junction), footprint creation, connectivity query, and cross-file atomic wiring. All four researchers converged on the same core finding: **zero new dependencies are needed**. kiutils 1.4.8 provides complete APIs for HierarchicalSheet, HierarchicalPin, Footprint, and Pad. The analysis/connectivity.py NetGraph and crossfile/atomic.py AtomicOperation are already built and tested. The milestone is wiring work, not invention.

Four of five features require only extending the existing executor registry pattern (schema + handler + registration). Only cross-file wiring introduces an architectural change -- a new `_CROSSFILE_HANDLERS` dispatch path that coordinates multiple files through AtomicOperation. The recommended approach is build-simple-first: remove operations (symmetric inverse of existing add ops, ~150 lines total), then connectivity query (wraps existing NetGraph, ~70 lines), then footprint creation (new PadSpec schema + handler, ~200 lines), then hierarchical sheets (most complex single-file feature, ~300 lines), and finally cross-file wiring (executor extension, ~200 lines modified + new files).

The dominant risk is the 7 critical pitfalls identified across the five features. Three involve hierarchical sheets (UUID path management, pin/label exact-match validation, sheetInstances tracking). One involves kiutils silently dropping UUIDs from footprint files during serialization. One involves cross-file partial failure. One involves wire adjacency cleanup after removal. One involves connectivity query accidentally mutating shared IR state. Each has a concrete prevention strategy documented in PITFALLS.md. The build order is designed so that simpler features establish patterns before complex ones, and cross-file wiring comes last because it depends on the executor being stable.

## Key Findings

### Recommended Stack

No stack changes. All five features use existing installed packages. This was verified by live Python inspection of kiutils 1.4.8 constructors and direct codebase analysis of the executor dispatch pattern, existing handler registrations, and already-built infrastructure modules.

**Core technologies (existing, no changes):**
- **kiutils 1.4.8:** HierarchicalSheet, HierarchicalPin, Footprint, Pad, Schematic.sheets -- all constructors verified present and field-complete
- **pydantic 2.12.5:** New operation schemas follow existing `_schema_*.py` pattern with discriminated unions
- **networkx 3.6.1:** Powers NetGraph in analysis/connectivity.py, already built and tested
- **sexpdata 1.0.0:** Fallback for footprint serialization if kiutils drops UUIDs (Pitfall 8)

### Expected Features

**Must have (table stakes):**
- **Remove operations** (remove_wire, remove_label, remove_junction) -- symmetric inverse of existing add ops. Users expect add/remove parity. Pattern exists in remove_component.py.
- **Hierarchical sheet operations** (add_sheet, add_sheet_pin, navigate_hierarchy) -- real KiCad projects use hierarchy. An agent that cannot navigate sub-sheets cannot handle production designs.
- **Connectivity query** (query_connectivity) -- the analysis code exists and works. Not exposing it is the gap.

**Should have (competitive):**
- **Footprint creation** (create_footprint) -- no other KiCad automation tool offers JSON-driven footprint generation. Enables programmatic footprint creation.
- **Cross-file atomic operations** (propagate_symbol_change, sync_schematic_pcb) -- true multi-file atomic transactions are unique. KiBot and kicad-python do not provide this.

**Defer (v2.3+):**
- Schematic connectivity graph (requires geometric wire tracing -- complex, not needed now)
- Footprint wizard / parameterized generators (explicit pad positions suffice)
- Remove-by-pattern / wildcard removal (dangerous in AI hands)
- Auto-sync of hierarchical pins when labels change (fragile, explicit operations are safer)

### Architecture Approach

The existing pipeline (LLM JSON -> Pydantic validate -> OperationExecutor -> Parse -> IR -> Handler -> Serialize -> Transaction) remains unchanged. All five features plug into the existing 4-registry dispatch pattern. Two features extend existing schema/handler files. Three create new schema/handler file pairs. One introduces a new executor dispatch path.

**Component changes:**

| Component | Change | Risk |
|-----------|--------|------|
| `ops/_schema_remove.py` (NEW) | RemoveWireOp, RemoveLabelOp, RemoveJunctionOp, RemoveNoConnectOp | None -- additive |
| `ops/remove_ops.py` (NEW) | Handlers using list-filter removal pattern from remove_component.py | None -- additive |
| `ops/_schema_sheet.py` (NEW) | AddSheetOp, AddSheetPinOp, NavigateSheetsOp | None -- additive |
| `ops/sheet_ops.py` (NEW) | Sheet/pin creation using kiutils HierarchicalSheet/HierarchicalPin | None -- additive |
| `ops/_schema_query.py` (NEW) | QueryConnectivityOp with query_type discriminator | None -- additive |
| `ops/connectivity_query.py` (NEW) | NetGraph wrapper for PCB connectivity queries | None -- additive |
| `ops/_schema_create.py` (EXTEND) | CreateFootprintOp + FootprintPadSpec | Low -- additive |
| `ops/create_file.py` (EXTEND) | create_footprint handler following create_symbol pattern | Low -- additive |
| `ops/_schema_crossfile.py` (NEW) | SyncSchematicPcbOp, PropagateLibRefOp | None -- additive |
| `ops/executor.py` (EXTEND) | Wire new handlers + add `_execute_cross_file()` path | Medium -- touches core dispatch |
| `ir/schematic_ir.py` (EXTEND) | remove_wire, remove_label, remove_junction methods | Low -- additive |
| `crossfile/atomic.py` | Wire, don't modify | None -- already built |
| `analysis/connectivity.py` | Wire, don't modify | None -- already built |

### Critical Pitfalls

1. **Sheet pin names must match hierarchical labels exactly** (Pitfall 1) -- Case-sensitive, no fuzzy matching. `add_sheet_pin` MUST validate against child sheet labels before accepting. Use `==` comparison only.

2. **Sheet fileName must be relative to parent, not project root** (Pitfall 2) -- In nested hierarchies, path resolution must use parent file's directory, not base_dir. Test with `root -> subdir/child -> subdir/subsubdir/grandchild`.

3. **Sheet instances must be updated alongside sheets** (Pitfall 3) -- `add_sheet` must append to BOTH `schematic.sheets` AND `schematic.sheetInstances`. Missing instances cause KiCad crashes and broken page numbering.

4. **kiutils drops UUIDs from footprint files** (Pitfall 8) -- `create_footprint` cannot use `Footprint.to_file()` directly. Must use raw S-expression serializer or construct S-expressions manually to preserve UUIDs on pads and graphics.

5. **Remove wire must check adjacency** (Pitfall 4) -- Removing a wire segment that other wires connect to leaves dangling endpoints (ERC errors). Check for shared endpoints before removal; refuse or cascade-remove the connected chain.

6. **Connectivity query must not mutate IR** (Pitfall 6) -- NetGraph holds references to IR objects. If the query is wrapped in a Transaction (which modifies file mtime), subsequent operations see stale state. Use a read-only handler path, not standard PCB handler registration.

7. **Cross-file partial failure** (Pitfall 7) -- If one file's mutation fails mid-operation, ALL files must roll back. MUST use AtomicOperation from crossfile/atomic.py. Validate ALL mutations before opening ANY Transaction.

## Implications for Roadmap

Based on combined research, the recommended build order follows dependency complexity: simple/standalone features first, complex/integrated features last.

### Phase 1: Remove Operations
**Rationale:** Simplest gap. Symmetric inverse of existing add_wire/add_label/add_junction. Exercises the remove pattern (list filter + mutation recording) that will be reused. No new architectural components. ~150 lines of handler code total.
**Delivers:** remove_wire, remove_label, remove_junction, remove_no_connect operations
**Addresses:** Table stakes -- add/remove parity
**Avoids:** Pitfall 4 (wire adjacency check), Pitfall 16 (UUID-based removal, not coordinates), Pitfall 10 (UUID cleanup)
**Estimated effort:** 1-2 days

### Phase 2: Connectivity Query
**Rationale:** Wraps existing NetGraph code with schema + handler. Exercises the schema-to-executor-to-IR path for read-only operations. No mutation risk. Establishes the pattern for query-type operations before the more complex cross-file work.
**Delivers:** query_connectivity operation with 5 query types (connected_pads, net_stats, are_connected, shortest_path, connected_components)
**Addresses:** Table stakes -- expose existing analysis capability
**Avoids:** Pitfall 6 (read-only semantics, no IR mutation)
**Estimated effort:** 0.5-1 day

### Phase 3: Footprint Creation
**Rationale:** Most new code of the standalone features (new PadSpec schema, new handler, footprint-specific serialization). Must be done before cross-file wiring because it tests the `_CREATE_OP_TYPES` extension pattern and the UUID serialization workaround.
**Delivers:** create_footprint operation with PadSpec schema, courtyard generation, pad layer validation
**Addresses:** Differentiator -- programmatic footprint generation
**Avoids:** Pitfall 8 (UUID serialization via raw S-expression), Pitfall 5 (pad/symbol pin number cross-validation), Pitfall 14 (_CREATE_OP_TYPES registration), Pitfall 18 (valid KiCad layer names via Literal type)
**Estimated effort:** 2-3 days

### Phase 4: Hierarchical Sheet Operations
**Rationale:** Most complex single-file feature. Requires careful UUID path management, instance tracking, pin/label validation, and sub-sheet file creation. Doing it after simpler features means the operation patterns are well-established and the executor is stable.
**Delivers:** add_sheet, add_sheet_pin, navigate_hierarchy operations
**Addresses:** Table stakes -- real projects use hierarchy
**Avoids:** Pitfalls 1, 2, 3, 9, 11 -- sheet pin name matching, path resolution, instance tracking, UUID uniqueness, pin boundary positioning
**Estimated effort:** 3-5 days

### Phase 5: Cross-File Atomic Wiring
**Rationale:** The only architectural change -- new `_CROSSFILE_HANDLERS` registry and `_execute_cross_file()` dispatch path. Depends on the executor being stable (all other features wired). Must come last because it touches the core dispatch logic. Wire existing AtomicOperation and propagation functions.
**Delivers:** propagate_symbol_change operation, cross-file executor dispatch path, AtomicOperation integration
**Addresses:** Differentiator -- true multi-file atomic transactions
**Avoids:** Pitfall 7 (partial failure via AtomicOperation), Pitfall 13 (path resolution relative to base_dir)
**Estimated effort:** 2-3 days

### Phase Ordering Rationale

- **Remove ops first** because they are standalone, low-risk, and establish the removal pattern that cross-file cleanup will need later.
- **Connectivity query second** because it is read-only, wraps existing code, and validates the query-operation pattern without mutation risk.
- **Footprint creation before sheets** because it tests the create-path extension (_CREATE_OP_TYPES) and UUID serialization workaround in isolation, before the more complex sheet creation which also creates sub-files.
- **Sheets before cross-file** because sheets are single-file operations (despite referencing sub-sheets). Cross-file wiring requires stable executor infrastructure.
- **Cross-file last** because it is the only feature that modifies the executor's core dispatch logic. All other features must be wired and tested before touching the dispatch path.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (Hierarchical Sheets):** Complex kiutils API interaction -- sheet instance UUID paths, sheetInstances format, pin/label bidirectional validation. The root_sheet.py code demonstrates navigation but creation has different edge cases. Worth a `/gsd-research-phase` to verify sheetInstances construction.
- **Phase 5 (Cross-File Wiring):** New executor dispatch path design. The AtomicOperation API is verified but the executor integration point needs careful design to maintain path confinement and single-file security model. Worth a `/gsd-research-phase` for executor extension architecture.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Remove Operations):** Exact pattern exists in remove_component.py. No API unknowns.
- **Phase 2 (Connectivity Query):** NetGraph already built. Just wiring.
- **Phase 3 (Footprint Creation):** Follows create_symbol pattern. kiutils Footprint/Pad API verified.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All APIs verified via live Python inspection. Zero new dependencies. kiutils 1.4.8 complete for all features. |
| Features | HIGH | 4 of 5 features have existing infrastructure. Gap analysis from Council audit (KNOWN_LIMITATIONS.md) is specific and actionable. |
| Architecture | HIGH | Direct codebase analysis of executor.py dispatch pattern, handler registration, IR mutation methods. ~230 lines modified + ~400 lines new across 10 files. |
| Pitfalls | HIGH | 18 pitfalls identified from codebase analysis, Council findings, and kiutils known limitations. 7 critical with concrete prevention strategies. |

**Overall confidence:** HIGH

### Gaps to Address

- **kiutils UUID serialization for footprints:** Pitfall 8 is real -- kiutils 1.4.8 drops UUIDs from .kicad_mod files. The workaround (raw S-expression serializer) needs validation during Phase 3 implementation. Verify by creating a footprint, parsing it back, and counting `(uuid` tokens.
- **Schematic connectivity is deferred:** The connectivity query only covers PCB (explicit net assignments). Schematic connectivity requires geometric wire tracing which is complex and out of scope for v2.2. The `ops/repair.py` wire propagation code is dead (Council finding H-08). Future milestone needed.
- **Cross-file handler signature design:** The architecture recommends `_CROSSFILE_HANDLERS` receive `dict[Path, BaseIR]` instead of single IR. This changes the handler contract. Needs validation during Phase 5 planning to ensure it does not break the existing registration pattern.
- **Sheet instances format:** The `sheetInstances` list structure and the UUID path format (`/root-uuid/sheet-uuid`) need exact verification during Phase 4. The root_sheet.py reads these but does not create them.

## Sources

### Primary (HIGH confidence)
- Live Python inspection of kiutils 1.4.8: HierarchicalSheet, HierarchicalPin, Footprint, Pad, Schematic.sheets APIs
- Direct codebase analysis: executor.py (dispatch pattern), schema.py (Pydantic schema pattern), create_file.py (create_symbol precedent), remove_component.py (removal pattern), root_sheet.py (sheet iteration), schematic_ir.py (add/query methods)
- Existing tested infrastructure: crossfile/atomic.py (AtomicOperation), analysis/connectivity.py (NetGraph), ir/transaction.py (per-file transaction)
- KNOWN_LIMITATIONS.md: Gaps H-1, M-1, M-3, M-4, M-6

### Secondary (MEDIUM confidence)
- Council of Ricks All-Hands Audit (Phase 24): Findings H-1, H-6, H-8, M-1, M-3, M-4, M-6, M-8
- kiutils GitHub issues for UUID serialization limitations
- KiCad S-expression format documentation (dev-docs.kicad.org)

### Tertiary (LOW confidence)
- Schematic wire tracing complexity estimate (Pitfall 12) -- the dead code in repair.py suggests this was attempted and abandoned. Needs fresh investigation if schematic connectivity is ever scoped.
- Cross-file race condition with KiCad GUI (FEATURES.md edge case) -- file locking via fcntl mitigates but does not eliminate this. Acceptable for v2.2.

---
*Research completed: 2026-05-29*
*Ready for roadmap: yes*
