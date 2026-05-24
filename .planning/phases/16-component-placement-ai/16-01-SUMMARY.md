---
phase: 16-component-placement-ai
plan: 01
subsystem: placement
tags: [graph, bipartite, features, gnn, networkx]
dependency_graph:
  requires: [generation/intent.py, generation/placement.py]
  provides: [placement/graph.py, placement/features.py]
  affects: []
tech_stack:
  added: [networkx, numpy]
  patterns: [bipartite-graph, feature-extraction]
key_files:
  created:
    - src/kicad_agent/placement/__init__.py
    - src/kicad_agent/placement/graph.py
    - src/kicad_agent/placement/features.py
    - tests/conftest_placement.py
    - tests/test_placement_graph.py
  modified:
    - tests/conftest.py
decisions:
  - Bipartite graph representation avoids O(n^2) edge explosion from power nets
  - Power nets assigned criticality 1.0 (lower) to prevent clustering artifacts
  - High-speed signal nets (SDA/SCL/CLK/MOSI/MISO/USB/HDMI/SPI) get criticality 3.0
  - Component features include library_id/value character hashes for GNN discrimination
  - Feature dimensions fixed at COMP_FEATURE_DIM=32 and NET_FEATURE_DIM=16 with reserved slots
metrics:
  duration: 4 min
  completed: 2026-05-24
  tasks: 1
  files: 6
  tests_added: 24
  tests_passing: 1108
---

# Phase 16 Plan 01: Bipartite Placement Graph Summary

Bipartite component-net graph construction from schematic netlists with fixed-size node feature extraction for GNN-based placement prediction.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Bipartite placement graph and feature extraction | 9d2ef10 | placement/__init__.py, graph.py, features.py, conftest_placement.py, test_placement_graph.py |

## What Was Built

### placement/graph.py
- `netlist_to_placement_graph()`: Converts ComponentSpec + NetSpec lists into a networkx bipartite graph with component nodes (bipartite=0) and net nodes (bipartite=1)
- `PlacementGraph` class: Wrapper providing `component_nodes()`, `net_nodes()`, `get_component_features()`, `get_net_features()`, `get_adjacency_matrix()`, `get_edge_weights()`, and board dimension properties
- Validation: board dimensions positive, component count <= 500, net count <= 200

### placement/features.py
- `extract_component_features()`: Returns float32 (32,) vector with size heuristic, type flags (IC/passive/connector), fixed position encoding, library_id/value character hashes
- `extract_net_features()`: Returns float32 (16,) vector with pin count, component count, power flag, criticality weight, fanout ratio
- Constants: `COMP_FEATURE_DIM=32`, `NET_FEATURE_DIM=16`

### Test Coverage
- 24 tests covering bipartite structure, node/edge counts, feature shapes and values, adjacency matrices, edge cases (empty netlist, count caps, invalid dims)

## Verification Results

- `pytest tests/test_placement_graph.py`: 24/24 passed
- `pytest tests/`: 1108 passed, 1 skipped, 0 failures
- Barrel import: OK
- Feature dimension constants: OK

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- src/kicad_agent/placement/__init__.py: FOUND
- src/kicad_agent/placement/graph.py: FOUND
- src/kicad_agent/placement/features.py: FOUND
- tests/conftest_placement.py: FOUND
- tests/test_placement_graph.py: FOUND
- Commit 9d2ef10: FOUND
