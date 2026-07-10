# PCB Routing Plans — tile-rp16 & tile-x64

## Context

Council of Ricks rejected both PCBs with 19 issues (5 critical). All auto-routed tracks on tile-x64 were removed (unmanufacturable: 0.089mm tracks, 0.25mm vias). tile-rp16 has 34 footprints with lost netlist linkage (REF**). Both boards need complete re-routes from scratch with proper net classes, manual critical-signal routing, and Freerouting for the rest.

---

## Plan A: tile-x64 (160x160mm, RP2040 + 64 LEDs + 8x8 buttons)

### Step 1: Relocate Crystal (<10mm from RP2040)
- Crystal currently at (98, 14.5) — **19.58mm** from RP2040 at (80.6, 39.7)
- Move crystal to ~(87, 32) or similar — within 10mm of RP2040 center
- KiCad Python API: `pcbnew.FOOTPRINT` position update
- **File**: `tile/tile-x64/tile.kicad_pcb`

### Step 2: Manual RP2040 QFN-56 Fanout
- Fanout all 56 pads with short escape traces
- Inner ring (pads 1-14, 15-28, 29-42, 43-56): 0.15mm tracks, 0.2mm clearance
- Thermal pad: via array (4-5 GND vias, 0.6mm drill / 1.0mm pad)
- **Script**: New `tools/fanout_rp2040_x64.py` using KiCad Python API
- **GPIO remap** (critical for routability): ROW signals → LEFT QFN side, COL signals → BOTTOM side

### Step 3: Manual USB Diff Pair
- USB_DP/USB_DM as coupled pair, 90Ω differential impedance
- Route from USB-C connector at (80, 155) to RP2040 USB pads
- Length-match within 0.5mm, 0.2mm track / 0.15mm gap
- No vias on diff pair if possible

### Step 4: Manual Crystal Routing
- XIN/XOUT traces <10mm (verified after Step 1 relocation)
- Guard traces (GND) flanking both sides
- 0.15mm tracks, minimize crossing other nets

### Step 5: Manual QSPI Flash Routing
- Flash at (79.365, 27.525), RP2040 at (80.6, 39.7) — ~12mm apart
- Short, direct traces for SD0-SD3, SCLK, CS#
- Length-match within 2mm

### Step 6: Manual Power Distribution
- +3V3 from LDO at (140.65, 137.8) to RP2040, flash, crystal
- +5V from USB-C to LDO input
- 0.35mm track width for all Power net class
- Star topology from LDO output

### Step 7: Freerouting for Remaining Signals
- Export DSN: `pcbnew.ExportSpecctraDSN("tile-x64.dsn")`
- Run Freerouting with net class constraints (already defined)
- Import SES: `pcbnew.ImportSpecctraSES("tile-x64.ses")`
- Expected: 4-56 unconnected, fix manually

### Step 8: GND Copper Pour
- Add GND pour on B.Cu (bottom layer)
- 0.5mm clearance from non-GND pads/tracks
- Thermal reliefs on GND pads
- KiCad Python API: `pcbnew.ZONE` on B.Cu with GND net

### Step 9: DRC Verification
- Target: 0 electrical errors, 0 unconnected
- Cosmetic silk warnings acceptable
- Run: `kicad-cli pcb drc tile.kicad_pcb`

**Files modified**:
- `tile/tile-x64/tile.kicad_pcb` — All routing changes
- `tile/tile-x64/DRC.rpt` — Verification output
- `tools/fanout_rp2040_x64.py` — New fanout script

---

## Plan B: tile-rp16 (275x70mm, RP2040 + 16 PB86 buttons + 2x 74HC595)

### Step 1: GUI — Update PCB from Schematic (MANUAL, cannot automate)
- Open `tile-rp16.kicad_pcb` in KiCad GUI
- Tools → Update PCB from Schematic (or icon)
- This restores netlist linkage for 34 REF** footprints
- **Blocker**: Cannot proceed with routing until this is done
- **User must do this step**

### Step 2: Create Design Rules File
- Create `tile/tile-rp16/tile-rp16.kicad_dru` matching tile-x64 rules
- Minimum clearance: 0.2mm
- Minimum track width: 0.15mm
- Power track width: 0.35mm
- Via minimum drill: 0.3mm
- Solder mask clearance: 0.05mm

### Step 3: Define Net Classes
- Use KiCad Python API to add net classes to board:
  - Power: 0.35mm track, 0.2mm clearance, 0.6mm drill / 1.0mm pad via
  - HighSpeed: 0.15mm track, 0.15mm clearance (USB)
  - LED_Data: 0.15mm track, 0.2mm clearance
  - Default: 0.15mm track, 0.2mm clearance

### Step 4: Manual RP2040 QFN-56 Fanout
- RP2040 at (274.85, 22) — right side of board
- Fanout all 56 pads with escape traces
- Thermal pad: GND via array
- **Script**: New `tools/fanout_rp2040_rp16.py`

### Step 5: Manual Critical Signal Routing
- USB diff pair from connector to RP2040
- Crystal XIN/XOUT with guard traces
- QSPI flash traces (short, direct)
- Power distribution (+3V3, +5V at 0.35mm)
- 74HC595 SPI (DATA, CLK, LATCH) to RP2040

### Step 6: Freerouting for Remaining Signals
- Export DSN → Run Freerouting → Import SES
- Button matrix (4x4), LED chains (SK6812 data lines)
- Expected: some unconnected, fix manually
- **Script**: Extend existing `tools/route_tile_rp16.py`

### Step 7: GND Copper Pour
- B.Cu GND pour with thermal reliefs
- 0.5mm clearance from non-GND features

### Step 8: DRC Verification
- Target: 0 electrical errors, 0 unconnected
- Run: `kicad-cli pcb drc tile-rp16.kicad_pcb`

**Files modified**:
- `tile/tile-rp16/tile-rp16.kicad_pcb` — All routing changes
- `tile/tile-rp16/tile-rp16.kicad_dru` — New design rules
- `tile/tile-rp16/DRC.rpt` — Verification output
- `tools/fanout_rp2040_rp16.py` — New fanout script
- `tools/route_tile_rp16.py` — Updated routing workflow

---

## Execution Order

1. **tile-x64 Steps 1-6** (fully automatable, no GUI dependency)
2. **tile-rp16 Step 2-4** (automatable, but Step 1 is user-blocking)
3. **Pause for user**: tile-rp16 Step 1 (GUI Update PCB from Schematic)
4. **tile-x64 Steps 7-9** (Freerouting + pour + DRC)
5. **tile-rp16 Steps 5-8** (after user completes GUI step)

## KiCad Python Path
```
/Applications/KiCad/kicad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
```

## Key APIs
- `pcbnew.FOOTPRINT.SetPosition()` — move components
- `pcbnew.PCB_TRACK()` / `pcbnew.PCB_VIA()` — create traces/vias
- `board.Add(track)` — add to board
- `pcbnew.ExportSpecctraDSN()` / `pcbnew.ImportSpecctraSES()` — Freerouting
- `pcbnew.ZONE()` — copper pours
- `board.GetDesignSettings().m_NetSettings.SetNetclass()` — net classes

## Verification
- DRC both boards: `kicad-cli pcb drc <file>`
- Target: 0 electrical, 0 unconnected per board
- Cosmetic silk warnings OK (text overlap on dense components)
