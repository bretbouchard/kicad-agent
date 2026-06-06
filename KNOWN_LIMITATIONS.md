# Known Limitations

Documented from Council of Ricks All-Hands Audit (Phase 24, 2026-05-28).

56 findings identified. All critical and high-priority items fixed. Architecture gaps addressed in subsequent phases. Remaining limitations documented below.

Last updated: 2026-06-06

---

## Architecture Gaps

### H-1: Hierarchical Sheet Operations
- **RESOLVED** — Phase 28: `add_sheet`, `add_sheet_pin`, `navigate_hierarchy` implemented

### H-2: MCP Server Missing Editing Operations
- **RESOLVED** — Phase 30-31: All 57 operations + 4 meta-tools exposed via MCP server (`kicad-agent-edit`)

### M-1: Cross-file Infrastructure Not Wired
- **RESOLVED** — Phase 29: `propagate_symbol_change` via AtomicOperation

### M-3: No Remove Operations for Wires, Labels, Junctions
- **RESOLVED** — Phase 25: `remove_wire`, `remove_label`, `remove_junction`, `remove_no_connect`

### M-6: No Connectivity/Netlist Query Operation
- **RESOLVED** — Phase 26: `query_connectivity` operation exposed

## Operations Gaps

### M-4: No Footprint Creation Operation
- **RESOLVED** — Phase 27: `create_footprint` with PadSpec schema

### M-5: Auto-router Single-Layer Only
- **PARTIALLY RESOLVED** — Phase 36 added multi-layer routing with via placement. Phase 62 added Steiner-tree multi-pin routing.
- Remaining: Via optimization for complex multi-layer designs

## Performance Limitations

### M-7: No Batch Operation Mode
- **RESOLVED** — Phase 32: `execute_batch` with in-memory IR caching

### M-8: IR Re-parsed from Scratch on Every Operation
- **RESOLVED** — Phase 32: Cache system with 30-second TTL, warm start on repeated files

## Architecture

### M-2: No Undo/Redo Stack
- **RESOLVED** — Phase 33: In-memory UndoStack + Phase 70: PersistentUndoStack with file-based persistence, CLI undo/redo

## Training Pipeline

### M-14: Circular Reward Model Evaluation
- Remaining: No held-out real-world evaluation set for reward model quality

### M-15: PPO Clip Applied to Advantages
- Remaining: Mathematically different from standard PPO/GRPO clipping — verify correctness

## Remaining Limitations (Post-v3.1)

### Roundtrip Regression
- One .kicad_pcb fixture in the regression suite fails round-trip due to UUID type mismatch (pad vs gr_line). Pre-existing issue, not caused by recent phases.

### Test Isolation Flakes
- 2 tests fail intermittently when run with full suite but pass individually (test_orphan_bridge_falls_back_to_labels, test_obstacles_cover_footprint_areas). Likely timing/ordering dependency.

### Native PCB Parser Coverage
- Phase 76 native parser handles most files but some edge cases may still fall back to kiutils with silent degradation.
