---
phase: 15-ai-generation-wiring
plan: 02
subsystem: llm
tags: [claude, extended-thinking, spatial-reasoning, design-critique, tool-use]
dependency_graph:
  requires: [llm/client.py, llm/context_builder.py, spatial/query.py, spatial/primitives.py]
  provides: [llm/design_critic.py]
  affects: [llm/__init__.py]
tech_stack:
  added: []
  patterns: [extended-thinking, spatial-context-builder, severity-based-scoring]
key_files:
  created:
    - src/kicad_agent/llm/design_critic.py
    - tests/test_llm_design_critic.py
  modified:
    - src/kicad_agent/llm/__init__.py
decisions:
  - CritiqueSeverity as str Enum (INFO/WARNING/CRITICAL) matching tool schema enum values
  - Quality score computed server-side from finding severities, not from LLM-reported score
  - build_spatial_context uses proximity(0,0,10000) to retrieve all entities via existing API
metrics:
  duration: 2 min
  completed: 2026-05-24
  tasks: 1
  files: 3
  tests: 15
---

# Phase 15 Plan 02: Design Critic with Spatial Reasoning Summary

Spatial reasoning design critic using Claude extended thinking to analyze PCB layouts for clearance violations, routing congestion, and thermal hotspots, with severity-based quality scoring.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Spatial context builder and design critic with extended thinking | 7cd5760 (RED), 23ddfc3 (GREEN) | design_critic.py, __init__.py, test_llm_design_critic.py |

## TDD Gate Compliance

- [x] RED gate: `7cd5760` - test(15-02): add failing tests for design critic with spatial reasoning
- [x] GREEN gate: `23ddfc3` - feat(15-02): implement design critic with spatial reasoning via extended thinking
- [ ] REFACTOR gate: Not needed - clean implementation on first pass

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. **Quality score computed server-side**: Rather than trusting the LLM-reported `overall_quality_score`, the DesignCritic recomputes it from finding severities using fixed penalties (critical=-0.3, warning=-0.1, info=-0.02). This ensures deterministic, reproducible scoring.

2. **build_spatial_context via proximity query**: Uses `engine.proximity(0, 0, radius_mm=10000)` to retrieve all entities through the existing SpatialQueryEngine API, avoiding direct access to internal primitives.

3. **CritiqueSeverity as str Enum**: Uses `str, Enum` pattern so `CritiqueSeverity("warning")` works for parsing LLM tool output directly.

## Test Results

```
15 design critic tests passed (0 failures)
34 total LLM tests passed (no regressions)
439 total tests passed (1 pre-existing failure in test_llm_refinement.py)
```

## Verification

- [x] All design critic tests pass with mocked Anthropic client
- [x] Import works: `from kicad_agent.llm.design_critic import DesignCritic, CritiqueReport`
- [x] Spatial context builder handles empty engine without error
- [x] Quality score always in [0.0, 1.0] range regardless of finding count
- [x] Extended thinking parameters (budget_tokens=8000) passed to Claude API call

## Self-Check: PASSED

All claimed files verified present. All commit hashes verified in git log.
