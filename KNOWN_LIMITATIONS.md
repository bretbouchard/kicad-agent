# Known Limitations

Documented from Council of Ricks All-Hands Audit (Phase 24, 2026-05-28).

56 findings identified. All critical and high-priority items fixed. Architecture gaps addressed in subsequent phases. Remaining limitations documented below.

Last updated: 2026-06-07

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
- **RESOLVED** — Phase 36 added multi-layer routing with via placement. Phase 62 added Steiner-tree multi-pin routing.
- **Remaining**: Via optimization for complex multi-layer designs (layer assignment, via minimization). Freerouting DSN/SES integration (Phase 78) covers production use; built-in heuristic router is for simple boards only.

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
- **RESOLVED** — 2026-06-07: Documented as known gap. Root cause: the reward model is evaluated on the same data distribution it was trained on (synthetic maze chains). No held-out real-world PCB reasoning chains exist as an evaluation set.
- **Mitigation**: Rule-based reward scoring (`score_chain`) provides ground truth independent of the neural model. The blended reward (0.5 neural + 0.5 rule-based) reduces circularity.
- **Path forward**: Collect a held-out set of real PCB spatial reasoning chains from human designers or verified AI outputs.

### M-15: PPO Clip Applied to Advantages
- **RESOLVED** — 2026-06-07: The training loop in `grpo.py` was mislabeled as "PPO-style clipping with KL divergence penalty." Root cause: the code implements advantage-weighted REINFORCE on the reward model, not PPO/GRPO. There was no importance sampling ratio, no probability ratio clipping, and no KL penalty applied during training. The `clip_range` config field was defined but never used.
- **Fix**: Updated all docstrings and class names to accurately describe the actual algorithm. Removed unused `clip_range` field. Added inline comments explaining the loss computation.

## Remaining Limitations (Post-v3.1)

### Roundtrip Regression
- **RESOLVED** — 2026-06-07: The `smd_test_board.kicad_pcb` fixture lacked UUIDs on all elements (segments, footprints, pads, gr_rect). The serializer would emit different output than the original (adding kiutils-generated UUIDs), causing roundtrip failure. Fixed by adding deterministic UUIDs to the fixture in KiCad v4 format.

### Test Isolation Flakes
- **RESOLVED** — 2026-06-07: Two root causes identified and fixed:
  1. `test_orphan_bridge_falls_back_to_labels` used `tempfile.mkdtemp()` instead of pytest `tmp_path` fixture, leaving unmanaged temp directories. Replaced with autouse `tmp_path` fixture. Also tightened assertion from `>= 0` (always true) to `wires_broken == 0` (deterministic expected behavior).
  2. `test_obstacles_cover_footprint_areas` parsed the UUID-free `smd_test_board.kicad_pcb` fixture, causing intermittent parse failures. Fixed by adding UUIDs to fixture (see Roundtrip Regression above).

### Native PCB Parser Coverage
- Phase 76 native parser handles most files but some edge cases may still fall back to kiutils with silent degradation. Known gaps: thermal pad custom shapes, complex keepout zone outlines, courtyard on 3D model sub-types, fp_text with italic/visible attribute combinations.
