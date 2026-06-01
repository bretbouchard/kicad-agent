# Technology Stack -- v3.0 Full-Stack EDA

**Project:** kicad-agent -- Constraint propagation, PCB spatial model, layout-aware placement, DRC intelligence, DFM
**Milestone:** v3.0-full-stack-eda
**Researched:** 2026-06-01
**Confidence:** HIGH

## Executive Summary

v3.0 needs exactly **two new dependency additions**: `scipy` (promoted from undeclared transitive to explicit) and `scikit-fem` (optional, for thermal simulation). Everything else builds on the existing stack. Shapely 2.1.1 already has STRtree spatial indexing and all geometry primitives needed for PCB spatial modeling. networkx 3.6.1 handles constraint dependency graphs. The existing `DesignRuleEngine` ABC pattern extends directly to PCB DRC and DFM rules. The existing `NetClassifier` with `SignalIntegrity` and `NetImportance` enums provides the foundation for constraint propagation.

The critical gap is not a missing library -- it is a missing parser. kiutils does not parse `.kicad_dru` files (custom design rules with net classes), and net class definitions moved out of `.kicad_pcb` into `.kicad_dru` in modern KiCad. We build a `.kicad_dru` parser using the already-installed `sexpdata` library, following the same pattern used in `PcbIR` for raw S-expression manipulation.

No constraint solver library (z3-solver, python-constraint) is needed. The constraint propagation system is deterministic rule-based: `NetClassifier.classify()` produces `SignalIntegrity`, which maps to PCB constraints via a rule table. This is the same ordered-rule pattern already proven in `violation_classifier.py` and `net_classifier.py`. Adding z3 would solve a problem we do not have -- our constraints are not combinatorial, they are lookup tables.

## Recommended Stack

### Core Dependencies (Existing -- No Changes)

| Technology | Installed | Purpose in v3.0 | Why Sufficient |
|------------|-----------|-----------------|----------------|
| `shapely` | 2.1.1 | PCB spatial model geometry, STRtree spatial queries, copper zone polygons, clearance checks | STRtree supports nearest-neighbor, predicate filtering, buffered queries. Polygon operations (union, intersection, buffer) handle copper zones, keepouts, DRC proximity. Already used in `spatial/primitives.py` via `to_shapely()`. |
| `networkx` | 3.6.1 | Constraint dependency graph, net-to-component connectivity, signal flow traversal | Directed graphs model constraint propagation chains (net class -> clearance -> via drill -> copper zone). Already used in `analysis/topology.py` for circuit topology. No additional graph library needed. |
| `kiutils` | >=1.4.8 | KiCad file parsing (.kicad_pcb, .kicad_sch) | Parses board files, footprints, tracks, vias, zones. Gaps exist (.kicad_dru, stackup epsilon_r) -- handled by sexpdata fallback. |
| `sexpdata` | 1.0.0 | Low-level S-expression parsing for .kicad_dru and stackup | Used in `PcbIR` for raw S-expression manipulation where kiutils falls short. Same pattern for .kicad_dru parsing. |
| `pydantic` | 2.12.5 | Constraint schemas, PCB spatial model types, DFM rule definitions | All new v3.0 types (PCB constraints, spatial violations, DFM results) use Pydantic BaseModel with validators. Same pattern as existing `DesignIntent`, `SubcircuitIntent`, `PlacementRequest`. |
| `numpy` | 1.26.4 | Numerical operations for impedance calculation, thermal grid, coordinate transforms | Foundation for scipy operations, Shapely coordinate arrays, impedance formula implementations. Already installed via transitive deps. |

### New Core Dependency

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `scipy` | >=1.11 | Spatial indexing (KDTree), constrained optimization (linear programming), distance calculations | Currently installed as undeclared transitive (1.11.4). Must be promoted to explicit dependency. Three modules used: `scipy.spatial.KDTree` for thermal proximity queries (complements Shapely STRtree for point-based nearest-neighbor), `scipy.optimize.linprog` for placement refinement with linear constraints, `scipy.spatial.distance.cdist` for pairwise thermal distance matrices. |

### New Optional Dependency

| Technology | Version | Purpose | Why Optional |
|------------|---------|---------|-------------|
| `scikit-fem` | >=10.0 | 2D thermal simulation via finite element method | Solves Poisson/Laplace equations on PCB-shaped meshes for thermal-aware placement. Heavy dependency (pulls mesh generation, sparse solvers). When absent, thermal analysis degrades to distance-based heuristic (still functional, less accurate). Only needed for boards with known thermal hotspots (power supplies, motor drivers, high-current paths). |

### Infrastructure (No Changes)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `kicad-cli` | 10.0.1 | ERC/DRC execution, Gerber export, 3D rendering | External binary, not a Python package. Already used for validation gates. v3.0 adds no new kicad-cli commands -- DRC intelligence parses existing DRC output, DFM validates existing exports. |
| `asyncio` | stdlib | MCP server async wrapping | No changes needed. |

## What NOT to Add

| Avoid | Why |
|-------|-----|
| `z3-solver` | Our constraint propagation is deterministic rule application (NetClassifier -> SignalIntegrity -> PCB constraint table), not combinatorial constraint satisfaction. z3 solves SAT/SMT problems; we have lookup tables. Would add 50MB+ binary dependency for zero benefit. |
| `python-constraint` | Same reasoning as z3. Our constraints are not CSP problems -- they are ordered rule chains following the pattern already proven in `net_classifier.py` and `violation_classifier.py`. |
| `matplotlib` / `plotly` | Visualization belongs in the existing `spatial/renderer.py` SVG renderer. Adding a plotting library creates rendering duplication. The SVG renderer already produces spatial visualizations. |
| `OpenCASCADE` / `cadquery` | 3D modeling is explicitly out of scope (PROJECT.md: "3D model manipulation -- out of scope for v1"). DFM checks operate on 2D Gerber/PCB data, not 3D models. |
| `pyaedb` / `skill` (Cadence) | We are KiCad-only. No need for proprietary EDA format support. |
| `ipc1850` / IPC standard libraries | IPC standards are implemented as rules in our `DesignRuleEngine`, not as external library calls. The rules encode IPC-2221 clearances, IPC-7351 land patterns, etc. as Python code. |
| `gdspy` / `klayout` | Gerber/GDSII manipulation. We use `kicad-cli pcb export gerbers` and validate outputs. No need to generate or manipulate Gerber files programmatically. |
| `pandas` | Tabular data analysis. Our DFM reports and constraint tables are Pydantic models, not DataFrames. Adding pandas for report generation would be over-engineering. |
| `sympy` | Symbolic math for impedance formulas. Microstrip/stripline impedance calculations are closed-form expressions (Hammerstad-Jensen, IPC-2141 formulas). They are 10-20 lines of arithmetic per formula. No symbolic math needed. |

## Capability-to-Stack Mapping

### 1. Constraint Propagation

**What:** Schematic intent (differential pairs, impedance targets, clearance requirements) propagates to PCB design rules.

**Stack:**
| Component | Module | Role |
|-----------|--------|------|
| `NetClassifier.classify()` | existing `analysis/net_classifier.py` | Produces `NetClassification` and `SignalIntegrity` from net name + topology |
| `NetClassifier.classify_signal_integrity()` | existing `analysis/net_classifier.py` | HIGH_SPEED / LOW_FREQUENCY / DC / POWER_INTEGRITY classification |
| `NetClassifier.rank_importance()` | existing `analysis/net_classifier.py` | CRITICAL / HIGH / MEDIUM / LOW importance mapping |
| New: `ConstraintTable` | new `constraints/table.py` | Maps `(SignalIntegrity, NetImportance)` to `PcbConstraint` objects. Pure Python dict lookup. |
| New: `.kicad_dru` parser | new `parser/dru_parser.py` | Uses `sexpdata` to parse net class definitions from .kicad_dru files |
| `DesignIntent` | existing `analysis/intent_schemas.py` | Source of schematic-level intent (design goals, subcircuit functions) |
| `DesignRuleEngine` | existing `analysis/design_rule_engine.py` | Runs constraint validation rules against PCB geometry |
| `networkx.DiGraph` | existing `networkx` | Models constraint dependency chains (impedance -> trace width -> clearance) |

**New libraries needed:** None. sexpdata already installed. Constraint lookup tables are pure Python.

**Integration pattern:** `DesignIntent.subcircuit_intents` -> `NetClassifier.classify_signal_integrity()` per net -> `ConstraintTable.lookup(classification, importance)` -> `PcbConstraint` -> validation via `DesignRuleEngine`.

### 2. PCB Spatial Model

**What:** Rich PCB geometry with layer-aware net/trace/copper zone queries via Shapely.

**Stack:**
| Component | Module | Role |
|-----------|--------|------|
| `PcbIR` | existing `ir/pcb_ir.py` | Board data access (footprints, nets, traces, zones) |
| `SpatialPoint/Box/Path/Region` | existing `spatial/primitives.py` | Foundation types with `to_shapely()` methods |
| `shapely.geometry` | `shapely` 2.1.1 | Polygon/LineString/Point construction from PCB coordinates |
| `shapely.STRtree` | `shapely` 2.1.1 | Spatial indexing for nearest-neighbor and proximity queries |
| `shapely.ops.unary_union` | `shapely` 2.1.1 | Copper zone merging, keepout area aggregation |
| New: `PcbSpatialModel` | new `spatial/pcb_model.py` | Extracts geometry from PcbIR into Shapely primitives, indexed by layer |
| New: `LayerGeometry` | new `spatial/pcb_model.py` | Per-layer Shapely geometry collections (traces as LineString, zones as Polygon) |
| `numpy` | 1.26.4 | Coordinate array construction for Shapely geometries |

**New libraries needed:** None. Shapely 2.1.1 has full STRtree API with predicate filtering.

**Integration pattern:** `PcbIR.board` -> `PcbSpatialModel.build()` -> per-layer `LayerGeometry` with STRtree index -> spatial queries (clearance check, proximity find, zone containment).

### 3. Layout-Aware Placement

**What:** Thermal-aware, signal flow-driven, decoupling-cap-aware component placement.

**Stack:**
| Component | Module | Role |
|-----------|--------|------|
| `HybridPlacementEngine` | existing `placement/engine.py` | Core placement with ML prediction + rule fallback |
| `PlacementRequest` | existing `placement/engine.py` | Input: components, nets, board dimensions, keepout zones |
| `PlacementOutput` | existing `placement/engine.py` | Output: positions, score, HPWL, violations |
| `scipy.spatial.KDTree` | new explicit dep `scipy>=1.11` | Thermal proximity queries (find neighbors within thermal radius) |
| `scipy.optimize.linprog` | new explicit dep `scipy>=1.11` | Constrained placement refinement (minimize wirelength subject to clearance constraints) |
| `scipy.spatial.distance.cdist` | new explicit dep `scipy>=1.11` | Pairwise distance matrix for thermal coupling calculation |
| `scikit-fem` | new optional dep `scikit-fem>=10.0` | 2D thermal FEM simulation for hotspot detection |
| `shapely.STRtree` | existing `shapely` | Spatial conflict detection during placement |
| `PcbSpatialModel` | new (from #2) | Board geometry context for placement constraints |

**New libraries needed:** `scipy` (promote to explicit), `scikit-fem` (optional).

**Integration pattern:** Extend `HybridPlacementEngine._rule_based_place()` with thermal constraint phase (pre-simulation or distance heuristic), signal flow phase (topological ordering from `DesignIntent.signal_flow_description`), decoupling cap phase (find IC power pins -> place caps within radius).

### 4. PCB DRC Intelligence

**What:** Spatial violation parsing with fix suggestions, signal/power integrity awareness.

**Stack:**
| Component | Module | Role |
|-----------|--------|------|
| `SpatialViolation` | existing `validation/spatial_drc.py` | Coordinate-grounded violations with spatial context |
| `enrich_drc_result()` | existing `validation/spatial_drc.py` | Converts raw DRC to spatial violations with nearest footprint |
| `kicad-cli pcb drc` | external binary | DRC execution, produces violation report |
| `DesignRuleEngine` | existing `analysis/design_rule_engine.py` | Runs pluggable design rules with severity sorting |
| `PcbSpatialModel` | new (from #2) | Geometric context for violation localization and fix computation |
| `NetClassifier` | existing `analysis/net_classifier.py` | Determines net criticality for violation severity escalation |
| New: PCB DRC rule classes | new `validation/pcb_rules/` | Extend `DesignRule` ABC for PCB-specific checks (clearance, impedance, thermal) |
| New: `DrcFixSuggester` | new `validation/fix_suggester.py` | Maps violation type + spatial context to actionable fix suggestions |

**New libraries needed:** None. All components extend existing patterns.

**Integration pattern:** `kicad-cli pcb drc` -> `enrich_drc_result()` -> `DrcFixSuggester.suggest(violation, spatial_model, net_classification)` -> fix suggestions with geometry-aware context.

### 5. Design for Manufacturing (DFM)

**What:** DFM checks, panelization awareness, thermal relief, assembly considerations.

**Stack:**
| Component | Module | Role |
|-----------|--------|------|
| `DesignRuleEngine` | existing `analysis/design_rule_engine.py` | Rule execution framework with severity sorting |
| `DesignRule` ABC | existing `analysis/design_rules.py` | Base class for DFM rules (same pattern as design rules) |
| `PcbSpatialModel` | new (from #2) | Board geometry for annular ring, trace width, spacing queries |
| `kicad-cli pcb export gerbers` | external binary | Gerber generation for DFM validation |
| New: DFM rule classes | new `validation/dfm_rules/` | Min annular ring, trace width, spacing, solder mask, paste, thermal relief |
| New: `DfmReport` schema | new `validation/dfm_schemas.py` | Pydantic model for DFM check results |

**New libraries needed:** None. DFM rules are pure Python geometry checks using Shapely and PcbSpatialModel.

**Integration pattern:** `PcbSpatialModel.build()` -> iterate DFM rules via `DesignRuleEngine.run()` -> `DfmReport` with pass/fail per check.

## .kicad_dru Parser Architecture

kiutils does not parse `.kicad_dru` files. This is the most critical integration gap. The parser follows the same sexpdata pattern used in `PcbIR`:

```
New file: src/kicad_agent/parser/dru_parser.py

Dependencies: sexpdata (existing)
Pattern: Same as PcbIR raw S-expression manipulation

Parses:
  - (net_class "name" (clearance X) (trace_width X) (via_dia X) (via_drill X) ...)
  - (net_class_rule ...)
  - Custom differential pair definitions
  - Custom clearance rules

Output: DruFile Pydantic model with:
  - net_classes: dict[str, NetClassDef]
  - custom_rules: list[CustomRule]
  - differential_pairs: list[DiffPairDef]
```

This is the single most important new module because constraint propagation cannot work without net class definitions, and those definitions now live in `.kicad_dru` files.

## pyproject.toml Changes

```toml
dependencies = [
    "kiutils>=1.4.8",
    "sexpdata>=1.0.0",
    "spicelib>=1.5.1",
    "networkx>=3.0",
    "httpx>=0.28.0",
    "pydantic>=2.0",
    "PyGithub>=2.9.1",
    "shapely>=2.0",
    "scipy>=1.11",          # NEW: promoted from transitive to explicit
]

[project.optional-dependencies]
# ... existing groups ...
eda = [
    "scikit-fem>=10.0",    # NEW: optional thermal simulation
]
```

Two changes total: `scipy>=1.11` added to core deps, `scikit-fem>=10.0` added to new `eda` optional group.

## Installation

```bash
# Core v3.0 (all capabilities except thermal FEM)
pip install -e "."

# With thermal simulation
pip install -e ".[eda]"

# Full development install
pip install -e ".[dev,eda,mcp]"
```

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Spatial indexing | Shapely STRtree | rtree (R-tree library) | Shapely 2.x bundles STRtree (based on GEOS). Adding rtree would duplicate spatial indexing. STRtree is sufficient for PCB-scale data (< 1M geometries per layer). |
| Constraint solver | Custom rule table (dict lookup) | z3-solver | Our constraints are not combinatorial -- they are deterministic mappings from net classification to PCB parameters. z3 would add 50MB+ for a problem that fits in a Python dict. |
| Constraint solver | Custom rule table | python-constraint | Same reasoning. Our constraint propagation is forward-chaining (A implies B), not backtracking search. |
| Thermal simulation | scikit-fem (optional) | FEniCS | FEniCS requires C++ compilation, Docker, or conda. scikit-fem is pure Python with pip install. FEniCS is overkill for 2D heat diffusion. |
| Thermal simulation | scikit-fem (optional) | Custom finite difference | Finite difference on rectangular grids cannot handle PCB-shaped domains (cutouts, slots, irregular outlines). FEM on triangular meshes handles arbitrary PCB shapes. |
| Thermal heuristic | scipy.spatial.distance (when no scikit-fem) | No thermal analysis | Distance-based thermal estimation (inverse square law from power-dissipating components) provides ~70% accuracy with zero additional dependencies. Good enough for most boards. |
| Impedance calculation | Pure Python (Hammerstad-Jensen, IPC-2141) | openEMS (FDTD simulation) | Closed-form microstrip/stripline formulas give < 5% error for standard stackups. Full-wave simulation is unnecessary when we have known stackup geometry and dielectric constants. |
| Board stackup parsing | sexpdata fallback | Patch kiutils | kiutils `Board.setup.stackup` exists but may not fully parse all fields. Patching kiutils is a contribution to an external project with uncertain timeline. sexpdata fallback gives us immediate control. Same pattern proven in PcbIR. |
| Placement optimization | scipy.optimize.linprog | scipy.optimize.minimize (nonlinear) | PCB placement constraints are predominantly linear (clearance >= X, position within bounds). Linear programming is faster and more reliable than general nonlinear optimization. |
| DFM checks | Shapely geometry queries | kicad-cli scripting | kicad-cli does not have DFM-specific checks. DRC covers electrical rules, not manufacturing rules (min annular ring, solder mask sliver, paste coverage). These require geometry analysis that only Shapely provides. |

## Key Design Decisions

### D-V3-01: No Constraint Solver Library
**Decision:** Build constraint propagation as ordered rule chains, not SAT/SMT/CSP.
**Why:** The existing codebase has two proven implementations of this pattern (`net_classifier.py` with 7 ordered rules, `violation_classifier.py`). Net classification -> SignalIntegrity -> PCB constraint is a deterministic lookup, not a search problem. Adding z3 or python-constraint would introduce complexity that provides zero value.

### D-V3-02: scipy as Explicit Dependency
**Decision:** Promote scipy from undeclared transitive to explicit core dependency.
**Why:** scipy 1.11.4 is already installed (via torch or another transitive dep) but not declared. v3.0 uses `scipy.spatial.KDTree`, `scipy.optimize.linprog`, and `scipy.spatial.distance.cdist` directly. Undeclared transitive dependencies break when the transitive chain changes. Declaring it explicitly is correct packaging practice.

### D-V3-03: scikit-fem as Optional
**Decision:** Thermal FEM simulation is optional, not required.
**Why:** scikit-fem pulls meshpy (triangle meshing) and sparse matrix solvers. Many boards do not need thermal simulation -- the distance-based heuristic suffices. Making it optional keeps the core install lean. The `eda` optional group signals "advanced EDA features" without forcing all users to install FEM libraries.

### D-V3-04: sexpdata for .kicad_dru, Not kiutils Patch
**Decision:** Build .kicad_dru parser using sexpdata rather than patching kiutils.
**Why:** kiutils maintainers may or may not add .kicad_dru support. We need it now. sexpdata is already installed and the same pattern is proven in PcbIR for raw S-expression manipulation. If kiutils adds .kicad_dru support later, we can migrate.

### D-V3-05: Extend Existing DesignRuleEngine, Not New Framework
**Decision:** PCB DRC rules and DFM rules both extend the existing `DesignRule` ABC and `DesignRuleEngine`.
**Why:** The existing engine has: pluggable rules, error handling per rule, severity sorting, disabled rule support, per-rule config. PCB rules and DFM rules are just more `DesignRule` subclasses. Creating a separate engine would duplicate all of this infrastructure for no benefit.

### D-V3-06: Impedance via Closed-Form, Not Simulation
**Decision:** Impedance calculation uses microstrip/stripline closed-form formulas (Hammerstad-Jensen, IPC-2141).
**Why:** PCB trace impedance is determined by geometry (trace width, dielectric thickness, epsilon_r) and is accurately modeled by well-known formulas. Full-wave electromagnetic simulation (openEMS, FDTD) is unnecessary when we have exact stackup parameters. The formulas are ~20 lines of Python each.

## New Modules Needed

| Module | Lines (est.) | Depends On | Purpose |
|--------|-------------|------------|---------|
| `parser/dru_parser.py` | ~250 | sexpdata | Parse .kicad_dru net class and custom rule definitions |
| `spatial/pcb_model.py` | ~400 | shapely, PcbIR | PCB spatial model with per-layer geometry and STRtree indexing |
| `spatial/pcb_geometry.py` | ~300 | shapely, numpy | PCB-specific geometry builders (track to LineString, zone to Polygon) |
| `constraints/table.py` | ~150 | pydantic, NetClassifier | Constraint lookup: SignalIntegrity -> PcbConstraint |
| `constraints/schemas.py` | ~200 | pydantic | PcbConstraint, DifferentialPairConstraint, ImpedanceConstraint types |
| `constraints/propagator.py` | ~250 | networkx, constraints/* | Forward-chain constraint propagation with dependency tracking |
| `validation/pcb_rules/` | ~500 total | DesignRuleEngine, PcbSpatialModel | PCB-specific design rules (clearance, impedance, thermal) |
| `validation/dfm_rules/` | ~400 total | DesignRuleEngine, PcbSpatialModel | DFM rules (annular ring, trace width, solder mask, thermal relief) |
| `validation/fix_suggester.py` | ~200 | SpatialViolation, PcbSpatialModel | Map violations to actionable fix suggestions |
| `spatial/thermal.py` | ~300 | scipy, scikit-fem (optional) | Thermal simulation: FEM with scikit-fem, heuristic fallback |
| `spatial/impedance.py` | ~200 | numpy | Microstrip/stripline impedance formulas from stackup parameters |
| `placement/thermal_placer.py` | ~250 | scipy, thermal.py | Thermal-aware placement phase extending HybridPlacementEngine |

**Total estimated new code:** ~3,400 lines across 12 modules.

## Version Pinning Rationale

| Package | Pin | Why |
|---------|-----|-----|
| `scipy>=1.11` | Minimum only | 1.11 introduced stable KDTree API. 1.14+ has performance improvements. No breaking changes in 1.11-1.17 range. |
| `scikit-fem>=10.0` | Minimum only | 10.0 introduced stable 2D mesh API. 12.0 is latest but 10.0+ all work. |
| `shapely>=2.0` | Already pinned | 2.0+ has vectorized STRtree. We need predicate-based queries only in 2.0+. |
| `numpy` | Do NOT pin | Already constrained by scipy and shapely version requirements. Pinning would create conflicts. |

## Sources

- Live inspection: scipy 1.11.4, shapely 2.1.1, numpy 1.26.4, networkx 3.6.1, sexpdata 1.0.0, pydantic 2.12.5
- PyPI latest: scipy 1.17.1, scikit-fem 12.0.1
- Codebase: `src/kicad_agent/spatial/primitives.py` (SpatialRegion entity_type supports "zone", "keepout", "copper_pour", "net_class_region")
- Codebase: `src/kicad_agent/ir/pcb_ir.py` (PcbIR board access, raw S-expression manipulation)
- Codebase: `src/kicad_agent/analysis/net_classifier.py` (SignalIntegrity, NetImportance, ordered rules)
- Codebase: `src/kicad_agent/analysis/design_rule_engine.py` (DesignRuleEngine, DesignRule ABC)
- Codebase: `src/kicad_agent/placement/engine.py` (HybridPlacementEngine, PlacementRequest/Output)
- Codebase: `src/kicad_agent/validation/spatial_drc.py` (SpatialViolation, enrich_drc_result)
- Codebase: `pyproject.toml` (current dependencies and optional groups)
- KiCad format: net classes in .kicad_dru (verified: kiutils DesignRules class has no content parsing)
- KiCad format: Board.setup.stackup contains epsilon_r and loss_tangent (verified via PcbIR)

---
*Stack research for: kicad-agent milestone v3.0-full-stack-eda*
*Researched: 2026-06-01*
