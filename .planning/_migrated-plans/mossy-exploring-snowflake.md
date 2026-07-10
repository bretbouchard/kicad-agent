# Plan: Implement GAP-CP9 — Batch Synthetic Footprint Expansion in kicad-agent

## Context

Channel strip PCB manufacturing pipeline (21.5.x) is blocked at auto-route (21.5.4): 211/215 footprints on analog board and 47/48 on digital board are "synthetic" — they have lib_id + position + reference + value but no pad geometry. The router can't find connection points.

kicad-agent already has `update_footprint_from_library()` in `pcb_ir.py` (line 396) that loads a single footprint from its library .kicad_mod file and replaces geometry while preserving position, rotation, net assignments. It's registered as a PCB operation handler at `ops/handlers/pcb.py:56`.

**Missing:** A batch operation that iterates all synthetic footprints and calls the existing single-footprint expansion. Plus KiCad 10 format handling (`tedit`/`tstamp` instead of `uuid`).

## Approach

Create a new `batch_expand_footprints` PCB operation that:
1. Scans all footprint blocks in the PCB raw content
2. Identifies synthetic footprints (no `(pad ...)` lines)
3. For each synthetic footprint, resolves lib_id → .kicad_mod file path
4. Reads the library footprint, strips metadata, injects preserved placement/net data
5. Replaces the synthetic block with the expanded geometry
6. Reports expanded count and any failures

This reuses the existing `lib_resolver.resolve_footprint_path()` and the injection logic from `update_footprint_from_library()`.

## Files to Modify

### 1. `src/kicad_agent/ops/handlers/pcb.py` — Add batch_expand_footprints handler (~60 lines)
- New `@register_pcb("batch_expand_footprints")` function
- Iterates all footprints, filters synthetic ones, calls batch expansion on each
- Returns expanded/failed/skipped counts

### 2. `src/kicad_agent/ops/pcb_raw_writer.py` — Add batch expansion logic (~80 lines)
- New `batch_expand_footprints()` static method
- Core logic: parse all footprint blocks, identify synthetic, resolve + expand each
- Uses existing `_find_footprint_block()`, `resolve_footprint_path()`, `_inject_*` helpers
- Handles KiCad 10 format: preserve `tedit`/`tstamp`, handle `(tstamp ...-....-....)` format
- Preserves pad net assignments from original synthetic block (if any)
- Graceful error handling: log failures, continue with next footprint

### 3. `src/kicad_agent/ops/_schema_pcb.py` — Add schema validation (~20 lines)
- Add `batch_expand_footprints` to PCB operation schema
- Minimal schema: just `dry_run: bool = False`

### 4. `src/kicad_agent/ir/pcb_ir.py` — Fix KiCad 10 tstamp handling (~10 lines)
- `update_footprint_from_library()` extracts `uuid` field but synthetic footprints use `tstamp`
- Update `_extract_field` pattern to also match KiCad 10 `(tstamp ...-....-....)` format
- Or use `saved_tedit`/`saved_tstamp` extraction as primary (KiCad 10)

### 5. `src/kicad_agent/ops/registry.py` — Register new operation (~1 line)
- Add `"batch_expand_footprints": {...}` to registry

## Key Implementation Details

### Synthetic Footprint Detection
```python
# A synthetic footprint has lib_id, at, property, but NO (pad ...) lines
def _is_synthetic(block: str) -> bool:
    return "(pad " not in block
```

### KiCad 10 Timestamp Format
KiCad 10 uses two formats:
- `(tedit SHORT_HEX) (tstamp UUID-V1)` — 1-arg variant
- `(tstamp UUID-V1)` — in PCB files

The extraction must preserve these. Existing `_extract_field` uses `^\t\t\(uuid "([^"]+)"` which won't match. Need to add `^\t\t\(tstamp "([^"]+)"` pattern.

### Preserving Pad Net Assignments
Synthetic footprints MAY have net assignments on pads from prior sync operations. Extract and re-inject:
```python
pad_nets = {}
for m in re.finditer(r'\(pad "(\d+)"[^)]*\(net (\d+) "([^"]+)"', block):
    pad_nets[m.group(1)] = (m.group(2), m.group(3))
```

### Library Resolution Error Handling
If a footprint's .kicad_mod file doesn't exist (wrong lib_id, missing library):
- Log the error with reference and lib_id
- Skip expansion for that footprint
- Continue with remaining footprints
- Report in final summary

### Atomic Replacement Order
Must replace footprints from **bottom to top** in the file to preserve character offsets. Or use the `update_footprint()` method which handles offset tracking.

## Verification

1. **Unit test:** Create a test PCB with 2 synthetic footprints, run `batch_expand_footprints`, verify both get pads
2. **Dry run:** Run with `dry_run=True` — should report count without modifying file
3. **Channel strip test:** Run on analog-board.kicad_pcb, verify 211 synthetic footprints get expanded
4. **ERC/DRC check:** Run `kicad-cli sch erc` and `kicad-cli pcb drc` after expansion
5. **Net preservation:** Verify pad net assignments are preserved after expansion
6. **KiCad GUI validation:** Open expanded PCB in KiCad GUI, verify footprints render correctly

## Execution Order
1. Add schema + registry entry first (enables operation discovery)
2. Add `batch_expand_footprints()` to PcbRawWriter (core logic)
3. Fix KiCad 10 tstamp handling in pcb_ir.py
4. Add handler to pcb.py (wires it to /kicad-agent skill)
5. Test on channel strip PCBs
6. Re-execute 21.5.4 auto-route
