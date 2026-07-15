# Architecture: Full-Stack EDA Integration Layer

**Domain:** Extending volta's schematic intelligence to PCB layout with constraint propagation, spatial modeling, layout-aware placement, DRC intelligence, and DFM.
**Researched:** 2026-06-01
**Confidence:** HIGH (direct codebase analysis of 15+ source files, existing patterns well established)

## Executive Summary

The volta codebase has a clean, layered architecture with clear integration points for extending schematic intelligence into the PCB domain. The key insight is that the infrastructure already exists -- PcbIR, spatial primitives, SpatialQueryEngine, placement engine with SA refinement, and DRC result parsing -- but it operates in isolation from the schematic analysis layer. The five new feature areas (constraint propagation, PCB spatial model, layout-aware placement, DRC intelligence, DFM) are not five separate modules to bolt on; they form a **pipeline** that bridges `analysis/` outputs through `ir/pcb_ir.py` to `validation/` and `placement/`.

The recommended architecture introduces four new modules inside `src/volta/` and extends three existing ones. The constraint propagation layer is the keystone -- it sits between `analysis/topology_graph.py` and `placement/engine.py`, translating schematic intent into PCB constraints. The PCB spatial model extends the existing `spatial/extractor.py` with net-class-aware geometry, copper zone topology, and layer stackup metadata. DRC intelligence wraps the existing `validation/erc_drc.py` DrcResult with spatial enrichment and fix-suggestion logic. DFM is a new module that parallels `analysis/builtin_rules.py` but operates on PCB data rather than schematic topology.

The build order is dictated by data dependencies: PCB spatial model first (everything else queries it), then constraint propagation (consumes topology, produces constraints), then layout-aware placement (consumes constraints), then DRC intelligence (consumes spatial data), and finally DFM (consumes spatial data and DRC results).

## Existing Architecture (Dependency Map)

The current codebase has this data flow for schematic intelligence:

```
.kicad_sch file
    |
    v
parser/ (kiutils S-expression parsing)
    |
    v
ir/schematic_ir.py (BaseIR subclass, mutation tracking)
    |
    +---> analysis/topology_graph.py (CircuitTopology: nodes, edges, signal flow)
    |         |
    |         +---> analysis/subcircuit_detector.py (Subcircuit clustering)
    |         +---> analysis/design_rule_engine.py (DesignRule ABC, pluggable rules)
    |         +---> analysis/builtin_rules.py (8 analog domain rules)
    |
    +---> analysis/schematic_spatial.py (SchematicSpatialExtractor -> SpatialBox)
    |
    +---> ops/executor.py (Operation dispatch, Transaction wrapping)
              |
              v
         serializer/ (kiutils -> .kicad_sch)
              |
              v
         validation/erc_drc.py (kicad-cli ERC wrapper)
```

And for PCB, the existing data flow is simpler:

```
.kicad_pcb file
    |
    v
parser/ (kiutils Board parsing + UUID extraction)
    |
    v
ir/pcb_ir.py (BaseIR subclass, UUID map, net/footprint mutation)
    |
    +---> spatial/extractor.py (PcbIR -> SpatialPoint/Box/Path/Region)
    |         |
    |         +---> spatial/query.py (SpatialQueryEngine, Shapely STRtree)
    |
    +---> ops/executor.py (PCB handler registry)
    |
    +---> placement/engine.py (HybridPlacementEngine, ML + rule-based)
              |
              +---> placement/interactive.py (ConstraintSet, SA refinement)
              +---> placement/scoring.py (HPWL, congestion)
              +---> placement/validation.py (overlap, clearance checks)
```

**The gap:** There is no data path from `analysis/` to `placement/` or `validation/`. Schematic intelligence (topology, subcircuits, design rules) stops at the schematic boundary. PCB placement and DRC are "dumb" -- they do not consume schematic intent.

## New Architecture: Full-Stack EDA Pipeline

### Overview Diagram

```
                    SCHEMATIC INTELLIGENCE (exists)
                    =============================
.kicad_sch --> parser/ --> ir/schematic_ir.py
                                |
                 +--------------+----------------+
                 |              |                |
          topology_graph  subcircuit_det  design_rule_engine
                 |              |                |
                 v              v                v
          CircuitTopology  Subcircuit[]   DesignRuleReport
                 |              |                |
                 +------+-------+----------------+
                        |
                        v
              +-------------------+
              | CONSTRAINT PROP   |  <-- NEW MODULE
              | constraints/      |
              +-------------------+
                        |
                  PCBConstraint[]  (differential pairs, impedance, clearance,
                                     thermal, decoupling, signal flow groups)
                        |
                        v
              +-------------------+
              | PCB SPATIAL MODEL |  <-- EXTENDS spatial/
              | spatial/pcb.py    |
              +-------------------+
                        |
                  PcbSpatialModel  (net-class geometry, layer stackup, copper zones)
                        |
             +----------+----------+
             |                     |
    +--------v--------+  +--------v--------+
    | LAYOUT-AWARE    |  | DRC INTELLIGENCE|  <-- EXTENDS validation/
    | PLACEMENT       |  | validation/     |
    | placement/      |  | drc_intel.py    |
    | (EXTENDED)      |  +-----------------+
    +--------+--------+           |
             |                    v
             |           IntelligentDrcReport (spatial + fix suggestions)
             |                    |
             v                    v
    +-----------------------------+
    | DFM                          |  <-- NEW MODULE
    | dfm/                         |
    +-----------------------------+
```

### Component Boundaries

| Component | Location (new/modified) | Responsibility | Consumes From | Produces For |
|-----------|------------------------|----------------|---------------|-------------|
| ConstraintPropagator | `constraints/` (NEW) | Translate schematic intent into PCB design constraints | CircuitTopology, Subcircuit[], DesignRuleReport, SchematicIR | PCBConstraint[] -> placement, validation |
| PcbSpatialModel | `spatial/pcb_model.py` (NEW) | Rich spatial representation with net classes, layer stackup, copper topology | PcbIR, spatial/extractor.py primitives | PcbSpatialModel -> placement, DRC intel, DFM |
| LayoutAwarePlacer | `placement/layout_aware.py` (NEW) | Signal-flow-driven, thermal-aware, decoupling-cap-aware placement | PcbSpatialModel, PCBConstraint[], PlacementGraph | PlacementOutput -> HybridPlacementEngine |
| IntelligentDrcAnalyzer | `validation/drc_intel.py` (NEW) | Spatial violation enrichment, fix suggestion, SI/PI checks | DrcResult, PcbSpatialModel, PCBConstraint[] | IntelligentDrcReport -> ops executor, CLI |
| DfmChecker | `dfm/` (NEW) | Manufacturing readiness checks | PcbSpatialModel, DrcResult | DfmReport -> CLI, ops executor |

### Data Flow: End-to-End

The full pipeline for a typical "schematic-to-PCB" workflow:

```
1. Parse schematic -> SchematicIR
2. Build topology -> CircuitTopology
3. Detect subcircuits -> Subcircuit[]
4. Run design rules -> DesignRuleReport
5. Propagate constraints -> PCBConstraint[]
    - Diff pair nets -> diff pair constraints (gap, length matching)
    - Power nets -> clearance constraints, decoupling cap proximity
    - High-speed nets -> impedance constraints, length limits
    - Thermal components -> keepout constraints, thermal pad spacing
6. Parse PCB -> PcbIR
7. Build PCB spatial model -> PcbSpatialModel
    - Enrich spatial primitives with net class metadata
    - Add layer stackup info (dielectric thickness, copper weight)
    - Build copper zone connectivity graph
8. Layout-aware placement -> PlacementOutput
    - Signal flow groups (from Subcircuit) placed contiguously
    - Decoupling caps placed adjacent to IC power pins
    - Thermal components get clearance margins
    - Differential pair components aligned
9. Run kicad-cli DRC -> DrcResult
10. Enrich DRC with spatial intelligence -> IntelligentDrcReport
    - Map violations to spatial coordinates
    - Suggest fixes based on constraint context
    - Classify: constraint violation vs manufacturing issue vs cosmetic
11. Run DFM checks -> DfmReport
    - Annular ring adequacy
    - Solder mask web minimum
    - Thermal relief on copper zones
    - Panelization score
```

## Module Design Details

### 1. Constraint Propagation Layer (`constraints/`)

**New module.** This is the bridge between schematic intelligence and PCB layout.

```
src/volta/constraints/
    __init__.py
    types.py           # PCBConstraint frozen dataclass hierarchy
    propagator.py       # ConstraintPropagator orchestrator
    diff_pair.py        # Differential pair constraint extraction
    power.py            # Power net clearance/decoupling constraints
    impedance.py        # Impedance constraint extraction
    thermal.py          # Thermal keepout/spacing constraints
    signal_flow.py      # Signal flow group constraints
    config.py           # YAML-loadable constraint defaults
```

**Pattern to follow:** Mirrors `analysis/design_rule_engine.py` structure (orchestrator + individual rule files) but produces constraints instead of violations.

**Key types (in `constraints/types.py`):**

```python
@dataclass(frozen=True)
class PCBConstraint:
    """Base constraint: something the PCB layout must satisfy."""
    constraint_id: str           # "DIFF_001", "PWR_003"
    constraint_type: str         # "differential_pair", "clearance", "impedance", "thermal"
    severity: ConstraintSeverity  # REQUIRED, RECOMMENDED, ADVISORY
    source_refs: tuple[str, ...] # Component references that generated this constraint
    net_names: tuple[str, ...]   # Affected nets
    description: str

@dataclass(frozen=True)
class DifferentialPairConstraint(PCBConstraint):
    gap_mm: float                # Required gap between pair traces
    max_length_mismatch_mm: float # Max allowed length difference
    impedance_ohm: float         # Target differential impedance

@dataclass(frozen=True)
class ClearanceConstraint(PCBConstraint):
    min_clearance_mm: float
    layer_restriction: tuple[str, ...]  # Empty = all layers
    reason: str                  # "creepage", "clearance", "manufacturing"

@dataclass(frozen=True)
class ImpedanceConstraint(PCBConstraint):
    target_impedance_ohm: float
    max_deviation_percent: float
    reference_layer: str         # Reference plane layer name

@dataclass(frozen=True)
class DecouplingConstraint(PCBConstraint):
    ic_ref: str                  # IC requiring decoupling
    max_distance_mm: float       # Max distance from IC power pin to cap
    required_capacitance: str    # e.g. "100nF"

@dataclass(frozen=True)
class ThermalConstraint(PCBConstraint):
    component_ref: str
    keepout_margin_mm: float
    thermal_pad_required: bool
```

**Integration with existing code:**

- `ConstraintPropagator.__init__()` accepts `CircuitTopology`, `list[Subcircuit]`, `DesignRuleReport`
- `ConstraintPropagator.propagate() -> list[PCBConstraint]` runs each constraint extractor
- Each extractor is a plain function: `(topology, config) -> list[PCBConstraint]`
- Config loaded from YAML (mirrors `analysis/rule_config.py` pattern)
- Constraint IDs follow `analysis/builtin_rules.py` pattern: `DIFF_01`, `PWR_01`, `IMP_01`, `THM_01`

**Why new module, not extend `analysis/`:** The `analysis/` module operates on schematic data (CircuitTopology, SchematicIR). Constraints are PCB-oriented artifacts. Mixing them would violate the single-responsibility separation between "understand the schematic" and "constrain the PCB." The constraint propagator is a *consumer* of analysis outputs, not an analyzer itself.

### 2. PCB Spatial Model (`spatial/pcb_model.py`)

**New file in existing `spatial/` module.** Extends the existing `extractor.py` primitives with net-class awareness, layer stackup, and copper connectivity.

```
src/volta/spatial/
    (existing files unchanged)
    pcb_model.py       # PcbSpatialModel: enriched spatial representation
    layer_stackup.py    # LayerStackup: dielectric/copper layer metadata
    copper_graph.py     # CopperConnectivityGraph: zone-to-zone connectivity
```

**Key types:**

```python
@dataclass(frozen=True)
class LayerStackup:
    """PCB layer stackup metadata for impedance and clearance calculations."""
    layers: tuple[StackupLayer, ...]
    total_thickness_mm: float
    copper_layers: tuple[str, ...]   # e.g. ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")

@dataclass(frozen=True)
class StackupLayer:
    name: str           # "F.Cu", "In1.Cu", "Core", "Prepreg"
    type: str           # "copper", "dielectric"
    thickness_mm: float
    copper_weight_oz: float  # 0 for dielectric layers
    dielectric_constant: float  # 4.5 for FR4 default

@dataclass(frozen=True)
class NetClassGeometry:
    """Spatial geometry metadata for a net class."""
    net_class_name: str
    trace_width_mm: float
    clearance_mm: float
    via_drill_mm: float
    via_diameter_mm: float
    diff_pair_gap_mm: float  # 0 for non-diff-pair classes
    nets: tuple[str, ...]

class PcbSpatialModel:
    """Rich PCB spatial representation built from PcbIR + net class metadata.

    Wraps the existing extract_all() primitives and adds:
    - Net class geometry constraints per net
    - Layer stackup information
    - Copper zone connectivity graph
    - Board outline polygon (Shapely)
    """
    def __init__(self, pcb_ir: PcbIR, constraints: list[PCBConstraint] | None = None):
        self._pcb_ir = pcb_ir
        self._primitives = extract_all(pcb_ir)
        self._constraints = constraints or []
        self._net_classes = self._extract_net_classes(pcb_ir)
        self._stackup = self._infer_stackup(pcb_ir)
        self._outline = self._build_outline(pcb_ir)
        self._query_engine = SpatialQueryEngine(
            self._primitives["points"] + self._primitives["boxes"]
        )

    @property
    def query_engine(self) -> SpatialQueryEngine:
        """Access the spatial query engine for proximity/containment/clearance queries."""
        return self._query_engine

    def get_net_geometry(self, net_name: str) -> NetClassGeometry | None:
        """Get geometry constraints for a specific net."""
        ...

    def get_component_clearance(self, ref: str) -> float:
        """Get the minimum required clearance for a component's nets."""
        ...

    def get_diff_pair_nets(self) -> list[tuple[str, str]]:
        """Find all differential pair net tuples."""
        ...
```

**Why extend `spatial/` rather than new module:** The `PcbSpatialModel` is a composition of existing `SpatialPoint/Box/Path/Region` primitives plus metadata. It is the natural evolution of `extract_all()` into a richer queryable model. Creating a separate module would duplicate the primitive types and lose the STRtree query infrastructure.

**Integration with existing code:**

- Consumes `PcbIR` (from `ir/pcb_ir.py`)
- Consumes `extract_all()` (from `spatial/extractor.py`)
- Consumes `SpatialQueryEngine` (from `spatial/query.py`)
- Consumes `PCBConstraint[]` (from `constraints/`) -- optional, for net-class-aware geometry
- Exposes `PcbSpatialModel` to `placement/`, `validation/`, and `dfm/`

**Why `PcbSpatialModel` is not an IR subclass:** Unlike `SchematicIR` and `PcbIR`, the spatial model is a **derived read-only view**. It does not track mutations or have a `dirty` flag. It is built from a `PcbIR` snapshot and becomes stale if the PCB is mutated. This is intentional -- the spatial model is a query layer, not an editing layer. If the PCB changes, you rebuild the spatial model.

### 3. Layout-Aware Placement (`placement/layout_aware.py`)

**New file in existing `placement/` module.** Extends `HybridPlacementEngine` with constraint-driven placement.

```
src/volta/placement/
    (existing files unchanged)
    layout_aware.py    # LayoutAwarePlacer: constraint-driven placement
    signal_flow.py     # SignalFlowGrouper: groups components by subcircuit
    thermal.py         # ThermalPlacer: thermal-aware component spacing
```

**Pattern to follow:** Mirrors `placement/engine.py` -- new placer class that produces `PlacementOutput`.

**Key types:**

```python
@dataclass(frozen=True)
class SignalFlowGroup:
    """Components that should be placed contiguously based on signal flow."""
    group_id: str
    component_refs: tuple[str, ...]
    input_ref: str        # Component closest to signal input
    output_ref: str       # Component closest to signal output
    subcircuit_type: str  # From SubcircuitType enum
    priority: int         # Placement priority (higher = placed first)

class LayoutAwarePlacer:
    """Constraint-driven placement that incorporates schematic intelligence.

    Wraps HybridPlacementEngine with pre-placement constraint analysis
    and post-placement constraint validation.

    Decision logic:
    1. Group components into SignalFlowGroups from subcircuit data
    2. Compute placement zones from board outline minus keepout constraints
    3. Place groups in priority order (input->output signal flow)
    4. Apply decoupling cap proximity constraints
    5. Apply differential pair alignment constraints
    6. Run SA refinement with constraint-aware objective
    7. Validate against all constraints
    """
    def __init__(self, spatial_model: PcbSpatialModel, constraints: list[PCBConstraint]):
        self._model = spatial_model
        self._constraints = constraints
        self._base_engine = HybridPlacementEngine()

    def place(self, request: PlacementRequest) -> PlacementOutput:
        """Execute constraint-aware placement.

        Wraps HybridPlacementEngine.place() with:
        - Pre-placement: add keepout zones from thermal constraints
        - During placement: SA objective includes constraint penalties
        - Post-placement: validate against constraint requirements
        """
        ...
```

**Integration with existing code:**

- Extends `placement/engine.py` (`HybridPlacementEngine` used as inner delegate)
- Consumes `PcbSpatialModel` (from `spatial/pcb_model.py`)
- Consumes `PCBConstraint[]` (from `constraints/`)
- Consumes `Subcircuit[]` (from `analysis/subcircuit_detector.py`) for signal flow grouping
- Produces `PlacementOutput` (existing Pydantic model) -- no schema changes needed
- Adds constraint penalty terms to SA objective in `placement/interactive.py`

**Why extend placement, not new module:** The layout-aware placer is a *strategy* within the existing placement architecture, not a separate concern. It reuses `PlacementGraph`, `PlacementValidator`, `PlacementScorer`, and the SA refinement from `placement/interactive.py`. The existing `HybridPlacementEngine.place()` method is the extension point -- layout-aware placement is a new branch in its decision logic, alongside ML prediction and rule-based fallback.

### 4. DRC Intelligence (`validation/drc_intel.py`)

**New file in existing `validation/` module.** Enriches kicad-cli DRC results with spatial context and fix suggestions.

```
src/volta/validation/
    (existing files unchanged)
    drc_intel.py       # IntelligentDrcAnalyzer: spatial enrichment + fix suggestions
    fix_suggest.py     # FixSuggester: generate actionable fix recommendations
```

**Pattern to follow:** Mirrors `validation/spatial_drc.py` (`enrich_drc_result`) but adds constraint-aware fix suggestions.

**Key types:**

```python
@dataclass(frozen=True)
class SpatialFixSuggestion:
    """Actionable fix suggestion for a DRC violation."""
    fix_type: str          # "move_component", "increase_clearance", "add_teardrop", "resize_pad"
    description: str
    affected_refs: tuple[str, ...]
    suggested_action: dict  # Type-specific action parameters
    confidence: float      # 0.0 - 1.0
    rationale: str

@dataclass(frozen=True)
class EnrichedViolation:
    """DRC violation with spatial context and fix suggestions."""
    violation: Violation                    # From erc_drc.py
    spatial_items: tuple[SpatialPoint, ...] # Coordinate-grounded items
    constraint: PCBConstraint | None        # Related constraint, if any
    fixes: tuple[SpatialFixSuggestion, ...]
    classification: str                     # "constraint_violation", "manufacturing", "cosmetic"

@dataclass(frozen=True)
class IntelligentDrcReport:
    """DRC report enriched with spatial intelligence and fix suggestions."""
    drc_result: DrcResult                       # Original kicad-cli result
    enriched_violations: tuple[EnrichedViolation, ...]
    constraint_coverage: dict[str, bool]        # Which constraints were checked
    summary: dict[str, int]                     # Classification counts
```

**Integration with existing code:**

- Consumes `DrcResult` (from `validation/erc_drc.py`) -- no changes to erc_drc.py
- Consumes `PcbSpatialModel` (from `spatial/pcb_model.py`) for spatial context
- Consumes `PCBConstraint[]` (from `constraints/`) for constraint-aware classification
- Consumes `SpatialViolation` (from `validation/spatial_drc.py`) as intermediate format
- Produces `IntelligentDrcReport` for CLI, MCP server, and ops executor

**Why new file in validation, not extend erc_drc.py:** The existing `run_drc()` function is a thin kicad-cli wrapper that returns raw results. DRC intelligence is a *post-processing* step that enriches those results. Keeping them separate preserves the existing `run_drc()` API (which many callers use) and allows DRC intelligence to be optional -- you can run plain DRC without the spatial model if you don't need fix suggestions.

### 5. DFM (`dfm/`)

**New module.** Manufacturing readiness checks that go beyond DRC.

```
src/volta/dfm/
    __init__.py
    types.py           # DfmViolation, DfmReport frozen dataclasses
    checker.py          # DfmChecker orchestrator
    annular_ring.py     # Annular ring adequacy checks
    solder_mask.py      # Solder mask web/slake checks
    thermal_relief.py   # Thermal relief on copper zone pads
    panelization.py     # Panelization readiness scoring
    assembly.py         # Assembly consideration checks (fiducials, tooling holes)
    config.py           # Manufacturer-specific capability profiles
```

**Pattern to follow:** Mirrors `analysis/design_rule_engine.py` (orchestrator + individual check files + config) and `analysis/design_rules.py` (ABC base class).

**Key types:**

```python
@dataclass(frozen=True)
class DfmViolation:
    """A manufacturing readiness issue."""
    check_id: str            # "ANNULAR_01", "SMASK_01", "THERMAL_01"
    severity: DfmSeverity    # CRITICAL, WARNING, INFO
    description: str
    location: str            # Reference or coordinates
    affected_refs: tuple[str, ...]
    suggestion: str
    manufacturer_note: str   # Human-readable explanation for specific manufacturer

class DfmCheck(ABC):
    """ABC for DFM checks, mirrors DesignRule ABC."""
    check_id: str
    description: str

    @abstractmethod
    def check(self, spatial_model: PcbSpatialModel, config: dict | None = None) -> list[DfmViolation]:
        ...

@dataclass(frozen=True)
class DfmReport:
    """Aggregated DFM check report."""
    violations: tuple[DfmViolation, ...]
    checks_run: int
    checks_passed: int
    checks_failed: int
    manufacturer_profile: str   # "jlcpcb_standard", "pcbway_standard", "custom"
    manufacturability_score: float  # 0.0 - 1.0
    summary: dict[str, int]

@dataclass(frozen=True)
class ManufacturerProfile:
    """Manufacturer capability profile loaded from YAML."""
    name: str
    min_annular_ring_mm: float
    min_solder_mask_sliver_mm: float
    min_trace_width_mm: float
    min_via_drill_mm: float
    min_clearance_mm: float
    copper_weights: tuple[float, ...]  # Available copper weights in oz
    max_layers: int
```

**Integration with existing code:**

- Consumes `PcbSpatialModel` (from `spatial/pcb_model.py`) for all spatial queries
- Consumes `DrcResult` (from `validation/erc_drc.py`) to avoid duplicating DRC checks
- Does NOT consume `PCBConstraint[]` -- DFM is manufacturing-focused, not design-intent-focused
- Produces `DfmReport` for CLI, MCP server
- `DfmCheck` ABC mirrors `DesignRule` ABC from `analysis/design_rules.py`

**Why new module, not extend `validation/`:** DFM checks are categorically different from DRC. DRC answers "does this board violate electrical/manufacturing rules?" DFM answers "how easy is this board to manufacture at a specific fab?" They have different inputs (DFM needs manufacturer profiles), different outputs (DFM produces a manufacturability score), and different lifecycles (DFM runs as a final check before export, not after every edit). Mixing them in `validation/` would blur the boundary between correctness checks and manufacturability assessment.

## Patterns to Follow

### Pattern 1: Frozen Dataclass Results (HIGH confidence)

Every module produces frozen dataclass result types. This is the established pattern across the entire codebase.

**Existing examples:** `Violation`, `ErcResult`, `DrcResult`, `TopologyNode`, `TopologyEdge`, `Subcircuit`, `SpatialViolation`, `PlacementOutput`

**New modules follow:** `PCBConstraint`, `EnrichedViolation`, `IntelligentDrcReport`, `DfmViolation`, `DfmReport`, `NetClassGeometry`, `SignalFlowGroup`

### Pattern 2: Pydantic Models for External Interfaces (HIGH confidence)

Pydantic BaseModel is used for validated input/output at API boundaries (ops executor, CLI, MCP).

**Existing examples:** `Operation`, `PlacementRequest`, `PlacementOutput`, `DesignRuleViolation`, `DesignRuleReport`

**New modules follow:** `ManufacturerProfile` (loaded from YAML), `LayoutAwarePlacer.place()` accepts existing `PlacementRequest`, produces existing `PlacementOutput`

### Pattern 3: ABC + Registry for Extensibility (HIGH confidence)

Pluggable components use an ABC base class with a registry/discovery pattern.

**Existing examples:** `DesignRule` ABC with `DesignRuleEngine` orchestrator, `register_schematic()`/`register_pcb()` decorators in `ops/executor.py`

**New modules follow:** `DfmCheck` ABC with `DfmChecker` orchestrator. Constraint extractors are plain functions (not ABC) because they are simpler -- they have no per-instance configuration beyond the global config.

### Pattern 4: Lazy Imports for Heavy Dependencies (HIGH confidence)

Heavy dependencies (shapely, numpy, scipy, torch) are imported lazily inside methods, not at module level.

**Existing examples:** `spatial/primitives.py` imports shapely in `to_shapely()`, `placement/engine.py` tries torch import in `__init__`

**New modules follow:** `spatial/pcb_model.py` imports shapely lazily in methods, `dfm/checker.py` does lazy numpy imports

## Anti-Patterns to Avoid

### Anti-Pattern 1: PcbSpatialModel as IR Subclass

**What:** Making PcbSpatialModel inherit from BaseIR.
**Why bad:** BaseIR enforces one-instance-per-ParseResult, tracks mutations, and manages a dirty flag. The spatial model is a derived read-only view that should be cheaply rebuildable. If it inherits BaseIR, creating a new spatial model would fail when the PcbIR already has the ParseResult registered.
**Instead:** PcbSpatialModel is a standalone class that holds a reference to PcbIR but does not subclass BaseIR. It is rebuilt when the PCB changes.

### Anti-Pattern 2: Constraints Module Consuming PcbIR

**What:** Having `constraints/propagator.py` read PcbIR directly.
**Why bad:** Constraints are derived from schematic intelligence, not PCB state. If the propagator reads PcbIR, it creates a circular dependency: schematic analysis -> constraints -> PCB placement -> PCB changes -> re-read PcbIR -> constraints change. The constraint propagator must be a pure function of schematic analysis outputs.
**Instead:** `ConstraintPropagator` accepts only `CircuitTopology`, `list[Subcircuit]`, `DesignRuleReport`, and optional config. No PcbIR, no PcbSpatialModel.

### Anti-Pattern 3: DFM Calling kicad-cli

**What:** Running `kicad-cli pcb drc` inside DFM checks.
**Why bad:** DRC is already run by the validation pipeline. Running it again inside DFM would double the wall-clock time and create duplicate results.
**Instead:** DFM checks consume the existing `DrcResult` and `PcbSpatialModel`. They add checks that kicad-cli does not perform (annular ring ratios, solder mask webs, thermal relief adequacy, panelization scoring).

### Anti-Pattern 4: Modifying Existing Base Classes

**What:** Adding PCB spatial methods to `PcbIR` or `BaseIR`.
**Why bad:** The IR layer is for AST mutation and serialization. Spatial analysis is a derived computation. Mixing them bloats the IR and creates tight coupling between parsing and analysis.
**Instead:** Spatial methods live in `spatial/pcb_model.py`, which is a separate class that *wraps* PcbIR.

## File Inventory: New vs Modified

### New Files

| File | Lines (est.) | Module | Purpose |
|------|-------------|--------|---------|
| `constraints/__init__.py` | 20 | constraints | Module init, public API |
| `constraints/types.py` | 120 | constraints | PCBConstraint hierarchy, frozen dataclasses |
| `constraints/propagator.py` | 80 | constraints | ConstraintPropagator orchestrator |
| `constraints/diff_pair.py` | 100 | constraints | Differential pair constraint extraction |
| `constraints/power.py` | 100 | constraints | Power net clearance/decoupling constraints |
| `constraints/impedance.py` | 80 | constraints | Impedance constraint extraction |
| `constraints/thermal.py` | 80 | constraints | Thermal keepout/spacing constraints |
| `constraints/signal_flow.py` | 90 | constraints | Signal flow group constraints |
| `constraints/config.py` | 60 | constraints | YAML-loadable constraint defaults |
| `spatial/pcb_model.py` | 250 | spatial | PcbSpatialModel: enriched spatial representation |
| `spatial/layer_stackup.py` | 100 | spatial | LayerStackup: layer metadata |
| `spatial/copper_graph.py` | 150 | spatial | Copper zone connectivity graph |
| `placement/layout_aware.py` | 200 | placement | LayoutAwarePlacer: constraint-driven placement |
| `placement/signal_flow.py` | 120 | placement | SignalFlowGrouper: subcircuit-based grouping |
| `placement/thermal.py` | 100 | placement | ThermalPlacer: thermal-aware spacing |
| `validation/drc_intel.py` | 200 | validation | IntelligentDrcAnalyzer: spatial enrichment |
| `validation/fix_suggest.py` | 180 | validation | FixSuggester: actionable fix recommendations |
| `dfm/__init__.py` | 20 | dfm | Module init, public API |
| `dfm/types.py` | 80 | dfm | DfmViolation, DfmReport, ManufacturerProfile |
| `dfm/checker.py` | 100 | dfm | DfmChecker orchestrator |
| `dfm/annular_ring.py` | 100 | dfm | Annular ring adequacy |
| `dfm/solder_mask.py` | 80 | dfm | Solder mask web/sliver |
| `dfm/thermal_relief.py` | 100 | dfm | Thermal relief on copper zone pads |
| `dfm/panelization.py` | 100 | dfm | Panelization readiness |
| `dfm/assembly.py` | 80 | dfm | Assembly considerations |
| `dfm/config.py` | 60 | dfm | Manufacturer capability profiles |

**Total new files: 26, estimated ~2,730 lines**

### Modified Files

| File | Change | Risk |
|------|--------|------|
| `spatial/__init__.py` | Add exports for PcbSpatialModel, LayerStackup | LOW -- additive |
| `placement/__init__.py` | Add exports for LayoutAwarePlacer, SignalFlowGroup | LOW -- additive |
| `validation/__init__.py` | Add export for IntelligentDrcReport (if exists) | LOW -- additive |
| `ops/executor.py` | Add layout-aware placement as query handler dispatch | MEDIUM -- needs new op_type |
| `cli/design_rules.py` (or equivalent) | Add CLI subcommand for constraint propagation | LOW -- additive |
| `cli/dfm.py` (new CLI subcommand) | Add CLI subcommand for DFM checks | LOW -- new file |

**Total modified files: ~6, all additive changes. No breaking changes to existing APIs.**

## Build Order

The build order is determined by data dependencies:

```
Phase A: PCB Spatial Model (spatial/pcb_model.py, layer_stackup.py, copper_graph.py)
    - No new dependencies -- consumes existing PcbIR + spatial primitives
    - Everything else depends on this
    - Can be tested standalone with any .kicad_pcb file

Phase B: Constraint Propagation (constraints/)
    - Depends on: CircuitTopology, Subcircuit, DesignRuleReport (all exist)
    - No dependency on Phase A -- consumes schematic data, not PCB data
    - Can be developed in parallel with Phase A

Phase C: Layout-Aware Placement (placement/layout_aware.py, signal_flow.py, thermal.py)
    - Depends on: Phase A (PcbSpatialModel) + Phase B (PCBConstraint[])
    - Extends existing HybridPlacementEngine

Phase D: DRC Intelligence (validation/drc_intel.py, fix_suggest.py)
    - Depends on: Phase A (PcbSpatialModel) + Phase B (PCBConstraint[])
    - Does NOT depend on Phase C -- consumes DRC results, not placement

Phase E: DFM (dfm/)
    - Depends on: Phase A (PcbSpatialModel) + DrcResult (exists)
    - Does NOT depend on Phase B, C, or D -- independent of constraints
    - Can be developed in parallel with Phase D

Parallelization:
    Phase A + Phase B can run in parallel (no dependency between them)
    Phase C must wait for A + B
    Phase D must wait for A + B
    Phase E must wait for A only
    C, D, E can run in parallel once their prerequisites are met
```

Dependency graph:

```
    [A: PCB Spatial]  [B: Constraints]
         |      \       /      |
         |       \     /       |
         v        \   /        v
    [C: Layout]    [D: DRC Intel]  [E: DFM]
```

## Scalability Considerations

| Concern | 100 components | 1,000 components | 10,000 components |
|---------|---------------|-------------------|---------------------|
| PcbSpatialModel build | <100ms | <1s | ~5s (STRtree scales O(n log n)) |
| SpatialQueryEngine queries | <10ms | <50ms | <200ms |
| Constraint propagation | <50ms | <200ms | <2s (topology graph traversal) |
| Layout-aware placement (SA) | ~1s | ~10s | ~60s (500 iteration cap) |
| DRC intelligence enrichment | <200ms | <1s | ~5s (one pass over violations) |
| DFM checks | <100ms | <500ms | ~3s |

The spatial query engine uses Shapely's STRtree which provides O(log n) spatial lookups. The constraint propagator uses networkx graph traversal which is O(V+E). Neither will be a bottleneck for realistic PCB sizes.

## Sources

- Direct codebase analysis: 15+ source files read and analyzed
- Existing patterns: frozen dataclass, Pydantic BaseModel, ABC + registry, lazy imports
- Architecture references: `ir/base.py` (BaseIR), `analysis/design_rules.py` (DesignRule ABC), `analysis/design_rule_engine.py` (orchestrator pattern), `spatial/extractor.py` (extraction pipeline), `placement/engine.py` (hybrid placement strategy)
