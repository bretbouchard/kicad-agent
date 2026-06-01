# Phase 48: Design Rule Intelligence

**Goal**: Domain-specific DRC beyond KiCad: configurable design rules engine for impedance matching, thermal relief, bypass cap placement, signal integrity, and project-specific checks. Moves Domain Intelligence from 8/10 to 10/10.

**Depends on**: Phase 45 (topology extraction), Phase 46 (subcircuit detection/classification)
**Context**: Phases 45-46 provide CircuitTopology, NetClassification, Subcircuit detection. Phase 47 provides design intent inference. This phase builds a pluggable rule engine on top of that infrastructure.
**Requirements**: DOMAIN-04
**Success Criteria** (what must be TRUE):
  1. `DesignRule` ABC defines the contract for all rules: name, category, severity, check() -> list[Violation]
  2. `DesignRuleEngine` loads rules, runs them against topology + schematic, produces structured report
  3. Built-in rules cover: bypass caps, feedback compensation, impedance, thermal, ground, power, signal protection, layout
  4. Rules can be enabled/disabled per project via YAML configuration
  5. Custom thresholds supported (e.g., bypass cap distance = 10mm instead of 5mm)
  6. Reports generated in JSON and Markdown formats
  7. CLI subcommand: `kicad-agent design-rules <schematic>` works end-to-end
  8. 20+ tests covering all built-in rules with real circuit patterns
**Plans**: 2 plans

Plans:
- [ ] 48-01-PLAN.md -- Domain-specific design rules engine with built-in rules (DOMAIN-04)
- [ ] 48-02-PLAN.md -- Configurable project rules + reporting + CLI integration (DOMAIN-04)

## Wave Structure

**Wave 1:** 48-01 (rules engine + built-in rules) -- depends on 45-01 and 46-01 output interfaces
**Wave 2:** 48-02 (configuration + reporting + CLI) -- depends on 48-01 engine

## Architecture

```
Phase 45/46 Output         Phase 48
┌──────────────────┐     ┌────────────────────────────────┐
│ CircuitTopology  │────▶│ DesignRuleEngine               │
│ NetClassification│     │  ┌──────────────────────────┐  │
│ Subcircuit[]     │     │  │ Built-in Rules           │  │
└──────────────────┘     │  │  - BYPASS_CAP_01         │  │
                         │  │  - FEEDBACK_01           │  │
                         │  │  - IMPEDANCE_01          │  │
                         │  │  - THERMAL_01            │  │
                         │  │  - GROUND_01             │  │
                         │  │  - POWER_01              │  │
                         │  │  - SIGNAL_01             │  │
                         │  │  - LAYOUT_01             │  │
                         │  └──────────────────────────┘  │
                         │         │                       │
                         │         ▼                       │
                         │  ┌──────────────────────────┐  │
                         │  │ YAML Config              │  │
                         │  │  - enable/disable rules   │  │
                         │  │  - custom thresholds      │  │
                         │  └──────────────────────────┘  │
                         │         │                       │
                         │         ▼                       │
                         │  DesignRuleReport               │
                         │  ├─ JSON output                 │
                         │  ├─ Markdown output             │
                         │  └─ CLI: kicad-agent design-rules│
                         └────────────────────────────────┘
```
