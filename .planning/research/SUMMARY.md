# Research Summary: v3.0 Full-Stack EDA

**Milestone:** v3.0-full-stack-eda
**Synthesized:** 2026-06-01
**Sources:** ARCHITECTURE.md, PITFALLS.md, STACK.md, FEATURES.md (partial)

## Core Insight

v3.0 is not five bolt-on modules — it is a **pipeline** that bridges the existing `analysis/` layer (topology, subcircuits, intent, design rules) through to `placement/`, `validation/`, and a new `dfm/` module. The critical missing piece is the bridge: constraint propagation that translates schematic intelligence into PCB design constraints.

## Architecture Summary

**26 new files (~2,730 lines), 6 modified files, zero breaking changes.**

```
analysis/ (exists) → constraints/ (NEW) → spatial/pcb_model.py (NEW)
                                              ↓
                              placement/layout_aware.py (NEW)
                              validation/drc_intel.py (NEW)
                              dfm/ (NEW)
```

Build order: A+B parallel (spatial model + constraints), then C+D+E parallel (placement + DRC intel + DFM).

## Stack Summary

**Two dependency changes total:**
- `scipy>=1.11` promoted from undeclared transitive to explicit core dependency
- `scikit-fem>=10.0` added as optional `eda` dependency for thermal FEM

Everything else builds on existing stack (Shapely 2.1.1 STRtree, networkx 3.6.1, kiutils, sexpdata, pydantic). No constraint solver needed — propagation is deterministic rule-chain, not SAT/CSP.

**Critical gap:** kiutils doesn't parse `.kicad_dru` files (net class definitions). Build a `.kicad_dru` parser using sexpdata following the PcbIR pattern.

## Critical Pitfalls (6)

1. **kiutils UUID loss** — Every new PCB code path MUST go through PcbIR, never `Board.from_file()` directly
2. **Y-axis flip** — Schematic Y-up vs PCB Y-down; need explicit coordinate converter at boundary
3. **Circular constraint dependencies** — Design propagation as strictly unidirectional (Schematic → PCB)
4. **Shapely floating-point precision** — Define `_CLEARANCE_TOLERANCE_MM = 1e-4` for all distance comparisons
5. **KiCad layer name canonicalization** — `LayerClassifier` utility with `is_copper()`, regex for `In\d+.Cu`
6. **Component size estimation** — Extract real footprint bounding boxes from PcbIR, replace scalar heuristic

## Phase Structure

| Phase | Topic | Key Deliverables | Dependencies |
|-------|-------|-----------------|--------------|
| 50 | Constraint Propagation | ConstraintPropagator, PCBConstraint types, .kicad_dru parser | Phase 45-48 (topology, subcircuits, intent, design rules) |
| 51 | PCB Spatial Intelligence | PcbSpatialModel, LayerStackup, CopperConnectivityGraph | Phase 50 (constraints), existing spatial/ + PcbIR |
| 52 | Layout-Aware Placement | LayoutAwarePlacer, SignalFlowGrouper, ThermalPlacer | Phase 50 + 51 |
| 53 | PCB DRC Intelligence | IntelligentDrcAnalyzer, FixSuggester, spatial violation enrichment | Phase 50 + 51 |
| 54 | Design for Manufacturing | DfmChecker, ManufacturerProfiles, multi-stage DFM | Phase 51 (spatial model) |

**Parallelism:** Phases 50 and 51 can run in parallel. Phases 52, 53, 54 can all run in parallel once 50+51 complete.

## Key Design Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| D-V3-01 | No constraint solver library | Propagation is deterministic lookup (SignalIntegrity → PcbConstraint), not SAT/CSP |
| D-V3-02 | scipy as explicit dependency | Already installed transitively; v3.0 uses KDTree, linprog, cdist directly |
| D-V3-03 | scikit-fem optional | Thermal FEM is heavy; distance-based heuristic suffices for most boards |
| D-V3-04 | sexpdata for .kicad_dru | kiutils doesn't parse it; same raw S-expression pattern as PcbIR |
| D-V3-05 | Extend existing DesignRuleEngine | PCB DRC and DFM rules extend existing ABC; no new framework |
| D-V3-06 | Closed-form impedance | Hammerstad-Jensen, IPC-2141 formulas; no EM simulation needed |

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| kiutils UUID loss in new PCB paths | Critical | Lint rule + roundtrip validation after every PCB phase |
| Y-axis coordinate mismatch | Critical | Coordinate converter tested against Arduino_Mega fixture |
| Shapely floating-point false positives | High | Explicit tolerance constant, rounded comparisons |
| DRC JSON report format change | Moderate | Schema version check at parse time, defensive parsing |
| Thermal analysis missing power data | Moderate | Opt-in ThermalProfile, graceful degradation to connectivity-driven |

## Estimated Scope

- **New code:** ~3,400 lines across 12 modules
- **Modified code:** ~6 files, all additive changes
- **New dependencies:** 1 core (scipy), 1 optional (scikit-fem)
- **Estimated test count:** 80-100 new tests across 5 phases

---
*Research synthesized: 2026-06-01*
*Ready for roadmap: yes*
