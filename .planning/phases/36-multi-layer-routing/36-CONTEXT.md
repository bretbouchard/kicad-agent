# Phase 36: Multi-Layer Routing - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Extend the existing single-layer routing engine (A* pathfinder on 2D grid) to support multi-layer PCB routing with impedance control, via placement optimization, and length-matching patterns for high-speed signals. Covers ROUTE-05, ROUTE-06, ROUTE-07.

**In scope:**
- 3D routing graph with layer dimension
- Via placement with layer transition cost model
- Impedance-controlled routing (microstrip + stripline, IPC-2141)
- Length matching with accordion serpentine + sawtooth patterns (mm tolerance)
- Operation schema updates to expose multi-layer routing

**Out of scope:**
- Coplanar waveguide (CPW) impedance models
- Time-based (picosecond) length tolerance
- Integration with external routers (Freerouting DSN/SES)
- GUI-based interactive routing UI
- RF-specific routing constraints

</domain>

<decisions>
## Implementation Decisions

### Routing Algorithm
- **D-01:** 3D graph approach — nodes become `(x, y, layer)`, single A* call finds optimal path including layer transitions. Natural extension of existing RoutingGraph. Memory concern is manageable: 4-layer board at 0.5mm grid on 50mm board = ~160k nodes (under 500k max_nodes cap).

### Impedance Control
- **D-02:** Support microstrip (outer layers) and stripline (inner layers) impedance models using IPC-2141 closed-form equations. No external dependencies. Trace width is calculated from target impedance, dielectric constant, and stackup geometry.

### Length Matching
- **D-03:** Add sawtooth pattern to existing accordion serpentine in diff_pair.py. Tolerance in absolute mm (aligns with existing DiffPairResult.mismatch_mm). No picosecond tolerance for now.

### Operation Schema
- **D-04:** Extend existing AutoRouteOp with new fields: `layers: list[str]` (multi-layer targets), `impedance_target: Optional[float]` (target impedance in ohms), `length_match_pairs: Optional[list[tuple[str, str, float]]]` (net pairs + tolerance mm). Single operation does everything.

### Claude's Discretion
- Exact via cost model weighting (research determines optimal values)
- Grid resolution per layer (may differ for inner vs outer layers)
- Impedance validation threshold (how close calculated Z must be to target)
- Sawtooth amplitude and spacing constraints

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Routing Code (MUST READ)
- `src/kicad_agent/routing/__init__.py` — Routing module public API and exports
- `src/kicad_agent/routing/graph.py` — RoutingGraph class (2D grid, networkx, DRC-aware)
- `src/kicad_agent/routing/constraints.py` — RoutingConstraints frozen dataclass
- `src/kicad_agent/routing/pathfinder.py` — A* pathfinding (route_net, route_all_nets)
- `src/kicad_agent/routing/diff_pair.py` — DiffPairResult, accordion serpentine length matching
- `src/kicad_agent/routing/interactive.py` — InteractiveRoutingSession
- `src/kicad_agent/routing/bridge.py` — Freerouting DSN/SES bridge (existing but out of scope)

### Schema and Executor
- `src/kicad_agent/ops/_schema_pcb.py` — AutoRouteOp schema (line ~135, extend this)
- `src/kicad_agent/ops/executor.py` — Auto-route handler registration
- `src/kicad_agent/ops/schema.py` — Operation union (74 ops, add updated AutoRouteOp)

### PCB IR
- `src/kicad_agent/ir/pcb_ir.py` — PCB IR for board access (zones, layers, stackup)
- `src/kicad_agent/ops/pcb_ops.py` — PCB operation implementations

### Requirements
- `.planning/REQUIREMENTS.md` §ROUTE-05, ROUTE-06, ROUTE-07

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RoutingGraph`: 2D grid-based networkx graph with DRC-aware edge costs — extend to 3D
- `RoutingConstraints`: Frozen dataclass with clearance, trace_width, via dimensions — add layer-specific params
- `route_net()`: A* pathfinder on networkx graph — works on 3D graph with (x,y,layer) nodes
- `route_differential_pair()`: Already does accordion serpentining for length matching
- `DiffPairResult`: Frozen result with mismatch_mm — add sawtooth variant
- `AutoRouteOp` schema: Has nets + layer fields — extend with layers, impedance_target, length_match_pairs

### Established Patterns
- Frozen dataclasses for immutable results (RouteResult, DiffPairResult, RoutingConstraints)
- Lazy imports (networkx, shapely) for graceful degradation
- Operation schema → executor handler → ops function pattern
- RoutingConstraints validation in __post_init__

### Integration Points
- `AutoRouteOp` handler in executor.py calls `pcb_ops.auto_route()`
- `pcb_ops.auto_route()` builds RoutingGraph, calls route_all_nets
- IR layer list available via `ir.board.layers` for multi-layer support
- Net class info (trace width, clearance) available via design rules

</code_context>

<specifics>
## Specific Ideas

- Via cost should be higher than same-layer edge cost (vias are expensive in manufacturing)
- Impedance calculation needs dielectric constant (Er) — could be a stackup parameter or come from design rules
- Existing accordion in diff_pair.py can be refactored into a shared length_matching.py module

</specifics>

<deferred>
## Deferred Ideas

- Coplanar waveguide (CPW) impedance model — add when RF routing becomes a priority
- Time-based (picosecond) length tolerance — needs propagation speed calculation from Er
- Freerouting DSN/SES multi-layer integration — bridge.py exists but this phase focuses on internal routing
- Auto-length-match detection — automatically identify nets that need matching based on net class

</deferred>

---

*Phase: 36-multi-layer-routing*
*Context gathered: 2026-05-31*
