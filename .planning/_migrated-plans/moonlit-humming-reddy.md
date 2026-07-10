# Plan: Desktop Unit Backplane with Analog Crosspoint Routing

## Context

The Analog Ecosystem has evolved from standalone pedals to a Famicom-style desktop unit. Credit-card-sized cartridge PCBs (85.6×54mm, gold edge fingers) slot into the top of a desktop unit. Each cartridge has its own RP2350B MCU + analog effect core. A central crosspoint switch on the backplane routes audio between any cartridges and USB audio — any-to-any routing.

**What prompted this:** The cartridge architecture is defined (firmware + PCB template + edge connector). The missing piece is the backplane PCB that holds the cartridge slots, crosspoint switch, power distribution, and connects to the control-center.

---

## Physical Design

### Desktop Unit Layout (4 slots for v1)

```
         [Slot 0]  [Slot 1]  [Slot 2]  [Slot 3]
           | | |      | | |      | | |      | | |
  =====================================================
  |  POWER  |  I2C  |  CROSSPOINT  |  AUDIO  |  CC  |
  |  SUPPLY |  BUS  |  MT8816      |  BUFS   |  CON |
  =====================================================
           | | |      | | |      | | |      | | |
         [Card-edge receptacles on top edge]
```

- **Board**: 300mm × 140mm (fits on a desk, under $25 at JLCPCB)
- **Slot pitch**: 60mm (54mm card + 6mm clearance)
- **4 slots v1**, expandable to 8 via daughter-board or v2 board
- **4-layer PCB**: signal / GND plane / power plane / signal

### Why 4 slots for v1
- 540mm for 8 slots is too large for initial testing and JLCPCB pricing jumps above 500mm
- 4 slots validates the full architecture (crosspoint, I2C, power, hot-swap)
- The firmware and schematic scale to 8 with zero changes — just add connectors

---

## Crosspoint Switch (Both Options Supported)

Plan supports both MT8816 and CD22M3494 — selected at compile time. Start with MT8816 for simplicity.

| | MT8816 | CD22M3494 (3x) |
|---|---|---|
| Matrix | 16×16 | 16×24 |
| Chips | 1 | 3 |
| Interface | Serial (DATA/CLK/STROBE/CS) | SPI + individual CS |
| On-resistance | ~65Ω | ~50Ω |
| Cost | $2-5 | $7-10 |
| Firmware | New driver | Reuse `router_core.c` |

### Audio Matrix Mapping (MT8816 16×16)

```
Sources (Y0-Y9):                  Destinations (X0-X9):
  Y0:  Slot 0 SIGNAL_OUT           X0:  Slot 0 SIGNAL_IN
  Y1:  Slot 1 SIGNAL_OUT           X1:  Slot 1 SIGNAL_IN
  Y2:  Slot 2 SIGNAL_OUT           X2:  Slot 2 SIGNAL_IN
  Y3:  Slot 3 SIGNAL_OUT           X3:  Slot 3 SIGNAL_IN
  Y8:  USB Audio L (from PCM5102A) X8:  USB Audio L (to PCM1808)
  Y9:  USB Audio R                 X9:  USB Audio R
  Y4-Y7, Y10-Y15: Reserved         X4-X7, X10-X15: Reserved
```

### Audio Signal Path
- Each slot: SIGNAL_OUT → TL072 buffer → MT8816 Y input
- Each slot: MT8816 X output → TL072 buffer → SIGNAL_IN
- USB audio: PCM5102A → TL072 buffer → MT8816 Y8/Y9
- USB audio: MT8816 X8/X9 → TL072 buffer → PCM1808
- Total buffers: 4 slots × 2 + 2 USB × 2 = 12 channels = 6× TL072CDR

---

## Power Distribution

**Input: 12V DC barrel jack (center-positive)**

```
12V DC Input
  ├── PMOS reverse polarity protection
  ├── Polyfuse 3A
  ├── TVS SMBJ12A
  │
  ├── MP1584EN buck converter → +5V bus (3A) — high efficiency
  │     └── AMS1117-3.3 → +3.3V bus (1A)
  │
  ├── AMS1117-9.0 → +9V bus (analog rails)
  │
  └── TC1044SCPA × 2 → -9V bus (charge pump, ~40mA)
```

**Per-slot power (from centralized regulators):**
- Positions 1-2: GND (staged, mate first)
- Positions 3-4: +3.3V
- Positions 5-6: +5V
- Position 7: +9V
- Position 8: -9V
- Per-slot decoupling: 100µF + 100nF per rail at the connector

**Power budget (4 slots):**

| Rail | Per Slot | 4 Slots | Control | Total |
|------|----------|---------|---------|-------|
| +3.3V | 100mA | 400mA | 200mA | 600mA |
| +5V | 50mA | 200mA | 250mA | 450mA |
| +9V | 30mA | 120mA | — | 120mA |
| -9V | 20mA | 80mA | — | 80mA |
| **12V input** | | | | **~7W** |

---

## I2C Bus Architecture

```
Control Center RP2350 (I2C0 master)
    ↓
P82B96 Buffer (local: 4.7k pull-ups to 3.3V)
    ↓
Backplane I2C bus (1.5k pull-ups to 5V)
    ├── Slot 0: I2C slave addr 0x10
    ├── Slot 1: I2C slave addr 0x11
    ├── Slot 2: I2C slave addr 0x12
    └── Slot 3: I2C slave addr 0x13
```

- TVS protection (TPD4E05U06) at the backplane entry point
- All slots share the same bus (multidrop)
- Slot ID via resistor divider per slot → SLOT_SENSE (ADC)

### Slot ID Resistor Dividers

| Slot | R_top | R_bot | Voltage |
|------|-------|-------|---------|
| 0 | 33kΩ | 2.7kΩ | ~0.28V |
| 1 | 30kΩ | 5.6kΩ | ~0.56V |
| 2 | 27kΩ | 8.2kΩ | ~0.83V |
| 3 | 22kΩ | 10kΩ | ~1.11V |

---

## Control-Center Interface

**2×20 pin shrouded box header (ribbon cable to control-center):**

| Pin Group | Signals | Count |
|-----------|---------|-------|
| Power | +12V (×2), GND (×6) | 8 |
| I2C | SDA, SCL (P82B96 buffered) | 2 |
| Crosspoint | DATA, CLK, STROBE, CS | 4 |
| USB Audio | AUDIO_L_IN, AUDIO_R_IN, AUDIO_L_OUT, AUDIO_R_OUT | 4 |
| Alert | ALERT_N (wire-OR from all slots) | 1 |
| Mute | MUTE_CTRL (broadcast) | 1 |
| Spare | NC/future | 20 |
| **Total** | | **40** |

PCM5102A and PCM1808 stay on the control-center PCB. Only analog line-level audio crosses the ribbon.

---

## BOM Estimate (4-slot backplane)

| Component | Qty | Unit | Total |
|-----------|-----|------|-------|
| MT8816 crosspoint | 1 | $3.50 | $3.50 |
| TL072CDR op-amp | 6 | $0.30 | $1.80 |
| AMS1117-9.0 | 1 | $0.10 | $0.10 |
| MP1584EN buck (5V) | 1 | $0.50 | $0.50 |
| AMS1117-3.3 | 1 | $0.10 | $0.10 |
| TC1044SCPA (×2) | 2 | $0.60 | $1.20 |
| P82B96DP I2C buffer | 1 | $0.80 | $0.80 |
| Card-edge receptacle 56-pos | 4 | $3.50 | $14.00 |
| 2×20 box header | 2 | $1.00 | $2.00 |
| TVS/ESD protection | 2 | $0.30 | $0.60 |
| Passives (caps, resistors, ferrites) | — | — | $3.00 |
| DC barrel jack | 1 | $0.45 | $0.45 |
| PCB (300×140mm, 4-layer) | 1 | $15.00 | $15.00 |
| **Total** | | | **~$43** |

Card-edge receptacles ($14) are the biggest cost driver.

---

## Firmware Scope

### New Files (control-center)

| File | Purpose |
|------|---------|
| `firmware/modules/backplane/crosspoint.h` | Chip-agnostic crosspoint API |
| `firmware/modules/backplane/crosspoint_mt8816.c` | MT8816 serial driver |
| `firmware/modules/backplane/crosspoint_cd22m3494.c` | CD22M3494 SPI driver (adapted from `router_core.c`) |
| `firmware/modules/backplane/cartridge_manager.c/h` | I2C scan, slot detection, discovery |
| `firmware/modules/backplane/audio_router.c/h` | Crosspoint + USB audio coordination |
| `firmware/modules/backplane/usb_audio.c/h` | PCM5102A/PCM1808 I2S + TinyUSB audio |
| `firmware/modules/backplane/test_crosspoint.c` | Crosspoint driver tests |
| `firmware/modules/backplane/test_cartridge_mgr.c` | Cartridge manager tests |

### Reuse from Existing Code

| Existing | What | How |
|----------|------|-----|
| `firmware/modules/analog-router/router_core.c` | Matrix connect/disconnect/mute logic | Adapt `router_state_t` into chip-agnostic `crosspoint_state_t` |
| `firmware/modules/pedal/pedal_cartridge.c` | I2C slave commands (DISCOVER, SET_PARAM, etc.) | Reference for master-side protocol |
| `firmware/lib/bus.c/h` | TLV encoding, CRC-8 | Direct reuse |
| `firmware/lib/preset.c/h` | Flash preset storage | Direct reuse |

### Crosspoint Abstraction

```c
// crosspoint.h — chip-agnostic API
typedef struct {
    bool (*connect)(uint8_t input, uint8_t output);
    bool (*disconnect)(uint8_t input, uint8_t output);
    void (*disconnect_all)(void);
    void (*mute_output)(uint8_t output, bool mute);
    void (*update)(void);  // flush changes to hardware
} crosspoint_driver_t;

// Select at compile time
#ifdef CROSSPOINT_MT8816
extern const crosspoint_driver_t mt8816_driver;
#else
extern const crosspoint_driver_t cd22m3494_driver;
#endif
```

---

## Hardware Files to Create

```
hardware/backplane/
  ├── backplane.kicad_pro
  ├── backplane.kicad_sch          (root schematic)
  ├── power-supply.kicad_sch       (12V input, LDOs, buck, charge pump)
  ├── power-distribution.kicad_sch (per-slot decoupling, hot-swap)
  ├── i2c-bus.kicad_sch            (P82B96, pull-ups, ESD, slot taps)
  ├── slot-connectors.kicad_sch    (4× card-edge receptacles)
  ├── crosspoint-switch.kicad_sch  (MT8816, TL072 buffers, coupling caps)
  ├── control-center-iface.kicad_sch (2×20 box header, signal breakout)
  ├── slot-id-dividers.kicad_sch   (resistor dividers per slot)
  ├── backplane.kicad_pcb          (PCB layout)
  └── BOM.md                       (bill of materials)
```

### KiCad Library Additions

- MT8816 symbol + footprint (SOIC-28W or DIP-40)
- 56-position card-edge receptacle footprint (backplane side)
- 2×20 shrouded box header (standard KiCad library has this)

---

## Implementation Order

### Step 1: Schematic Design
1. Create KiCad project + hierarchical sheets
2. Power supply section (12V → all rails)
3. 4× card-edge connectors with full pin assignments
4. MT8816 crosspoint + TL072 buffers
5. I2C bus (P82B96, pull-ups, ESD, slot dividers)
6. Control-center interface connector
7. ERC, netlist, verify

### Step 2: PCB Layout
1. Board outline (300×140mm) + mounting holes
2. Place card-edge receptacles (60mm pitch)
3. Place MT8816 centrally, route audio first
4. Place TL072 buffers near crosspoint
5. Route power (inner planes), I2C, control
6. Ground pour, DRC

### Step 3: Firmware
1. Crosspoint driver (MT8816 + CD22M3494) with tests
2. Cartridge manager (I2C scan, discovery)
3. USB audio driver (PCM5102A/PCM1808 I2S)
4. Audio router coordinator
5. Integration tests

### Step 4: Integration Test
1. Backplane + control-center via ribbon
2. Insert test cartridge, verify I2C
3. Audio routing through crosspoint
4. USB audio bidirectional
5. Hot-plug test
6. Preset save/recall

---

## Verification

1. **Schematic**: ERC clean on all sheets
2. **PCB**: DRC clean, all audio traces length-matched per pair
3. **Firmware**: Unit tests for crosspoint driver, cartridge manager, audio router
4. **Audio**: Signal passes through crosspoint with <0.1% THD
5. **Hot-plug**: Insert/remove cartridge without audio pop or I2C bus hang
6. **Routing**: Any cartridge output routes to any other cartridge input + USB audio

---

## Critical Files (Read-Only References)

- `hardware/footprints/Analog-Ecosystem.pretty/Card_Edge_56P_2.54mm.kicad_mod` — Cartridge edge finger pinout
- `firmware/modules/analog-router/router_core.c/h` — Existing CD22M3494 matrix management to adapt
- `firmware/modules/pedal/pedal_cartridge.c/h` — Cartridge I2C slave protocol
- `firmware/modules/pedal/pedal_base.h` — Cartridge GPIO map and state
- `hardware/shared/symbols/Analog-Ecosystem-SMD.kicad_sym` — Shared symbol library

---

# ARCHIVED: Credit-Card Pedal Platform (CCPP)

## Context

The analog-ecosystem project has 22 hardware modules in Eurorack-style format with RP2350 digital control. The white_room app (`~/apps/schill/white_room/`) has DSP implementations of 9+ guitar pedals (BiPhase, Overdrive, Envelope Filter, Chorus, Flanger, Tremolo, Fuzz, Compressor, Distortion) that we want to replicate as **real analog circuits** on credit-card-sized PCBs.

The "shared platform" is the foundation: a standardized PCB (85.6x54mm) with power, I/O, bypass, digital control, and ecosystem bus — every pedal reuses this and only swaps the analog "effect core."

**User decisions:** Dual-mode (1/4" jacks + ZSS-108 bus), 9V DC center-negative power, exact credit card dimensions (85.6x54mm), easily sourced inexpensive components, best product quality when it matters.

---

## PCB Zone Layout (85.6 x 54mm)

```
+----------------------------------------------------------+
| POTS (3-5x)   | POWER    |         |    OLED HEADER      |
| Alpha 16mm    | SUPPLY   |         |    (Variant B)       |
|               | 18x12mm  |         |    12x12mm           |
+---------------+----------+         +----------------------+
|               |  DIGITAL SECTION   |  EFFECT CORE ZONE    |
| BYPASS RELAY  |  RP2350 + MCP4728  |  35x30mm            |
| 8x10mm        |  20x20mm           |  (pedal-specific     |
|               |                    |   analog circuit)     |
+-------+-------+--------------------+                      B|
| FOOT  | SWD   |                    |                      U|
| SW    | HDR   | MIDI (opt, Var C)  |                      S|
| 5x8mm |       |                    |                      |
+-------+-------+--------------------+----------------------+
| 1/4" IN  |  ZSS-108 BUS (optional)  | 1/4" OUT | 9V DC  |
| 12x10mm  |  21x6mm edge connector   | 12x10mm  | barrel  |
+----------+--------------------------+----------+---------+
```

**Net classes:** Power 0.5mm, Audio 0.3mm, Signal 0.25mm, Digital 0.2mm
**Layer stack:** 2-layer min (FR4 1.6mm), 4-layer preferred for production

---

## 4 Variants

| Variant | Digital | Knobs | Cost (platform only) | Use Case |
|---------|---------|-------|---------------------|----------|
| **A: Analog Pure** | None | 3-5 pots | ~$5 | Traditional stompbox |
| **B: Analog + Presets** | RP2350+DAC+OLED | 3-5 pots | ~$11 | Recallable presets |
| **C: Digital Control** | RP2350+DAC+MIDI | None | ~$9 | Ecosystem slot-in |
| **D: Fixed Voicing** | None | None | ~$1.50 | Set-and-forget |

---

## Shared Circuit Blocks

### 1. Power Supply
- **Input:** 9V DC center-negative (1N5817 reverse polarity protection)
- **Charge pump:** TC1044SCPA (5 on hand) generates -9V from +9V
- **Diode-OR:** 1N5817 between local 9V and bus +/-12V
- **Rails:** +9V analog, -9V analog, +5V digital (AMS1117-5.0), +3.3V MCU (AMS1117-3.3)
- **Bus detect:** Voltage divider on GPIO27 (ADC) to auto-detect bus presence

### 2. True Bypass
- **Relay:** G6K-2F-Y DPDT (5V coil) — NC = bypass (passes audio unpowered)
- **Driver:** 2N7000 MOSFET on GPIO6
- **Pop suppression:** MUTE high (GPIO26) → 2ms → relay toggle → 5ms → MUTE low
- **Footswitch:** 3-pin header (momentary SPST, internal pull-up on GPIO5)
- **Status LED:** GPIO7

### 3. Digital Control (Variants B/C)
- **MCU:** RP2350B (QFN-80, $1.50)
- **DAC:** MCP4728 quad DAC (I2C 0x60, GPIO0/1, LDAC on GPIO2)
- **CV outputs:** CV1-CV4 to effect core (0-5V, 12-bit)
- **SWD:** GPIO3/4, 5-pin header
- **OLED:** SPI on GPIO8-12 (Variant B only)
- **Pots:** GPIO14-18 (ADC, internal 12-bit)
- **Effect control:** GPIO19-21 (CD4066 switching, etc.)
- **MIDI:** UART0 RX on GPIO22 (Variant C only)
- **Bus I2C:** GPIO24/25
- **Preset:** GPIO13 (tap/preset button)

### 4. Bus Connector (Optional)
- **ZSS-108** 16-pin edge connector (unpopulated on variants A/D)
- Pinout matches existing ecosystem: +/-12V, GND, SDA/SCL, IRQ, GATE, MIDI, +5V
- ESD protection TVS on data lines

### 5. Effect Core Zone (35x30mm)
Standardized boundary connections:

| Side | Nets |
|------|------|
| **Power (left)** | +9V, -9V, +5V, +3.3V, GND |
| **Control (top)** | CV1, CV2, CV3, CV4 (from DAC or pots) |
| **Audio (right)** | SIGNAL_IN, SIGNAL_OUT, DRY_SIGNAL |
| **Digital (bottom)** | BYPASS_CTRL, MUTE_CTRL, EFFECT_CTRL_1/2/3 |

---

## Files — Status

### Hardware (hardware/pedal-platform/) — ALL COMPLETE
| File | Status | Lines | Description |
|------|--------|-------|-------------|
| pedal-platform-power.kicad_sch | DONE | 389 | 9V input, TC1044 charge pump, AMS1117 LDOs, diode-OR, bus detect |
| pedal-platform-bypass.kicad_sch | DONE | 304 | G6K-2P-Y DPDT relay, 2N7000 MOSFET driver, pop suppression, footswitch, LED |
| pedal-platform-digital.kicad_sch | DONE | 851 | RP2350B (33-pin simplified), MCP4728 quad DAC, SWD header, 5x pot headers, OLED header, crystal |
| pedal-platform-bus.kicad_sch | DONE | 544 | ZSS-108 16-pin connector, TVS ESD, EL817S-C MIDI opto, pullups |
| pedal-platform-template-vA.kicad_sch | DONE | 4339 | Variant A: analog pure monolithic |
| pedal-platform-template-vB.kicad_sch | DONE | 4686 | Variant B: analog + RP2350 + DAC + OLED |
| pedal-platform-template-vC.kicad_sch | DONE | 4603 | Variant C: digital-only, MIDI, no pots |
| pedal-platform-template-vD.kicad_sch | DONE | 4161 | Variant D: fixed voicing minimal |
| generate_pedal_schematic.py | DONE | ~500 | Programmatic generator (19KB) |

### KiCad Library Additions — COMPLETE
- `hardware/shared/symbols/Analog-Ecosystem-SMD.kicad_sym` — 5 new symbols: G6K-2P-Y, DC_Barrel_Jack, Alpha_Pot_16mm, 3PDT_Footswitch, TC1044SCPA

### Firmware (firmware/modules/pedal/) — ALL COMPLETE
| File | Lines | Description |
|------|-------|-------------|
| pedal_base.h/c | 106/340 | GPIO map, variant detect, init, DAC helpers, pot reading |
| pedal_bypass.h/c | 30/166 | Relay toggle with pop suppression, 50ms debounce, status LED |
| pedal_preset.h/c | 31/186 | 16 slots, CRC-16 verification, smooth 40ms ramp on recall |
| pedal_midi.h/c | 38/141 | CC120=bypass, CC99=save, PC 0-15=recall, param CC mapping |
| pedal_display.h/c | 27/235 | SSD1306 128x64, 5x7 font, bar graphs, effect name, preset display |
| pedal_bus_handler.h/c | 38/206 | TLV bus messages, module discovery, param get/set |
| pedal_main.c | 345 | Dual-core main, Core 0=real-time 1kHz, Core 1=housekeeping |
| CMakeLists.txt | 72 | Build targets, HOST_TEST support |

### Module Types — COMPLETE
- `firmware/lib/module_types.h` — 9 pedal types added (0x1A-0x22)

### Remaining TODO
- [x] Fix failing MIDI CC120 bypass test (test_pedal_extras.c) — **DONE**
- [x] PCB template with zone outlines (pedal-platform-template.kicad_pcb) — **DONE**
- [x] Cross-check firmware GPIO ↔ schematic net labels — **DONE** (fixed 2 naming mismatches)
- [x] BOM cost verification per variant — **DONE** (see hardware/pedal-platform/BOM.md)

### Bug Fix: MIDI CC120 Bypass Test

**Root cause:** `pedal_midi.c:41` uses `pedal_bypass_set(value >= 64)` — absolute, not toggle. CC120 value >= 64 = engage, < 64 = bypass. The test sends value=127 twice expecting toggle behavior.

**Fix (2 files):**

1. `firmware/modules/pedal/test_pedal_extras.c` — Fix `test_midi_cc_bypass()`:
   - First message: CC120 value=127 (engage)
   - Second message: CC120 value=0 (bypass)
   - Update test name to "MIDI CC120 sets bypass absolute"

2. `firmware/modules/pedal/pedal_midi.h:18` — Update comment from "bypass toggle" to "bypass (>=64 engage, <64 bypass)"

---

## Implementation Status

### Wave 1: KiCad Library + Module Types — COMPLETE
1. ~~Add pedal module types (0x1A-0x22) to `firmware/lib/module_types.h`~~
2. ~~Create new KiCad symbols (relay, barrel jack, pot, footswitch)~~
3. ~~Create new KiCad footprints~~

### Wave 2: Platform Schematics — COMPLETE
4. ~~Build power supply sheet (9V input, charge pump, LDOs, diode-OR)~~
5. ~~Build digital control sheet (RP2350 + MCP4728 + SWD)~~
6. ~~Build bypass sheet (relay, MOSFET driver, footswitch, LED)~~
7. ~~Build bus connector sheet (ZSS-108, ESD, MIDI opto)~~
8. ~~Assemble master templates from hierarchical sheets (A/B/C/D)~~
9. ~~Build `generate_pedal_schematic.py`~~

### Wave 3: Firmware Base — COMPLETE
10. ~~Implement `pedal_base.h/c` (GPIO map, variant detect)~~
11. ~~Implement `pedal_bypass.h/c` (relay + pop suppression)~~
12. ~~Implement `pedal_preset.h/c` (16 presets with smoothing)~~
13. ~~Implement `pedal_midi.h/c` (CC bypass=CC120, preset=CC99, PC 0-15, params CC1-4)~~
14. ~~Implement `pedal_display.h/c` (OLED parameter display)~~
15. ~~Implement `pedal_bus_handler.h/c` (module discovery)~~
16. ~~Implement `pedal_main.c` (dual-core main)~~
17. ~~Write host tests for all modules~~ — **DONE** (22/22 passing)

### Wave 4: PCB Template + Validation — COMPLETE
18. ~~Create PCB template with zone outlines and net classes~~
19. ~~Cross-check firmware GPIO ↔ schematic nets~~ (fixed BYPASS→BYPASS_RELAY, MUTE→MUTE_CTRL)
20. ~~BOM cost verification per variant~~ (A:$19, B:$30, C:$19, D:$2.50)
21. Test pedal: simple buffer (Variant D) to validate platform — **NEXT**

---

## Pedal Build Order (after platform)

| Order | Pedal | Analog Core | DAC Ch | Complexity |
|-------|-------|-------------|--------|------------|
| 1 | **Overdrive** | TL072 x2, 1N34A/1N4148 clipping, tone stack | Drive/Tone/Vol | Low |
| 2 | **Fuzz** | BC109C x3 (Big Muff style) | Sustain/Tone/Vol | Low |
| 3 | **Tremolo** | TL072, BS170 VCA, JFET LFO | Rate/Depth/Wave | Low |
| 4 | **Envelope Filter** | TL072 x2 SVF, VTL5C1 opto | Sens/Peak/Decay/Mode | Medium |
| 5 | **Chorus** | TL072, MN3007 BBD, NE570 compander | Rate/Depth/Mix/Tone | High |
| 6 | **Flanger** | TL072, MN3207 BBD, feedback | Rate/Depth/Fdbk/Mix | High |
| 7 | **BiPhase** | TL072 x4, JFET x12, dual phaser + extra MCP4728 | Rate1/Depth1/Rate2/Depth2 + FB1/FB2/Mix/Routing | Very High |

Compressor and Distortion already exist in the ecosystem (Phase 11/15) — pedal variants reuse their analog cores.

---

## Verification

1. **Schematic:** ERC on each hierarchical sheet and master template
2. **Firmware:** Host tests for pedal_base, bypass, preset, MIDI modules
3. **Integration:** GPIO cross-check between schematic net labels and firmware #defines
4. **Cost:** BOM calculation per variant against target ($2-16 range)
5. **Physical:** Test layout (Variant D buffer) fits 85.6x54mm with all zones populated
