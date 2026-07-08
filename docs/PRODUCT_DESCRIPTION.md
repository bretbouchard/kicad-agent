# kicad-agent — Product Description

## For App Store / Consumer-Facing

### Short Description (30 words)

Design real circuit boards by describing what you want. Type "I need a preamp with 18dB gain" — get a manufacturable PCB. No EDA experience required.

### Full Description

**kicad-agent turns words into circuit boards.**

Describe your project in plain English — an LED blinker, a sensor breakout, a guitar pedal, a motor controller — and kicad-agent designs the circuit, lays out the PCB, and generates manufacturing files you can send to any fab house.

**No schematic editor. No PCB layout tool. No learning curve.**

Just describe what you want:
- *"I need an ESP32 breakout with 22 pins, I2C pull-ups, and a USB-C power input"*
- *"Design a microphone preamp with 40dB gain and phantom power"*
- *"Make a 4-channel LED driver for a grow light with PWM dimming"*

kicad-agent handles everything:
1. **Circuit design** — selects components, calculates values, wires them together
2. **Schematic** — generates a proper KiCad schematic with ERC validation
3. **SPICE simulation** — verifies analog performance (gain, bandwidth, noise)
4. **PCB layout** — places components, routes traces, runs DRC
5. **Manufacturing** — exports Gerbers, drill files, BOM, pick-and-place

**Who is this for?**

- **Makers and hobbyists** who have ideas but find KiCad too complex
- **Engineers** who want to prototype faster without manual schematic capture
- **Educators** who teach electronics without spending weeks on tool training
- **Inventors** who need a custom board but can't afford PCB design services
- **Repair enthusiasts** who need replacement boards for vintage gear

**What makes it different?**

Unlike Tinkercad (too simple) or Altium (too complex), kicad-agent sits in the sweet spot: real manufacturable PCBs without the EDA learning curve. It uses SKIDL — a Python-based circuit description language — as its "thinking language," so circuits are programmable, version-controllable, and AI-readable.

**Technical capabilities:**
- Natural language → SKIDL code → KiCad schematic → PCB → Gerbers
- 142+ structural operations on KiCad files (schematic, PCB, symbols, footprints)
- Built-in ERC (electrical rules check) and DRC (design rules check)
- SPICE simulation via ngspice (AC, transient, noise, THD analysis)
- Auto-routing via Freerouting with AI-guided strategy
- Component search across JLCPCB/EasyEDA (50,000+ parts)
- 3D board renders for visual review

---

## For Engineering Team Briefing

### Executive Summary

kicad-agent is an AI-native EDA platform that bridges natural language and KiCad's file format. It uses a three-layer architecture: NL → SKIDL (Python IR) → KiCad (S-expressions), with validation gates at every stage. The platform is built on 142+ atomic operations, a multimodal AI model (Gemma 4 12B), and a bidirectional KiCad↔SKIDL converter.

### Architecture

```
User (NL prompt)
    ↓
[NL → SKIDL Model]     Gemma 4 12B + LoRA (rank 64, 7 target modules)
    ↓                   Trained on 21K examples (SchGen + crawled + synthetic)
SKIDL Python code
    ↓
[ERC Gate]              skidl ERC — rejects invalid circuits
    ↓
[SPICE Gate]            ngspice AC/transient/noise — verifies analog specs
    ↓
[SKIDL → KiCad]         circuit_ir/skidl_to_kicad — generates .kicad_sch
    ↓
[Floor Planner]         YAML spec → LayoutAwarePlacer vectors
    ↓
[PCB Populate]          skidl_to_pcb — netlist → footprints → placement
    ↓
[Auto-Route]            RoutingOrchestrator → Freerouting / A* / AI strategy
    ↓
[DRC Gate]              kicad-cli DRC — rejects violations
    ↓
[Manufacturing Export]  Gerbers, drill, BOM, P&P, STEP
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **SKIDL as canonical IR** | Python-readable, version-controllable, AI-trainable. SchGen paper proved Code-L1 (pin-name wiring) beats raw KiCad files 82% vs 32% valid circuits. |
| **Atomic operations (not compound)** | One mutation per op, one file per op. Transactions with rollback. No partial state. |
| **Validation gates (not advisory)** | ERC and DRC are HARD gates. Failed circuits never advance. Auto-rollback on violation. |
| **Multimodal model (not text-only)** | Gemma 4 12B sees schematic images AND PCB renders. Learns visual layout quality alongside code generation. |
| **Local-first inference** | mlx-vlm on Apple Silicon. 23.8 GB model, 5.6 tokens/sec, ~$0/cloud. Training on Vast.ai RTX 4090. |

### Current Capabilities

| Layer | Status | Notes |
|---|---|---|
| KiCad file parse/serialize | Production | 4 file types, round-trip verified, 3,857+ tests |
| 142+ atomic operations | Production | Components, nets, tracks, vias, footprints, repair |
| SKIDL ↔ KiCad converter | Production | Bidirectional, L1 (pin-level) and L2 (component-level) |
| Freerouting integration | Production | DSN/SES, multi-layer, net classes, zones |
| SPICE pipeline | Production | ngspice 45.2, AC/transient/noise/THD |
| Floor planner | Production | YAML spec → placement vectors |
| NL → SKIDL model | In training | Gemma 4 12B + LoRA rank 64, v3 dataset (21K examples) |
| Component search | Production | JLCPCB/EasyEDA, 50K+ parts, MCP server |
| Manufacturing export | Production | Gerbers, drill, BOM, P&P, STEP, 3D render |

### Data Pipeline

| Source | Examples | Quality |
|---|---|---|
| Microsoft SchGen (converted) | 8,396 | NL → SKIDL pairs, AST-converted from their custom API |
| Crawled KiCad repos (Phase 156) | 6,287 | Real-world schematics → SKIDL L1 (deep-normalized) |
| Synthetic topology templates | 5,600 | 16 templates (LED, RC, opamp, MOSFET, MCU, etc.) |
| SKIDL repo (devbisme/skidl) | 51 | Gold-standard examples from the author |
| Phase 159 seeds | 13 | Hand-curated exemplars |
| Maze routing (downsampled) | 1,000 | Spatial reasoning (for vision capability) |
| **Total v3** | **21,347** | All deep-normalized to canonical L1 form |

### Training Infrastructure

- **Model:** Gemma 4 12B (google/gemma-4-12b-it)
- **Quantization:** 4-bit NFQ (BitsAndBytes) for Vast.ai training
- **LoRA:** rank 64, alpha 128, 7 target modules (q/k/v/o/gate/up/down)
- **Platform:** Vast.ai RTX 4090, $0.37/hr, ~3.5h per run
- **Data transfer:** HF Hub (push from Mac) + aria2c (parallel download on instance)
- **Local inference:** mlx-community/gemma-4-12B-it-8bit on Apple Silicon

### Roadmap

| Milestone | Description | Status |
|---|---|---|
| v3 Training | Deep-normalized SKIDL, canonical L1 | In progress |
| Hierarchical SKIDL | @SubCircuit, Bus, multi-unit ICs | Next |
| Full pipeline test | NL → SKIDL → ERC → SPICE → PCB → Gerbers | Next |
| MLX conversion | Vast.ai PEFT → MLX for local inference | After training |
| App UI | SwiftUI macOS app wrapping the pipeline | Future |
| iPad app | Touch-based circuit design | Future |
