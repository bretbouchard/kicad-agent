# Plan: Component Relocation + Re-route (Tile-x64)

## Context

The tile-x64 PCB has 59 unconnected pads after Freerouting v3 (1926 tracks, 0 shorts, 502 DRC violations). Many unconnected nets require long traces across the board because components are poorly placed relative to U1 (RP2040). Moving crystal, decoupling caps, I2C pullups, and R_series1 closer to U1 will dramatically improve routability. After relocation, strip all traces/zones and re-run Freerouting from scratch.

## Steps

### 1. Move components via pcbnew Python script

Use KiCad Python to relocate footprints to optimized positions:

| Component | Current | New | Reason |
|-----------|---------|-----|--------|
| Y1 (Crystal) | (119.4, 77.85) | (81.5, 72.5) | Directly above U1 XIN/XOUT pins |
| C_xtal1 | (97, 73) | (77.0, 73.0) | Near crystal pin 1 |
| C_xtal2 | (97, 87) | (86.0, 73.0) | Near crystal pin 2 |
| R_i2c_scl1 | (15, 80) | (86.0, 83.5) | Right of U1 SCL pad |
| R_i2c_sda1 | (15, 85) | (86.0, 85.5) | Right of U1 SDA pad |
| C_inj_1 | (66.05, 75) | (85.5, 75.0) | Decoupling near U1 |
| C_inj_2 | (73, 88) | (85.5, 77.0) | Decoupling near U1 |
| C_inj_3 | (91.95, 75.5) | (85.5, 79.0) | Decoupling near U1 |
| C_inj_4 | (87, 88) | (88.0, 75.0) | Decoupling near U1 |
| C_inj_5 | (70.05, 75) | (88.0, 77.0) | Decoupling near U1 |
| R_series1 | (80, 120) | (79.0, 87.5) | Near U1 LED output pad |

**File**: Write `/tmp/move_components.py`, run with KiCad Python.

**Critical**: Only move these components — do NOT move U1, U_flash1, U2, J_usb1, J_swd1, J3, J4, LEDs, buttons, diodes, or column pulldown resistors.

### 2. Strip all traces and zones

Write `/tmp/strip_pcb_v2.py` using text manipulation (regex) to remove all `(segment ...)`, `(via ...)`, and `(zone ...)` blocks from `tile.kicad_pcb`. This avoids pcbnew crashes.

### 3. Export DSN

Use KiCad Python (`pcbnew.ExportSpecctraDSN`) to export Specctra DSN from the clean board.

### 4. Run Freerouting

**Requires user to be at the machine** — Freerouting opens a GUI window even in CLI mode and needs a display to render. Run:

```bash
java -jar /tmp/freerouting.jar -de /tmp/tile_v5.dsn -do /tmp/tile_v5.ses
```

Estimated time: 10-20 minutes. Save the SES when complete.

### 5. Import SES + add zones

Use KiCad Python to:
1. `pcbnew.ImportSpecctraSES` to import routing
2. Add +3V3 copper fill zone on F.Cu (board outline)
3. Add GND copper fill zone on B.Cu (board outline)
4. `pcbnew.ZONE_FILLER(board).Fill(board.Zones())`
5. Save board

### 6. DRC verification

```bash
kicad-cli pcb drc --output /tmp/tile_drc_v5.rpt tile.kicad_pcb
```

Review violations — target: 0 shorts, minimize unconnected.

### 7. Manual routing (if needed)

Route any remaining unconnected pads using targeted single-segment traces on appropriate layers. Use B.Cu for long horizontal runs (ROW nets), F.Cu for short connections.

### 8. Commit

Commit with message: `feat(pcb): relocate components + Freerouting v5`

## Files Modified

- `tile/tile-x64/tile.kicad_pcb` — Main PCB file (all changes)
- `/tmp/move_components.py` — Script (temporary)
- `/tmp/strip_pcb_v2.py` — Script (temporary)

## Verification

1. DRC report shows 0 shorts
2. Unconnected count significantly reduced from 59
3. No overlapping footprints (visual check in KiCad)
4. Copper zones fill correctly
5. Board outline unchanged (160x160mm)
