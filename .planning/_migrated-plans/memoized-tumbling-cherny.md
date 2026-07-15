# Break Wire Shorts Operation

## Context

The analog board has 9 `multiple_net_names` ERC violations where physical wire segments on the root sheet connect nets that shouldn't be connected (e.g. ADC_IN_1 ↔ GND, +3.3V ↔ VCC_5V). The existing `fix_shorted_nets` operation only removes duplicate *labels* — it doesn't break the actual wire connections. We need a new operation that identifies and removes the bridge wires causing the shorts.

## How KiCad Wire Shorts Work

- Wires are line segments with `(start_x, start_y)` and `(end_x, end_y)` in mm
- Two wires connect when they share an endpoint position (within 0.01mm tolerance)
- A "short" occurs when wire connectivity links two positions with different net labels
- The "bridge wire" is the wire segment(s) on the path between a Net A label and a Net B label

## Algorithm

1. **Detect shorts** — Reuse `detect_shorted_nets()` from `repair.py` to find all shorted net pairs
2. **Filter to requested pairs** — If user specifies net pairs, only process those
3. **For each short, find bridge wires:**
   - Map all label positions to their net names
   - Build wire adjacency graph (position → list of connected positions via wires)
   - BFS from Net A label positions to Net B label positions
   - The wire on the shortest path = bridge wire
4. **Remove bridge wire** — Pop from `sch.graphicalItems` and record mutation
5. **Optionally re-route** — Not in v1; the user re-routes manually or via the router

## Files to Modify

| File | Change |
|------|--------|
| `src/volta/ops/_schema_repair.py` | Add `BreakWireShortsOp` schema |
| `src/volta/ops/repair.py` | Add `break_wire_shorts()` handler + `find_bridge_wires()` helper |
| `src/volta/ops/executor.py` | Register handler (hook will auto-generate) |
| `tests/test_erc_auto_fix.py` | Add tests for schema + handler |
| `tests/test_slc_compliance.py` | Update op count 62 → 63 |

## New Schema: `BreakWireShortsOp`

```python
class BreakWireShortsOp(BaseModel):
    op_type: Literal["break_wire_shorts"] = "break_wire_shorts"
    target_file: TargetFile
    net_pairs: Optional[list[tuple[str, str]]] = None  # specific pairs, or None for all
    strategy: Literal["shortest_path", "all_bridges"] = "shortest_path"
    dry_run: bool = False
```

## New Handler: `break_wire_shorts()`

```
def break_wire_shorts(ir, file_path, *, net_pairs=None, strategy="shortest_path", dry_run=False):
    1. detect_shorted_nets(ir) → get all shorts
    2. Filter to net_pairs if specified
    3. For each short:
       a. Get label positions for each net in the pair
       b. Build position adjacency via wire endpoints
       c. BFS from net_A positions → find shortest path to net_B positions
       d. Identify the bridge wire(s) on that path
       e. Record for removal
    4. Remove bridge wires (reverse index order to preserve indices)
    5. Return {shorts_found, wires_removed, details}
```

## Helper: `find_bridge_wires()`

Core geometry + BFS logic:
- Input: SchematicIR, net_a_name, net_b_name
- Build `_wire_endpoints_map` from `ir.get_wire_endpoints()`
- Build position adjacency: for each wire, connect start↔end
- BFS from all net_a label positions, tracking parent wires
- When we reach a net_b label position, trace back to find the bridge wire
- Return list of wire indices to remove

## Reused Infrastructure

| Component | File | What we use |
|-----------|------|-------------|
| `detect_shorted_nets()` | `repair.py:168` | Find all shorted net pairs |
| `_round_pos()` | `repair.py` | Position hashing (2-decimal rounding) |
| `ir.get_label_positions()` | `schematic_ir.py` | Map labels → positions |
| `ir.get_wire_endpoints()` | `schematic_ir.py` | Get all wire segments with indices |
| `sch.graphicalItems` | kiutils | Wire removal by index |
| `ir._record_mutation()` | schematic_ir.py | Mutation audit trail |

## Verification

1. **Unit tests**: Schema validation, dry_run reports correct shorts, handler removes correct wires
2. **Fixture test**: Run on Arduino_Mega fixture with dry_run (no modifications)
3. **Op count**: Update `test_slc_compliance.py` from 62 → 63
4. **Regression**: Full test suite passes (1781+ tests)
