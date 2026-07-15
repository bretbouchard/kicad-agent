# Domain Pitfalls -- v3.0 Full-Stack EDA Features

**Domain:** Adding constraint propagation, PCB spatial intelligence, layout-aware placement, DRC intelligence, and DFM checks to an existing KiCad automation tool
**Researched:** 2026-06-01
**Context:** volta has 85+ operations, deep schematic understanding, limited PCB understanding. This document covers pitfalls SPECIFIC to adding PCB layout intelligence to this existing codebase.
**Confidence:** HIGH (verified against codebase analysis: PcbIR, spatial primitives, placement engine, crossfile propagation, design rule engine, net classifier, erc_drc module, routing constraints)

---

## Critical Pitfalls

Mistakes that cause rewrites or major issues.

---

### Pitfall 1: kiutils Drops All UUIDs from PCB Files -- Spatial Feature Code Must Never Rely on kiutils Round-Trip

**What goes wrong:**
kiutils 1.4.8 silently drops all `(uuid "...")` tokens from `.kicad_pcb` and `.kicad_mod` files during serialization. The codebase already handles this via `UUIDMap` extraction and `uuid_reinjector.py`, but the new PCB spatial features will create many new code paths that parse, query, and serialize PCB data. Any new module that calls `board.to_file()` without the UUID re-injection pipeline will produce files with missing UUIDs, causing KiCad to regenerate them and breaking cross-references between schematic and PCB.

**Why it happens:**
A developer building a new PCB spatial analysis feature reads a `.kicad_pcb` file via `PcbIR`, performs spatial queries, and writes results back. The `PcbIR` already documents this ("CRITICAL: kiutils drops all UUID tokens from PCB files"), but new PCB-focused code paths (DFM checks modifying zone parameters, constraint propagation writing net class rules, placement engine updating footprint positions) may bypass `PcbIR` and use `Board.from_file()` / `board.to_file()` directly, losing the UUID safety net.

**Consequences:**
- KiCad regenerates UUIDs on next load, breaking schematic-to-PCB cross-references
- DRC results reference stale UUIDs, making spatial violation mapping unreliable
- AtomicOperation rollback fails because UUIDs don't match the snapshot
- Silent data corruption -- the file looks valid but cross-references are broken

**Prevention:**
1. Every new PCB code path MUST go through `PcbIR`, which enforces `_uuid_map` in `__post_init__`
2. Never call `Board.from_file()` / `board.to_file()` directly in new modules -- always use `parse_pcb()` + `PcbIR`
3. For read-only spatial analysis (no writes), kiutils `Board` is safe to use directly -- but document that this is read-only
4. Add a lint rule: grep new modules for `Board.from_file` or `.to_file()` calls not wrapped in `PcbIR`

**Detection:**
Run roundtrip validation (`validation/roundtrip.py`) after any PCB feature work. If UUIDs are missing, the roundtrip test will catch it.

**Phase to address:** Every phase that touches `.kicad_pcb` files. First line of defense.

---

### Pitfall 2: Y-Axis Direction Differs Between Schematic and PCB -- Spatial Features Will Compute Wrong Coordinates

**What goes wrong:**
KiCad schematics use standard math coordinates (Y increases upward), while KiCad PCB files use screen coordinates (Y increases downward). The existing `SpatialPoint` and `SpatialBox` primitives state "Y-axis increases downward (standard screen coordinate convention)" in their docstrings. The schematic spatial module (`analysis/schematic_spatial.py`) works in schematic coordinates. When constraint propagation bridges schematic intent to PCB spatial rules, a Y-coordinate flip must occur. Missing this flip produces constraints that are geometrically inverted on the PCB.

**Why it happens:**
The developer working on constraint propagation extracts net topology from schematic analysis (which operates in schematic coordinate space) and creates PCB placement constraints (which must operate in PCB coordinate space). The coordinate systems are not documented in a single place -- the schematic module does not state its Y direction, and the PCB spatial primitives state Y-down without referencing the schematic mismatch. The flip is easy to miss because both systems use millimeters and similar-looking coordinate values.

**Consequences:**
- Decoupling capacitor placement constraints place caps on the wrong side of their ICs
- Differential pair length-matching constraints apply to wrong trace segments
- Thermal zone calculations place heat sources in wrong quadrants
- All spatial queries return correct but wrong-coordinate results

**Prevention:**
1. Create a canonical coordinate conversion utility: `schematic_to_pcb_coords(x, y)` and `pcb_to_schematic_coords(x, y)` in the spatial module
2. The conversion is simply `y_pcb = -y_schematic` (or `y_pcb = board_height - y_schematic` depending on origin placement) -- verify against real files before implementing
3. Every constraint propagation function that crosses the schematic-PCB boundary MUST call the converter explicitly
4. Add a coordinate system assertion in tests: verify that a known component position in schematic maps to the correct PCB position

**Detection:**
Write a test with a real KiCad project (e.g., Arduino_Mega fixture) that has both schematic and PCB. Verify that `PcbIR.get_footprint_by_ref("U1").position` and the schematic component position map through the converter to the same physical location.

**Phase to address:** Phase 1 (constraint propagation) -- this is the first feature that bridges both coordinate systems.

---

### Pitfall 3: Constraint Propagation Creates Circular Dependencies Between Schematic and PCB

**What goes wrong:**
Constraint propagation extracts intent from the schematic (net classes, differential pairs, impedance requirements) and generates PCB design rules. But some PCB constraints feed back to schematic intent -- for example, a PCB layout might reveal that a differential pair cannot achieve target impedance given the board stackup, requiring a schematic change (different termination, different trace geometry class). If the constraint system creates bidirectional links without cycle detection, a constraint resolver will loop infinitely or produce contradictory rules.

**Why it happens:**
The existing `crossfile/propagation.py` is unidirectional (schematic -> PCB or library ref updates). The existing `DesignRuleEngine` is unidirectional (checks topology, reports violations). Neither has the concept of bidirectional constraint flow. Building constraint propagation as "extract from schematic, apply to PCB" is the natural first step, but the moment someone adds a PCB-to-schematic feedback path (e.g., "PCB DRC found impedance mismatch, suggest changing net class in schematic"), the cycle appears.

**Consequences:**
- Infinite loop in constraint resolution
- Conflicting rules (schematic says 50-ohm impedance, PCB says impossible with 2-layer stackup)
- Constraint resolver crashes or produces nonsensical merged rules
- Hard to debug because the cycle may span multiple files and modules

**Prevention:**
1. Design constraint propagation as strictly unidirectional: Schematic -> PCB. No feedback path.
2. If PCB analysis produces schematic-change suggestions, these are separate "suggestions" (advisory), not "constraints" (enforced). The suggestion system is fire-and-forget.
3. If bidirectional constraint resolution is needed later, implement a constraint DAG (directed acyclic graph) with explicit cycle detection before resolution. Topological sort the DAG, resolve in order.
4. Use the existing `DesignRuleReport` pattern (check, report violations, suggest fixes) for PCB-to-schematic feedback rather than creating a new constraint feedback mechanism.
5. Add a `ConstraintGraph` class with explicit `add_edge(source, target)` that runs cycle detection on each addition.

**Detection:**
Unit test: create a constraint graph with a known cycle, verify that `add_edge` raises `CycleError`. Integration test: propagate constraints from a schematic with mutually-referencing net classes, verify no infinite loop.

**Phase to address:** Phase 1 (constraint propagation) -- architecture decision before any code.

---

### Pitfall 4: Shapely Coordinate Precision Causes Clearance False Positives at Sub-Micrometer Scale

**What goes wrong:**
Shapely uses IEEE 754 double-precision floating point for all geometry operations. At the boundaries of PCB features (pad edges, trace corners, via edges), Shapely's `distance()` and `intersects()` methods can produce false positives for clearance violations due to floating-point precision. A clearance check between two pads that are exactly at minimum clearance (e.g., 0.2mm) may report 0.19999999999999998mm instead of 0.2mm, triggering a spurious DRC violation. Conversely, two pads that barely overlap may report a tiny positive distance instead of zero, missing a real violation.

**Why it happens:**
The existing `PlacementValidator` already computes `distance < self._min_clearance` and `distance < 1e-9` for overlap detection. But the new DRC intelligence and DFM features will perform many more clearance checks with tighter tolerances (e.g., copper-to-copper clearance of 0.1mm for fine-pitch BGA, solder mask expansion of 0.05mm). At these tolerances, floating-point error becomes a significant fraction of the clearance budget.

**Consequences:**
- False DRC violations that confuse the AI agent and the user
- Missed real violations near pad/trace boundaries
- Non-deterministic results: the same clearance check may pass or fail depending on the order of geometric operations
- DFM checks report boards as non-manufacturable when they are actually fine

**Prevention:**
1. Define an explicit tolerance constant: `_CLEARANCE_TOLERANCE_MM = 1e-4` (0.1 micrometers -- well below manufacturing precision but above floating-point noise)
2. All clearance comparisons should use `distance < (required_clearance - _CLEARANCE_TOLERANCE_MM)` for violation detection
3. All overlap detection should use `distance < _CLEARANCE_TOLERANCE_MM` instead of `distance < 1e-9`
4. Round all spatial primitive coordinates to 4 decimal places (already done in `SpatialPoint.to_json()`) but also round Shapely computation results before comparison
5. Consider using `shapely.prepare()` for complex geometries to improve both performance and precision

**Detection:**
Write tests with geometric edge cases: two boxes at exactly minimum clearance, two boxes that overlap by exactly 0.0mm at a single vertex, a point on the edge of a polygon. Verify deterministic pass/fail results.

**Phase to address:** Phase 2 (PCB spatial model) and Phase 4 (DRC intelligence) -- anywhere Shapely distance checks are used.

---

### Pitfall 5: KiCad Layer Names Are Canonical Strings With Subtle Variations -- String Comparison Will Fail

**What goes wrong:**
KiCad uses canonical layer names like `F.Cu`, `B.Cu`, `In1.Cu`, `In2.Cu`, `F.SilkS`, `B.SilkS`, `F.Mask`, `B.Mask`, `Edge.Cuts`, `Dwgs.User`, etc. The codebase already uses these exact strings in several places (see `routing/constraints.py`, `spatial/renderer.py`, `generation/template_board.py`). But KiCad also has user-defined layers, and some layer names have historical aliases. If spatial features use exact string comparison for layer filtering (e.g., "find all copper objects on front layer"), the comparison may fail for boards that use layer aliases, boards from different KiCad versions, or boards with custom layer definitions.

**Why it happens:**
The existing `SpatialQueryEngine.find_by_layer()` does exact string equality (`p.layer == layer_name`). The DFM checks will need to filter by layer type (copper vs. silkscreen vs. solder mask) rather than individual layer names. A board with 6 copper layers needs DFM checks applied to all of them, not just `F.Cu` and `B.Cu`.

**Consequences:**
- Inner copper layers (`In1.Cu`, `In2.Cu`, etc.) are missed by DFM checks that only look at `F.Cu` and `B.Cu`
- Differential pair impedance constraints apply to wrong layers because the layer name format changed
- Thermal analysis misses internal copper planes that act as heat spreaders
- String comparison fails silently (returns empty results instead of error)

**Prevention:**
1. Create a `LayerClassifier` utility with methods like `is_copper(layer_name)`, `is_silkscreen(layer_name)`, `is_mask(layer_name)`, `is_paste(layer_name)`, `is_edge(layer_name)`
2. Copper layers: `F.Cu`, `B.Cu`, and any `In\d+.Cu` pattern
3. Never hardcode individual layer name lists for checks that should cover all copper layers
4. Use the classifier in all spatial queries that need layer-type filtering
5. Support the regex pattern `r"^(F|B|In\d+)\.Cu$"` for copper layer detection

**Detection:**
Test with a 6-layer board fixture. Verify that copper-layer spatial queries return objects from all 6 layers, not just top and bottom.

**Phase to address:** Phase 2 (PCB spatial model) -- the spatial model must correctly classify layers from the start.

---

### Pitfall 6: Component Size Estimation Is a Rough Heuristic -- Placement Features Will Produce Bad Results for Real Boards

**What goes wrong:**
The existing placement engine estimates component size from the reference designator prefix: `U` -> 10mm, `Q`/`TR` -> 8mm, `L`/`D` -> 5mm, `R`/`C` -> 2mm, default -> 3mm (see `placement/graph.py` line 335). This is a placeholder heuristic that works for synthetic training data but fails for real boards where a QFN-48 IC (ref `U1`, actual size ~7mm) shares a board with a D2PAK MOSFET (ref `Q1`, actual size ~10mm), or a 0402 resistor (ref `R1`, actual size 1.0mm) shares a board with a 2512 resistor (ref `R2`, actual size 6.3mm).

**Why it happens:**
The placement engine was built for training data generation and synthetic boards, not for production placement. The `estimated_size` field in the placement graph is used for bounding box computation in `PlacementValidator`. When the new layout-aware placement features (thermal, signal flow, decoupling) use these estimated sizes for clearance calculations, they will produce systematically wrong results for mixed-component boards.

**Consequences:**
- Overlapping placement suggestions (estimated size too small for large components)
- Wasted board space (estimated size too large for small components)
- Thermal analysis uses wrong component areas for heat dissipation calculations
- Decoupling cap placement optimization fails because IC size estimates are off by 30-50%

**Prevention:**
1. Extract actual footprint bounding box from `PcbIR` when available: iterate footprint pads and graphics, compute real bounding box
2. When `PcbIR` is not available (schematic-only mode), use footprint library lookup: resolve the footprint's `.kicad_mod` file via `lib_resolver.resolve_footprint_path()` and parse its actual geometry
3. As a fallback, keep the reference-prefix heuristic but add package-size lookup tables for common footprints (0402, 0603, 0805, QFN-48, SOIC-8, etc.)
4. Add a `ComponentGeometry` dataclass that holds real width, height, pad positions, and thermal area -- computed once from footprint data, not estimated
5. Never use `estimated_size` as a single scalar. Real components have different widths and heights.

**Detection:**
Compare placement results using estimated sizes vs. actual footprint sizes on the Arduino_Mega fixture. If clearance violations differ by more than 10%, the heuristic is insufficient.

**Phase to address:** Phase 3 (layout-aware placement) -- before thermal and signal flow analysis begin.

---

## Moderate Pitfalls

---

### Pitfall 7: DFM Rules Are Manufacturer-Specific -- Hardcoding One Vendor's Rules Alienates All Others

**What goes wrong:**
DFM checks (minimum trace width, minimum drill size, minimum annular ring, solder mask expansion, minimum clearance, board thickness constraints) vary significantly between manufacturers. JLCPCB has different capabilities than PCBWay, which has different capabilities than OSH Park. Hardcoding JLCPCB's rules (which the codebase might default to since the component search MCP uses JLCPCB/EasyEDA) means the DFM system produces false failures for boards destined for other fabs, or misses real failures for boards going to fabs with tighter constraints.

**Why it happens:**
The existing component search MCP server is JLCPCB-specific. The developer naturally gravitates toward JLCPCB's design rules as defaults. But DFM is fundamentally a per-manufacturer concern, and the volta tool positions itself as "works across any KiCad 10+ project."

**Consequences:**
- DFM reports are wrong for non-JLCPCB boards
- Users lose trust in DFM results and stop using the feature
- Adding new manufacturer rules requires code changes instead of configuration
- The DFM system becomes "JLCPCB validation" rather than "design for manufacturing"

**Prevention:**
1. Create a `ManufacturerCapabilities` dataclass with all relevant DFM parameters (min trace width, min drill, min annular ring, min clearance, layer count range, supported copper weights, etc.)
2. Ship capability profiles for 3-5 common manufacturers as JSON/YAML config files in a `resources/` directory
3. Allow user-provided capability profiles via project-level config
4. Default to a "generic 2-layer" conservative profile that covers most fabs, not to any specific vendor
5. The DFM check API should accept a `ManufacturerCapabilities` parameter, not read global state

**Detection:**
Write DFM tests using the same board against two different manufacturer profiles. Results should differ where the profiles differ.

**Phase to address:** Phase 5 (DFM) -- architecture decision from day one.

---

### Pitfall 8: DRC Intelligence Parses kicad-cli JSON Reports -- Report Format May Change Between KiCad Versions

**What goes wrong:**
The existing `erc_drc.py` parses JSON reports from `kicad-cli sch erc --format json` and `kicad-cli pcb drc --format json`. The `spatial_drc.py` module enriches these parsed violations with coordinate data by extracting `pos.x` and `pos.y` from item dicts. The DRC JSON report format is not a public API -- it is an implementation detail of kicad-cli that may change between KiCad versions. The codebase targets KiCad 10+, but within the KiCad 10.x lifecycle, the JSON report format could change.

**Why it happens:**
kicad-cli's `--format json` flag is documented for use but the JSON schema is not formally versioned or stabilized. KiCad developers may restructure the report format (e.g., nesting violations differently, renaming fields, changing coordinate representation). The DRC intelligence features will be deeply dependent on the structure of these reports.

**Consequences:**
- All DRC intelligence features break silently (empty violation lists, missing coordinates)
- Spatial violation enrichment produces `SpatialPoint(0.0, 0.0)` for all items (default fallback in `enrich_drc_result`)
- No error message -- the enrichment just produces degraded results

**Prevention:**
1. Add a JSON report schema version check at parse time: verify expected top-level keys exist (`sheets`, `violations`, `unconnected_items`, `kicad_version`)
2. Add defensive parsing: if expected fields are missing, log a warning with the actual JSON structure rather than silently degrading
3. Pin the minimum tested KiCad version in documentation and CI
4. Write a DRC report compatibility test: run DRC on a known board, verify the parsed `DrcResult` matches expected structure
5. Store the `kicad_version` from the report in all DRC intelligence results for future compatibility checks

**Detection:**
After any KiCad update, run the DRC report compatibility test. If it fails, the report format changed.

**Phase to address:** Phase 4 (DRC intelligence) -- add the schema version check in the first implementation.

---

### Pitfall 9: Thermal Analysis Requires Component Power Dissipation Data That Schematics Don't Contain

**What goes wrong:**
Layout-aware thermal placement needs to know how much heat each component dissipates. Schematics contain component values (resistance, capacitance) but not power dissipation. PCBs contain footprints but not thermal data. The only source for power dissipation is the component datasheet or user annotation. Building a thermal-aware placement system without power data produces placement suggestions that look thermal-aware but are actually random with respect to thermal concerns.

**Why it happens:**
The developer sees that the net classifier can identify power nets (`NetClassification.POWER`) and assumes this is sufficient for thermal analysis. But knowing that a net is a 3.3V power rail tells you nothing about how much power the connected IC dissipates. A 3.3V microcontroller might dissipate 50mW while a 3.3V LDO regulator might dissipate 2W.

**Consequences:**
- "Thermal-aware" placement is not actually thermal-aware
- Hot components are placed next to temperature-sensitive components
- Thermal relief calculations produce nonsensical results
- User trust erodes when "intelligent" placement produces worse results than random

**Prevention:**
1. Thermal analysis should be explicitly opt-in with user-provided power data, not automatic
2. Create a `ThermalProfile` dataclass that users populate per-component: `reference`, `power_dissipation_watts`, `max_temp_celsius`, `thermal_resistance`
3. Provide reasonable defaults based on component type (resistors use `I^2 * R`, regulators use `(V_in - V_out) * I_load`, ICs default to a conservative 0.5W)
4. Thermal placement should degrade gracefully: if no thermal data, fall back to connectivity-driven placement (which the existing `HybridPlacementEngine` already does)
5. Document clearly: "Thermal-aware placement requires user-annotated power dissipation data. Without it, placement is connectivity-driven only."

**Detection:**
Run thermal placement with and without thermal profiles. Without profiles, it should produce identical results to the existing rule-based placement.

**Phase to address:** Phase 3 (layout-aware placement) -- before building thermal analysis, decide whether it's user-annotated or inferred.

---

### Pitfall 10: STRtree Is Immutable -- PCB Spatial Model Must Be Rebuilt After Every Mutation

**What goes wrong:**
The existing `SpatialQueryEngine` builds a Shapely `STRtree` at construction time from a list of primitives. The tree is immutable -- it cannot be updated in place. When the PCB spatial model is used in an interactive or iterative workflow (place component, check clearance, place next component, check again), the spatial index must be rebuilt from scratch after every mutation. For boards with thousands of primitives, rebuilding the STRtree on every placement step is expensive.

**Why it happens:**
The `SpatialQueryEngine` was designed for one-shot spatial queries (build index, query, discard). The new PCB spatial model needs to support iterative placement workflows where the spatial index changes with each placement decision. The developer may not realize the STRtree is immutable until performance testing reveals that each placement step takes 10x longer than expected.

**Consequences:**
- O(n log n) rebuild cost on every placement step, making iterative placement O(n^2 log n) total
- Interactive placement feels sluggish for boards with 100+ components
- DRC intelligence features that need to recheck violations after suggesting fixes become slow
- The developer works around it by caching stale spatial indices, leading to incorrect clearance checks

**Prevention:**
1. Design the PCB spatial model with explicit `build()` and `rebuild()` lifecycle methods
2. Track a `dirty` flag on the spatial model -- mutations set it, queries check it and trigger rebuild if dirty
3. Batch mutations: support `update_positions(new_positions: dict)` that applies all changes at once, then rebuilds once
4. For iterative placement, use the existing `PlacementValidator` pattern which creates a fresh `SpatialQueryEngine` per validation pass -- this is correct if the pass covers all components
5. Document the rebuild cost: log the rebuild time and warn if it exceeds 100ms

**Detection:**
Performance test: create a spatial model with 1000 primitives, measure query time (should be <1ms) vs. rebuild time (may be 10-50ms). Profile iterative placement with 100 components and verify total time is acceptable.

**Phase to address:** Phase 2 (PCB spatial model) -- the API surface must account for mutability from the start.

---

### Pitfall 11: Constraint Propagation Maps Schematic Net Classes to PCB Design Rules -- But KiCad's Net Class System Has Gaps

**What goes wrong:**
KiCad's net class system (`(net_class "...")` in `.kicad_pcb`) defines trace width, clearance, via diameter, and via drill per net class. The constraint propagation feature needs to map schematic intent (differential pair, impedance-controlled, high-current, etc.) to PCB net class parameters. But KiCad net classes have limited expressiveness: they don't support differential pair constraints (pair name, gap, length tolerance), impedance constraints, or per-layer trace widths natively. The existing `RoutingConstraints` dataclass already has `layer_trace_widths` and impedance-related fields (`dielectric_constant`, `dielectric_height_mm`), showing that the codebase has already hit this gap.

**Why it happens:**
KiCad's net class system was designed for basic routing rules, not for high-speed design constraints. Differential pairs in KiCad are handled by the interactive router, not by net class definitions. Impedance calculations require stackup information that is not stored in the net class. The developer may assume that mapping schematic intent to net classes is sufficient, only to discover that half the constraints they want to propagate have no net class equivalent.

**Consequences:**
- Differential pair constraints are silently dropped (no net class field for them)
- Impedance constraints require separate storage outside net classes
- The constraint propagation system becomes a partial solution that users cannot rely on
- Confusion between what KiCad's net class system supports and what the constraint system tries to propagate

**Prevention:**
1. Clearly separate constraints into two categories: "KiCad net class constraints" (trace width, clearance, via size) and "extended constraints" (differential pair, impedance, length matching)
2. Extended constraints should be stored in a custom metadata system (e.g., a `.volta-constraints.json` sidecar file or design rule file), not in KiCad's net class definitions
3. The constraint propagation API should have two methods: `propagate_net_class_rules(schematic_ir, pcb_ir)` for KiCad-native rules, and `propagate_extended_constraints(schematic_ir) -> ExtendedConstraints` for non-native rules
4. Document which constraints map to KiCad net classes and which require extended storage
5. The existing `add_design_rule` operation in `_PROJECT_HANDLERS` may be the right place for extended constraints

**Detection:**
Test with a schematic that includes differential pairs and impedance-controlled nets. Verify that net class constraints are propagated to `.kicad_pcb` and extended constraints are stored separately.

**Phase to address:** Phase 1 (constraint propagation) -- architecture decision before implementation.

---

### Pitfall 12: PcbIR.get_board_bounds() Only Uses Edge.Cuts Line Segments -- Misses Arcs and Complex Outlines

**What goes wrong:**
The existing `PcbIR.get_board_bounds()` iterates `graphicItems` looking for `Edge.Cuts` layer graphics, but only handles `start`/`end` (line segments) and `center`/`radius` (circles). It misses arcs (KiCad `gr_arc` elements), Bezier curves, and polygon outlines on `Edge.Cuts`. Real boards often have rounded corners (arcs), mounting holes, and complex outlines. DFM checks that depend on board bounds will produce wrong results for any board with a non-rectangular outline.

**Why it happens:**
`get_board_bounds()` was built for basic board dimension estimation, not for precise outline extraction. The `Edge.Cuts` layer in real KiCad boards uses a mix of line segments, arcs, and sometimes polygons. The current implementation handles line segments and circles but not arcs or complex shapes.

**Consequences:**
- DFM panelization calculations are wrong for boards with rounded corners
- Board utilization percentage (component area / board area) is wrong
- Placement bounds checking (`PlacementValidator`) uses inflated bounds, allowing components near complex outlines to violate the actual board edge
- DRC intelligence may miss edge clearance violations

**Prevention:**
1. Enhance `get_board_bounds()` to handle `gr_arc` elements by sampling arc endpoints and midpoint
2. For precise outline work, build a Shapely Polygon from all Edge.Cuts elements (line segments + arcs) rather than using bounding box approximation
3. Add a `get_board_outline() -> Shapely Polygon` method to the PCB spatial model (Phase 2) that constructs the actual board shape
4. Use the board outline polygon for DFM checks, not the bounding box
5. For `get_board_bounds()`, add a `precise: bool = False` parameter that uses the polygon for bounds calculation

**Detection:**
Test with a board that has rounded corners (arc elements on Edge.Cuts). Verify `get_board_bounds()` includes the arc extents and `get_board_outline()` produces a polygon that matches the visual outline.

**Phase to address:** Phase 2 (PCB spatial model) -- the spatial model needs a proper board outline representation.

---

## Minor Pitfalls

---

### Pitfall 13: NetGraph Uses O(n^2) Edge Construction for Pads Sharing a Net

**What goes wrong:**
The existing `NetGraph.from_pcb_ir()` in `analysis/connectivity.py` creates a complete graph among all pads sharing the same net: for each net with k pads, it creates k*(k-1)/2 edges. For power nets (GND, VCC) with hundreds of pads, this produces O(n^2) edges, consuming excessive memory and slowing graph operations.

**Why it happens:**
The code explicitly iterates `for i in range(len(pads)): for j in range(i + 1, len(pads)):` creating pairwise edges. This is correct for connectivity semantics (all pads on the same net are mutually reachable) but produces quadratic edge counts for high-fanout nets.

**Consequences:**
- PCB spatial model that uses NetGraph becomes slow for boards with large power nets
- Memory usage spikes for boards with many pads on GND/VCC nets
- Graph algorithms (shortest path, connected components) are slower than necessary

**Prevention:**
1. The existing placement graph (`PlacementGraph`) already solves this correctly with bipartite representation -- route connectivity through net nodes instead of pairwise edges
2. For PCB spatial analysis, follow the same bipartite pattern or use the placement graph directly
3. If NetGraph is used, cap the number of edges per net (e.g., create a star topology with a virtual net center node instead of complete graph)
4. Power nets can be represented as a single connectivity group without explicit edges

**Detection:**
Profile NetGraph construction for a board with 200+ pads on GND. If construction takes >100ms, the O(n^2) edge construction is the bottleneck.

**Phase to address:** Phase 2 (PCB spatial model) if NetGraph is reused for spatial queries.

---

### Pitfall 14: Placement Graph Uses Estimated Component Size as Scalar -- Real Footprints Have Non-Square Bounding Boxes

**What goes wrong:**
`_estimate_size_inline()` returns a single float, and `positions_to_boxes()` uses it as both width and height (`half_w = size / 2.0`, `half_h = size / 2.0`). Real footprints have different widths and heights. A SOIC-8 IC (5mm x 6mm) gets treated as a 5mm x 5mm square (or 6mm x 6mm depending on the heuristic). This distorts clearance calculations and thermal area estimates.

**Why it happens:**
The placement graph was built for training data where precise geometry doesn't matter. The `estimated_size` scalar is sufficient for synthetic boards but insufficient for production DRC intelligence.

**Prevention:**
1. Replace `estimated_size: float` with `estimated_bbox: tuple[float, float]` (width, height) in the placement graph
2. Update `positions_to_boxes()` to use per-axis sizes
3. This is related to Pitfall 6 (component size estimation) -- both should be addressed together

**Detection:**
Check placement results for a board with both SOIC and QFP packages. Verify that clearance violations are detected correctly along both axes.

**Phase to address:** Phase 3 (layout-aware placement).

---

### Pitfall 15: DFM Check Timing -- DFM Runs After Layout Is Complete, But Some DFM Issues Require Layout Changes

**What goes wrong:**
DFM checks are typically run after PCB layout is complete (export gerbers, run DFM). But some DFM issues (insufficient solder mask expansion, annular ring too small, thermal relief spokes too narrow) require footprint changes that should have been made before placement. Running DFM only at the end means users discover problems too late to fix them easily.

**Why it happens:**
The natural pipeline is: schematic -> placement -> routing -> DRC -> export -> DFM. But DFM-aware design requires earlier checks: footprint selection (before placement), pad geometry (before routing), and board stackup (before anything).

**Prevention:**
1. Offer DFM checks at multiple stages: footprint selection stage (pad geometry), placement stage (component spacing for assembly), post-routing (manufacturing constraints)
2. The earliest DFM check should be "footprint audit" -- verify all footprints meet manufacturer capabilities before placement begins
3. Post-routing DFM should focus on trace/drill constraints that depend on the actual layout

**Detection:**
Run a complete DFM audit on a board with known manufacturing issues. Verify that footprint-level issues are caught before placement.

**Phase to address:** Phase 5 (DFM) -- design the DFM API to support multi-stage checking.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation | Phase to Address |
|-------------|---------------|------------|-----------------|
| Constraint propagation schema design | Circular dependencies (Pitfall 3) | Unidirectional propagation, Constraint DAG with cycle detection | Phase 1 |
| Constraint propagation net class mapping | KiCad net class gaps (Pitfall 11) | Separate net class vs. extended constraints, sidecar storage | Phase 1 |
| Schematic-to-PCB coordinate bridge | Y-axis flip (Pitfall 2) | Explicit coordinate converter, tested against real project | Phase 1 |
| PCB spatial model layer handling | Layer name canonicalization (Pitfall 5) | LayerClassifier utility, regex for inner layers | Phase 2 |
| PCB spatial model mutability | STRtree rebuild cost (Pitfall 10) | Dirty flag, batch mutations, document rebuild cost | Phase 2 |
| PCB spatial model board outline | Arc/complex outline handling (Pitfall 12) | Shapely polygon from all Edge.Cuts elements | Phase 2 |
| Component geometry for placement | Heuristic size estimation (Pitfall 6) | Real footprint bounding box extraction | Phase 3 |
| Thermal-aware placement | Missing power dissipation data (Pitfall 9) | Opt-in thermal profiles, graceful degradation | Phase 3 |
| Bounding box shape | Scalar size vs. real width/height (Pitfall 14) | Per-axis bounding boxes | Phase 3 |
| DRC spatial violation parsing | Report format changes (Pitfall 8) | Schema version check, defensive parsing | Phase 4 |
| DRC clearance precision | Shapely floating-point noise (Pitfall 4) | Explicit tolerance constant, rounded comparisons | Phase 4 |
| DFM manufacturer rules | Vendor-specific hardcoding (Pitfall 7) | ManufacturerCapabilities profiles, config files | Phase 5 |
| DFM check timing | Late discovery of footprint issues (Pitfall 15) | Multi-stage DFM (footprint audit, placement check, post-route) | Phase 5 |

## Recommended Implementation Order (Pitfall-Aware)

Based on pitfall severity and dependency:

1. **Phase 1: Constraint Propagation** -- Must address Pitfalls 2, 3, 11
   - Coordinate converter (Pitfall 2) -- foundational for all spatial features
   - Unidirectional constraint DAG (Pitfall 3) -- prevents architectural rework
   - Net class vs. extended constraint separation (Pitfall 11) -- prevents dead-end design
   - UUID safety enforcement (Pitfall 1) -- continuous concern

2. **Phase 2: PCB Spatial Model** -- Must address Pitfalls 4, 5, 10, 12
   - LayerClassifier utility (Pitfall 5) -- needed by all spatial queries
   - Board outline polygon (Pitfall 12) -- needed by DFM and placement
   - Dirty-flag mutable spatial index (Pitfall 10) -- needed for iterative workflows
   - Clearance tolerance constant (Pitfall 4) -- needed by DRC and DFM

3. **Phase 3: Layout-Aware Placement** -- Must address Pitfalls 6, 9, 14
   - Real footprint geometry extraction (Pitfall 6) -- prerequisite for thermal analysis
   - Per-axis bounding boxes (Pitfall 14) -- prerequisite for accurate clearance
   - Thermal profile opt-in design (Pitfall 9) -- prevents misleading "intelligence"

4. **Phase 4: DRC Intelligence** -- Must address Pitfalls 4, 8
   - DRC report schema version check (Pitfall 8) -- prevents silent breakage
   - Clearance tolerance in DRC checks (Pitfall 4) -- prevents false positives

5. **Phase 5: DFM** -- Must address Pitfalls 7, 15
   - ManufacturerCapabilities profiles (Pitfall 7) -- prevents vendor lock-in
   - Multi-stage DFM API (Pitfall 15) -- prevents late discovery

## Sources

- Direct codebase analysis: `src/volta/ir/pcb_ir.py` (812 lines), `src/volta/spatial/primitives.py` (165 lines), `src/volta/spatial/query.py` (251 lines)
- Direct codebase analysis: `src/volta/placement/engine.py` (416 lines), `src/volta/placement/graph.py` (368 lines), `src/volta/placement/validation.py` (415 lines)
- Direct codebase analysis: `src/volta/validation/erc_drc.py` (461 lines), `src/volta/validation/spatial_drc.py` (253 lines)
- Direct codebase analysis: `src/volta/crossfile/propagation.py` (182 lines), `src/volta/crossfile/atomic.py` (203 lines)
- Direct codebase analysis: `src/volta/analysis/design_rules.py` (135 lines), `src/volta/analysis/design_rule_engine.py` (148 lines)
- Direct codebase analysis: `src/volta/analysis/net_classifier.py` (220 lines), `src/volta/analysis/intent_schemas.py` (83 lines)
- Direct codebase analysis: `src/volta/routing/constraints.py` (115 lines)
- Direct codebase analysis: `src/volta/analysis/connectivity.py` (132 lines)
- Direct codebase analysis: `src/volta/validation/constants.py` (22 lines)
- Context7: kiutils PCB parsing documentation (`Board.from_file`, `to_file`, Position handling)
- Context7: Shapely STRtree immutability, query predicates, coordinate handling
- Existing project memory: PCB training data sources, component search API research

---
*Full-stack EDA pitfalls research for: volta milestone v3.0 full-stack-eda*
*Researched: 2026-06-01*
*Confidence: HIGH (all pitfalls verified against source code)*
