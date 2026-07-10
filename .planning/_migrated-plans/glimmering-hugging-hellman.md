# Improve A* Router — Vias, Multi-Pass, Avoidance

## Context

`hardware/dumb-cartridges/router_utils.py` is the shared router used by doom-core, doom-destroy, and other cartridge auto_route.py scripts. It has 5 concrete problems:

1. **Vias land on occupied cells** — `astar_multilayer` via transitions only check `grids[target_layer][cx][cy]` for the single cell; no via pad clearance check
2. **No trace clearance** — `mark_path_occupied` marks only the exact grid cells a path occupies; adjacent cells stay free, so subsequent routes can run parallel at 0 spacing
3. **Multi-pass is weak** — Failed nets retry in the same order with the same strategy; no shuffling, no strategy variation
4. **Scanning via is shallow** — Only 14 fixed candidates, no density awareness
5. **Heap tie-breaking** — `(f_score, 0, gx, gy)` means ties break by coordinates alone, causing erratic path choices

## Changes (single file: `router_utils.py`)

### 1. Trace clearance (`mark_path_occupied` / `build_grids`)

Add a `clearance` parameter (default 1 grid cell = 0.25mm) that marks a buffer zone around each occupied cell. This gives proper trace-to-trace spacing.

- `mark_path_occupied` — expand each cell to a 3x3 block (or configurable radius)
- `unmark_path_occupied` — same expansion, for clean rip-up
- `build_grids` — pad clearance already uses pad_w/2 + trace_w/2; keep as-is (pads are bigger)

### 2. Via pad clearance (`astar_multilayer`)

When placing a via at (cx, cy), check a via_pad_radius around (cx, cy) is clear on BOTH the source and target layers. If not, skip the transition.

```python
VIA_CLEARANCE = max(1, int((self.via_pad / 2 + self.trace_width / 2) / self.grid))
# Check (cx±VIA_CLEARANCE, cy±VIA_CLEARANCE) on both layers
```

### 3. Better heap tie-breaking

Use `(f_score, layer_tiebreaker, h_score, gx, gy)` so:
- Prefer moves on preferred layers (direction bonuses)
- Among equal f-scores, prefer nodes closer to goal (higher h resolution)
- Stable ordering by coordinates as last resort

### 4. Improved scanning via

- Add more candidates: diagonal offsets from midpoint, plus ring around endpoints
- Score candidates by distance to nearest pad (penalize via placements near pads)
- Sort candidates by score before trying (best first)

### 5. Better multi-pass

- Pass 1: normal order (priority nets first, then by pad count)
- Pass 2+: failed nets first, then remaining, with randomized order within tiers
- Each pass tracks strategy used per net; alternate preferred layer on retry
- Early termination if no improvement (already exists, keep it)

### 6. Via cost increase

Increase `VIA_COST` from 3 to 5 (relative to move cost 1-2). Vias are expensive in manufacturing and the router currently over-uses them. Higher cost makes single-layer routes preferred unless genuinely blocked.

## Files Modified

- `hardware/dumb-cartridges/router_utils.py` — all changes here

## Verification

```bash
# Test on doom-core (already has auto_route.py consuming router_utils)
cd hardware/dumb-cartridges/doom-core/schematic
python3 auto_route.py --dry-run --passes 3

# Compare: check via count drops, failed nets drops, route count increases
# Before: note current stats
# After: expect fewer vias, same or better completion rate
```
