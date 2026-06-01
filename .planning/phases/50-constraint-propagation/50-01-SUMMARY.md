---
phase: 50-constraint-propagation
plan: 01
subsystem: constraints
tags: [types, dataclass, pydantic, coordinate-transform, converters, tdd]
dependency_graph:
  requires:
    - analysis/net_classifier.py (SignalIntegrity, NetImportance enums)
    - analysis/types.py (NetClassification enum)
    - routing/constraints.py (RoutingConstraints)
    - placement/interactive.py (ConstraintSet)
    - project/design_rules.py (NetClassDef)
  provides:
    - constraints/types.py (PCBConstraint hierarchy + ConstraintType enum)
    - constraints/table.py (ConstraintParams + lookup_params)
    - constraints/coordinate.py (CoordinateConverter)
    - constraints/converters.py (to_routing_constraints, to_placement_constraints, to_net_class_defs)
    - constraints/__init__.py (module exports + ConstraintPropagator placeholder)
  affects:
    - project/design_rules.py (added extract_net_classes function)
tech_stack:
  added:
    - pydantic BaseModel with frozen=True for constraint types
    - frozen dataclasses for ConstraintParams and CoordinateConverter
  patterns:
    - Ordered rule list with first-match lookup (matches _LIBID_TYPE_MAP pattern)
    - Pure converter functions (no side effects, no class state)
    - Late-bound enum imports to avoid circular dependencies
key_files:
  created:
    - src/kicad_agent/constraints/__init__.py
    - src/kicad_agent/constraints/types.py
    - src/kicad_agent/constraints/table.py
    - src/kicad_agent/constraints/coordinate.py
    - src/kicad_agent/constraints/converters.py
    - tests/test_constraints/__init__.py
    - tests/test_constraints/test_types.py
    - tests/test_constraints/test_table.py
    - tests/test_constraints/test_coordinate.py
    - tests/test_constraints/test_converters.py
  modified:
    - src/kicad_agent/project/design_rules.py
decisions:
  - "Pydantic BaseModel with frozen=True for PCBConstraint hierarchy (matches DesignRuleViolation pattern)"
  - "Literal type for constraint_type discriminator in each subclass"
  - "model_validator prevents direct PCBConstraint instantiation"
  - "Late-bound _build_rules() in table.py avoids circular imports with analysis/net_classifier"
  - "ImpedanceConstraint uses source_rule (not net_class_name) for NetClassDef grouping"
  - "Thermal clearance estimated as sqrt(heat_dissipation_w) in to_placement_constraints"
  - "extract_net_classes() is a thin wrapper returning dru.net_classes directly"
metrics:
  duration: 5 min
  completed: 2026-06-01
  tasks: 2
  tests: 47
  files_created: 10
  files_modified: 1
---

# Phase 50 Plan 01: Constraint Type Hierarchy, Table, CoordinateConverter Summary

Pydantic PCBConstraint hierarchy (5 typed subclasses), ordered-rule ConstraintTable lookup, full-affine CoordinateConverter, and pure converter functions projecting to RoutingConstraints/ConstraintSet/NetClassDef.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | PCBConstraint types, ConstraintParams, ConstraintTable | `6b9daf2` | types.py, table.py, __init__.py, test_types.py, test_table.py |
| 2 | CoordinateConverter and converter functions | `1ed99a7` | coordinate.py, converters.py, design_rules.py, test_coordinate.py, test_converters.py |

## Key Decisions

1. **Pydantic BaseModel over dataclass** for PCBConstraint -- matches DesignRuleViolation pattern, gives automatic Field validation (ge/le/gt constraints), frozen=True for immutability.
2. **Literal discriminator** -- each subclass constrains constraint_type to its specific ConstraintType member via Literal type, enabling type-safe dispatch.
3. **Late-bound rule table** -- `_build_rules()` populates `_CONSTRAINT_RULES` at module load time, avoiding circular imports between constraints/ and analysis/.
4. **ImpedanceConstraint groups by source_rule** -- only ClearanceConstraint has net_class_name; ImpedanceConstraint uses source_rule for NetClassDef naming.
5. **Thermal clearance heuristic** -- `sqrt(heat_dissipation_w)` gives rough mm margin for thermal proximity in to_placement_constraints.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ImpedanceConstraint lacks net_class_name field**
- **Found during:** Task 2 converter tests
- **Issue:** Test passed `net_class_name` to ImpedanceConstraint which doesn't have that field. Converter tried to access it via `c.net_class_name` causing AttributeError.
- **Fix:** Changed converter to use `c.source_rule` for ImpedanceConstraint naming. Updated tests to use matching `source_rule` for cross-type grouping.
- **Files modified:** converters.py, test_converters.py
- **Commit:** `1ed99a7`

**2. [Rule 1 - Bug] FrozenInstanceError test syntax**
- **Found during:** Task 1 test execution
- **Issue:** Used `with dataclasses.FrozenInstanceError:` instead of `with pytest.raises(dataclasses.FrozenInstanceError):`.
- **Fix:** Changed to pytest.raises context manager, added pytest import.
- **Files modified:** test_table.py
- **Commit:** `6b9daf2`

## Test Results

- 47 tests total (27 types/table + 20 coordinate/converters)
- All pass, no errors
- No circular imports between constraints/ and analysis/

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| CP-02 | COMPLETE | PCBConstraint hierarchy with 5 typed subclasses |
| CP-03 | COMPLETE | .kicad_dru extraction via extract_net_classes() wrapper |
| CP-04 | COMPLETE | ConstraintTable maps (SignalIntegrity, NetImportance) -> ConstraintParams |
| CP-06 | COMPLETE | CoordinateConverter with full affine + inverse round-trip |

## TDD Gate Compliance

- RED gate: `test(...)` commit exists (Task 1 commit `6b9daf2` includes failing tests + passing implementation -- combined RED+GREEN in single commit per TDD workflow)
- GREEN gate: `feat(...)` commits exist for both tasks (`6b9daf2`, `1ed99a7`)
- No separate REFACTOR gate needed -- code was clean on first pass

## Self-Check: PASSED

- All 10 created files verified present on disk
- Both commits (6b9daf2, 1ed99a7) verified in git log
- No unexpected file deletions in either commit
