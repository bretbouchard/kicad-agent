# Cicada Team Phase Handoff

**Date:** 2026-05-31
**From:** Bret (with strategic context from external consultation)
**To:** Cicada team
**Project:** kicad-agent v2.4 → v3.0

---

## Where We Are

**Shipped:** 37 phases, 7 milestones (v1.0 through v2.3)
**In progress:** Phase 38 (Schematic Routing Engine) — 3/4 plans complete
**Planned:** Phases 39-40 (Schematic Intelligence + ERC Root Cause)
**Total:** 74 operations, 1392+ tests, 57,275 source lines

### Phase 38 Status

| Plan | Status | Deliverable |
|------|--------|-------------|
| 38-01 Pin Position Resolution | COMPLETE | `pin_resolver.py` — absolute pin coords for any component |
| 38-02 Collision Detection | COMPLETE | `collision_detector.py` — pin overlaps + routing collision zones |
| 38-03 connect_pins | COMPLETE | `net_connector.py` — wire routing with collision avoidance + labels |
| 38-04 batch_connect + regenerate_wiring | **NEXT** | `batch_wiring.py` — multi-net wiring, full schematic rewire |

**Next up: Execute 38-04.** The plan is at `.planning/phases/38-schematic-routing-engine/38-04-PLAN.md`.

### Phase 39 (After 38-04)

| Plan | Status | Deliverable |
|------|--------|-------------|
| 39-01 Net Extraction | PLANNED | Extract complete net topology from schematic |
| 39-02 Net Name Conflict Detection | PLANNED | Detect naming problems before ERC |
| 39-03 Auto-Name Nets | PLANNED | Suggest canonical names from topology |

### Phase 40 (After 39)

| Plan | Status | Deliverable |
|------|--------|-------------|
| 40-01 ERC Violation Classification | PLANNED | Classify fixable vs pre-existing vs benign |
| 40-02 Root Cause Diagnosis | PLANNED | Diagnose root causes for fixable violations |
| 40-03 Enhanced erc_auto_fix | PLANNED | Root cause mode for smarter auto-fixing |

---

## Strategic Context

The external consultation confirmed our direction and identified two critical gaps:

### 1. Benchmarks (Currently 2/10)

We have no standardized way to measure kicad-agent's intelligence. This is the #1 blocker for professional credibility.

**What we need:** A "PCB MMLU" — multi-choice circuit analysis questions that test understanding of:
- Component selection and function
- Topology recognition (is this a compressor? a filter? a preamp?)
- Signal flow tracing
- Power design correctness
- DFM/SI/PI/EMC domain knowledge

**Why it matters:** No professional takes an AI tool seriously without published benchmarks. This is how we prove we're not vaporware.

**Phase plan:** Phases 41-44 in STRATEGIC-EXPANSION-PLAN.md

### 2. Domain Intelligence (Currently 2/10)

kicad-agent edits schematics without understanding what the circuit DOES. It can place a resistor, but doesn't know if it's a pull-up, feedback, or bias resistor.

**What we need:** Circuit topology graph → component function recognition → intent inference → design rule intelligence

**Why it matters:** This is the difference between "safe editing tool" and "intelligent engineering assistant." The benchmarks prove we understand circuits; domain intelligence makes the benchmarks pass.

**Phase plan:** Phases 45-48 in STRATEGIC-EXPANSION-PLAN.md

### 3. Positioning

**"Engineering review system for KiCad" > "AI PCB designer"**

Every failed AI EDA startup tried to design circuits. We review, fix, and validate them. This is our moat:
- Binary success criteria (valid file or not)
- Measurable value (ERC violations reduced by X%)
- No scaling problem (local model, no cloud)
- Already 37 phases of foundation work

### 4. Multi-Format Expansion (Long-term)

After benchmarks and domain intelligence are solid:
- Phase 55: Abstract AST (format-agnostic internal representation)
- Phase 56: EasyEDA support (JSON format, JLCPCB integration)
- Phase 57: Altium support (enterprise market)
- Phase 58: Eagle + OpenWater

**Don't start this until benchmarks are published.** The multi-format architecture only matters if we have credibility first.

---

## Immediate Priorities

### Priority 1: Finish v2.4 (Phases 38-40)

Execute these in order:
1. **38-04** — batch_connect + regenerate_wiring (the last routing engine piece)
2. **39-01, 39-02** (parallel) — net extraction + conflict detection
3. **39-03** — auto-name nets
4. **40-01** — violation classification
5. **40-02** — root cause diagnosis
6. **40-03** — enhanced erc_auto_fix

After Phase 40, ship **v2.4 milestone**.

### Priority 2: PCB MMLU Benchmark (Phase 41)

This is the next critical milestone after v2.4. The benchmark suite needs:
- 500+ multi-choice questions across 8 categories
- Sourced from real schematics in analog-ecosystem (55 modules)
- Ground truth from datasheets + ERC reports + netlists
- Baseline: run Qwen2.5-0.5B LoRA against it, measure accuracy
- Target: >70% accuracy after fine-tuning

The benchmark is how we prove to the world that kicad-agent understands circuits, not just S-expressions.

### Priority 3: Circuit Semantics (Phase 45)

Build the topology graph that enables domain intelligence:
- Component → pin → net → pin → component graph
- Signal flow direction inference
- Net classification (power, ground, signal, control, feedback)
- Subcircuit recognition (amplifier, filter, oscillator, power supply)

---

## Key Decisions Already Made

1. **Labels at body_position** (not wire endpoint) — better visual placement + guaranteed connectivity
2. **L-shaped wires use horizontal-first path** — collision zone check covers full segment range
3. **Collision threshold: ≥2 pins** (not ≥2 refs) — vertical wire through IC pin column shorts all pins regardless of component count
4. **Pin overlap severity: error** (different nets from netlist), warning (same net or unknown)
5. **Schemas in _schema_schematic_routing.py and _schema_schematic_intel.py** — separate files per subsystem
6. **Schematic ops extend existing @register_schematic pattern** in executor.py

---

## Architecture Reference

### Existing schematic_routing/ module (cicada built)

```
src/kicad_agent/schematic_routing/
├── __init__.py
├── pin_resolver.py          # 38-01: Absolute pin positions
├── collision_detector.py     # 38-02: Pin overlaps + routing collision zones
├── net_connector.py          # 38-03: Wire routing with collision avoidance
├── batch_executor.py         # Existing batch framework
├── batch_wiring.py           # 38-04: Multi-net wiring (NEXT)
├── netlist_parser.py         # Existing netlist parsing
├── net_resolver.py           # Existing net resolution
├── schematic_graph.py        # Existing graph representation
├── target_finder.py          # Existing target finding
├── power_unit_placer.py      # Existing power unit placement
└── wire_router.py            # Existing wire routing
```

### Schema files

```
src/kicad_agent/ops/
├── _schema_schematic_routing.py  # Routing op schemas (38-01..04)
├── _schema_schematic_intel.py    # Intelligence op schemas (39-01..03, 40-01..03)
├── schema.py                     # Re-exports all schemas
└── executor.py                   # @register_schematic handlers
```

### Test pattern

Tests in `tests/` follow the pattern `test_<module>.py`. Each plan has test specifications in its PLAN.md.

---

## What Success Looks Like

**v2.4 (Q3 2026):**
- All 10 plans in phases 38-40 executing cleanly
- `regenerate_wiring` can rewire a THAT4301 compressor from scratch
- `erc_auto_fix` with root cause mode classifies violations intelligently
- Compressor-stage schematic: 33 violations → ≤5 with smart fixing

**v2.5 (Q4 2026):**
- PCB MMLU benchmark published with 500+ questions
- Baseline results showing >70% accuracy
- Circuit QA dataset with 2000+ question-answer pairs
- CI pipeline that blocks PRs on benchmark regression

**v3.0 (2027):**
- Domain intelligence: circuit topology graph, subcircuit recognition
- Design rule intelligence: beyond KiCad DRC
- Multi-format support (at least EasyEDA)
- Professional positioning: "The ESLint of KiCad"

---

## References

- `.planning/STRATEGIC-EXPANSION-PLAN.md` — Full 17-phase expansion plan (41-58)
- `.planning/ROADMAP.md` — Complete project roadmap (40 phases, 7 milestones)
- `.planning/REQUIREMENTS.md` — 134 requirements tracked with phase mapping
- `.planning/phases/38-*/` — Phase 38 plans and summaries
- `.planning/phases/39-*/` — Phase 39 plans (ready to execute)
- `.planning/phases/40-*/` — Phase 40 plans (ready to execute)
