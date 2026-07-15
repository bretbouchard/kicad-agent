---
phase: 237
type: summary
status: complete
---

# Phase 237 Summary — safe_sync_pcb_from_schematic Real Implementation

## Status: COMPLETE (real implementation, not stub)

Replaced the stub `SafeSyncPcbFromSchematicGenOp` with a real diff computation.
The op now parses both the schematic and PCB, indexes symbols/footprints by
reference, and returns the full delta: added, removed, updated.

## What Changed

**File:** `macos-app/Sources/Volta/Parsing/VoltaEngineRemaining.swift`

**Before** (stub):
```swift
func execute(params: [String: Any], on fileURL: URL) throws -> [String: Any] {
    let board = try PCBParser.parse(fileURL)
    return ["status": "ok", "footprints": board.footprints.count,
            "message": "PCB synced (full sync requires schematic+PCB pair)"]
}
```

**After** (real diff): parses schematic + PCB, computes 3-way diff, returns
`{added, removed, updated, has_changes, ...}`. Op is still non-mutating
(caller journals the diff and applies via existing add_footprint /
remove_footprint / set_footprint_lib_id ops).

## Op Contract (now real)

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `schematic_path` | String | derived from PCB | `.kicad_sch` sibling of the PCB file |
| `dry_run` | Bool | `true` | matches Python `dry_run` semantics |
| `remove_orphans` | Bool | `false` | non-destructive by default (matches ae-26) |

## Return Shape

```json
{
  "status": "ok",
  "schematic_path": "...",
  "pcb_path": "...",
  "dry_run": true,
  "has_changes": true,
  "added":      [{"reference": "R1", "lib_id": "Resistor_SMD:R_0805", "action": "add_footprint"}],
  "removed":    [{"reference": "J1", "lib_id": "Connector_PinHeader:...", "action": "remove_footprint"}],
  "updated":    [{"reference": "U1", "from_lib_id": "old", "to_lib_id": "new", "action": "update_lib_id"}],
  "added_count": 3,
  "removed_count": 0,
  "updated_count": 1,
  "schematic_symbols": 12,
  "pcb_footprints": 9,
  "remove_orphans": false
}
```

## Preserve Invariants (matches Python ae-26)

- **Non-mutating**: this op returns a diff, never mutates the PCB
- **Routing preserved**: not touched (no segment/zone mutation)
- **Zones preserved**: not touched
- **Placement preserved**: not touched
- **`remove_orphans=false` by default**: orphans stay (avoids accidental deletion)
- **Caller applies**: the journal + existing add/remove ops handle atomicity

## Synced Ops

Three other ops in the same file previously delegated to the stub — they
now also get the real diff:
- `UpdatePcbFromSchematicGenOp` (`update_pcb_from_schematic`)
- `UpdateFromSchematicGenOp` (`update_from_schematic`)
- `RebuildPcbNetsGenOp` (different: it touches nets, not footprints)

## What's NOT in this slice (deferred)

- **Journal/undo integration**: the op returns a diff, doesn't push to the
  journal itself. The caller (the model-router or the chat-pipeline) is
  expected to journal. Wiring the journal push is Phase 237-02 (next slice).
- **Pad-net updates**: Python's `safe_sync` also updates pad nets via
  `sync_pcb_from_netlist`. Swift's PCB model doesn't yet have a per-pad
  net-edit op — that needs `set_pad_net` first.
- **Cross-file dispatch**: the Python op goes through `_CROSSFILE_HANDLERS`
  in execution.py. Swift has a single-op dispatch in VoltaEngine. Wiring
  multi-file context is a separate concern.

## Verification

- `swiftc -parse` passed (syntax check)
- Re-uses existing `SchematicParser` and `PCBParser` (no new parsers)
- Re-uses existing `SymbolInstance.reference` + `libId` (already in IR)
- Re-uses existing `PCBFootprint.reference` + `libId` (already in IR)
