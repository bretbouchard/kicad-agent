# Gap Analysis — Pro vs Hobbyist, Untapped Markets, Standards

## The Spectrum: Who Designs PCBs Today

| Tier | User | Tools | Complexity | Volume |
|---|---|---|---|---|
| **Pro** | EE at a company | Altium, Cadence, Zuken | 6-16 layers, high-speed, RF, mixed-signal | 1K-1M units |
| **Prosumer** | Consultant, startup | KiCad (advanced), Altium Designer | 4-8 layers, moderate speed | 100-10K units |
| **Maker** | Hobbyist, educator | KiCad (basic), EasyEDA, Fritzing | 1-2 layers, through-hole + basic SMD | 1-100 units |
| **Curious** | Has an idea, no tools | Nothing — or asks someone else | Doesn't know where to start | 1 unit |

**kicad-agent targets the gap between Maker and Curious.** We make it possible for someone with ZERO EDA experience to produce a real, manufacturable PCB. The Pro and Prosumer tiers are future expansion.

---

## What We Cover Well (Maker → Prosumer)

- **Simple-to-medium circuits** (1-50 components)
- **1-4 layer boards** with standard stackups (JLC 4-layer: Top/GND/PWR/Bottom)
- **Through-hole + basic SMD** (0805, 0603, TQFP, SOIC)
- **Standard components** (Device, Connector, MCU, Sensor libraries)
- **Manufacturing-ready output** (Gerbers, drill, BOM, P&P for JLCPCB/PCBWay)
- **SPICE verification** (AC/transient/noise for analog circuits)
- **Auto-routing** (Freerouting with AI strategy guidance)
- **ERC + DRC** (electrical and design rule validation)

## What We DON'T Cover (Pro Tier)

### IPC Standards (Missing)

| Standard | What It Covers | Impact |
|---|---|---|
| **IPC-2221** | Generic PCB design (trace width vs current, annular rings, clearance) | Without this, our DRC rules are generic, not IPC-compliant |
| **IPC-7351** | Land pattern calculations for SMD | Our footprints come from KiCad libs (usually IPC-compliant) but we don't verify |
| **IPC-2152** | Current-carrying capacity of traces | We don't calculate trace width from current requirements |
| **IPC-6012** | Performance qualification for rigid PCBs | We don't generate fab house qualification docs |

### High-Speed Design (Missing)

- **Impedance control** — no 50Ω/90Ω/100Ω trace width calculations
- **Length matching** — no DDR/SerDes equal-length routing
- **Crosstalk analysis** — no coupling estimation between adjacent traces
- **Eye diagrams** — no signal integrity simulation
- **Power integrity** — no PDN impedance analysis, no decoupling optimization
- **S-parameters** — no frequency-domain characterization

### Safety/Compliance (Missing)

- **IEC 61010** — safety for measurement/control equipment (creepage/clearance for mains)
- **IEC 60601** — medical device safety (patient leakage currents, isolation)
- **UL 94** — flammability rating (V-0, V-1, V-2 for PCB material)
- **FCC Part 15** — EMI/EMC compliance (radiated/conducted emissions)
- **CE marking** — EU compliance documentation
- **RoHS/REACH** — material compliance (lead-free, restricted substances)

### Multi-Board Systems (Missing)

- Board-to-board connectivity planning
- System-level power distribution
- Mechanical constraint integration (enclosures, mounting holes, connectors)

### Supply Chain (Missing)

- Part lifecycle awareness (EOL, NRND, active)
- Second-source qualification
- Real-time stock/price from distributors (Digi-Key, Mouser, LCSC)
- BOM cost analysis with quantity-based pricing

---

## The Gap Between Pro and Home User

The gap is NOT just features — it's **workflow and risk tolerance**:

| Dimension | Pro User | Home User |
|---|---|---|
| **Time budget** | Weeks-months per design | Hours-days |
| **Iteration** | Many design reviews, formal sign-off | "Good enough, order it" |
| **Risk tolerance** | Zero defects (field failure = liability) | "If it doesn't work, I'll re-spin" |
| **Documentation** | Formal design docs, test plans | Wiki page or README |
| **Standards** | Must comply (ISO, IPC, IEC, UL) | Nice to have, not required |
| **Budget** | $10K-100K per design | $5-50 per board |
| **Volume** | 1K-1M units | 1-10 units |
| **Tools** | $5K-50K/seat/year | Free or $0 |

**kicad-agent's positioning:** "Professional-quality output at hobbyist accessibility." We can't compete with Altium on features, but we can give a hobbyist a board that WORKS without learning any EDA tool.

---

## Untapped Communities (Where Hobbies Haven't Overlapped)

### Communities That Design PCBs But We Don't Target Yet

**1. Synth DIY / Eurorack Modular**
- **Size:** 50K+ active hobbyists (ModWiggler, r/synthesizers 400K+ members)
- **Need:** VCOs, VCFs, VCAs, envelope generators, LFOs, sequencers
- **Special requirements:** ±12V power bus, 1V/octave scaling, 3.5mm jacks, Euro power connectors (10/16/20 pin IDC)
- **What we don't know:** Power bus standards, Eurorack mechanical specs (128.5mm × 3HP width), +5V rail management, CV normalization (switched jacks)
- **Why they'd use us:** "Design a Mutable Instruments-style smoothie clone" → working PCB

**2. Custom Keyboards**
- **Size:** 500K+ members (r/MechanicalKeyboards)
- **Need:** Matrix scanning controllers, USB-C interfaces, hot-swap sockets, rotary encoders, OLED displays
- **Special requirements:** QMK/ZMK firmware integration, plate-mounted PCB, per-key RGB (WS2812/SK6812), TRRS for split boards
- **What we don't know:** Key matrix ghosting/diodes, QMK pin mapping, Kailh hot-swap footprint, split keyboard TRRS wiring
- **Why they'd use us:** "Design a 60% keyboard with per-key RGB and USB-C" → working PCB

**3. Ham Radio / RF**
- **Size:** 3M+ licensed operators worldwide (ARRL 170K US)
- **Need:** RF filters, amplifiers, antenna tuners, SDR interfaces, transverters
- **Special requirements:** 50Ω impedance, shielded enclosures, RF connectors (SMA/BNC/N), toroid winding patterns, ground plane design
- **What we don't know:** Smith chart matching, LC filter tables (Chebyshev/Butterworth), RF-specific layout rules (keepout zones, via stitching for shielding)
- **Why they'd use us:** "Design a 40m band low-pass filter for 100W" → working PCB

**4. Model Railroading**
- **Size:** 500K+ active hobbyists (NMRA 15K members)
- **Need:** DCC decoders, block detectors, signal controllers, turnout motor drivers, occupancy sensors
- **Special requirements:** DCC protocol compatibility (9-bit/14-bit addressing), track current sensing (Hall effect), LED drivers for signals, servo PWM for turnouts
- **What we don't know:** DCC track signal format, NMRA standards (S-9.1 electrical, S-9.2 DCC), accessory decoder wiring
- **Why they'd use us:** "Design a DCC block occupancy detector for my layout" → working PCB

**5. Vintage Computer Restoration**
- **Size:** 100K+ active (Amiga, C64, Spectrum, Apple II communities)
- **Need:** Replacement boards, RAM upgrades, video adapters, SD card interfaces, FPGA accelerators
- **Special requirements:** Period-correct footprints (DIP, PLCC, PGA), through-hole priority, vintage connector availability (D-sub, edge card), 5V/12V power
- **What we don't know:** PAL/GAL programming, vintage bus protocols (Zorro, ISA, VLB), through-hole repair techniques
- **Why they'd use us:** "Design a replacement keyboard controller for Amiga 500" → working PCB

**6. Home Automation / Smart Home (DIY)**
- **Size:** Millions of "smart home" enthusiasts (r/homeautomation 2M+ members)
- **Need:** ESP32 sensor nodes, relay controllers, dimmer modules, door/window sensors, temperature/humidity monitors
- **Special requirements:** WiFi/BLE, battery power (LiPo + charging), solar charging, low-power modes, waterproof enclosures (IP67)
- **What we don't know:** HomeKit certification (MFi), Matter protocol, Zigbee mesh routing, deep sleep power budgets
- **Why they'd use us:** "Design a solar-powered ESP32 soil moisture sensor" → working PCB

**7. Guitar Effects / Audio DIY**
- **Size:** 200K+ (r/diypedals 100K+, freestompboxes.org)
- **Need:** Distortion circuits, delays, reverbs, loopers, preamps, MIDI controllers
- **Special requirements:** Audio-grade opamps (TL072, NE5532, OPA2134), 9V battery/adapter power, 1/4" jacks, true bypass switching, LED indicators
- **What we don't know:** Guitar signal levels (instrument vs line), true bypass wiring, charge pump voltage inversion (ICL7660), audio-specific layout (keep audio ground separate from digital)
- **Why they'd use us:** "Design a Tube Screamer-style overdrive with modified clipping" → working PCB

**8. LED Art / Installations**
- **Size:** 100K+ (burning man community, r/FastLED 80K+)
- **Need:** WS2812/SK6812 drivers, DMX interfaces, Art-Net nodes, power distribution for long LED strips
- **Special requirements:** High-current 5V/12V/24V distribution, level shifters (3.3V to 5V data), power injection points, capacitor sizing for LED inrush
- **What we don't know:** DMX512 protocol, Art-Net/sACN over Ethernet, color calibration, power budget calculations for 1000+ LEDs
- **Why they'd use us:** "Design an ESP32 Art-Net node driving 8 universes of WS2812" → working PCB

**9. Astronomy / Astrophotography**
- **Size:** 500K+ active amateur astronomers
- **Need:** Dew heater controllers, motorized focusers, filter wheels, guiding interfaces, camera triggers
- **Special requirements:** Precision stepper control, low-noise analog (for sensor readout), RTC for timed exposures, USB/Serial to mount
- **What we don't know:** ASCOM driver integration, mount protocols (Meade LX200, Celestron NexStar), dew point calculation
- **Why they'd use us:** "Design a 4-channel PWM dew heater controller" → working PCB

**10. Wearables / E-Textiles**
- **Size:** Growing (r/wearables, Adafruit FLORA/GEMMA community)
- **Need:** Small-form-factor boards, conductive thread interfaces, flexible PCB considerations, battery-powered BLE
- **What we don't know:** Flexible PCB material specs, conductive thread conductivity, washability, body-safe encapsulation
- **Why they'd use us:** "Design a coin-cell-powered BLE heart rate monitor patch" → working PCB

### The "Unknown Unknowns" — Problems People Don't Know PCBs Can Solve

These are the most exciting. People have problems but don't realize a custom PCB could solve them:

- **Beekeeper** monitoring hive temperature/humidity/weight across 20 hives
- **Homebrewer** building precision fermentation temperature controller
- **Teacher** wanting a classroom quiz/response system (30 wireless buttons)
- **Physical therapist** prototyping a biofeedback device
- **Magician** building an RFID-triggered stage prop
- **Sculptor** embedding interactive LED patterns in a sculpture
- **Dog owner** building an automated pet feeder with scheduling
- **Plant parent** monitoring soil moisture across 15 houseplants
- **Cyclist** building a custom bike computer with GPS + lights
- **Coffee enthusiast** building a precision espresso machine controller
- **Aquarium owner** automating dosing, lighting cycles, and temperature
- **Locksmith/security researcher** prototyping NFC/RFID tools
- **Solar installer** building a custom charge controller for off-grid
- **Drone builder** prototyping a custom flight controller
- **Cosplay maker** embedding LED/sound effects in armor

**Each of these people has a problem. None of them knows how to design a PCB. That's the gap we fill.**

---

## Summary: What to Build Next

### Immediate Gaps (blocks basic usefulness)
1. **Interactive design mode** — user iterates ("add a decoupling cap here", "change R1 to 10k")
2. **Visual preview** — show schematic render before generating full PCB
3. **Part availability check** — verify components are in stock before using them
4. **Cost estimate** — tell user "this board will cost $X to manufacture at JLC"

### Community-Specific Features (unlocks untapped markets)
5. **Synth module templates** — VCO/VCF/VCA with ±12V power bus
6. **Keyboard templates** — matrix scanning with QMK-compatible pin mapping
7. **Guitar pedal templates** — 1590B/1590BB enclosure fit, true bypass, 9V power
8. **ESP32 sensor node** — battery + WiFi + sensor interfacing
9. **LED controller** — WS2812 driver with power injection planning

### Pro Features (future expansion)
10. **IPC-2221 compliance** — trace width from current, annular ring from voltage
11. **Impedance control** — 50Ω/90Ω/100Ω for high-speed
12. **BOM with live pricing** — Digi-Key/Mouser/LCSC API integration
13. **Safety compliance checks** — creepage/clearance for IEC 61010
