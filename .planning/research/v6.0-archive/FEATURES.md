# Feature Landscape: v3.0 Full-Stack EDA

**Domain:** Bridging schematic intelligence to PCB layout via constraint propagation, spatial modeling, layout-aware placement, DRC intelligence, and DFM
**Milestone:** v3.0-full-stack-eda (Phases 50-54)
**Researched:** 2026-06-01
**Confidence:** HIGH
**Scope:** 5 new feature areas extending kicad-agent's existing schematic analysis into PCB layout intelligence

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Design Context](#design-context)
3. [Table Stakes](#table-stakes)
4. [Differentiators](#differentiators)
5. [Anti-Features](#anti-features)
6. [Feature Dependencies](#feature-dependencies)
7. [MVP Recommendation](#mvp-recommendation)
8. [Sources](#sources)

---

## Executive Summary

v3.0 closes the most significant gap in kicad-agent: schematic intelligence stops at the schematic boundary, while PCB placement and DRC operate without any knowledge of design intent. The five feature areas are not independent modules but a **pipeline**: constraint propagation translates schematic analysis outputs into PCB design constraints, the PCB spatial model provides geometry-rich query infrastructure, layout-aware placement consumes both to produce intelligent component positions, DRC intelligence enriches violation reports with spatial context and fix suggestions, and DFM adds manufacturing-readiness assessment.

The critical feature is constraint propagation -- it is the keystone that connects the existing `analysis/` layer (topology graphs, subcircuit detection, intent inference, design rules) to the PCB domain. Without it, placement is connectivity-driven but blind to differential pairs, impedance targets, and thermal requirements. With it, the entire pipeline from schematic capture through manufacturing export becomes aware of what the designer intended.

Three of the five feature areas build directly on existing infrastructure: layout-aware placement extends `HybridPlacementEngine`, DRC intelligence extends `enrich_drc_result()`, and DFM follows the `DesignRule` ABC pattern. The two genuinely new modules are constraint propagation (`constraints/`) and the PCB spatial model (`spatial/pcb_model.py`), which together add approximately 1,200 lines of new code. The remaining three areas add approximately 2,200 lines across extensions to existing modules.

---

## Design Context

### What Already Exists

The kicad-agent codebase has 85+ operations, 2,899 tests, and deep schematic understanding from Phases 1-49. The following existing modules form the foundation for v3.0:

| Component | Location | Capability | v3.0 Role |
|-----------|----------|------------|-----------|
| CircuitTopology | `analysis/topology_graph.py` | Graph of components (nodes), connections (edges), net classifications, signal paths | Source for constraint propagation -- net types drive PCB constraints |
| SubcircuitDetector | `analysis/subcircuit_detector.py` | IC-centric clustering into functional blocks (PREAMP, COMPRESSOR, VCA, etc.) | Source for signal flow grouping in layout-aware placement |
| IntentInferrer | `analysis/intent_inference.py` | Rule-based design intent inference (no LLM) -- overall circuit type, subcircuit functions | Source for constraint priority and placement strategy |
| NetClassifier | `analysis/net_classifier.py` | Net type (POWER/GROUND/SIGNAL/CLOCK), SignalIntegrity (HIGH_SPEED/LOW_FREQUENCY/DC), NetImportance (CRITICAL/HIGH/MEDIUM/LOW) | Primary input to constraint lookup table |
| DesignRuleEngine | `analysis/design_rule_engine.py` | Pluggable rule ABC with severity sorting, error handling, per-rule config | Pattern to extend for PCB DRC rules and DFM checks |
| DesignRule ABC | `analysis/design_rules.py` | `check(topology, config) -> list[DesignRuleViolation]` with severity, category, location | Base class for DFM checks |
| PcbIR | `ir/pcb_ir.py` | PCB file access with UUID map, footprint/net/trace queries | Data source for PCB spatial model |
| SpatialPoint/Box/Path/Region | `spatial/primitives.py` | Frozen dataclasses with `to_shapely()` methods, coordinate-grounded | Foundation types for PCB spatial model |
| SpatialQueryEngine | `spatial/query.py` | Shapely STRtree spatial indexing, proximity/containment queries | Query layer for PCB spatial model |
| extract_all() | `spatial/extractor.py` | PcbIR coordinate data to spatial primitives | Pipeline step for PCB spatial model construction |
| HybridPlacementEngine | `placement/engine.py` | ML prediction + rule-based placement, SA refinement | Core engine to extend with constraint awareness |
| PlacementScorer | `placement/scoring.py` | HPWL, congestion, clearance, edge, board utilization scores | Scoring to extend with constraint penalty terms |
| PlacementValidator | `placement/validation.py` | Overlap, clearance, keepout violation detection | Validation to extend with constraint checks |
| enrich_drc_result() | `validation/spatial_drc.py` | Raw DRC violations to SpatialViolation with nearest footprint | Enrichment pipeline to extend with fix suggestions |
| run_drc() | `validation/erc_drc.py` | kicad-cli DRC wrapper, structured Violation/DrcResult | Data source for DRC intelligence |
| ConstraintSet | `placement/interactive.py` | Fixed positions, keepout zones, min_clearance, SA parameters | Constraint model to extend with PCB-aware constraints |

### What Is Missing (The Gap)

There is **no data path** from `analysis/` to `placement/` or `validation/`. Schematic intelligence (topology, subcircuits, design rules, intent inference) produces structured outputs that are consumed only by the schematic design rule engine. PCB placement uses component connectivity but ignores net classification, signal integrity, and design intent. DRC enrichment adds spatial coordinates but not constraint context or fix suggestions.

This gap means that an AI agent editing both schematic and PCB has no way to translate "this net is a 100-ohm differential pair carrying USB 3.0 signals" into PCB placement and routing constraints. The agent can see the schematic intent but cannot enforce it on the PCB.

### KiCad Format Constraints

KiCad's net class system defines trace width, clearance, via diameter, and via drill per class, but does **not** natively support differential pair constraints, impedance targets, or per-layer trace widths within net class definitions. Custom design rules (`.kicad_dru` files) extend net classes with conditional rules, but kiutils does not parse `.kicad_dru` files. v3.0 must work within these limitations by separating constraints into KiCad-native (propagated to net classes) and extended (stored in sidecar metadata).

---

## Table Stakes

Features users expect from a "full-stack EDA intelligence" system. Missing any makes the feature set feel incomplete or unreliable.

### TS-1: Schematic-to-PCB Constraint Propagation

**Why expected:** Any EDA tool that understands schematic intent should be able to translate that understanding into PCB design rules. Without this, the "intelligence" is locked inside the schematic domain.

**Complexity:** HIGH

**Notes:** The existing `NetClassifier` already produces `SignalIntegrity` and `NetImportance` for every net. The constraint table maps these to PCB parameters (clearance, trace width, via drill, impedance target). The `DesignIntent` provides design goals (AUDIO_PROCESSING, POWER_SUPPLY, CONTROL) that influence constraint priority. The `.kicad_dru` parser (needed because kiutils does not parse it) is a prerequisite.

**Key sub-features:**
- Differential pair detection from net name patterns and schematic connectivity
- Power net clearance rules derived from voltage levels and net importance
- Impedance target assignment from net classification and board stackup
- Thermal keepout zones from component type and design intent
- Signal flow group identification from subcircuit boundaries

### TS-2: PCB Spatial Model with Net-Class-Aware Geometry

**Why expected:** Any PCB intelligence feature needs to query board geometry by layer, net, and net class. Running Shapely operations from scratch every time is both slow and error-prone.

**Complexity:** HIGH

**Notes:** The existing `extract_all()` pipeline and `SpatialQueryEngine` provide 80% of this. The remaining 20% is: (a) layer stackup metadata (dielectric thickness, copper weight, epsilon_r), (b) net class geometry metadata (trace width, clearance, via drill per net), (c) copper zone connectivity graph, and (d) board outline as a Shapely Polygon rather than a bounding box.

**Key sub-features:**
- Layer-aware spatial indexing (query objects on specific copper layers)
- Net-class-tagged geometry (ask "what objects are on a HIGH_SPEED net?")
- Board outline polygon (not bounding box) for DFM and clearance calculations
- Copper zone connectivity (which zones connect to which nets, via thermal reliefs)
- Stackup metadata for impedance calculations (dielectric height between layers)

### TS-3: Constraint-Aware Component Placement

**Why expected:** The existing `HybridPlacementEngine` places components by connectivity (HPWL optimization). Users who provide schematic intelligence expect the placer to use it -- placing decoupling caps near IC power pins, keeping differential pair components aligned, respecting thermal keepouts.

**Complexity:** MEDIUM

**Notes:** The existing SA refinement in `placement/interactive.py` already accepts keepout zones and min_clearance. The extension adds constraint penalty terms to the SA objective function and pre-placement signal flow grouping from subcircuit data.

**Key sub-features:**
- Signal flow groups from subcircuit boundaries (input subcircuits first, output last)
- Decoupling cap proximity (caps placed within max_distance of their IC power pins)
- Differential pair component alignment (pair components placed at same Y for horizontal routing)
- Thermal-aware spacing (hot components get keepout margins)
- Constraint penalty terms in SA objective function

### TS-4: DRC Results with Fix Suggestions

**Why expected:** Running DRC and getting "clearance violation between pad U1.3 and trace on net GND" is useful. Getting "move U1 0.3mm to the right or reroute the GND trace around the pad" is transformative. Any "intelligent" DRC system should suggest fixes, not just report problems.

**Complexity:** MEDIUM

**Notes:** The existing `enrich_drc_result()` adds spatial coordinates and nearest-footprint context. The extension adds constraint-aware classification (is this a constraint violation, a manufacturing issue, or cosmetic?) and fix suggestion templates keyed by violation type and spatial context.

**Key sub-features:**
- Violation classification (constraint_violation vs manufacturing vs cosmetic)
- Fix suggestion templates (move component, increase clearance, add teardrop, resize pad)
- Constraint context (was this violating a propagated constraint?)
- Spatial proximity analysis (what else is nearby that constrains the fix?)

### TS-5: Manufacturing Readiness Checks (DFM)

**Why expected:** Running DRC catches electrical rule violations. But a board can pass DRC and still fail at the fab house due to annular ring minimums, solder mask slivers, thermal relief issues, or assembly problems. DFM is the "will this actually build?" check.

**Complexity:** MEDIUM

**Notes:** DFM checks use the same `DesignRule` ABC pattern as schematic design rules and the PCB spatial model for geometry queries. Each check is a pure function of the spatial model and a manufacturer capability profile.

**Key sub-features:**
- Annular ring adequacy (pad diameter vs drill diameter ratio)
- Minimum trace width and spacing verification
- Solder mask web/sliver minimums
- Thermal relief spoke width and air gap checks
- Panelization readiness (fiducials, tooling holes, board edge clearance)
- Assembly considerations (component spacing for pick-and-place)

### TS-6: Manufacturer Capability Profiles

**Why expected:** DFM rules vary between fabs. JLCPCB has different minimums than OSH Park. A DFM system that hardcodes one vendor's rules is wrong for all other vendors.

**Complexity:** LOW

**Notes:** A `ManufacturerProfile` dataclass with all relevant DFM parameters, loaded from YAML config files. Ship profiles for 3-5 common manufacturers. Default to a conservative "generic 2-layer" profile.

---

## Differentiators

Features that set kicad-agent apart from other EDA automation tools. Not expected by users, but they significantly raise the value ceiling.

### D-1: Constraint Propagation from Schematic Intent (Not Just Net Names)

**Value:** Most EDA tools propagate constraints from net names or manual net class assignment. kicad-agent propagates from inferred design intent -- the system knows a subcircuit is a "compressor VCA" because of the IC topology, and it knows the VCA control net is HIGH_SPEED because of the net classifier, and it propagates impedance constraints accordingly. No manual net class assignment required.

**Complexity:** HIGH (builds on TS-1)

**Notes:** The chain is: `IntentInferrer` -> `SubcircuitIntent.function` -> `NetClassifier.classify_signal_integrity()` per net -> `ConstraintTable.lookup()` -> `PCBConstraint`. This is deterministic, no LLM required. The key differentiator is that the constraint system consumes the *output* of the schematic intelligence pipeline, not just net name patterns.

### D-2: Signal Flow-Driven Placement Ordering

**Value:** Placement that respects the physical signal flow of the circuit. Input buffers placed near board edge, processing stages in the middle, output stages near the opposite edge. This matches how experienced engineers place components by hand.

**Complexity:** MEDIUM (builds on TS-3)

**Notes:** The `DesignIntent.signal_flow_description` already produces ordered signal flow chains ("Input -> Switch (SW1, SW2) -> VCA (U3) -> Output"). Signal flow groups translate this into placement zones on the board. Priority ordering ensures input subcircuits are placed before output subcircuits, so downstream components can be positioned relative to upstream ones.

### D-3: Impedance-Aware Constraint Validation

**Value:** Closed-form microstrip/stripline impedance calculations (Hammerstad-Jensen, IPC-2141) validate that the board stackup and trace geometry can achieve target impedance. This catches impedance mismatches before the board is manufactured, not after signal integrity testing fails.

**Complexity:** MEDIUM (builds on TS-2)

**Notes:** Impedance formulas are ~20 lines of Python each. Input: trace width, dielectric thickness, copper thickness, epsilon_r (all from layer stackup). Output: characteristic impedance. Compare against `ImpedanceConstraint.target_impedance_ohm`. Report deviation percentage. This runs as part of DRC intelligence, not as a separate simulation step.

### D-4: Multi-Stage DFM (Not Just Post-Layout)

**Value:** DFM checks run at three stages: (1) footprint audit before placement (pad geometry, land pattern compliance), (2) placement check during layout (component spacing for assembly), (3) post-route check after DRC (trace/drill constraints). This catches manufacturing issues early when they are cheap to fix.

**Complexity:** MEDIUM (builds on TS-5)

**Notes:** Most DFM tools run only after layout is complete. Multi-stage DFM requires the `DfmChecker` API to accept different inputs at each stage (footprint library only, spatial model without routes, full spatial model). Each stage runs a subset of DFM checks appropriate to the available data.

### D-5: Thermal Simulation with Graceful Degradation

**Value:** When `scikit-fem` is installed, thermal analysis runs a 2D finite element simulation on the PCB-shaped mesh. When it is not installed, thermal analysis degrades to a distance-based heuristic (inverse square law from power-dissipating components) that provides ~70% accuracy with zero additional dependencies. Users get thermal intelligence regardless of their install.

**Complexity:** HIGH (optional dependency, dual path)

**Notes:** The thermal system is opt-in because it requires user-provided power dissipation data per component (`ThermalProfile`). Without thermal profiles, placement falls back to connectivity-driven (existing behavior). This prevents the "looks thermal-aware but is actually random" pitfall.

### D-6: Constraint Coverage Reporting

**Value:** After DRC intelligence runs, the report includes a `constraint_coverage` dict showing which propagated constraints were checked and which were not. This gives the user confidence that their design intent was actually enforced on the PCB, not just propagated to a file.

**Complexity:** LOW

**Notes:** The `IntelligentDrcReport.constraint_coverage` maps each `PCBConstraint.constraint_id` to a boolean (checked or not). Unchecked constraints are flagged as warnings. This is a small feature with high trust value.

---

## Anti-Features

Features to explicitly NOT build. These would harm reliability, over-engineer the solution, or create maintenance burden disproportionate to their value.

### AF-1: Bidirectional Constraint Resolution

**Why avoid:** Allowing PCB constraints to feed back to schematic intent (e.g., "PCB can't achieve 50-ohm impedance, change the schematic net class") creates circular dependencies. The constraint system becomes a constraint solver, which is a fundamentally different and much more complex problem.

**What to do instead:** Constraint propagation is strictly unidirectional: Schematic -> PCB. If PCB analysis reveals issues, they are surfaced as *suggestions* (advisory), not *constraints* (enforced). The existing `DesignRuleReport` pattern handles this: check, report violations, suggest fixes. No feedback loop.

### AF-2: Full-Wave Electromagnetic Simulation

**Why avoid:** Running FDTD or FEM electromagnetic simulation for impedance validation is massive overkill. Closed-form microstrip/stripline formulas give < 5% error for standard stackups. Full-wave simulation adds a heavy dependency (openEMS), long runtimes, and complex meshing for marginal accuracy improvement.

**What to do instead:** Hammerstad-Jensen and IPC-2141 closed-form formulas. These are well-established in the PCB industry and sufficient for all but the highest-frequency designs (which are out of scope for v3.0).

### AF-3: Constraint Solver Library (z3, python-constraint)

**Why avoid:** The constraint propagation system is deterministic rule application (SignalIntegrity -> PCBConstraint lookup table), not combinatorial constraint satisfaction. Adding z3 (50MB+ binary) or python-constraint solves a problem we do not have. Our constraints are ordered rule chains, not SAT/SMT/CSP problems.

**What to do instead:** Python dict lookup with `networkx` DAG for dependency ordering. The existing `net_classifier.py` and `violation_classifier.py` already prove this pattern works.

### AF-4: Real-Time File Watching / Live PCB Editing

**Why avoid:** Watching the PCB file for changes and auto-updating the spatial model adds significant complexity (inotify/fsevents, debouncing, concurrent modification detection) for minimal benefit in the current use case (batch processing, CLI-driven workflows).

**What to do instead:** The PCB spatial model is rebuilt on demand via explicit `build()` call. The caller decides when to rebuild. This matches the existing `SpatialQueryEngine` pattern.

### AF-5: DFM Via Gerber File Manipulation

**Why avoid:** Generating or manipulating Gerber files programmatically requires a Gerber library (gdspy, gerber) and duplicates what `kicad-cli pcb export gerbers` already does. DFM checks should validate the Gerber output, not generate it.

**What to do instead:** DFM checks operate on the PCB spatial model (Shapely geometry), not on Gerber files. The spatial model provides all the geometry data needed for manufacturing checks. Export validation uses `kicad-cli` output.

### AF-6: 3D Model Analysis

**Why avoid:** 3D STEP model analysis (interference checking, thermal simulation in 3D) is explicitly out of scope. The spatial model is 2D (layer-aware but flat per layer). Adding 3D would require OpenCASCADE or cadquery and is a different product entirely.

**What to do instead:** All analysis operates on 2D per-layer geometry. Thermal simulation is 2D FEM on the PCB outline. Clearance checks are per-layer distance calculations.

### AF-7: Proprietary EDA Format Support

**Why avoid:** Supporting Altium, Cadence, or Eagle formats would massively expand scope. kicad-agent is KiCad 10+ only.

**What to do instead:** Focus exclusively on KiCad file formats. LTspice import already exists. No additional EDA format support needed.

---

## Feature Dependencies

### Internal Dependency Graph

```
Phase 45-48 (EXISTING: topology, subcircuits, intent, design rules)
    |
    v
TS-1: Constraint Propagation (Phase 50)
    |   depends on: CircuitTopology, Subcircuit[], NetClassifier, DesignIntent
    |   produces: PCBConstraint[]
    |
    v
TS-2: PCB Spatial Model (Phase 51)
    |   depends on: PcbIR, spatial/extractor.py, SpatialQueryEngine
    |   produces: PcbSpatialModel
    |   also consumes: PCBConstraint[] (optional, for net-class geometry)
    |
    +---------------------------+
    |                           |
    v                           v
TS-3: Layout-Aware Placement   TS-4: DRC Intelligence
(Phase 52)                     (Phase 53)
    |   depends on: TS-1 + TS-2    |   depends on: TS-1 + TS-2
    |   produces: PlacementOutput   |   produces: IntelligentDrcReport
    |                                |
    +------------+-------------------+
                 |
                 v
         TS-5 + TS-6: DFM (Phase 54)
             |   depends on: TS-2 (PcbSpatialModel)
             |   optionally consumes: TS-4 (DrcResult)
             |   produces: DfmReport
```

### Parallelism

- **Phase 50 (Constraints) and Phase 51 (Spatial Model) can run in parallel** -- they have no dependency on each other. Constraints consume schematic data; spatial model consumes PCB data.
- **Phase 52 (Placement), Phase 53 (DRC Intel), Phase 54 (DFM) can all run in parallel** once Phases 50+51 complete, because they consume the same inputs but produce independent outputs.

### External Dependencies

| Dependency | Type | Status | Notes |
|------------|------|--------|-------|
| `shapely` 2.1.1 | Python package | Installed | STRtree, geometry primitives, all spatial queries |
| `networkx` 3.6.1 | Python package | Installed | Constraint dependency graph, net connectivity |
| `scipy` >=1.11 | Python package | Installed (undeclared) | Must promote to explicit. KDTree, linprog, cdist |
| `scikit-fem` >=10.0 | Python package | NOT installed | Optional `eda` extra for thermal FEM |
| `sexpdata` 1.0.0 | Python package | Installed | For `.kicad_dru` parser |
| `kiutils` >=1.4.8 | Python package | Installed | PCB/Schematic parsing (gap: no .kicad_dru) |
| `pydantic` 2.12.5 | Python package | Installed | All new schema types |
| `numpy` 1.26.4 | Python package | Installed | Coordinate arrays, impedance formulas |
| `kicad-cli` 10.0.1 | External binary | Installed | DRC execution, Gerber export |

---

## MVP Recommendation

### Phase 50: Constraint Propagation (Must-Have First)

The constraint propagation layer is the keystone. Without it, none of the downstream features have access to schematic intent.

| Feature | Sub-Feature | Est. Effort |
|---------|-------------|-------------|
| TS-1: Constraint Propagation | PCBConstraint type hierarchy | 1-2 days |
| | ConstraintTable (SignalIntegrity -> PcbConstraint) | 1 day |
| | Differential pair extraction | 1 day |
| | Power net clearance/decoupling | 1 day |
| | Impedance target assignment | 1 day |
| | Thermal keepout extraction | 0.5 day |
| | Signal flow group identification | 0.5 day |
| | `.kicad_dru` parser (sexpdata) | 1-2 days |

**Total: 7-9 days**

### Phase 51: PCB Spatial Model (Must-Have Second)

The spatial model provides the query infrastructure that placement, DRC intelligence, and DFM all need.

| Feature | Sub-Feature | Est. Effort |
|---------|-------------|-------------|
| TS-2: PCB Spatial Model | PcbSpatialModel class | 2-3 days |
| | LayerStackup metadata | 1 day |
| | Net-class geometry enrichment | 1 day |
| | Board outline polygon | 1 day |
| | Copper zone connectivity graph | 1-2 days |
| | LayerClassifier utility | 0.5 day |

**Total: 6-8 days**

### Phase 52: Layout-Aware Placement (Parallel with 53, 54)

| Feature | Sub-Feature | Est. Effort |
|---------|-------------|-------------|
| TS-3: Constraint-Aware Placement | SignalFlowGrouper | 1-2 days |
| | Decoupling cap proximity | 1 day |
| | Diff pair alignment | 1 day |
| | Thermal spacing | 1 day |
| | SA constraint penalty terms | 1-2 days |
| | Real footprint bounding boxes | 1 day |

**Total: 6-8 days**

### Phase 53: DRC Intelligence (Parallel with 52, 54)

| Feature | Sub-Feature | Est. Effort |
|---------|-------------|-------------|
| TS-4: DRC with Fix Suggestions | Violation classification | 1 day |
| | FixSuggester templates | 2-3 days |
| | Constraint context integration | 1 day |
| D-3: Impedance validation | Microstrip/stripline formulas | 1-2 days |
| D-6: Constraint coverage | Coverage reporting | 0.5 day |

**Total: 5-7 days**

### Phase 54: DFM (Parallel with 52, 53)

| Feature | Sub-Feature | Est. Effort |
|---------|-------------|-------------|
| TS-5: DFM Checks | Annular ring checks | 1 day |
| | Solder mask checks | 1 day |
| | Thermal relief checks | 1 day |
| | Trace width/spacing checks | 0.5 day |
| | Assembly checks | 1 day |
| | Panelization scoring | 1 day |
| TS-6: Manufacturer Profiles | Profile dataclass + YAML loading | 1 day |
| | Ship 3-5 vendor profiles | 0.5 day |
| D-4: Multi-stage DFM | Footprint audit stage | 1 day |
| | Placement check stage | 1 day |

**Total: 8-10 days**

### Deferred

| Feature | Reason |
|---------|--------|
| Bidirectional constraint resolution (AF-1) | Unidirectional is sufficient; bidirectional creates solver-level complexity |
| Thermal FEM simulation (D-5, full) | Distance heuristic is adequate for most boards; FEM is opt-in `eda` extra |
| Signal flow visualization | SVG renderer already exists; signal flow overlay can be added later without architecture changes |
| Custom constraint authoring API | Users can edit the YAML constraint config; a programmatic API adds complexity for minimal benefit |
| Integration with external SI/PI tools | Out of scope for v3.0; closed-form impedance is sufficient |

---

## Sources

- Codebase: `analysis/topology_graph.py` -- CircuitTopology, TopologyNode, TopologyEdge, NetClassification, PinRole
- Codebase: `analysis/net_classifier.py` -- NetClassifier, SignalIntegrity, NetImportance, ordered classification rules
- Codebase: `analysis/intent_schemas.py` -- DesignIntent, SubcircuitIntent, DesignGoal
- Codebase: `analysis/intent_inference.py` -- IntentInferrer, InferenceResult, signal flow templates
- Codebase: `analysis/subcircuit_detector.py` -- SubcircuitDetector, Subcircuit, SubcircuitType
- Codebase: `analysis/design_rules.py` -- DesignRule ABC, DesignRuleViolation, DesignRuleReport, RuleSeverity, RuleCategory
- Codebase: `analysis/design_rule_engine.py` -- DesignRuleEngine orchestrator with error handling, severity sorting
- Codebase: `analysis/feature_extraction.py` -- SubcircuitFeatures, extract_features (ML-ready feature vectors)
- Codebase: `spatial/primitives.py` -- SpatialPoint, SpatialBox, SpatialPath, SpatialRegion with to_shapely()
- Codebase: `spatial/extractor.py` -- extract_all() pipeline from PcbIR to spatial primitives
- Codebase: `spatial/query.py` -- SpatialQueryEngine with STRtree
- Codebase: `ir/pcb_ir.py` -- PcbIR, board access, footprint/net/trace queries, UUID map
- Codebase: `placement/engine.py` -- HybridPlacementEngine, PlacementRequest, PlacementOutput
- Codebase: `placement/interactive.py` -- ConstraintSet, SA refinement via scipy.optimize.dual_annealing
- Codebase: `placement/scoring.py` -- PlacementScore, compute_hpwl_score()
- Codebase: `placement/validation.py` -- PlacementValidator, SpatialQueryEngine STRtree clearance queries
- Codebase: `validation/erc_drc.py` -- Violation, ErcResult, DrcResult, run_drc()
- Codebase: `validation/spatial_drc.py` -- SpatialViolation, enrich_drc_result()
- KiCad format: NETCLASS properties (clearance, trace_width, via_dia, via_drill, diff_pair_width/gap/via_gap) -- verified via Context7
- KiCad format: Custom DRC rules API (get_custom_design_rules, MinimumConstraints) -- verified via Context7 kicad-source-mirror
- KiCad format: Board stackup (epsilon_r, loss_tangent, thickness, material per layer) -- verified via Context7
- KiCad format: Zone thermal parameters (thermal_bridge_width, thermal_gap, fill) -- verified via Context7
- Shapely 2.1.1: STRtree spatial indexing, buffer, polygon, intersection, nearest_points -- verified via Context7
- scipy: dual_annealing, KDTree, linprog, cdist -- verified via Context7

---
*Feature landscape research for: kicad-agent milestone v3.0-full-stack-eda*
*Researched: 2026-06-01*
*Confidence: HIGH*
