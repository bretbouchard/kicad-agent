---
phase: 98-ai-routing-strategy-advisor
plan: 02
subsystem: routing
tags: [validation, fallback, defense-in-depth, tdd, untrusted-model]
requires:
  - "Phase 100 RoutingStrategy Protocol + DeterministicStrategy"
  - "Phase 98 Plan 01 AiRoutingStrategy (raised _AiStrategyError)"
  - "NativeBoard layer stackup (general.layers + setup.stackup.layers)"
provides:
  - "StrategyValidator with R-4 semantic gate (coordinates, nets, layers)"
  - "AiRoutingStrategy R-6 graceful degradation (broad except -> DeterministicStrategy)"
  - "ai_fallback: routing_notes prefix for audit-trail grepability"
affects:
  - "src/kicad_agent/routing/strategy_validator.py (new)"
  - "src/kicad_agent/routing/ai_strategy.py (modified - fallback wiring)"
  - "tests/test_phase98_strategy_validator.py (new)"
  - "tests/test_phase98_ai_strategy.py (modified - fallback tests replace raises tests)"
tech-stack:
  added: []
  patterns:
    - "Defense in depth: R-4 semantic gate + Phase 100 H4 structural gate"
    - "Graceful degradation: broad except Exception -> trusted deterministic fallback"
    - "Audit trail via routing_notes prefix (ai_fallback:) for post-hoc analysis"
    - "Layer-stackup discovery chain: typed stackup -> general.layers regex -> {F.Cu, B.Cu} default"
key-files:
  created:
    - "src/kicad_agent/routing/strategy_validator.py"
    - "tests/test_phase98_strategy_validator.py"
  modified:
    - "src/kicad_agent/routing/ai_strategy.py"
    - "tests/test_phase98_ai_strategy.py"
decisions:
  - "Broad `except Exception` is intentional and documented - model is untrusted, DeterministicStrategy is trusted deterministic code that always succeeds"
  - "R-4 validator runs AFTER translation, BEFORE return - catches semantic errors the translator's permissive filtering does not (e.g. incomplete net_priorities)"
  - "Translator filters unknown nets before R-4 runs - R-4's unknown-net check is a defense-in-depth backstop (verified directly in SC-4 batch tests, not via AiRoutingStrategy flow)"
  - "Layer-stackup discovery chain: typed stackup (setup.stackup.layers[*].type=='copper') -> general.layers regex filtered -> {F.Cu, B.Cu} default"
  - "Two Plan 01 translator tests updated to provide complete net_priorities - R-4 now (correctly) rejects incomplete priorities which triggers fallback"
  - "H-1 council finding (routing_notes not in durable JSONL audit trail) accepted as limitation - filed as out-of-scope Bead per Council Option A"
metrics:
  duration: "6min"
  completed: 2026-06-25
  tasks_completed: 2
  tests_added: 44
  files_created: 2
  files_modified: 2
---

# Phase 98 Plan 02: StrategyValidator + R-6 Fallback Summary

Built the R-4 semantic validation gate (StrategyValidator) and wired R-6 graceful degradation into AiRoutingStrategy. The validator rejects out-of-bounds coordinates, unknown net names, and impossible layer assignments; the fallback catches any failure in the AI path and returns a DeterministicStrategy result prefixed `ai_fallback:`.

## What Was Built

### 1. StrategyValidator (R-4) — `src/kicad_agent/routing/strategy_validator.py`

Single `validate(result, board_state, netlist) -> None` entry point that raises `ValueError` on the first violation. Four sub-validators run in fixed order so the first error is deterministic:

- **Coordinate bounds** (`_validate_keepouts`): every keepout x1/x2/y1/y2 must be inside `board_bounds`, and `x1 < x2`, `y1 < y2` (positive area). 13 `raise ValueError` sites across the four categories.
- **Net references** (`_validate_net_references`): every net in `net_priorities`, `router_assignment`, `layer_hints` must exist in the netlist; every netlist net must appear in both `router_assignment` and `net_priorities` (full coverage).
- **Layer hints** (`_validate_layer_hints`): every `layer_hints` value must be a valid copper layer for the board.
- **Keepout layers** (`_validate_keepout_layers`): every `keepout.layer` must likewise be valid.

Layer discovery chain (`_extract_valid_copper_layers`): typed stackup (`setup.stackup.layers[*].type == 'copper'`) -> `general.layers` tuple filtered by `_COPPER_LAYER_RE` (`^(F|B|In\d+)\.Cu$`) -> `{F.Cu, B.Cu}` default when both are empty or board is None.

### 2. R-6 Fallback Wiring — `src/kicad_agent/routing/ai_strategy.py`

`AiRoutingStrategy.__init__` now accepts optional `validator` and `board` params; when `validator` is None, a default `StrategyValidator(board=board)` is constructed so layer validation uses the provided board (or the 2-layer default).

`strategize()` wraps the entire AI path (render -> prompt -> inference -> parse -> translate -> validate) in a single `try/except Exception`. On any failure the method calls `DeterministicStrategy().strategize(board_state, netlist)` and returns the result with `routing_notes` replaced by `f"ai_fallback: {type(exc).__name__}: {exc}"`. The broad `except Exception` is intentional and documented per RESEARCH.md Graceful Degradation Strategy: the model is untrusted, DeterministicStrategy is trusted deterministic code that always succeeds. The failure is logged at WARNING level for the audit trail.

### 3. Tests

- `tests/test_phase98_strategy_validator.py` (new, 24 tests): TestCategoryCoordinateBounds (8), TestCategoryNetValidation (6), TestCategoryLayerValidation (6), TestCategorySyntheticInvalid (4 incl. SC-4 batch of 10 invalid results).
- `tests/test_phase98_ai_strategy.py` (modified, 20 tests): Plan 01 happy-path/translation tests preserved; TestErrorPaths (3 raises-asserting tests) replaced with TestCategoryFallback (11 fallback-asserting tests) + TestCategoryDeterminism (1).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Two Plan 01 translator tests provided incomplete net_priorities**
- **Found during:** Task 2 GREEN
- **Issue:** `test_missing_net_in_router_assignment_defaults_to_astar` and `test_unknown_backend_string_defaults_to_astar` had `net_priorities` lists that omitted nets present in the netlist. Under Plan 01 (no R-4 gate) this was fine. Under Plan 02, R-4 correctly rejects incomplete priorities and triggers fallback, so the tests were exercising the fallback path instead of the translator behavior they intended to verify.
- **Fix:** Updated both tests to provide complete `net_priorities` (all nets in netlist). The translator behavior under test (safe-default fill for missing router_assignment; ASTAR coercion for unknown backend strings) is unchanged and now correctly exercised on the happy path.
- **Files modified:** tests/test_phase98_ai_strategy.py
- **Commit:** a4e13a1

**2. [Rule 1 - Bug] test_f4_unknown_net_falls_back could not trigger fallback via AiRoutingStrategy flow**
- **Found during:** Task 2 GREEN
- **Issue:** The Plan 02 test spec for F4 assumed an unknown net in `net_priorities` would reach R-4 and trigger fallback. But the Plan 01 translator deliberately filters unknown nets from `net_priorities`, `router_assignment`, and `layer_hints` before R-4 runs (permissive design). So PHANTOM was dropped and R-4 saw a clean result - no fallback.
- **Fix:** Repurposed test_f4 to `test_f4_net_coverage_violation_falls_back` - a real net-coverage violation R-4 catches through the AiRoutingStrategy flow (missing N1 from net_priorities, which the translator does NOT auto-fill). The unknown-net rejection path is still verified directly in the SC-4 synthetic batch (TestCategorySyntheticInvalid) which calls `StrategyValidator.validate` directly without the translator in front.
- **Files modified:** tests/test_phase98_ai_strategy.py
- **Commit:** a4e13a1

### Council Findings (H-1)

**H-1 (HIGH): Fallback `routing_notes` does not reach the durable JSONL audit trail.** Per Council Option A, this is accepted as a documented limitation. The `ai_fallback:` prefix is visible in (1) Python `logger.warning()` output and (2) the in-memory `RoutingStrategyResult.routing_notes` field (discarded after orchestrator dispatch). The Phase 100 `RoutingAuditEntry` schema captures `strategy=type(strategy).__name__` but does not persist `routing_notes`. Fixing this requires modifying Phase 100 `RoutingOrchestrator`/`RoutingAuditEntry` which is out of scope for Plan 02. Filing as out-of-scope Bead per bureaucracy.md §7 out-of-scope finding rule.

## Test Results

- **Plan 02 unit tests:** 44/44 pass
  - test_phase98_strategy_validator.py: 24/24
  - test_phase98_ai_strategy.py: 20/20
- **Phase 98 full suite:** 62/62 pass (Plan 01 + Plan 02)
- **Phase 100 + routing regression:** 267/267 pass (zero impact on orchestrator)

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (validator) | 4d3488a | PASS - 24 failing tests (module not found) |
| GREEN (validator) | 7ee1c1e | PASS - 24 tests pass |
| RED (fallback) | 523bed1 | PASS - 17 failing tests (kwargs + fallback not wired) |
| GREEN (fallback) | a4e13a1 | PASS - 20 tests pass |

Both tasks followed strict RED -> GREEN TDD cycle. No REFACTOR needed.

## Verification

```
$ grep -c "raise ValueError" src/kicad_agent/routing/strategy_validator.py
13
$ grep -c "ai_fallback:" src/kicad_agent/routing/ai_strategy.py
2
$ grep -c "except Exception" src/kicad_agent/routing/ai_strategy.py
4
$ grep -c "DeterministicStrategy().strategize" src/kicad_agent/routing/ai_strategy.py
1
```

## Known Stubs

None. StrategyValidator is fully implemented across all four validation categories. AiRoutingStrategy fallback is fully wired across all failure paths (empty, malformed, invalid-coord, net-coverage, invalid-layer, render-fail, inference-fail).

## Threat Flags

None. The threat model in the plan (T-98-02-01 through T-98-02-06) is fully mitigated:
- T-01 (Tampering - coordinates): `_validate_keepouts` rejects any coordinate outside `board_bounds`
- T-02 (Tampering - layers): `_validate_layer_hints` + `_validate_keepout_layers` reject layers not in stackup
- T-03 (Spoofing - nets): `_validate_net_references` rejects unknown nets (defense-in-depth backstop; translator filters first)
- T-04 (DoS - fallback): broad `except Exception` -> DeterministicStrategy
- T-05 (EoP - routing_notes disclosure): accepted (informational, not privileged)
- T-06 (Repudiation - logging): `logger.warning` records every fallback with exception type and message

## Self-Check: PASSED

Files verified present:
- FOUND: src/kicad_agent/routing/strategy_validator.py
- FOUND: tests/test_phase98_strategy_validator.py

Files verified modified:
- FOUND: src/kicad_agent/routing/ai_strategy.py (validator + fallback wiring)
- FOUND: tests/test_phase98_ai_strategy.py (TestCategoryFallback + TestCategoryDeterminism)

Commits verified in git log:
- FOUND: 4d3488a (test RED validator)
- FOUND: 7ee1c1e (feat GREEN validator)
- FOUND: 523bed1 (test RED fallback)
- FOUND: a4e13a1 (feat GREEN fallback)

Self-check result: PASSED (4/4 files, 4/4 commits).
