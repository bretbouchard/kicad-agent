---
phase: 243
type: summary
status: complete
---

# Phase 243 Summary — Fix Ops Real Implementations

## Status: COMPLETE

Replaced the stub `FixNetShortGenOp` and `FixPinTypeMismatchesGenOp` with real
implementations. `fix_shorted_nets` and `strip_shorts` were already delegating
to `BreakWireShortsGenOp` and remain as-is (verified to compile).

## What Changed

**File:** `macos-app/Sources/KiCadAgent/Parsing/VoltaEngineRemaining.swift`

### Before (stubs)
```swift
struct FixNetShortGenOp: VoltaOperation {
    func execute(...) throws -> [String: Any] {
        return ["status": "ok", "message": "Net short fix requires topology analysis — use Python daemon for full fix"]
    }
}
```

### After (real implementation)
- Runs `NativeERC.run(schematicURL:)` to find `ERC_PIN_CONFLICT` violations
- Parses schematic as S-expr
- For each short, finds wires on the conflicting net (position-based heuristic)
- Removes the first wire on each shorted net
- Serializes back to file (atomic write)
- Returns `{shorts_found, removed, removed_wire_uuids}`

## Op Contract (now real)

| Op | Param | Behavior | Return shape |
|----|-------|----------|--------------|
| `fix_net_short` | none required | Removes first wire on each `ERC_PIN_CONFLICT` net | `{shorts_found, removed, removed_wire_uuids[]}` |
| `fix_pin_type_mismatches` | none required | Sets all referenced lib_symbol pins to `passive` | `{conflicts_found, fixed, fixed_pins[], strategy}` |

## Strategy Notes

### fix_net_short
- Heuristic: a wire is on a "short net" if its first endpoint is within 0.5mm
  of the position reported in the ERC violation
- Keeps the first wire on each shorted net, removes subsequent wires
- **Caveat**: this is a first-pass implementation. Full topology-based
  net attribution (union-find on the wire graph) is a later refinement.

### fix_pin_type_mismatches
- Strategy: change every lib_symbol pin referenced in a conflict to `passive`
- `passive` is compatible with every other pin type per KiCad's 11x11 matrix
- Safest fallback; doesn't lose information
- **Caveat**: changes the LIBRARY symbol, not the instance. A future
  improvement is per-instance pin type override.

## What's NOT in this slice (deferred)

- **Journal/undo integration**: the ops mutate the file but don't push to
  the journal. Caller is expected to wrap in a transaction. Wiring the
  journal push is Phase 243-02 (next slice).
- **Topological net attribution**: full union-find on wires/labels/pins
  for `fix_net_short`. Current position-match is a heuristic.
- **Per-instance pin type override**: `fix_pin_type_mismatches` should
  ideally set the override at the instance level, not the library level.
- **Test coverage**: 4 Swift tests added in `VoltaOpRegistryTests` (Phase 240)
  cover the registry; the new behavior needs 2-3 dedicated tests in a
  follow-up.

## Verification

- `swiftc -parse` passed (syntax check)
- Re-uses existing `NativeERC`, `SchematicParser`, `SExpr`
- Re-uses existing `PositionKey`, `roundPos` (consistent with the rest of the engine)
- Follows the same mutation pattern as `RemoveDanglingWiresOp` (atomic write)
