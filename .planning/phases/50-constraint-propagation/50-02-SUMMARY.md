---
phase: 50-constraint-propagation
plan: 02
subsystem: constraints
tags: [extractors, propagator, orchestrator, tdd, integration]
dependency_graph:
  requires:
    - constraints/types.py (PCBConstraint hierarchy)
    - constraints/table.py (lookup_params, ConstraintParams)
    - analysis/topology_graph.py (CircuitTopology, TopologyEdge, TopologyNode)
    - analysis/net_classifier.py (SignalIntegrity, NetImportance)
    - analysis/subcircuit_detector.py (Subcircuit, SubcircuitType)
    - analysis/intent_schemas.py (DesignIntent, SubcircuitIntent)
    - analysis/design_rules.py (DesignRuleReport)
    - analysis/types.py (NetClassification)
  provides:
    - constraints/extractors.py (five extractor functions)
    - constraints/propagator.py (ConstraintPropagator orchestrator)
    - constraints/__init__.py (updated exports with real ConstraintPropagator)
  affects:
    - constraints/__init__.py (placeholder replaced with real import)
tech_stack:
  added:
    - Plain function extractors with uniform signature
    - Orchestrator pattern matching DesignRuleEngine
  patterns:
    - Five extractors as plain functions (not ABC/classes)
    - Deterministic ordered extractor registration
    - Error isolation: one failed extractor does not block others
    - Strict unidirectional propagation (schematic -> PCB)
key_files:
  created:
    - src/kicad_agent/constraints/extractors.py
    - src/kicad_agent/constraints/propagator.py
    - tests/test_constraints/test_extractors.py
    - tests/test_constraints/test_propagator.py
  modified:
    - src/kicad_agent/constraints/__init__.py
decisions:
  - "Extractors are plain functions, not class instances with check() methods (simpler, no ABC needed)"
  - "Error handling: log warning and continue (one broken extractor does not kill propagation)"
  - "Diff pair detection uses regex patterns for +/-, _P/_N, _POS/_NEG suffixes"
  - "Power extractor creates both DecouplingConstraint (IC-cap pairs) and ClearanceConstraint (power net clearance)"
  - "Thermal extractor uses pin_count >= 16 or power_pins >= 8 as trigger threshold"
  - "Signal flow extractor uses subcircuit confidence directly, orders by intent when available"
  - "Config dict passed through to all extractors for per-extractor overrides"
  - "__init__.py placeholder replaced with real ConstraintPropagator import"
metrics:
  duration: 8 min
  completed: 2026-06-01
  tasks: 2
  tests: 34
  files_created: 4
  files_modified: 1
---

# Phase 50 Plan 02: ConstraintPropagator and Five Extractors Summary

ConstraintPropagator orchestrator and five constraint extractors that translate analysis outputs (CircuitTopology, Subcircuit, DesignIntent, DesignRuleReport) into typed PCBConstraint instances via unidirectional propagation.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Five constraint extractors + 24 tests | `f331628` | extractors.py, test_extractors.py |
| 2 | ConstraintPropagator orchestrator + 10 integration tests | `c6ef9bc` | propagator.py, __init__.py, test_propagator.py |

## Key Decisions

1. **Plain functions over ABC** -- Extractors are plain functions with uniform signature `(topology, subcircuits, intent, rule_report, config) -> list[PCBConstraint]`. No abstract base class needed since the orchestrator just calls functions, not `.check()` methods.
2. **Error isolation** -- Each extractor runs in try/except. A failing extractor logs a warning but does not block others from running, following the same resilience pattern as DesignRuleEngine.
3. **Diff pair confidence tiers** -- Explicit `+/-` net names get 0.9 confidence; pattern matches (`_P/_N`, `_POS/_NEG`) get 0.6 confidence.
4. **Thermal trigger thresholds** -- pin_count >= 16 or power_pins >= 8 triggers thermal constraint generation. Uses 50.0 C/W default thermal resistance (typical DIP/SOIC) and 0.5W per power pin heat dissipation heuristic.
5. **Signal flow ordering** -- When DesignIntent is provided, subcircuits are ordered by intent position (input -> processing -> output). Without intent, subcircuits maintain their original order.

## Deviations from Plan

None -- plan executed exactly as written.

## Test Results

- 34 new tests (24 extractor + 10 propagator)
- 81 total tests in constraints/ module (all pass)
- No circular imports between constraints/ and analysis/
- End-to-end pipeline verified: topology -> propagate -> to_routing_constraints

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| CP-01 | COMPLETE | ConstraintPropagator propagates topology to PCBConstraint list |
| CP-05 | COMPLETE | Five extractors produce correctly typed constraints |

## TDD Gate Compliance

- RED gate: Tests written first, failed with ModuleNotFoundError before implementation
- GREEN gate: `feat(...)` commits exist for both tasks (`f331628`, `c6ef9bc`)
- No REFACTOR gate needed -- code was clean on first pass

## Self-Check: PASSED

- All 4 created files verified present on disk
- Both commits (f331628, c6ef9bc) verified in git log
- No unexpected file deletions in either commit
