# kicad-agent

**Design real circuit boards by describing what you want.**

Type *"I need a preamp with 18dB gain"* — get a manufacturable PCB. No EDA experience required.

```
"I need an ESP32 breakout with USB-C power and I2C pull-ups"
    ↓
Natural Language → SKIDL code → KiCad schematic → PCB → Gerbers → Order from JLCPCB
```

[![PyPI version](https://img.shields.io/pypi/v/kicad-agent.svg)](https://pypi.org/project/kicad-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-6000%2B-green.svg)]()
[![KiCad](https://img.shields.io/badge/KiCad-10%2B-blue.svg)](https://www.kicad.org/)

## What This Does

kicad-agent is an AI-native EDA platform. It takes a natural-language circuit request and produces a complete, manufacturable PCB design — schematic, layout, routing, and manufacturing files. Along the way, every stage has hard validation gates: ERC (electrical rules), SPICE (analog simulation), and DRC (design rules). Bad designs never advance.

**The pipeline:**
1. **NL → SKIDL** — A Gemma 4 12B multimodal model generates SKIDL Python code (the circuit's DNA)
2. **ERC gate** — skidl validates electrical connectivity (every pin connected, no shorts)
3. **SPICE gate** — ngspice simulates analog performance (gain, bandwidth, noise)
4. **SKIDL → KiCad** — Circuit IR generates a valid KiCad schematic
5. **Floor plan** — YAML spec drives component placement
6. **PCB layout** — footprints populated, copper routed (Freerouting + AI strategy)
7. **DRC gate** — KiCad DRC catches manufacturing violations
8. **Manufacturing** — Gerbers, drill, BOM, pick-and-place, 3D render

## Who Is This For?

| User | What you get |
|---|---|
| **Maker / hobbyist** | Describe a circuit → order boards from JLCPCB. No KiCad learning curve. |
| **Engineer** | Prototype 10x faster. SKIDL is version-controllable, testable, scriptable. |
| **Educator** | Students focus on circuit theory, not tool UI. SPICE shows why designs work (or don't). |
| **Inventor** | Custom board for a niche problem without hiring a PCB designer. |

## Why SKIDL?

SKIDL is a Python-based circuit description language. Instead of drawing schematics with a mouse, you write code:

```python
from skidl import Part, Net, Circuit

def build_board() -> Circuit:
    ckt = Circuit()
    with ckt:
        # ===== COMPONENTS (3 total) =====
        R1 = Part("Device", "R", value="220")  # R1
        D1 = Part("Device", "LED", value="red")  # D1
        V1 = Part("Device", "Battery", value="5V")  # V1

        # ===== NET CONNECTIVITY (3 signal nets) =====
        vcc = Net("VCC")
        vcc += V1[1], R1[1]

        r_to_led = Net("R_TO_LED")
        r_to_led += R1[2], D1[1]

        gnd = Net("GND")
        gnd += V1[2], D1[2]
    return ckt

if __name__ == "__main__":
    build_board()
```

**Why not just use KiCad files?** Microsoft's SchGen paper proved that code-based circuit descriptions (like SKIDL) produce 82% valid circuits vs 32% for raw KiCad files when used with LLMs. SKIDL is also:
- **Programmable** — loop, condition, parameterize circuits
- **Version-controllable** — diff circuits in git
- **Testable** — run ERC/SPICE in CI
- **AI-readable** — perfect training format for LLMs

## Quick Start

### Install

```bash
pip install kicad-agent
```

**Requires:** Python 3.11+, KiCad 10+ (for ERC/DRC validation)

## SPICE Simulation (Phase 204)

Phase 204 ships a closed-box SPICE simulation pipeline. To run the demo
and `tests/sim/`, install:

**ngspice CLI** (external dependency, not pip-installable):
```bash
# macOS
brew install ngspice

# Linux
apt install ngspice          # Debian/Ubuntu
dnf install ngspice          # Fedora
```

**Python deps**:
```bash
pip install -e ".[sim]"
```

Verify:
```bash
ngspice --version            # Should print version >= 41
python -c "import optuna; print(optuna.__version__)"   # >= 4.5
```

Run the closed-box demo:
```bash
python3 scripts/demo_closed_box.py
# Outputs: bode.png, bom.md, sweeps/eurorack_preamp.db
# Asserts: gain >= 17 dB (BLK-1 strict), exits non-zero on failure
```

### Tuning

For faster iteration (trade quality for speed):
```bash
python3 scripts/demo_closed_box.py --n-trials 10
```

Recommended ceiling: 100 trials. Beyond that, marginal returns; consider a v2
multi-stage module. The default (50 trials) fits the 60-second budget on
Apple Silicon; slower hardware may need `--n-trials 20` or lower.

### Edit a KiCad File

```bash
# Add a 10k resistor via JSON operation
kicad-agent '{"root": {"op_type": "add_component", "target_file": "board.kicad_sch", "library_id": "Device:R", "reference": "R1", "value": "10k", "position": {"x": 50, "y": 30}}}'

# Run ERC after edits
kicad-cli sch erc board.kicad_sch

# Run DRC after layout edits
kicad-cli pcb drc board.kicad_pcb

# Export Gerbers for manufacturing
kicad-cli pcb export gerbers board.kicad_pcb -o gerbers/
```

### Use as Claude Code Skill

```bash
/kicad-agent add a 10uF decoupling capacitor next to U1
/kicad-agent convert this schematic to SKIDL
/kicad-agent run ERC and fix any errors
```

### Analyze a PCB with AI

```bash
# Local analysis — no API key, runs on Apple Silicon
kicad-agent analyze board.kicad_pcb
```

### Search Components

```bash
# Search JLCPCB/EasyEDA — 50K+ parts, no API key
kicad-agent component-search "ESP32-S3 WROOM"
```

## Full Pipeline (NL → Manufacturing)

```
"I need a microphone preamp with 40dB gain"
    ↓
[NL → SKIDL Model]          Gemma 4 12B + LoRA (rank 64, 7 modules)
    ↓
SKIDL Python code           Part("Amplifier_Operational", "NE5534", ...)
    ↓
[ERC Gate]                  skidl ERC — every pin connected?
    ↓
[SPICE Gate]                ngspice — gain = 40dB? noise < -128dBu?
    ↓
[SKIDL → KiCad]             .kicad_sch — valid schematic
    ↓
[Floor Planner]             .floorplan.yaml → placement vectors
    ↓
[PCB Populate]              .kicad_pcb — footprints placed
    ↓
[Auto-Route]                Freerouting + AI strategy → routed traces
    ↓
[DRC Gate]                  kicad-cli DRC — no manufacturing violations
    ↓
[Export]                    Gerbers + drill + BOM + P&P + STEP + 3D render
    ↓
Order from JLCPCB / PCBWay / OSH Park
```

## Supported File Types

| File | Extension | Operations |
|---|---|---|
| Schematic | `.kicad_sch` | 60+ ops (add/remove/move components, wires, labels, no-connects, SKIDL convert) |
| PCB Layout | `.kicad_pcb` | 80+ ops (components, tracks, vias, zones, footprints, DRC, export) |
| Symbol Library | `.kicad_sym` | Symbol creation, modification, library management |
| Footprint Library | `.kicad_mod` | Footprint creation, pad management |

**KiCad 10+ only.** 142+ atomic operations across 22 categories.

## Architecture

```
LLM / CLI
    ↓
+-------------+     +-------------+     +-------------+     +-------------+
|   Parser     |───>|  Circuit IR |───>|    Ops      |───>|  Serializer |
| S-expr → AST |    | SKIDL ↔ Kicad   | 142 atomic  |    | Valid KiCad |
| 4 file types |    | Bidirectional    | operations  |    | S-expr      |
+-------------+     +-------------+    +------+------+    +-------------+
                                          │
                                  +-------v-------+
                                  |  Validation   |
                                  | ERC (skidl)   |
                                  | SPICE (ngspice)|
                                  | DRC (kicad-cli)|
                                  | Auto-rollback |
                                  +---------------+
```

### Key Modules

| Module | Purpose |
|---|---|
| `circuit_ir/` | Bidirectional KiCad ↔ SKIDL converter (Phase 156). L1 pin-level + L2 component-level. |
| `ops/` | 142+ operation handlers, Pydantic schema, atomic executor with transactions |
| `routing/` | RoutingOrchestrator + Freerouting + AI strategy advisor (Gemma 4 vision) |
| `spice/` | ngspice pipeline: AC, transient, noise, THD. Analog subcircuit extraction. |
| `floorplan/` | YAML floor-plan spec → LayoutAwarePlacer placement vectors |
| `training/` | Gemma 4 12B multimodal LoRA training pipeline (SFT + GRPO) |
| `validation/` | ERC/DRC gates, structural validation, round-trip fidelity |
| `inference/` | Vision pipeline for PCB/schematic analysis |
| `analysis/` | Legibility critic, routing quality (RES score) |

### Key Design Decisions

- **SKIDL as canonical IR** — SchGen proved Code-L1 beats raw KiCad 82% vs 32% for LLM generation
- **Atomic operations** — one mutation per op, one file per op, transactions with rollback
- **Hard validation gates** — ERC and DRC reject bad designs. Files that fail are rolled back.
- **Multimodal AI** — Gemma 4 12B sees schematic images + PCB renders + generates SKIDL code
- **Local-first** — mlx-vlm on Apple Silicon for inference. Vast.ai for training.

## Training Pipeline

### Model
- **Base:** Google Gemma 4 12B (multimodal — text + vision)
- **Adapter:** LoRA rank 64, alpha 128, 7 target modules (q/k/v/o/gate/up/down)
- **Quantization:** 4-bit NFQ for training (BitsAndBytes), 8-bit for local inference (MLX)

### Training Data (v3 — 21,347 examples)

| Source | Examples | What It Teaches |
|---|---|---|
| Microsoft SchGen (converted) | 8,396 | NL → SKIDL from real PCB design requests |
| Crawled KiCad repos | 6,287 | Real-world 20-150 component circuits with SCH+PCB images |
| Synthetic topology templates | 5,600 | 16 templates: LED, RC filter, opamp, MOSFET, MCU, crystal, etc. |
| SKIDL repo (devbisme/skidl) | 51 | Gold-standard examples from the author |
| Maze routing (downsampled) | 1,000 | Spatial reasoning / vision capability |
| Phase 159 seeds | 13 | Hand-curated canonical exemplars |

All examples deep-normalized to canonical Phase 156 L1 form (consistent variable naming, quoting, value formatting, Circuit wrapper).

### Infrastructure
- **Training:** Vast.ai RTX 4090 ($0.37/hr, ~3.5h per run)
- **Data transfer:** HuggingFace Hub (push from Mac) + aria2c (parallel download on instance)
- **Local inference:** mlx-vlm on M2 Pro (23.8 GB model, ~5.6 tokens/sec)

## Development

```bash
pip install ".[dev]"
pytest                    # 6000+ tests
ruff check src/ tests/    # Lint
mypy src/                 # Type check
```

## Routing Stack (v2.2)

```
User Intent JSON
    ↓
RoutingOrchestrator
    ├─ DeterministicStrategy (A* for simple nets)
    ├─ AiRoutingStrategy (Gemma 4 vision → strategy)
    ├─ Freerouting v2.2 (complex multi-layer)
    └─ JSONL audit trail + UUID rollback
```

Key files: `routing/orchestrator.py`, `routing/strategy.py`, `routing/ai_strategy.py`, `routing/freerouting.py`

## Documentation

- [Product Description](docs/PRODUCT_DESCRIPTION.md) — App Store description + engineering briefing
- [Gap Analysis](docs/GAP_ANALYSIS.md) — Pro vs hobbyist, untapped markets, IPC/ISO standards
- [Operations Reference](skills/prompt.md) — Full list of 142+ operations with field descriptions
- [Known Limitations](KNOWN_LIMITATIONS.md) — Phase 26 bugs and workarounds

## License

[MIT](LICENSE)
