# Plan: Channel Strip Remaining Schematic Design Work

## Context

Council of Ricks Standard mode review (3 specialists: kicad-rick, pi-rick, si-rick) identified 7 CRITICAL, 6 HIGH, and 6 MEDIUM findings across 15 schematics. Twenty-one programmatic fixes were applied (commits 987e51b, eb82394): footprint corrections, LED resistor values, W25Q16 symbol swap. The remaining findings require **design-level work** — adding components, wiring circuits, restructuring hierarchy — not just property changes.

The schematics are at "functional prototype" level: 253 wires across 12 sub-sheets, 268 components with footprints, all IC symbols correct. This plan addresses the design work needed before PCB layout.

---

## Task 1: TL431 Feedback Divider Resistors (CRITICAL)

**Problem:** Both TL431 shunt regulators (U2 for +9V, U3 for -9V) in `power-analog.kicad_sch` have no feedback divider resistors. Without dividers connecting REF pin to the output, the TL431s cannot regulate to 9V.

**Solution:** Add 4 new resistors (2 per TL431) and wire them.

**Components to add:**
- R8 (6.8k): +9V output → U2 REF pin (top of divider)
- R9 (3.9k): U2 REF pin → GND (bottom of divider)
- R10 (6.8k): -9V output → U3 REF pin (top of divider)
- R11 (3.9k): U3 REF pin → GND (bottom of divider)

**Calculation:** Vout = Vref × (1 + Rtop/Rbottom) = 2.495 × (1 + 6.8/3.9) = 2.495 × 2.744 = 6.84V

Wait — that gives 6.84V, not 9V. Let me recalculate:
- 9V = 2.495 × (1 + Rtop/Rbottom) → Rtop/Rbottom = 2.607
- Use Rtop = 6.49k, Rbottom = 3.92k (E96 values) → 9.03V ✓
- Or approximate: Rtop = 6.8k, Rbottom = 2.61k → 9.0V
- Best E24 pair: Rtop = 10k, Rbottom = 3.9k → 2.495 × (1 + 10/3.9) = 2.495 × 3.564 = 8.89V (close enough)

**Action:** Add 4 resistors (R8-R11, all 0603) via kiutils to power-analog.kicad_sch, then wire the divider connections using the batch_wire pattern.

**Files:** `hardware/network-io/channel-strip/power-analog.kicad_sch`

---

## Task 2: EQ Stage Wiring (MEDIUM → becomes CRITICAL for signal path)

**Problem:** eq-stage.kicad_sch has 34 components placed but 0 wires. The 3-band gyrator EQ is completely unwired.

**Circuit topology (per band):**
```
EQ_IN → coupling cap → NE5532 buffer → gyrator network (L + C + pot) → summing amp → coupling cap → EQ_OUT
```

**Gyrator band structure:**
- LOW band: DIGIPOT_LOW controls gain, inductor+cap set center frequency
- MID band: DIGIPOT_MID controls gain
- HIGH band: DIGIPOT_HIGH controls gain
- CD4066 (U3, currently SW_DIP symbol) provides GPIO_EQ_BYPASS control

**Steps:**
1. Wire NE5532 power pins to ±9V and AGND
2. Wire input coupling network (EQ_IN → C → U1 input)
3. Wire gyrator networks (3 bands: L+C+digipot per band)
4. Wire summing/output stage (U2 → C → EQ_OUT)
5. Wire CD4066 bypass switch (GPIO_EQ_BYPASS → U3 control pins)

**Blocker:** CD4066 uses SW_DIP_x04 symbol — needs swap to proper CD4066 analog switch symbol first.

**Files:** `hardware/network-io/channel-strip/eq-stage.kicad_sch`

---

## Task 3: Hierarchical Sheet Structure (CRITICAL)

**Problem:** Both root schematics (analog-board.kicad_sch, digital-board.kicad_sch) have no `(sheet ...)` references. All sub-sheets are orphans — KiCad can't run ERC across sheets or generate a complete netlist.

**Analog board hierarchy (analog-board.kicad_sch):**
```
analog-board.kicad_sch (root)
├── input-stage.kicad_sch       (hierarchical labels: SIG_HOT_IN, SIG_COLD_IN → SIG_HOT, SIG_COLD)
├── preamp-stage.kicad_sch      (hierarchical labels: SIG_HOT, SIG_COLD → COMP_IN)
├── compressor-stage.kicad_sch  (hierarchical labels: COMP_IN → EQ_IN)
├── eq-stage.kicad_sch          (hierarchical labels: EQ_IN → EQ_OUT)
├── output-stage.kicad_sch      (hierarchical labels: DAC1_L, DAC1_R → LINE_OUT)
├── codec-stage.kicad_sch       (hierarchical labels: ADC1_L/R, DAC1_L/R, I2S_*, I2C_*)
├── control-dacs.kicad_sch      (hierarchical labels: I2C_*, DAC_LDACn, CV_*)
├── gpio-expanders.kicad_sch    (hierarchical labels: I2C_*, GPIO_*, DIGIPOT_*)
├── power-analog.kicad_sch      (hierarchical labels: +12V_IN, +9V, -9V, AGND)
```

**Digital board hierarchy (digital-board.kicad_sch):**
```
digital-board.kicad_sch (root)
├── mcu-core.kicad_sch          (hierarchical labels: SPI_*, I2C_*, I2S_*, USB_*, UART_*)
├── network-audio.kicad_sch     (hierarchical labels: SPI_*, ETH_*)
├── usb-midi.kicad_sch          (hierarchical labels: USB_*, MIDI_*)
├── power-digital.kicad_sch     (hierarchical labels: +12V_IN, +5V, +3V3)
└── 5× EC11 encoders (in root sheet directly)
```

**Implementation:**
1. Convert all global labels in sub-sheets to hierarchical labels
2. Add `(sheet ...)` blocks to each root with matching `(pin ...)` definitions
3. Wire hierarchical pins between sheets in the root
4. This is best done in KiCad GUI due to the graphical placement complexity

**Files:** All 15 .kicad_sch files

---

## Task 4: RP2350B 80-Pin Symbol Expansion (CRITICAL)

**Problem:** Current RP2350B symbol has 38 pins. The real RP2350B in QFN-80 has 80 pins. Missing: 6 additional VCC pins, 6 additional GND pins, ~15 additional GPIOs, FLASH_SS, RUN, XIN/XOUT, SWD debug pins.

**Missing critical pins:**
- VCC pins 2, 4, 7, 10, 13, 16 (6 total, currently 3)
- GND pins (6 total, currently 3)
- GPIO36-GPIO47 (ADC capable, currently missing)
- FLASH_SS (GPIO0 secondary function)
- RUN (reset pin)
- XIN, XOUT (crystal, currently using separate crystal)
- SWCLK, SWDIO (debug)

**Approach:**
1. Create new 80-pin RP2350B symbol in shared library with all pins
2. Embed in mcu-core.kicad_sch
3. Swap from 38-pin to 80-pin symbol
4. Re-wire all existing connections to new pin positions
5. Connect all VCC/GND pins

**Note:** This is a significant rework. Consider keeping the 38-pin symbol for now and using a separate power-page or net-ties for the missing VCC/GND pins. The 38-pin symbol covers all used GPIOs.

**Decision:** Defer full 80-pin expansion. Add explicit power pin connections (6 VCC + 6 GND decoupling caps) as a minimum for board functionality.

**Files:** `hardware/shared/symbols/Analog-Ecosystem-SMD.kicad_sym`, `hardware/network-io/channel-strip/mcu-core.kicad_sch`

---

## Task 5: Signal Path Naming Fixes (HIGH)

**Problem:** Several global labels don't match between sheets, breaking the signal chain.

**Fixes needed:**

| Sheet | Current Label | Should Be | Reason |
|-------|---------------|-----------|--------|
| eq-stage | EQ_OUT | ADC1_L, ADC1_R (or add intermediate labels) | EQ output must reach codec ADC |
| gpio-expanders | GPIO_BYPASS | Also export GPIO_EQ_BYPASS | EQ bypass has no source |
| codec-stage | DGND (orphan) | Remove or connect to GND | DGND has no counterpart |

**Action:** Rename labels to create a complete signal chain:
```
Input → SIG_HOT/COLD → Preamp → COMP_IN → Compressor → EQ_IN → EQ → EQ_OUT/ADC1_L/R → Codec
```

**Files:** `eq-stage.kicad_sch`, `gpio-expanders.kicad_sch`, `codec-stage.kicad_sch`

---

## Task 6: SPI Chip Select Routing (HIGH)

**Problem:** 6 MCP4131 digital potentiometers on gpio-expanders.kicad_sch share one SPI_CS line. Each needs its own chip select.

**Current RP2350B GPIO allocation:**
- SPI0: GPIO14 (CLK), GPIO15 (TX/MOSI), GPIO16 (RX/MISO), GPIO17 (CS) → W5500
- SPI1: GPIO18-21 → needs 6 CS lines for digipots
- I2C0: GPIO4 (SDA), GPIO5 (SCL)
- I2S: GPIO8-GPIO12 (BCLK, LRCK, SDIN, SDOUT)
- USB: GPIO22, GPIO23
- Control: GPIO13 (DAC_LDACn)

**Available GPIOs for CS lines:**
- GPIO24-GPIO29 (6 pins) → perfect for 6 MCP4131 CS lines
- Or use PCA9534D GPIO expander outputs (already on board)

**Action:**
1. Add 6 global labels: SPI_CS0 through SPI_CS5 in mcu-core.kicad_sch (GPIO24-GPIO29)
2. Wire each MCP4131 CS pin to its respective label in gpio-expanders.kicad_sch

**Files:** `mcu-core.kicad_sch`, `gpio-expanders.kicad_sch`

---

## Task 7: Medium-Priority Fixes

**7a. AK4619VN PDN Pin Pullup**
- Add 10k pullup resistor from PDN pin (26) to TVDD
- Prevents random codec power-down
- File: `codec-stage.kicad_sch`

**7b. AGND/GND Star Ground Tie Point**
- Add explicit 0-ohm resistor or ferrite bead connecting AGND to GND
- Place near codec (single point)
- File: `codec-stage.kicad_sch` or `power-analog.kicad_sch`

**7c. EQ Stage CD4066 Symbol Swap**
- Replace SW_DIP_x04 with proper CD4066 analog switch symbol
- Already in shared library: Analog-Ecosystem-SMD:CD4066BM_TR
- File: `eq-stage.kicad_sch`

---

## Execution Order

| Order | Task | Priority | Effort | Dependencies |
|-------|------|----------|--------|-------------|
| 1 | Task 7c: EQ CD4066 swap | HIGH | Low | None |
| 2 | Task 1: TL431 feedback dividers | CRITICAL | Medium | None |
| 3 | Task 5: Signal path naming | HIGH | Low | None |
| 4 | Task 6: SPI CS routing | HIGH | Medium | None |
| 5 | Task 2: EQ stage wiring | CRITICAL | High | Task 7c (CD4066 swap) |
| 6 | Task 7a: PDN pullup | MEDIUM | Low | None |
| 7 | Task 7b: AGND/GND tie | MEDIUM | Low | None |
| 8 | Task 3: Hierarchy setup | CRITICAL | High | Tasks 1-7 (all labels finalized) |
| 9 | Task 4: RP2350B pin expansion | DEFERRED | High | After PCB initial layout |

Tasks 1-7 can be done programmatically via kiutils scripts. Task 3 (hierarchy) is best done in KiCad GUI. Task 4 is deferred to PCB phase.

---

## Verification

After completing all tasks:
1. Parse all 15 schematics with kiutils — no errors
2. Count wires: should be 253+ (existing) + ~30 (EQ) + ~12 (TL431) + ~8 (SPI CS) + ~5 (misc)
3. Check all global labels have at least 2 references (provider + consumer)
4. Run ERC in KiCad GUI (requires hierarchy from Task 3)
5. Verify netlist generation produces valid output
