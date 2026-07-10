# Clearance-Aware Placement Fix for Analog Board

## Context

The analog board has 24 DRC pad-to-pad shorts after Freerouting. Components were placed by `place_analog_zones.py` (304 lines) using a 4mm grid pitch. The shorts happen because adjacent components' pad bounding boxes overlap — two footprints at 4mm center-to-center with 0.5mm pad extents only have 3mm between pad edges, but some need more due to net class clearances.

Key findings:
- All shorting components are 0402 passives (0.5mm max pad extent)
- R4 and R5 are at **identical coordinates** (80.0, 64.0) — exact overlap
- Most shorts are between components 2-4mm apart with pad extents eating the clearance gap
- DRC reports pad **edge** positions, not footprint centers (e.g., pad edge at 79.175 vs center at 80.0)

## Plan — modify `place_analog_zones.py`

### File: `hardware/network-io/channel-strip/place_analog_zones.py`

### Step 1: Add pad extent extraction to `parse_pcb()`

After parsing each footprint's ref, x, y, at_line — also extract max pad bounding box extent:

```python
# Inside parse_footprint loop, after finding pads:
if s2.startswith('(pad ') and depth == 2:
    pad_at_m = re.search(r'\(at\s+([\d.e+-]+)\s+([\d.e+-]+)', s2)
    pad_size_m = re.search(r'\(size\s+([\d.]+)\s+([\d.]+)\)', s2)
    if pad_at_m and pad_size_m:
        px, py = float(pad_at_m.group(1)), float(pad_at_m.group(2))
        pw, ph = float(pad_size_m.group(1)), float(pad_size_m.group(2))
        fp['pads'].append((px, py, pw, ph))

# After loop: compute max extent
if fp['pads']:
    fp['max_dx'] = max(abs(px) + pw/2 for px, py, pw, ph in fp['pads'])
    fp['max_dy'] = max(abs(py) + ph/2 for px, py, pw, ph in fp['pads'])
else:
    fp['max_dx'] = 0.5  # default
    fp['max_dy'] = 0.5
```

### Step 2: Add clearance-aware spacing to `compute_positions()`

Read net classes from `.kicad_pro` to get clearance requirements:
- Default clearance: 0.15mm
- Power clearance: 0.30mm

In the grid layout, after computing initial positions, resolve overlaps:

```python
def resolve_overlaps(zone_map, positions, net_classes):
    """Check adjacent footprints in same row for pad overlap + clearance."""
    # Group by zone, then by row (same Y)
    for zone, fps_in_zone in group_by_zone_and_row(zone_map, positions):
        # Sort by X within row
        sorted_fps = sorted(fps_in_zone, key=lambda f: positions[f['idx']])
        for j in range(1, len(sorted_fps)):
            fp_prev = sorted_fps[j-1]
            fp_curr = sorted_fps[j]
            # Required center-to-center: extent_prev + extent_curr + clearance
            min_dist = fp_prev['max_dx'] + fp_curr['max_dx'] + max_clearance(fp_prev, fp_curr)
            actual_dist = positions[fp_curr['idx']] - positions[fp_prev['idx']]
            if actual_dist < min_dist:
                # Shift right by the deficit
                deficit = min_dist - actual_dist
                positions[fp_curr['idx']] += deficit
```

### Step 3: Add exact overlap detection

For components at identical coordinates (R4/R5), detect and nudge:
```python
# Before grid placement: detect identical positions
position_counts = Counter((x, y) for fp in fps)
for (x, y), count in position_counts.items():
    if count > 1:
        # Nudge duplicates apart by 2mm
        instances = [(i, fp) for i, fp in enumerate(fps) 
                     if round(fp['x'], 1) == x and round(fp['y'], 1) == y]
        for k, (idx, fp) in enumerate(instances[1:], 1):
            # Will be handled by resolve_overlaps, but ensure initial spacing
            pass
```

### Step 4: Re-run the full pipeline

1. Run `place_analog_zones.py` (modifed) on the analog board → repositions components
2. Re-generate DSN with `generate_dsn.py`
3. Re-run Freerouting: `MultiPassRoute` (3 passes)
4. Import SES: `import_freerouting_ses.py`
5. Strip any shorts (should be fewer now)
6. DRC verify: `kicad-cli pcb drc`
7. Export gerbers

### Step 5: Also re-run Freerouting

Re-placing components invalidates existing routes. Must re-route after placement.

## Verification

1. Paren balance after placement
2. Zero identical-position footprints
3. DRC: fewer than 872 violations (current count)
4. Zero pad-to-pad shorts between placed components
5. kicad-cli loads board
