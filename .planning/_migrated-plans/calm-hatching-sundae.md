# Wire Router — Fix Category A Card-Edge Overlaps

## Context

Steps 1-4 (previous plan) fixed Category B inter-sheet routing with channel allocation + same-side pin selection. Category B is clean. But **4 `multiple_net_names` violations remain** in the generated `rat.kicad_sch`, all from Category A (card-edge to sheet) routing.

**Root cause**: Category A routes use direct Manhattan routing from card-edge pin to sheet pin. Left-side pins (x=63.5) route rightward through x=88.9 where right-side pin labels sit. Right-side pins (x=88.9) have horizontal wire segments at x=88.9 that pass through other right-side labels. **Every left/right pin pair shares the same Y coordinate** (31 pairs total), so every left-side wire going right passes through a right-side label.

**Current violations** (4):
- ALERT_N / I2C_SCL (both right-side, wires at x=88.9)
- AGND / CV_1 (right-side)
- CV_2 / CV_3 (right-side)
- CV_5 / CV_7 (right-side)

## Fix: Center Channel Allocation for Category A

Apply the same 3-segment channel routing to Category A that works for Category B. Each signal gets a unique vertical center channel between the card-edge (x=88.9) and the sheets (x=167.64).

**Center channel placement**: `ChannelAllocator._center_start` already computes `(card_edge_right_x + min(sheet_lefts)) / 2` = (88.9 + 167.64) / 2 = 128.27mm. Channels increment by 2.54mm.

**Why this fixes it**: The horizontal wire segment at the card-edge pin's Y only extends from the pin to the channel (e.g., x=88.9 to x=128.27), NOT through other pin labels. The label stays at the card-edge position. The wire from the label goes right to the channel, then vertically to the target Y, then right to the sheet.

**Remaining risk**: Left-side pins at x=63.5 route rightward to their center channel. Their horizontal segment passes through x=88.9 (right-side labels). If a left-side pin and right-side pin share the same Y, the horizontal wire body passes through the right-side label. This is a KiCad wire-body-through-label overlap — KiCad treats wire bodies and labels differently: a wire passing through a label position DOES create a junction. However, this is the SAME problem that existed before, just with center channels instead of Manhattan routing. The 4 current violations are all right-side signals, so this fix should eliminate them. Left/right Y collisions are a separate issue.

## File

`hardware/dumb-cartridges/cartridge-gen/wiring/wire_router.py` — sole file to modify.

## Changes

### 1. Add `channel_x` param to `_route_card_edge_to_sheet` (line 529)

Add optional `channel_x: float | None = None`. When provided, use 3-segment routing:

```python
def _route_card_edge_to_sheet(
    cep: CardEdgePin,
    sheet_pin: SheetPin,
    sheets: list[SheetInfo],
    channel_x: float | None = None,
) -> list[str]:
    sx, sy = cep.abs_x, cep.abs_y
    dx, dy = sheet_pin.abs_x, sheet_pin.abs_y

    if channel_x is not None:
        return [
            wire(sx, sy, channel_x, sy),
            wire(channel_x, sy, channel_x, dy),
            wire(channel_x, dy, dx, dy),
        ]

    # Fallback: existing Manhattan with sheet-collision avoidance
    ...
```

### 2. Pass `allocator` to `_route_card_edge_wires` (line 566)

Add `allocator: ChannelAllocator` parameter. For each signal, allocate a center channel:

```python
channel_x = allocator.allocate_center(signal_name)
route = _route_card_edge_to_sheet(cep, target_pin, sheets, channel_x=channel_x)
```

Also move `sheet_by_name` construction outside the inner loop (currently rebuilt every iteration).

### 3. Pass allocator from `route_wires` (line 730)

```python
a_wires, a_labels = _route_card_edge_wires(
    sheets, card_edge_pins, signal_map, card_edge_map, used_signals,
    allocator=allocator)
```

## Implementation Steps

1. Edit `_route_card_edge_to_sheet` — add `channel_x` param, 3-segment path
2. Edit `_route_card_edge_wires` — add `allocator` param, allocate center channel per signal, pass to route function
3. Edit `route_wires` — pass `allocator` to `_route_card_edge_wires`

## Verification

1. `cd hardware/dumb-cartridges/cartridge-gen && python3 generate.py /Users/bretbouchard/apps/analog-ecosystem/hardware/dumb-cartridges/specs/rat-overdrive.yaml`
2. Run ERC: `kicad-cli sch erc /Users/bretbouchard/apps/analog-ecosystem/hardware/dumb-cartridges/rat-overdrive/schematic/rat.kicad_sch`
3. Count `multiple_net_names` — target: 0 (from current 4)
4. Total violations should decrease
5. Category B and C should be unaffected
