# Milestone v5.0 Requirements — Skidl-Native Design Pipeline

## SKIDL Converter (Phase 156)

- [ ] **CONV-01**: `convert_to_skidl` operation reads .kicad_sch → extracts components + nets → generates Python build_*.py
- [ ] **CONV-02**: Supports L1 representation (pin-level, exact reproduction — per SchGen)
- [ ] **CONV-03**: Supports L2 representation (component-level, for training data)
- [ ] **CONV-04**: Maps KiCad library parts to existing parts.py wrappers or generates new wrappers
- [ ] **CONV-05**: Handles multi-unit symbols (NE5532 units A/B/C, RP2350B)
- [ ] **CONV-06**: Handles power symbols (GND, +3V3, etc.) as Net assignments
- [ ] **CONV-07**: Handles hierarchical sheets (recursive sub-sheet extraction)
- [ ] **CONV-08**: Bidirectional: SKIDL → KiCad schematic (via existing gen_schematic.py pipeline)
- [ ] **CONV-09**: Test: convert ADSR (35 parts) → verify ERC = same result as original
- [ ] **CONV-10**: Test: convert backplane (16 sheets, 94 parts) → verify hierarchical structure preserved

## Floor Planner (Phase 157)

- [ ] **FLOOR-01**: Define placement spec YAML schema (zones, edges, mounting, keepout, power, decoupling)
- [ ] **FLOOR-02**: gen_pcb.py reads placement spec → places components in functional zones
- [ ] **FLOOR-03**: Pre-place connectors at board edges (locked for Quilter)
- [ ] **FLOOR-04**: Mounting holes at corners + structural points
- [ ] **FLOOR-05**: Keepout zones (board edge clearance, connector clearance)
- [ ] **FLOOR-06**: Ground pour preparation (copper zone definitions)
- [ ] **FLOOR-07**: Decoupling proximity constraints (caps placed near ICs)
- [ ] **FLOOR-08**: Multi-strip replication (N identical channels, evenly spaced)
- [ ] **FLOOR-09**: Test: mono blade with floor plan vs without → compare Quilter routing quality

## SPICE Pipeline (Phase 158)

- [ ] **SPICE-01**: skidl → ngspice export (Circuit.generate_netlist(tool="spice"))
- [ ] **SPICE-02**: SPICE models for NE5532, THAT340, DG413, TL072, LM358
- [ ] **SPICE-03**: AK4619VN marked as UNSIMULATABLE (delta-sigma codec)
- [ ] **SPICE-04**: Testbench generator: AC analysis (frequency response, gain, phase)
- [ ] **SPICE-05**: Testbench generator: Transient (step response, gain reduction)
- [ ] **SPICE-06**: Testbench generator: Noise analysis (input/output noise floor)
- [ ] **SPICE-07**: Testbench generator: THD (total harmonic distortion)
- [ ] **SPICE-08**: Result parser: ngspice .raw → structured JSON (gain, BW, noise, THD)
- [ ] **SPICE-09**: Regression baselines: store simulation results as JSON for comparison
- [ ] **SPICE-10**: Test: simulate mono blade preamp → verify +18dB gain, BW > 100kHz
- [ ] **SPICE-11**: Parasitic injection: extract trace parasitics from PCB → re-simulate → measure degradation

## AI Training Data (Phase 159)

- [ ] **TRAIN-01**: Convert 71K crawled KiCad repos → SKIDL Python code
- [ ] **TRAIN-02**: Generate natural-language descriptions for each circuit (SFT pairs)
- [ ] **TRAIN-03**: Placement → routing quality pairs (from Quilter results)
- [ ] **TRAIN-04**: SPICE degradation as reward signal (pre-route vs post-route simulation delta)
- [ ] **TRAIN-05**: Qwen text adapter for circuit generation (SKIDL is pure text)
- [ ] **TRAIN-06**: Gemma vision adapter for routing (existing, enhanced with placement context)
- [ ] **TRAIN-07**: Training data format: matches existing generate_gap_training_data.py output

## Natural-Language Circuit Generation (Phase 160)

- [ ] **NLGEN-01**: Fine-tuned LLM generates SKIDL Python from natural language description
- [ ] **NLGEN-02**: Execute SKIDL → ERC validation gate (must pass 0 errors)
- [ ] **NLGEN-03**: SPICE validation gate (circuit must meet spec targets)
- [ ] **NLGEN-04**: Full pipeline: NL → SKIDL → ERC → SPICE → floor plan → PCB → Quilter
- [ ] **NLGEN-05**: Test: "I need a preamp with +18dB gain and -128dBu EIN" → generates working circuit

## Traceability — Requirement → Phase

Every requirement maps to exactly one phase. Phases 156-160 continue from analog-ecosystem cross-repo numbering.

| Phase | Title | Requirements | Depends on |
|-------|-------|--------------|------------|
| **156** | SKIDL Converter | CONV-01, CONV-02, CONV-03, CONV-04, CONV-05, CONV-06, CONV-07, CONV-08, CONV-09, CONV-10 | Phases 108-111 |
| **157** | Floor Planner | FLOOR-01, FLOOR-02, FLOOR-03, FLOOR-04, FLOOR-05, FLOOR-06, FLOOR-07, FLOOR-08, FLOOR-09 | 156 |
| **158** | SPICE Pipeline | SPICE-01, SPICE-02, SPICE-03, SPICE-04, SPICE-05, SPICE-06, SPICE-07, SPICE-08, SPICE-09, SPICE-10, SPICE-11 | — (independent, parallel with 156) |
| **159** | AI Training Data | TRAIN-01, TRAIN-02, TRAIN-03, TRAIN-04, TRAIN-05, TRAIN-06, TRAIN-07 | 156, 157, 158 |
| **160** | NL Circuit Generation | NLGEN-01, NLGEN-02, NLGEN-03, NLGEN-04, NLGEN-05 | 159 |

**Totals:** 5 phases, 42 requirements (10 + 9 + 11 + 7 + 5).

See `.planning/ROADMAP.md` § "v5.0 Skidl-Native Design Pipeline" for phase goals, success criteria, and dependency rationale.
