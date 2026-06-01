# Phase 47: Circuit Intent Inference

**Goal**: Given a schematic with topology and subcircuit data, infer designer intent and suggest improvements. Combines topology graph + component recognition + design rules to answer "what was this designer building?" and "what could be better?"

**Depends on**: Phase 46 (subcircuit detection and classification)
**Context**: Phases 45-46 provide CircuitTopology, NetClassification, Subcircuit detection, and CircuitClassifier. This phase consumes that data to produce human-readable design intent and actionable improvement suggestions.
**Requirements**: DOMAIN-03
**Success Criteria** (what must be TRUE):
  1. `IntentInferrer` correctly identifies compressor intent from THAT4301 + sidechain topology
  2. `IntentInferrer` correctly identifies buffer/amplifier intent from NE5532 + feedback network
  3. `IntentInferrer` correctly identifies switch/bypass intent from CD4066 + control nets
  4. `DesignReviewer` identifies missing bypass caps on IC power pins
  5. `DesignReviewer` identifies missing feedback compensation caps on op-amp circuits
  6. Signal flow descriptions are human-readable: "Audio input -> bypass switch -> VCA -> output buffer"
  7. All inference is deterministic and template-based (no LLM calls)
  8. 20+ tests covering real analog-ecosystem circuit patterns
**Plans**: 2 plans

Plans:
- [ ] 47-01-PLAN.md -- Design intent inference from topology + subcircuits (DOMAIN-03)
- [ ] 47-02-PLAN.md -- Improvement suggestions and design review (DOMAIN-03)

## Wave Structure

**Wave 1:** 47-01 (intent inference) -- standalone, depends on 46-01 output interfaces
**Wave 2:** 47-02 (improvement suggestions) -- depends on 47-01 schemas

## Architecture

```
Phase 46 Output              Phase 47
┌──────────────────┐     ┌────────────────────────┐
│ CircuitTopology  │────▶│ IntentInferrer         │──▶ DesignIntent
│ Subcircuit[]     │     │  - component patterns   │    SubcircuitIntent[]
│ NetClassification│     │  - topology patterns    │    signal_flow_description
│ CircuitClassifier│     │  - signal flow tracing  │    confidence scores
└──────────────────┘     └────────────────────────┘
                                    │
                                    ▼
                         ┌────────────────────────┐
                         │ DesignReviewer         │──▶ DesignReview
                         │  - bypass cap check    │    findings[]
                         │  - feedback comp check │    suggestions[]
                         │  - thermal check       │    severity levels
                         │  - signal integrity    │
                         └────────────────────────┘
```
