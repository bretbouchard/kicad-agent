---
phase: 46-component-function-recognition
plan: 01
subsystem: analysis
tags: [subcircuit, classification, clustering, bfs, rule-based, ic-centric, feature-extraction]

# Dependency graph
requires:
  - phase: 45-circuit-topology-graph
    provides: CircuitTopology with directed signal flow, TopologyNode, TopologyEdge, NetClassification
provides:
  - SubcircuitDetector with IC-centric BFS clustering from CircuitTopology
  - SubcircuitType enum with 15 categories (PREAMP, COMPRESSOR, FILTER, VCA, etc.)
  - Subcircuit frozen dataclass with components, nets, boundary_nets, features, confidence
  - CircuitClassifier with 13 ordered rules matching violation_classifier pattern
  - Feature extraction computing component counts, feedback detection, sidechain detection
  - Boundary net identification between adjacent subcircuits
  - Passive-only group assignment to nearest IC subcircuit
affects: [46-02, domain-intelligence, circuit-qa]

# Tech tracking
tech-stack:
  added: []
patterns: [ic-centric-bfs-clustering, ordered-rule-first-match-wins, frozen-dataclass-results, feature-extraction-dict]

key-files:
  created:
    - src/kicad_agent/analysis/subcircuit_detector.py
    - src/kicad_agent/analysis/circuit_classifier.py
    - tests/test_subcircuit_detection.py
  modified:
    - src/kicad_agent/analysis/__init__.py

key-decisions:
  - "BFS clustering does not traverse through ICs -- each IC forms its own subcircuit to prevent absorption"
  - "PREAMP rule requires resistor_count >= 2 to distinguish from OUTPUT_STAGE (low component count buffers)"
  - "SubcircuitDetector._extract_features as standalone method for reuse by Plan 46-02"
  - "Passive-only components assigned to nearest IC subcircuit via BFS distance"

patterns-established:
  - "IC-centric BFS clustering: traverse up to max_hops from each IC, skip other ICs at boundary"
  - "Feature dict pattern: _extract_features produces dict consumed by CircuitClassifier rules"

requirements-completed: [DOMAIN-02]

# Metrics
duration: 17min
completed: 2026-06-01
---

# Phase 46 Plan 01: Subcircuit Detection Summary

**IC-centric BFS clustering with 13-rule ordered classifier detecting PREAMP, FILTER, COMPRESSOR, VCA, OSCILLATOR, LFO, POWER_SUPPLY, DIGITAL_CONTROL, ANALOG_SWITCH, MIXER, OUTPUT_STAGE subcircuits**

## Performance

- **Duration:** 17 min
- **Started:** 2026-06-01T04:40:30Z
- **Completed:** 2026-06-01T04:57:48Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- SubcircuitDetector clusters components around ICs using BFS with configurable max_hops
- BFS stops at IC boundaries ensuring each IC forms its own subcircuit
- CircuitClassifier with 13 ordered rules for subcircuit type classification (first match wins)
- Feature extraction: component counts, feedback detection, sidechain detection, multiple inputs
- Boundary net identification between adjacent subcircuits
- Passive-only groups assigned to nearest IC subcircuit via BFS distance
- 66 TDD tests covering schemas, detection, classification, confidence, integration
- 182 total tests with topology graph tests, no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create SubcircuitType enum, Subcircuit schema, and SubcircuitDetector with tests** - `669100b` (test, RED) + `ce8f1b5` (feat, GREEN)
2. **Task 2: CircuitClassifier with rule-based subcircuit type classification** - `4749ed1` (test)
3. **Task 3: Full integration -- detector + classifier on mock topologies** - `2b850f7` (feat)

## Files Created/Modified
- `src/kicad_agent/analysis/subcircuit_detector.py` - SubcircuitDetector with IC-centric BFS clustering, feature extraction, boundary nets, passive assignment
- `src/kicad_agent/analysis/circuit_classifier.py` - CircuitClassifier with 13 ordered rules, ClassificationResult, batch classification
- `tests/test_subcircuit_detection.py` - 66 TDD tests: SubcircuitType enum, Subcircuit schema, detector (empty/single-IC/multi-IC/boundary/passive/sequential/confidence/determinism), classifier (12 type rules, confidence, unknowns, ordered rules, batch), integration (multi-IC, compressor, overlap, features)
- `src/kicad_agent/analysis/__init__.py` - Updated exports for SubcircuitDetector, Subcircuit, SubcircuitType, CircuitClassifier, ClassificationResult

## Decisions Made
- BFS clustering does not traverse through ICs -- each IC forms its own subcircuit, preventing absorption of adjacent ICs
- PREAMP rule requires resistor_count >= 2 to distinguish from OUTPUT_STAGE (unity gain buffers have 1 resistor)
- Feature extraction is a standalone method for reuse by Plan 46-02 (feature vector generation)
- Passive-only components (no IC nearby) are assigned to nearest IC subcircuit via BFS distance

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed list/tuple concatenation in SubcircuitDetector.detect()**
- **Found during:** Task 1 (single IC test)
- **Issue:** _cluster_around_ic returns list for comp_refs, but detect() tried to concatenate with tuple
- **Fix:** Used list() + [item] instead of tuple concatenation
- **Files modified:** src/kicad_agent/analysis/subcircuit_detector.py
- **Verification:** All 37 tests pass
- **Committed in:** ce8f1b5

**2. [Rule 1 - Bug] Fixed BFS clustering absorbing adjacent ICs**
- **Found during:** Task 1 (multi-IC test -- produced 1 subcircuit instead of 2)
- **Issue:** BFS from U1 reached U2 within 2 hops via NET_A edge, absorbing U2 into U1's cluster
- **Fix:** Added ic_refs parameter to _cluster_around_ic; BFS stops at other ICs and records their connecting nets
- **Files modified:** src/kicad_agent/analysis/subcircuit_detector.py
- **Verification:** Multi-IC topology correctly produces 2 subcircuits
- **Committed in:** ce8f1b5

**3. [Rule 1 - Bug] Fixed list/tuple concatenation in _assign_passive_groups**
- **Found during:** Task 1 (passive assignment test)
- **Issue:** sc["components"] is list but code appended tuple
- **Fix:** Used list(sc["components"]) + [ref] pattern
- **Files modified:** src/kicad_agent/analysis/subcircuit_detector.py
- **Verification:** Passive assignment test passes
- **Committed in:** ce8f1b5

**4. [Rule 1 - Bug] Fixed PREAMP/OUTPUT_STAGE rule overlap**
- **Found during:** Task 2 (output_stage classifier test)
- **Issue:** Output stage features (NE5532, feedback_resistor_count=1, no caps) matched PREAMP rule first
- **Fix:** Added resistor_count >= 2 requirement to PREAMP rule; output stages have <= 1 resistor (unity gain)
- **Files modified:** src/kicad_agent/analysis/circuit_classifier.py, tests/test_subcircuit_detection.py
- **Verification:** Output stage classified correctly as OUTPUT_STAGE, preamp still classified as PREAMP
- **Committed in:** 4749ed1

---

**Total deviations:** 4 auto-fixed (3 bugs, 1 rule overlap)
**Impact on plan:** All auto-fixes necessary for correctness. IC boundary handling was a fundamental algorithmic fix. No scope creep.

## Issues Encountered
- Multi-IC clustering required IC-boundary awareness in BFS -- naive hop-based traversal absorbed adjacent ICs into a single cluster
- PREAMP and OUTPUT_STAGE classification rules overlapped for op-amp subcircuits with low component count -- resolved by requiring minimum 2 resistors for PREAMP

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SubcircuitDetector ready for Plan 46-02 (feature vector generation for ML classification)
- CircuitClassifier ready for extension with additional rules
- _extract_features method ready for reuse as standalone feature extraction
- 66 tests provide comprehensive regression coverage

---
*Phase: 46-component-function-recognition*
*Completed: 2026-06-01*
