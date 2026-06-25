---
phase: 98-ai-routing-strategy-advisor
status: approved-scope
approved_date: 2026-06-24
replaces: original Phase 98 scope "Closed-loop vision-guided PCB routing"
---

# Phase 98 — AI Routing Strategy Advisor (Approved Scope)

## Reframe History

**Original scope (2026-06-24, earlier this session):** "Closed-loop vision-guided PCB routing" — render PCB → vision model emits routing strategy + coordinate hints → parse to ops → feed pathfinder → re-render → iterate.

**Why reframed:** Architectural review revealed the closed-loop autonomous approach was premature. The vision model can't drive routing if there's no orchestrator to receive strategy and no reliable multi-layer backend to execute it. Decided on Option A: use Freerouting as the heavy lifter (Phase 99), build a deterministic orchestrator (Phase 100), then add AI as a strategy advisor on top.

**What changed:**
- Phase 98 no longer builds a closed loop. It produces strategy consumed by Phase 100.
- Phase 98 no longer parses coordinates to ops directly — orchestrator handles execution.
- Phase 98 dependency chain: was Phase 97 → now Phase 99 + Phase 100.

## Goal

Use the trained Gemma 4 12B V2 vision LoRA to generate routing strategy — net priorities, layer assignments, keepout suggestions — consumed by the Phase 100 orchestrator as `RoutingStrategy` inputs.

## Dependencies

- **Phase 99** (multi-layer backend exists)
- **Phase 100** (orchestrator with pluggable `RoutingStrategy` interface)
- Trained adapter: `/Volumes/Storage/models/kicad-agent/adapters/kicad-vision-v2-mlx/`
  - rank 64, 2000 steps, loss 0.06, ~98.7% token accuracy
  - 524.6MB, mlx-converted, loads at 23.8 GB / 5.6 tok/s on Apple Silicon
- Existing `KiCadVisionPipeline` at `src/kicad_agent/inference/vision_pipeline.py`

## Requirements

| ID | Requirement |
|---|-------------|
| R-1 | `KiCadVisionPipeline` wired into `RoutingOrchestrator` via `RoutingStrategy` interface (Phase 100 R-1) |
| R-2 | Strategy prompt emits structured JSON: `{net_priorities: [...], layer_hints: {net: layer}, keepouts: [...], routing_notes: "..."}` |
| R-3 | Strategy-to-constraints translator: model JSON → `RoutingConstraints` deltas + per-net overrides |
| R-4 | Validation gate: reject out-of-bounds coordinates, unknown net names, impossible layer assignments (e.g., `In3.Cu` on a 2-layer board) |
| R-5 | Eval harness: AI-guided routing vs. Phase 100 deterministic baseline — completion rate, via count, trace length, DRC pass |
| R-6 | Graceful degradation: invalid model output falls back to deterministic policy (Phase 100 R-6) |

## Success Criteria (falsifiable)

1. Model emits parseable strategy JSON on ≥95% of fixture board renders
2. AI-guided routing matches or beats deterministic baseline on at least 2 of: completion rate, via count, total trace length
3. Zero DRC regressions vs. baseline (model never causes a board that baseline routed cleanly to fail DRC)
4. Validation gate rejects 100% of synthetic invalid outputs (out-of-bounds, unknown nets, impossible layers) in unit tests
5. End-to-end: render board → model emits strategy → orchestrator applies → routes → DRC passes — on at least 3 fixture boards

## Out of Scope

- Retraining the model — use existing V2 adapter
- Building a new router — using Freerouting (Phase 99) and existing A*
- Closed-loop autonomous routing without human approval — the orchestrator (Phase 100) gates every model-emitted strategy through approval

## Safety

- All model-emitted coordinates validated against board bounds before application
- All model-emitted net references cross-checked against actual netlist
- All layer assignments validated against board stackup
- Invalid output → deterministic fallback (Phase 100 R-6) + logged to audit trail
- Never skip DRC — even with AI guidance, post-route DRC is mandatory

## Estimated Effort

3 plans, ~2-3 weeks. Eval harness (R-5) is the long pole.

## Open Questions for Planning

- Should the model see the rendered PCB image AND the netlist as text, or only the image? (Current pipeline accepts both; training was image-only on synthetic mazes.)
- What's the right cadence for re-strategizing during routing? Once at start? After each net? After each failed net?
- How do we handle disagreement between AI strategy and Freerouting's own optimization? AI wins? Router wins? Log and surface to human?
