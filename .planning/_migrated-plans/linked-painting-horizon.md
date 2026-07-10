# Plan: Fix 9 Remaining Backplane Shorts (Programmatic, No GUI)

## Context

Backplane has 9 `multiple_net_names` ERC violations remaining. Each is caused by wires on a sub-sheet physically connecting two different-named labels together. These can all be fixed programmatically by finding and removing the offending wire segments.

## Approach

For each short:
1. Parse the sub-sheet's wires into a connectivity graph
2. Find the wire chain connecting label A to label B (using coordinates from ERC report)
3. Identify which specific wire segment(s) to remove to break the connection
4. Remove those wire S-expressions from the file

## The 9 Shorts

| # | Short | Sheet File | Label A (coord) | Label B (coord) |
|---|-------|-----------|----------------|----------------|
| 1 | ADC_IN_1 ↔ GND | `backplane.kicad_sch` | Global (330.20, 121.92) | Global (78.74, 40.64) |
| 2 | +3.3V ↔ VCC_5V | `power-supply.kicad_sch` | Label (142.24, 91.44) | HLabel (180.34, 50.80) |
| 3 | VCC_12V ↔ VCC_5V | `control-center-iface.kicad_sch` | Global (60.96, 91.44) | HLabel (289.56, 91.44) |
| 4 | ALERT_N ↔ VCC_3V3 | `control-center-iface.kicad_sch` | Global (269.24, 116.84) | HLabel (289.56, 99.06) |
| 5 | GND ↔ VCC_-12V | `slot-connectors.kicad_sch` | Label (157.48, 203.20) | Label (261.62, 185.42) |
| 6 | GUITAR_TO_XPOINT ↔ XPOINT_TO_AMP | `guitar-io.kicad_sch` | Global (110.49, 48.26) | HLabel (185.42, 49.53) |
| 7 | ALERT_N ↔ SCL_LOCAL | `i2c-bus.kicad_sch` | Label (54.61, 63.50) | Label (45.72, 68.58) |
| 8 | I2C_SDA ↔ TDM_BCLK | `codecs.kicad_sch` | HLabel (30.48, 49.53) | HLabel (30.48, 59.69) |
| 9 | DAC_OUT_1 ↔ DAC_OUT_3 | `codecs.kicad_sch` | HLabel (369.57, 69.85) | HLabel (369.57, 76.20) |

## Execution Steps

### Step 1: Read each sheet and trace wire chains

For each of the 9 shorts, read the sheet file and:
- Extract all wire endpoints `(wire (pts (xy x1 y1) (xy x2 y2)))`
- Extract all label/hierarchical_label/global_label positions
- Build connectivity graph (points within 0.01mm tolerance are connected)
- Find the wire path from Label A position to Label B position

### Step 2: Remove the shortest wire segment that breaks the connection

For each short, identify the minimum wire(s) to remove that:
- Breaks the connection between the two labels
- Doesn't remove wires that are needed for other connections on the same net
- Use graph cut analysis — find the bridge edges in the path

### Step 3: Edit the files

Remove the identified wire S-expressions from each file.

### Step 4: Verify

- Re-run ERC: `kicad-cli sch erc hardware/backplane/backplane.kicad_sch`
- Count `multiple_net_names` — should be 0
- Commit

## Key Files to Read/Modify

| File | Shorts |
|------|--------|
| `hardware/backplane/backplane.kicad_sch` | #1 |
| `hardware/backplane/power-supply.kicad_sch` | #2 |
| `hardware/backplane/control-center-iface.kicad_sch` | #3, #4 |
| `hardware/backplane/slot-connectors.kicad_sch` | #5 |
| `hardware/backplane/guitar-io.kicad_sch` | #6 |
| `hardware/backplane/i2c-bus.kicad_sch` | #7 |
| `hardware/backplane/codecs.kicad_sch` | #8, #9 |

## Verification

1. `kicad-cli sch erc hardware/backplane/backplane.kicad_sch` — 0 multiple_net_names
2. No new violation types introduced
3. Paren balance check on all modified files
4. Target: 908 → ~899 violations
