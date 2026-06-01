---
phase: 45-circuit-topology-graph
plan: 01
subsystem: analysis
tags: [topology, signal-flow, net-classification, directed-graph, union-find, bfs, feedback-detection]

# Dependency graph
requires:
  - phase: 39-schematic-intelligence
    provides: SchematicGraph with pin positions, wire connectivity, labels
provides:
  - CircuitTopology with directed signal flow from TopologyBuilder
  - NetClassification enum for POWER, GROUND, SIGNAL, CONTROL, FEEDBACK, CLOCK, UNKNOWN
  - PinRole enum for INPUT, OUTPUT, POWER, BIDIRECTIONAL, CONTROL, UNKNOWN
  - NetClassifier with ordered rule-based classification (first match wins)
  - IC pin role rules for NE5532, TL072, LM358, LM324, THAT4301, THAT2181, CD4066, CD4060
  - Feedback loop detection via BFS depth analysis
  - Signal path tracing from input to output nets
affects: [46-component-function-recognition, domain-intelligence, circuit-qa]

# Tech tracking
tech-stack:
  added: []
  patterns: [ordered-rule-first-match-wins, union-find-net-grouping, frozen-dataclass-results, bfs-depth-feedback-detection]

key-files:
  created:
    - src/kicad_agent/analysis/types.py
    - src/kicad_agent/analysis/topology_graph.py
    - src/kicad_agent/analysis/net_classifier.py
    - tests/test_topology_graph.py
  modified:
    - src/kicad_agent/analysis/__init__.py

key-decisions:
  - "Shared types.py module for NetClassification and PinRole to prevent circular imports between topology_graph and net_classifier"
  - "Union-Find net resolution instead of BFS wire tracing for correctness on multi-hop connections"
  - "Ordered list (not dict) for _LIBID_TYPE_MAP to handle prefix ordering (LED before L, Crystal before C)"
  - "Feedback edges reclassified regardless of initial classification (not just SIGNAL -> also UNKNOWN)"
  - "Non-power members in nets without OUTPUT drivers get bidirectional edge pairs"

patterns-established:
  - "Ordered rule list with first-match-wins: follows violation_classifier pattern for consistency"
  - "Frozen dataclass result types: TopologyNode, TopologyEdge, CircuitTopology are immutable"
  - "Union-Find with path compression for electrical connectivity grouping"

requirements-completed: [DOMAIN-01]

# Metrics
duration: 26min
completed: 2026-06-01
---

# Phase 45: Circuit Topology Graph Summary

**Directed net-to-component graph with signal flow inference from IC pin types, Union-Find net resolution, and rule-based net classification**

## Performance

- **Duration:** 26 min
- **Started:** 2026-06-01T03:20:40Z
- **Completed:** 2026-06-01T03:46:00Z
- **Tasks:** 4
- **Files modified:** 5

## Accomplishments
- TopologyBuilder produces CircuitTopology from SchematicGraph with directed signal flow
- IC pin role classification for NE5532, TL072, LM358, LM324, THAT4301, THAT2181, CD4066, CD4060, voltage regulators
- Union-Find net resolution groups connected pins into nets (with or without labels)
- NetClassifier uses ordered rules matching violation_classifier pattern (first match wins)
- Feedback loop detection via BFS depth analysis
- Signal path tracing from input to output through directed edges
- 87 TDD tests covering schemas, pin roles, edge direction, net classification, feedback, and integration

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CircuitTopology schema, TopologyBuilder, and core tests** - `d03588b` (feat)
2. **Task 2: IC pin role classification and signal flow inference** - `31b1a84` (feat)
3. **Task 3: NetClassifier with rule-based classification** - `6387d05` (test)
4. **Task 4: Feedback detection and signal path tracing** - `01342db` (feat)

## Files Created/Modified
- `src/kicad_agent/analysis/types.py` - Shared NetClassification and PinRole enums
- `src/kicad_agent/analysis/topology_graph.py` - TopologyBuilder, CircuitTopology, TopologyNode, TopologyEdge with Union-Find net resolution
- `src/kicad_agent/analysis/net_classifier.py` - NetClassifier with ordered rule-based classification
- `src/kicad_agent/analysis/__init__.py` - Updated exports for new modules
- `tests/test_topology_graph.py` - 87 TDD tests for all topology, classification, and flow features

## Decisions Made
- Shared `types.py` module for enums to prevent circular imports (topology_graph -> net_classifier -> topology_graph)
- Union-Find with path compression for net resolution instead of BFS wire tracing -- BFS failed to connect multi-hop pin chains without labels
- Ordered list for `_LIBID_TYPE_MAP` instead of dict -- prefix ordering matters (Device:LED must match before Device:L, Device:Crystal before Device:C)
- Feedback edges reclassified from any non-POWER classification, not just SIGNAL -- most anonymous nets get UNKNOWN classification

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed _LIBID_TYPE_MAP prefix ordering for LED and Crystal**
- **Found during:** Task 1 (component type mapping tests)
- **Issue:** Dict iteration matched Device:LED to Device:L (inductor) and Device:Crystal to Device:C (capacitor)
- **Fix:** Changed to ordered list with longer prefixes first (LED before L, Crystal before C)
- **Files modified:** src/kicad_agent/analysis/topology_graph.py
- **Verification:** All component type mapping tests pass
- **Committed in:** d03588b (Task 1 commit)

**2. [Rule 1 - Bug] Fixed Union-Find path compression returning wrong root**
- **Found during:** Task 2 (op-amp subcircuit net resolution)
- **Issue:** Path compression `find()` broke out of loop when grandparent==parent instead of returning root, leaving connected pins in separate clusters
- **Fix:** Rewrote find() with proper two-pass path compression (find root, then compress)
- **Files modified:** src/kicad_agent/analysis/topology_graph.py
- **Verification:** Connected pins correctly grouped into same net
- **Committed in:** 31b1a84 (Task 2 commit)

**3. [Rule 1 - Bug] Fixed edge creation for mixed BIDIRECTIONAL + INPUT nets**
- **Found during:** Task 2 (R1.2 -> U2.IN+ edge missing)
- **Issue:** Edge builder only created bidirectional pairs within the `bidirectional` list, missing mixed BIDIRECTIONAL+INPUT nets
- **Fix:** Changed to use `non_power` member list instead of `bidirectional` list for no-driver nets
- **Files modified:** src/kicad_agent/analysis/topology_graph.py
- **Verification:** test_resistor_to_opamp_input passes
- **Committed in:** 31b1a84 (Task 2 commit)

**4. [Rule 3 - Blocking] Fixed signal path tracing for single-pin input/output nets**
- **Found during:** Task 2 (signal path tracing returned empty)
- **Issue:** Signal path tracer only looked for edge source/target refs, but SIG_IN/OUT nets had single pins (no edges)
- **Fix:** Added pin_nets lookup to find components connected to input/output nets even without edges; refactored to pass pin_nets from from_schematic_graph
- **Files modified:** src/kicad_agent/analysis/topology_graph.py
- **Verification:** Signal path U1 -> R1 -> U2 traced correctly
- **Committed in:** 31b1a84 (Task 2 commit)

**5. [Rule 1 - Bug] Fixed feedback reclassification filter for non-SIGNAL edges**
- **Found during:** Task 4 (feedback edges not reclassified)
- **Issue:** Feedback reclassification only applied to SIGNAL-classified edges, but anonymous nets are UNKNOWN
- **Fix:** Changed condition to reclassify any non-POWER edge in a feedback net
- **Files modified:** src/kicad_agent/analysis/topology_graph.py
- **Verification:** Feedback edges correctly reclassified as FEEDBACK
- **Committed in:** 01342db (Task 4 commit)

---

**Total deviations:** 5 auto-fixed (3 bugs, 1 blocking, 1 bug)
**Impact on plan:** All auto-fixes necessary for correctness. Net resolution and signal flow needed fundamental fixes for multi-hop circuits. No scope creep.

## Issues Encountered
- Union-Find net resolution replaced the original BFS wire tracing approach because BFS could not name nets that had no label on any connected endpoint. The Union-Find approach groups all electrically connected positions first, then assigns names from labels or generates anonymous names.
- The op-amp feedback circuit required careful test mock design: pin positions must align with wire endpoints for the Union-Find to correctly union them.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- TopologyBuilder ready for Phase 46 (component function recognition) as the foundation graph layer
- NetClassifier ready for circuit QA and intelligent repair
- Feedback detection enables stability analysis in future phases
- All 87 tests provide comprehensive regression coverage

---
*Phase: 45-circuit-topology-graph*
*Completed: 2026-06-01*
