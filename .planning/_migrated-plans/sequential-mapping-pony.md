# SMD Variant Strategy — Analog Ecosystem Hardware

## Context

The Analog Ecosystem has 25 hardware module schematics, all designed with through-hole (THT) components for prototyping. The ecosystem aims to support both **hand-made/prototype** builds (THT) and **mass-produced open source** builds (SMD). We need a comprehensive SMD component selection strategy that prioritizes components that are common, sourceable, and inexpensive, with JLCPCB/LCSC assembly compatibility as the primary production path.

User preferences from discussion:
- Assembly: **JLCPCB/LCSC as primary**, with generic SMD fallback
- Obsolete ICs: **Modern SMD replacements** (new modules, not proto-only)
- Structure: **Per-module variant directories** with separate KiCad projects

---

## IC Inventory & SMD Mapping

### Tier 1: High-Volume ICs (used in 10+ modules)

| IC | THT Pkg | Count | Modules | SMD Equivalent | LCSC Part | Est. Cost | Status |
|----|---------|-------|---------|----------------|-----------|-----------|--------|
| **TL072** | DIP-8 | 36+28=64 | 15 | TL072CDR (SOIC-8) | C6762 | ~$0.30 | Active, recommended |
| **MCP3008** | DIP-16 | 34 | 19 | MCP3008T-I/SL (SOIC-16) | C108308 | ~$1.50 | Active, recommended |
| **L7805** | TO-220 | 34 | 17 | AMS1117-5.0 (SOT-223) | C6187 | ~$0.10 | Active, cheaper than 7805 |
| **AMS1117-3.3** | SOT-223 | 43 | 21 | AMS1117-3.3 (SOT-223) — already SMD | C6186 | ~$0.08 | Already SMD-compatible |
| **MCP4728** | DIP-8/TSSOP | 25 | 14 | MCP4728-E/UN (QFN-20 or TSSOP-20) | C740462 | ~$2.00 | Active |
| **CD4066** | DIP-14 | 21 | 9 | CD4066BM/TR (SOIC-14) | C512975 | ~$0.20 | Active |
| **4N25** | DIP-6 | 16 | 11 | 4N25S (SMD-6) or EL817S (SOP-4) | C311652 | ~$0.10 | Active |
| **TL074** | DIP-14 | 16 | 9 | TL074CDR (SOIC-14) | C6764 | ~$0.50 | Active, recommended |
| **NE5532** | DIP-8 | 20 | 3 | NE5532DR (SOIC-8) | C73919 | ~$0.30 | Active |
| **74HC595** | DIP-16 | 12 | 2 | SN74HC595DR (SOIC-16) | C5948 | ~$0.15 | Active |
| **SN74HC14N** | DIP-14 | 8 | 7 | SN74HC14DR (SOIC-14) | C5581 | ~$0.15 | Active |

### Tier 2: Medium-Volume ICs (used in 3-9 modules)

| IC | THT Pkg | Count | Modules | SMD Equivalent | LCSC Part | Est. Cost | Status |
|----|---------|-------|---------|----------------|-----------|-----------|--------|
| **RP2350B** | QFN-60 | 32 | 15 | RP2350B (already QFN — SMD native) | — | ~$1.20 | Already SMD |
| **RP2354A** | QFN | 8 | 4 | RP2354A (already QFN — SMD native) | — | ~$0.80 | Already SMD |
| **MCP23017** | DIP-28/SP | 4+2=6 | 4 | MCP23017-E/SP (SSOP-28) or MCP23017T-E/ML (QFN-28) | C470119 | ~$1.80 | Active |
| **LM13700** | DIP-16 | 3 | 2 | LM13700M/NOPB (SOIC-16) | C73414 | ~$2.00 | Active |
| **TC1044SCPA** | DIP-8 | 6+2=8 | 3 | TC1044SCPA(TR) — already available in SOIC-8 | C82231 | ~$0.60 | Active |
| **2N3904** | TO-92 | 10 | — | MMBT3904 (SOT-23) | C426096 | ~$0.01 | Active, ultra-cheap |
| **G6K-2F-Y** | DIP | 8 | 2 | G6K-2F-Y (already has SMD variant — G6K-2P) | C141369 | ~$2.50 | Active relay |

### Tier 3: Module-Specific ICs (1-2 modules)

| IC | THT Pkg | Modules | SMD Equivalent | LCSC Part | Est. Cost | Notes |
|----|---------|---------|----------------|-----------|-----------|-------|
| **AS3320** | DIP-18 | vcf | AS3320 (already produced by Alfa — check SMD pkg) | — | ~$8.00 | Analog VCF chip, limited sources |
| **PT2399** | DIP-16 | delay | PT2399-S (already available in SOP-16) | C82362 | ~$0.60 | Active, echo/delay |
| **VTL5C1** | DIP | 3 modules | VTL5C1 (no direct SMD — use diy optocoupler or Silonex NSL-32) | C336826 | ~$1.50 | Optocoupler, limited SMD options |
| **P82B96** | DIP-8 | control-center | P82B96DP (SOIC-8) | C93128 | ~$0.80 | Active, I2C bus extender |
| **MCP4131** | DIP-8 | 2 | MCP4131-103E/SN (SOIC-8) | C79878 | ~$0.60 | Active, digital pot |
| **LM3916N** | DIP-18 | 2 | No direct SMD — use MAX7219 (SOIC-24) or TM1640 (SOP-28) | C99644 | ~$1.00 | See obsolete section |
| **MF10-N** | DIP-20 | 2 | No SMD — **REPLACE with modern DSP** | — | — | **OBSOLETE** — see below |
| **ICL8038** | DIP-14 | 1 | **REPLACE with AD9833** (TSSOP-10 — already SMD!) | C329122 | ~$2.50 | **OBSOLETE** — AD9833 already in one module |

### Passive Components (High Volume)

| Component | THT Pkg | Count | SMD Equivalent | LCSC Part | Est. Cost |
|-----------|---------|-------|----------------|-----------|-----------|
| **100nF cap** | Radial | 197 | CL05B104KO5NNNC (0402) or generic 0805 | C1525 | ~$0.003 |
| **10uF cap** | Radial | 52 | CL10A106KP8NNNC (0805) | C1585 | ~$0.01 |
| **1k resistor** | Axial | 150 | RC0805JR-071KL (0805) | C17513 | ~$0.001 |
| **10k resistor** | Axial | 136 | RC0805JR-0710KL (0805) | C17414 | ~$0.001 |
| **100k resistor** | Axial | 28+16=44 | RC0805JR-07100KL (0805) | C149504 | ~$0.001 |

---

## Obsolete IC Replacement Strategy

### 1. ICL8038 → AD9833 (Already implemented in icl8038-generator)
- AD9833BRMZ is TSSOP-10 — **already SMD native**
- Lower cost, digital frequency control, more stable
- `icl8038-generator` module already has the AD9833 variant schematic
- **Action:** Mark ICL8038 schematic as "THT prototype only", AD9833 as "production SMD"

### 2. MF10-N → Modern Switched Capacitor Filter Approach
- MF10-N is obsolete (originally by TI/National, no longer produced)
- **Option A:** Use LTC1060 (SOIC-20) — closest modern SCF, still active
- **Option B:** Use RP2350B onboard DSP for filter implementation (PDM output)
- **Recommendation:** Option B — RP2350B is already on every module, free DSP
- **Action:** Create new `scf-dsp` module variant using RP2350B DSP filter instead of MF10-N

### 3. LM3916N → MAX7219 or TM1640 (LED Driver)
- LM3916 is bar/dot display driver, increasingly scarce
- **MAX7219CWG (SOIC-24):** Industry standard LED driver, $0.80, LCSC C99644
- **TM1640 (SOP-28):** Cheaper Chinese alternative, $0.15, widely available
- **Recommendation:** MAX7219 for reliability, TM1640 for budget builds
- **Action:** Create new VU meter variant with MAX7219

### 4. VTL5C1 → Silonex NSL-32SR3 or build-a-vactrol
- VTL5C1 (vactrol) is increasingly scarce, no SMD version
- **NSL-32SR3 (SMD):** Silonex, LED-LDR optocoupler in SMD package, LCSC C336826
- **DIY vactrol:** SMD LED + SMD LDR in heat-shrink (for THT builds)
- **Recommendation:** NSL-32SR3 for production, VTL5C1 for THT/proto

---

## KiCad Project Structure

```
hardware/
├── <module-name>/
│   ├── <module-name>.kicad_sch          # THT prototype (existing)
│   ├── <module-name>.kicad_pro
│   └── ...
├── <module-name>-smd/                    # SMD production variant (NEW)
│   ├── <module-name>-smd.kicad_sch      # SMD variant schematic
│   ├── <module-name>-smd.kicad_pro
│   ├── <module-name>-smd.kicad_pcb      # PCB layout
│   └── BOM.md                            # LCSC-sourced BOM
└── shared/
    ├── footprints/
    │   ├── Analog-Ecosystem.pretty/     # THT footprints
    │   └── Analog-Ecosystem-SMD.pretty/ # SMD footprints (NEW)
    ├── symbols/
    │   ├── Analog-Ecosystem.kicad_sym   # THT symbols
    │   └── Analog-Ecosystem-SMD.kicad_sym # SMD symbols (NEW)
    └── BOM-templates/
        ├── JLCPCB-BOM-template.csv
        └── LCSC-preferred-parts.md      # Preferred parts list with LCSC#s
```

**Rationale:** Separate directories per variant because:
- Different footprints require different PCB layouts
- BOM/CPL files are completely different
- Assembly instructions differ (reflow vs hand-solder)
- KiCad's native variant mechanism is immature; per-project is cleaner

---

## Execution Plan (by priority)

### Wave 1: Foundation (do first)
1. **Create shared SMD libraries**
   - `hardware/shared/footprints/Analog-Ecosystem-SMD.pretty/` with SMD footprints
   - `hardware/shared/symbols/Analog-Ecosystem-SMD.kicad_sym` with SMD symbols
   - Create `LCSC-preferred-parts.md` master parts list

2. **Create BOM templates**
   - JLCPCB CSV format with LCSC part numbers
   - CPL (pick-and-place) position file template
   - Preferred parts matrix (IC → SMD part → LCSC# → cost)

### Wave 2: High-Impact SMD Variants (most modules benefit)
3. **Delay module SMD variant** (`delay-smd/`)
   - Uses: RP2350B, TL072, TL074, MCP3008, MCP4728, CD4066, 4N25, PT2399, SN74HC14N, L7805, AMS1117-3.3
   - Most IC-dense module — proves the full BOM strategy

4. **VCF module SMD variant** (`vcf-smd/`)
   - Uses: AS3320, TL072, CD4066, 4N25, MCP3008, MCP4728, L7805, RP2350B
   - Tests the AS3320 SMD sourcing challenge

5. **Compressor module SMD variant** (`compressor-smd/`)
   - Uses: TL072, TL074, MCP3008, MCP4728, CD4066, 4N25, VTL5C1, SN74HC14N
   - Tests VTL5C1 → NSL-32SR3 replacement

### Wave 3: Remaining SMD Variants (all other modules)
6-20. Create SMD variants for remaining 15 modules following the pattern established in Wave 2

### Wave 4: Obsolete IC Replacement Modules
21. **SCF-DSP module** (replaces MF10-N with RP2350B DSP filter)
22. **VU-Meter MAX7219 variant** (replaces LM3916N)
23. Verify ICL8038 → AD9833 variant is production-ready

---

## JLCPCB Assembly Optimization Notes

### Part Selection Rules
1. **Always prefer "Basic" parts** in LCSC catalog — no extra assembly fee
2. **Minimize unique LCSC part numbers** — reduces setup costs
3. **Use 0805 passives** — JLCPCB default, widest availability
4. **Avoid parts not in LCSC catalog** — triggers extended component sourcing (2-7 day delay + $3-6 fee)
5. **Panelize small boards** — JLCPCB minimum charge is per-board

### Cost-Saving Strategy
- Consolidate IC purchases: TL072CDR is $0.30 vs TL072CP (DIP) at $0.45
- SMD passives are essentially free: 0805 resistors at $0.001 each
- AMS1117-5.0 (SOT-223) at $0.10 vs L7805CV (TO-220) at $0.25 — but consider **mini360 buck converter modules** for better efficiency at $0.50 each (pre-built, not pick-and-place)
- RP2350B is already QFN — no THT→SMD conversion needed

---

## Verification

1. **Each SMD variant schematic** passes ERC with zero errors
2. **BOM completeness** — every component has an LCSC part number
3. **JLCPCB compatibility check** — upload BOM to JLCPCB assembly calculator, verify all parts resolve
4. **Footprint verification** — each SMD footprint matches LCSC-recommended pad pattern
5. **Cost target** — SMD variant BOM should be ≤70% of THT variant cost
6. **DRC pass** on PCB layout (when PCBs are laid out)
