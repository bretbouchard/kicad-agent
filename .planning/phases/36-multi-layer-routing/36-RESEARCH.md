# Phase 36: Multi-Layer Routing - Research

**Researched:** 2026-05-31
**Domain:** PCB multi-layer routing, impedance control, length matching
**Confidence:** MEDIUM

## Summary

This phase extends the existing single-layer A* routing engine (2D `(x, y)` grid) to support multi-layer PCB routing with `(x, y, layer)` 3D nodes, via placement cost modeling, IPC-2141 impedance-controlled trace width calculation, and sawtooth length-matching patterns. The existing codebase provides a solid foundation: `RoutingGraph` uses networkx, `route_net()` already uses tuple-indexed heuristics that generalize to 3D, `bridge.py` `TrackSegment` already carries a per-segment `layer` field, and `diff_pair.py` has a mature measure-and-refine serpentine loop that can be extended for sawtooth.

The primary technical risk is the 3D graph memory expansion: a 4-layer 100mm board at 0.5mm grid yields ~640k nodes, which exceeds the current `max_nodes=500_000` cap. The planner must either raise the cap or use coarser grid resolution for inner layers. IPC-2141 formulas are closed-form and verified numerically -- bisection inversion for trace width converges in ~20 iterations. Sawtooth geometry is simpler than accordion (triangle vs U-shape) but adds less length per bump.

**Primary recommendation:** Extend `RoutingGraph` to accept a `layers` parameter and build 3D `(x, y, layer)` nodes with via edges between same-xy nodes on adjacent layers. Add `impedance.py` and `length_matching.py` as new modules in the routing package. Keep the existing `diff_pair.py` accordion intact, and share `_interpolate_path` / `_direction_at` helpers from a common `geometry.py` utility module.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** 3D graph approach -- nodes become `(x, y, layer)`, single A* call finds optimal path including layer transitions. Natural extension of existing RoutingGraph.
- **D-02:** Support microstrip (outer layers) and stripline (inner layers) impedance models using IPC-2141 closed-form equations. No external dependencies.
- **D-03:** Add sawtooth pattern to existing accordion serpentine in diff_pair.py. Tolerance in absolute mm. No picosecond tolerance for now.
- **D-04:** Extend existing AutoRouteOp with new fields: `layers: list[str]`, `impedance_target: Optional[float]`, `length_match_pairs: Optional[list[tuple[str, str, float]]]`. Single operation does everything.

### Claude's Discretion
- Exact via cost model weighting (research determines optimal values)
- Grid resolution per layer (may differ for inner vs outer layers)
- Impedance validation threshold (how close calculated Z must be to target)
- Sawtooth amplitude and spacing constraints

### Deferred Ideas (OUT OF SCOPE)
- Coplanar waveguide (CPW) impedance model -- add when RF routing becomes a priority
- Time-based (picosecond) length tolerance -- needs propagation speed calculation from Er
- Freerouting DSN/SES multi-layer integration -- bridge.py exists but this phase focuses on internal routing
- Auto-length-match detection -- automatically identify nets that need matching based on net class
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ROUTE-05 | Multi-layer routing with layer transition cost model and via placement optimization | RQ1 (3D graph) + RQ2 (via cost model) |
| ROUTE-06 | Impedance-controlled routing with stackup-aware trace width calculation | RQ3 (IPC-2141 impedance formulas + bisection inversion) |
| ROUTE-07 | Length-matching engine with serpentine and sawtooth patterns for high-speed signals | RQ4 (sawtooth geometry) + existing accordion in diff_pair.py |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 3D routing graph construction | API / Backend | -- | RoutingGraph is a pure algorithmic component, no UI involvement |
| Via cost modeling | API / Backend | -- | Cost model affects A* edge weights, purely computational |
| Impedance calculation | API / Backend | -- | Closed-form math, no state, pure function domain |
| Trace width inversion (bisection) | API / Backend | -- | Numerical solver, pure function |
| Sawtooth length matching | API / Backend | -- | Geometry generation, extends existing diff_pair pattern |
| Operation schema (AutoRouteOp) | API / Backend | -- | Pydantic schema for JSON operation dispatch |
| Via segment generation | API / Backend | -- | bridge.py TrackSegment extension for layer transitions |
| Stackup parameter access | API / Backend | -- | IR layer/stackup data from kiutils Board object |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| networkx | 3.6.1 | Graph construction and A* pathfinding | Already used by RoutingGraph; verified installed [VERIFIED: python3 import] |
| kiutils | 1.4.8 | KiCad file I/O (Board, Zone, Position) | Already used throughout IR layer [VERIFIED: CLAUDE.md] |
| pydantic | v2 | Operation schema validation | Already used for AutoRouteOp [VERIFIED: _schema_pcb.py] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| math (stdlib) | -- | Trigonometric functions for impedance and geometry | All impedance and sawtooth calculations |
| dataclasses (stdlib) | -- | Frozen result types | RouteResult, DiffPairResult, ViaSegment |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| IPC-2141 closed-form | Saturn PCB Toolkit (external) | External dependency violates D-02 decision |
| Custom A* on 3D graph | Dijkstra with per-layer graphs | D-01 locks 3D single-graph approach |
| Separate impedance module | Inline in graph construction | Separation of concerns: impedance is a pure math domain |

**Installation:**
No new packages needed. All dependencies are already installed.

## Architecture Patterns

### System Architecture Diagram

```
AutoRouteOp (schema)
  |
  v
executor._handle_auto_route()
  |
  +---> build_routing_graph()  -->  RoutingGraph (3D: x,y,layer nodes)
  |         |                           |
  |         |                           +-- same-layer edges (grid_res weight)
  |         |                           +-- via edges (via_cost weight)
  |         |                           +-- DRC penalty edges
  |         |
  |         +---> impedance.calculate_trace_width()  (if impedance_target set)
  |         |         |
  |         |         +-- microstrip_z0() or stripline_z0() via bisection
  |         |
  |         v
  +---> route_all_nets()  -->  A* on 3D graph
  |         |
  |         v
  +---> route_to_segments()  -->  TrackSegment + ViaSegment list
  |         |                        |
  |         |                        +-- extract per-segment layer from 3D path
  |         |                        +-- generate via segments at layer transitions
  |         |
  |         v
  +---> length_matching.add_sawtooth()  (if length_match_pairs set)
  |         |
  |         v
  +---> ir.insert_track_segments()
```

### Recommended Project Structure
```
src/kicad_agent/routing/
  __init__.py          -- Update exports for new modules
  graph.py             -- Extend RoutingGraph to 3D (x,y,layer) nodes
  constraints.py       -- Add layer/stackup/via-cost parameters
  pathfinder.py        -- Update heuristic + RouteResult path type
  impedance.py         -- NEW: IPC-2141 microstrip/stripline + bisection
  length_matching.py   -- NEW: sawtooth pattern (shared with diff_pair.py)
  geometry.py          -- NEW: extract shared _interpolate_path, _direction_at
  diff_pair.py         -- Refactor: extract shared helpers to geometry.py
  bridge.py            -- Add ViaSegment, multi-layer segment extraction
  interactive.py       -- Minimal changes: path type (x,y,layer) support
```

### Pattern 1: 3D Graph Node as Tuple
**What:** NetworkX nodes become `(x: float, y: float, layer: str)` tuples instead of `(x: float, y: float)`.
**When to use:** All routing graph construction for multi-layer boards.
**Example:**
```python
# Current 2D node
node = (10.5, 20.3)

# New 3D node
node = (10.5, 20.3, "F.Cu")
node = (10.5, 20.3, "In1.Cu")

# Via edge connects same (x,y) across adjacent layers
graph.add_edge(
    (10.5, 20.3, "F.Cu"),
    (10.5, 20.3, "In1.Cu"),
    weight=via_cost,  # Higher than same-layer edges
)
```

### Pattern 2: Layer-Independent A* Heuristic
**What:** The `_euclidean_heuristic` function already indexes tuple[0] and tuple[1], ignoring additional dimensions. It works without modification for 3D nodes because it only computes 2D distance.
**When to use:** A* pathfinding on the 3D graph.
**Example:**
```python
# Current heuristic -- already works with 3D nodes!
def _euclidean_heuristic(u, v):
    return math.hypot(u[0] - v[0], u[1] - v[1])
# u[0]=x, u[1]=y, u[2]=layer is IGNORED (correct: via cost in edge weight)
```

### Pattern 3: Frozen Dataclass for Immutable Results
**What:** All routing results use `@dataclass(frozen=True)`. New types follow this pattern.
**When to use:** ViaSegment, ImpedanceResult, LengthMatchResult.
**Example:**
```python
@dataclass(frozen=True)
class ViaSegment:
    """A single via connecting two copper layers."""
    x: float
    y: float
    from_layer: str
    to_layer: str
    diameter: float
    drill: float
    net: str
```

### Pattern 4: Measure-and-Refine Convergence Loop
**What:** Existing `_add_serpentining()` uses up to 10 iterations with proportional amplitude scaling. Sawtooth follows the same pattern.
**When to use:** Sawtooth length matching implementation.
**Example:**
```python
for _ in range(10):  # Up to 10 refinement iterations
    result = _generate_sawtooth_bumps(path, amplitude, ...)
    actual_delta = _path_length(result) - total_len
    if close_enough(actual_delta, target_delta):
        break
    amplitude = amplitude * (target_delta / actual_delta)
```

### Anti-Patterns to Avoid
- **Flat layer encoding as string in node:** Do NOT encode layer as a numeric index inside the coordinate. Use a proper 3-tuple `(x, y, layer_string)` so layer names match KiCad conventions (`"F.Cu"`, `"In1.Cu"`).
- **Modifying the heuristic to consider layer distance:** The A* heuristic must remain admissible (never overestimate). Adding layer distance to the heuristic makes it inadmissible and can produce suboptimal paths. Via cost belongs in edge weights only.
- **Separate graph per layer:** D-01 explicitly locks the single 3D graph approach. Do not build per-layer graphs with manual via stitching.
- **Mutating frozen dataclasses:** All result types are frozen. Create new instances, never modify existing ones.
- **Duplicating geometry helpers:** `_interpolate_path` and `_direction_at` are used by both accordion and sawtooth. Extract to `geometry.py` -- do not copy them.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| A* pathfinding on 3D graph | Custom priority queue with layer transitions | `nx.astar_path()` on 3D graph | networkx 3.6.1 already handles arbitrary hashable nodes; via edges are just weighted edges |
| Impedance trace width inversion | Newton-Raphson or closed-form approximation | Bisection method | IPC-2141 equations are not monotonic over all w/h ratios; bisection is robust and converges in ~20 iterations |
| Length matching convergence | Analytical amplitude calculation | Measure-and-refine loop (10 iterations) | Existing pattern in `_add_serpentining` -- proven convergence, handles edge cases |
| Via S-expression generation | Manual string formatting | Frozen ViaSegment with `to_sexpr()` method | Matches TrackSegment pattern in bridge.py |

**Key insight:** The existing codebase already handles most of the complexity. The 3D graph is a natural extension of the 2D graph (networkx handles it), the heuristic works as-is, and the measure-and-refine loop is proven. The new work is impedance formulas (pure math) and sawtooth geometry (simpler than accordion).

## Common Pitfalls

### Pitfall 1: Node Count Explosion with 3D Graph
**What goes wrong:** A 4-layer 100mm board at 0.5mm grid yields ~640k nodes (4 layers * 200 * 200 * 2 - obstacles), exceeding `max_nodes=500_000`.
**Why it happens:** The 2D graph uses a flat grid. Adding layers multiplies node count by the number of layers.
**How to avoid:** Either raise `max_nodes` to 2_000_000 (still fits in memory -- each node is a small tuple), or use coarser grid resolution for inner layers (Claude's discretion per CONTEXT.md). A 4-layer 50mm board at 0.5mm grid = ~160k nodes, well under cap.
**Warning signs:** `ValueError: Grid would have N nodes, exceeding max_nodes` during construction.

### Pitfall 2: Via Edge Cost Too Low
**What goes wrong:** If via cost is close to same-layer edge cost, A* will zigzag between layers excessively, producing unrealizable boards.
**Why it happens:** Vias have real manufacturing cost (drill precision, reliability, signal integrity degradation). A* will take the cheapest path regardless of physical meaning.
**How to avoid:** Via cost should be 5-20x the grid resolution. At 0.5mm grid, via cost = 2.5-10.0mm equivalent. Typical value: `via_cost = grid_resolution_mm * 10.0`.
**Warning signs:** Routes with more than 3-4 vias for short nets; layer transitions at every grid point.

### Pitfall 3: Inadmissible Heuristic with Layer Penalty
**What goes wrong:** Adding a layer-distance penalty to the A* heuristic makes it inadmissible (overestimates), producing non-optimal paths.
**Why it happens:** It's tempting to "guide" A* toward the target layer by penalizing heuristic distance to wrong-layer nodes.
**How to avoid:** Keep the heuristic as pure 2D Euclidean distance (ignoring layer). Via cost belongs exclusively in edge weights. The heuristic is already correct -- `u[0], u[1]` indexes work on 3-tuples.
**Warning signs:** Paths that are longer than expected; A* explores fewer nodes but produces worse routes.

### Pitfall 4: Sawtooth Detour Ratio Exceeds Manufacturing Limits
**What goes wrong:** Sawtooth bumps with amplitude/spacing ratio > 3:1 create sharp angles that fail manufacturing or cause signal integrity issues.
**Why it happens:** Without explicit detour ratio constraints, the measure-and-refine loop increases amplitude until the target length is reached.
**How to avoid:** Cap `amplitude / half_pitch <= 3.0` (typical manufacturing limit). If target cannot be reached within this ratio, return `valid=False` like accordion does when max amplitude is insufficient.
**Warning signs:** Bumps with very tall, narrow triangles; acute angles < 30 degrees.

### Pitfall 5: Impedance Width Below Minimum Manufacturable Trace
**What goes wrong:** Bisection solver returns a trace width below the PCB fab's minimum (typically 0.1mm for standard, 0.075mm for advanced).
**Why it happens:** High target impedance (e.g., 100 ohm) on thin dielectric requires very narrow traces.
**How to avoid:** Clamp the bisection search range `[min_width, max_width]` where `min_width = 0.1mm`. If bisection hits the floor, return the minimum and report `achieved_z != target_z`.
**Warning signs:** Trace widths below 0.1mm; impedance target not met.

### Pitfall 6: Forgetting to Update `bridge.py` for Via Segments
**What goes wrong:** 3D paths with layer transitions are converted to flat TrackSegments, losing the via information.
**Why it happens:** `route_to_segments()` currently applies a single `layer` parameter to all segments.
**How to avoid:** When path nodes are `(x, y, layer)` tuples, detect layer transitions between consecutive path points and insert both a TrackSegment (ending at transition) and a ViaSegment (connecting layers).
**Warning signs:** All routed segments on the same layer despite multi-layer routing; no vias in the output.

## Code Examples

### RQ1: 3D Graph Extension (graph.py changes)

```python
# Source: Adapted from existing graph.py + CONTEXT.md D-01
# Key change: nodes become (x, y, layer) tuples

class RoutingGraph:
    def __init__(
        self,
        board_bounds: tuple[float, float, float, float],
        obstacles: list,
        constraints: RoutingConstraints | None = None,
        query_engine: SpatialQueryEngine | None = None,
        layers: list[str] | None = None,  # NEW
    ) -> None:
        # ... existing validation ...
        active_layers = layers or ["F.Cu"]  # Default single-layer backward compat

        # Build obstacle geometries (same as current) ...

        # Generate grid nodes -- now 3D
        nodes: list[tuple[float, float, str]] = []
        for layer in active_layers:
            for gx in xs:
                for gy in ys:
                    pt = ShapelyPoint(gx, gy)
                    inside = any(pt.within(geom) for geom in obstacle_geoms)
                    if not inside:
                        nodes.append((gx, gy, layer))

        if len(nodes) > self.constraints.max_nodes:
            raise ValueError(...)

        self._graph.add_nodes_from(nodes)
        node_set = set(nodes)

        # Same-layer edges (4-directional, same as current but 3D nodes)
        for gx, gy, layer in nodes:
            for dx, dy in ((grid_res, 0), (0, grid_res)):
                neighbor = (round(gx + dx, 6), round(gy + dy, 6), layer)
                if neighbor not in node_set:
                    continue
                # ... DRC check and cost calculation (same as current) ...
                self._graph.add_edge((gx, gy, layer), neighbor, weight=cost)

        # Via edges between adjacent layers at same (x, y)
        via_cost = self.constraints.via_cost_mm  # NEW field on RoutingConstraints
        for i in range(len(active_layers) - 1):
            layer_a = active_layers[i]
            layer_b = active_layers[i + 1]
            for gx, gy in xs:
                for gy_val in ys:
                    # Use gy_val from the outer loop (renamed to avoid shadow)
                    pass
            # More efficient: iterate existing nodes
            layer_a_nodes = {(gx, gy) for gx, gy, l in nodes if l == layer_a}
            for gx, gy, l in nodes:
                if l == layer_b and (gx, gy) in layer_a_nodes:
                    self._graph.add_edge(
                        (gx, gy, layer_a),
                        (gx, gy, layer_b),
                        weight=via_cost,
                    )
```

### snap_to_node with Layer Support

```python
# Source: Adapted from existing graph.py snap_to_node
def snap_to_node(
    self, x: float, y: float, layer: str | None = None
) -> tuple[float, float, str] | None:
    """Find nearest grid node, optionally on a specific layer."""
    grid_res = self.constraints.grid_resolution_mm
    tolerance = grid_res

    gx = round(round(x / grid_res) * grid_res, 6)
    gy = round(round(y / grid_res) * grid_res, 6)

    if layer is not None:
        # Snap to specific layer
        if (gx, gy, layer) in self._graph:
            dist = math.hypot(x - gx, y - gy)
            if dist <= tolerance:
                return (gx, gy, layer)
    else:
        # Original behavior: find nearest node on any layer
        # (backward compatible with 2D callers)
        for node in self._graph.nodes:
            if math.hypot(x - node[0], y - node[1]) <= tolerance:
                if node[0] == gx and node[1] == gy:
                    return node
    return None
```

### mark_path_as_obstacle with 3D Paths

```python
# Source: Adapted from existing graph.py mark_path_as_obstacle
# The existing implementation already uses tuple comparison:
#   self._graph.has_edge(u, v)
# This works for 3D tuples without modification -- just need to
# update the type annotation.
def mark_path_as_obstacle(
    self, path: tuple[tuple[float, float, str], ...]
) -> None:
    """Remove edges along a routed 3D path."""
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        if self._graph.has_edge(u, v):
            self._graph.remove_edge(u, v)
```

### RQ2: Via Cost Model (constraints.py additions)

```python
# Source: CONTEXT.md D-01 + domain knowledge [ASSUMED]
# Via cost model based on manufacturing and signal integrity factors

@dataclass(frozen=True)
class RoutingConstraints:
    # ... existing fields ...

    # NEW: Multi-layer parameters
    via_cost_mm: float = 5.0  # Equivalent distance cost for a single via
    # Typical range: 2.5-10.0mm (5-20x grid resolution at 0.5mm)
    # Manufacturing factors:
    #   - Via drill precision cost
    #   - Reliability (each via is a failure point)
    #   - Signal integrity (via stubs cause reflections at high speed)
    #   - Layer 1->2 cheaper than 1->3 (fewer drilled layers)

    # NEW: Layer-specific trace widths (populated by impedance solver)
    layer_trace_widths: dict[str, float] | None = None
    # Key: "F.Cu", "In1.Cu", etc.
    # Value: calculated trace width in mm for impedance target

    # NEW: Stackup parameters for impedance calculation
    dielectric_constant: float = 4.5  # FR4 typical
    dielectric_height_mm: float = 0.2  # Prepreg thickness
    copper_thickness_mm: float = 0.035  # 1 oz copper

    def effective_trace_width(self, layer: str) -> float:
        """Get trace width for a specific layer (impedance-adjusted)."""
        if self.layer_trace_widths and layer in self.layer_trace_widths:
            return self.layer_trace_widths[layer]
        return self.trace_width_mm
```

### RQ3: IPC-2141 Impedance Formulas (new impedance.py)

```python
# Source: IPC-2141 standard formulas [ASSUMED -- verified numerically]
# Verified: microstrip_z0(w=0.47, h=0.2, t=0.035, er=4.5) = 50.00 ohm

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ImpedanceResult:
    """Result of impedance-controlled trace width calculation."""
    trace_width_mm: float
    target_z0: float
    achieved_z0: float
    impedance_error_percent: float
    model: str  # "microstrip" or "stripline"
    valid: bool


def microstrip_z0(w: float, h: float, t: float, er: float) -> float:
    """IPC-2141 surface microstrip impedance.

    Args:
        w: Trace width in mm.
        h: Dielectric height (trace to reference plane) in mm.
        t: Copper thickness in mm.
        er: Dielectric constant (relative permittivity).

    Returns:
        Characteristic impedance Z0 in ohms.
    """
    eff_er = ((er + 1) / 2
              + (er - 1) / 2 * math.pow(1 + 12 * h / w, -0.5))
    z0 = (87 / math.sqrt(eff_er)
          * math.log(5.98 * h / (0.8 * w + t)))
    return z0


def stripline_z0(w: float, h: float, t: float, er: float) -> float:
    """IPC-2141 symmetric stripline impedance.

    Args:
        w: Trace width in mm.
        h: Distance between reference planes / 2 (half-height) in mm.
        t: Copper thickness in mm.
        er: Dielectric constant.

    Returns:
        Characteristic impedance Z0 in ohms.
    """
    z0 = (60 / math.sqrt(er)
          * math.log(1.9 * (2 * h + t) / (0.8 * w + t)))
    return z0


def solve_trace_width(
    target_z0: float,
    h: float,
    t: float,
    er: float,
    model: str = "microstrip",
    tolerance_percent: float = 1.0,
    min_width: float = 0.1,
    max_width: float = 2.0,
) -> ImpedanceResult:
    """Find trace width for target impedance using bisection.

    Converges in ~20 iterations for 1% tolerance.

    Args:
        target_z0: Target characteristic impedance in ohms.
        h: Dielectric height in mm.
        t: Copper thickness in mm.
        er: Dielectric constant.
        model: "microstrip" or "stripline".
        tolerance_percent: Acceptable impedance error as percentage.
        min_width: Minimum manufacturable trace width in mm.
        max_width: Maximum trace width in mm.

    Returns:
        ImpedanceResult with calculated width and achieved impedance.
    """
    z_func = microstrip_z0 if model == "microstrip" else stripline_z0

    lo, hi = min_width, max_width
    best_w = (lo + hi) / 2

    for _ in range(50):  # Convergence guaranteed in <30
        mid = (lo + hi) / 2
        z = z_func(mid, h, t, er)

        if abs(z - target_z0) / target_z0 * 100 < tolerance_percent:
            best_w = mid
            break

        # Z0 decreases with increasing w (wider trace = lower impedance)
        if z > target_z0:
            lo = mid  # Need wider trace
        else:
            hi = mid  # Need narrower trace
        best_w = mid

    achieved_z = z_func(best_w, h, t, er)
    error_pct = abs(achieved_z - target_z0) / target_z0 * 100

    return ImpedanceResult(
        trace_width_mm=round(best_w, 4),
        target_z0=target_z0,
        achieved_z0=round(achieved_z, 2),
        impedance_error_percent=round(error_pct, 2),
        model=model,
        valid=error_pct <= tolerance_percent,
    )
```

### RQ4: Sawtooth Length Matching (new length_matching.py)

```python
# Source: Derived from existing accordion pattern in diff_pair.py + CONTEXT.md D-03

import math


def _sawtooth_extra_length(amplitude: float, half_pitch: float) -> float:
    """Compute extra length from a single sawtooth (triangle) bump.

    A sawtooth replaces a straight segment of length 2*half_pitch with
    two diagonal legs forming a triangle: out-diagonal, return-diagonal.

    Args:
        amplitude: Perpendicular height of the triangle in mm.
        half_pitch: Half the bump span along the path in mm.

    Returns:
        Extra length added by the bump beyond the straight segment.
    """
    leg = math.hypot(half_pitch, amplitude)
    return 2 * leg - 2 * half_pitch


def _generate_sawtooth_bumps(
    path: tuple[tuple[float, float], ...],
    num_bumps: int,
    amplitude: float,
    bump_pitch: float,
    margin: float,
    half_pitch: float,
    total_len: float,
) -> tuple[tuple[float, float], ...]:
    """Generate sawtooth (triangle) bumps along a path.

    Uses the same interpolation framework as accordion but generates
    triangle shapes instead of U-shapes. Each bump is a single triangle
    peak perpendicular to the path direction.

    Args:
        path: Original path waypoints (x, y).
        num_bumps: Number of bumps to insert.
        amplitude: Perpendicular height of each triangle.
        bump_pitch: Distance between bump centers.
        margin: Start/end margin along the path.
        half_pitch: Half the bump span along the path.
        total_len: Total arc length of the path.

    Returns:
        New path tuple with sawtooth bumps inserted.
    """
    # Uses _interpolate_path and _direction_at from geometry.py
    from kicad_agent.routing.geometry import _interpolate_path, _direction_at

    if amplitude < 1e-9:
        return path

    usable_length = total_len - 2.0 * margin
    spacing_between = usable_length / num_bumps
    bump_positions = [
        margin + spacing_between * (i + 0.5)
        for i in range(num_bumps)
    ]

    new_points: list[tuple[float, float]] = [path[0]]

    for bp in bump_positions:
        # Triangle: start -> peak -> end
        start_pts = _interpolate_path(path, [max(0.0, bp - half_pitch)])
        peak_pts = _interpolate_path(path, [bp])
        end_pts = _interpolate_path(path, [min(total_len, bp + half_pitch)])

        start_pt = start_pts[0]
        peak_pt = peak_pts[0]
        end_pt = end_pts[0]

        _, _, px, py = _direction_at(path, bp)

        # Peak is perpendicular offset from path center
        peak_x = peak_pt[0] + px * amplitude
        peak_y = peak_pt[1] + py * amplitude

        new_points.append((round(start_pt[0], 6), round(start_pt[1], 6)))
        new_points.append((round(peak_x, 6), round(peak_y, 6)))
        new_points.append((round(end_pt[0], 6), round(end_pt[1], 6)))

    new_points.append(path[-1])
    return tuple(new_points)


def add_sawtooth_matching(
    path: tuple[tuple[float, float], ...],
    target_delta_mm: float,
    spacing_mm: float,
    max_detour_ratio: float = 3.0,
) -> tuple[tuple[float, float], ...]:
    """Add sawtooth bumps to a path for length matching.

    Follows the same measure-and-refine pattern as _add_serpentining
    in diff_pair.py. Sawtooth adds less length per bump than accordion
    but creates gentler geometry for high-speed signals.

    Args:
        path: Original path as (x, y) waypoints.
        target_delta_mm: Additional length to add in mm.
        spacing_mm: Target pair spacing, bounds amplitude.
        max_detour_ratio: Maximum amplitude/half_pitch ratio (default 3.0).

    Returns:
        New path tuple with sawtooth bumps.
    """
    if target_delta_mm <= 0 or len(path) < 2:
        return path

    total_len = _path_length(path)
    if total_len < 1e-9:
        return path

    bump_pitch = max(spacing_mm, 0.5)
    half_pitch = bump_pitch * 0.5
    max_amplitude = half_pitch * max_detour_ratio
    max_bumps = 50

    margin = bump_pitch * 0.5
    usable_length = total_len - 2.0 * margin
    if usable_length < bump_pitch:
        return path

    num_bumps = min(int(usable_length / bump_pitch), max_bumps)
    if num_bumps < 1:
        return path

    amplitude = max_amplitude
    effective_target = target_delta_mm * 1.01  # 1% overshoot for convergence

    for _ in range(10):  # Up to 10 refinement iterations
        result = _generate_sawtooth_bumps(
            path, num_bumps, amplitude, bump_pitch,
            margin, half_pitch, total_len,
        )
        actual_delta = _path_length(result) - total_len

        if abs(actual_delta - effective_target) < 0.01:
            break

        if actual_delta > 0:
            amplitude = max(
                0.0,
                min(max_amplitude, amplitude * effective_target / actual_delta),
            )
        else:
            amplitude = max_amplitude

    return _generate_sawtooth_bumps(
        path, num_bumps, amplitude, bump_pitch,
        margin, half_pitch, total_len,
    )
```

### AutoRouteOp Schema Extension

```python
# Source: CONTEXT.md D-04 + existing _schema_pcb.py

class AutoRouteOp(BaseModel):
    """Auto-route nets on a PCB with optional multi-layer and impedance control."""

    op_type: Literal["auto_route"] = "auto_route"
    target_file: TargetFile
    nets: list[str] = Field(default_factory=list, description="Net names to route")
    layer: str = Field(
        default="F.Cu", pattern=r"^(?:[FB]\.Cu|In[1-9]\d*\.Cu)$",
        description="Target copper layer (single-layer backward compat)",
    )
    # NEW: Multi-layer routing
    layers: list[str] = Field(
        default_factory=list,
        description="Target copper layers for multi-layer routing. "
                    "Empty = use 'layer' field (single-layer mode).",
    )
    impedance_target: Optional[float] = Field(
        default=None, gt=0, le=200,
        description="Target impedance in ohms (e.g., 50.0 for controlled impedance)",
    )
    length_match_pairs: Optional[list[tuple[str, str, float]]] = Field(
        default=None,
        description="Net pairs for length matching: "
                    "[(net_a, net_b, tolerance_mm), ...]",
    )
```

### ViaSegment and Multi-Layer bridge.py

```python
# Source: Adapted from existing bridge.py TrackSegment + CONTEXT.md D-01

@dataclass(frozen=True)
class ViaSegment:
    """A single via connecting two copper layers."""

    x: float
    y: float
    from_layer: str
    to_layer: str
    diameter: float
    drill: float
    net: str

    def to_sexpr(self, uuid_tag: str = "") -> str:
        """Serialize to KiCad via S-expression."""
        parts = [
            f"  (via",
            f"    (at {self.x:.4f} {self.y:.4f})",
            f"    (size {self.diameter:.4f})",
            f"    (drill {self.drill:.4f})",
            f'    (layers "{self.from_layer}" "{self.to_layer}")',
        ]
        if self.net:
            parts.append(f'    (net 0 "{self.net}")')
        if uuid_tag:
            parts.append(f"    (uuid {uuid_tag})")
        parts.append("  )")
        return "\n".join(parts)


def route_to_segments_multilayer(
    results: dict[str, RouteResult],
    constraints: RoutingConstraints | None = None,
) -> list[TrackSegment | ViaSegment]:
    """Convert 3D routing results to track + via segments.

    Detects layer transitions in 3D paths and generates ViaSegments.
    """
    constraints = constraints or RoutingConstraints()
    segments: list[TrackSegment | ViaSegment] = []

    for net_name, result in results.items():
        if not result.success or len(result.path) < 2:
            continue

        for i in range(len(result.path) - 1):
            p0 = result.path[i]
            p1 = result.path[i + 1]

            # 3D path: (x, y, layer)
            if len(p0) == 3 and p0[2] != p1[2]:
                # Layer transition -- generate via
                segments.append(ViaSegment(
                    x=round(p0[0], 4),
                    y=round(p0[1], 4),
                    from_layer=p0[2],
                    to_layer=p1[2],
                    diameter=constraints.via_diameter_mm,
                    drill=constraints.via_drill_mm,
                    net=net_name,
                ))
            else:
                # Same-layer segment
                layer = p0[2] if len(p0) == 3 else "F.Cu"
                segments.append(TrackSegment(
                    start_x=round(p0[0], 4),
                    start_y=round(p0[1], 4),
                    end_x=round(p1[0], 4),
                    end_y=round(p1[1], 4),
                    width=constraints.effective_trace_width(layer),
                    layer=layer,
                    net=net_name,
                ))
    return segments
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Separate routing per layer | 3D graph with unified A* | Established practice | Single A* call finds globally optimal multi-layer path |
| Fixed trace width | Impedance-calculated width | IPC-2141 standard | Controlled-impedance routing for high-speed designs |
| Accordion-only length matching | Accordion + sawtooth | Modern PCB practice | Sawtooth has better signal integrity for very high speed |
| Via cost = 0 (free layer transitions) | Weighted via edges | Routing literature | Prevents unrealistic via-heavy routes |

**Deprecated/outdated:**
- Manual impedance tables: replaced by IPC-2141 closed-form equations in code
- Single-layer routing assumption: `layer` field on AutoRouteOp defaults to `"F.Cu"` but `layers` list enables multi-layer

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | IPC-2141 microstrip formula: `Z0 = 87/sqrt(Eeff) * ln(5.98*h/(0.8*w+t))` with `Eeff = (Er+1)/2 + (Er-1)/2*(1+12*h/w)^(-0.5)` | RQ3 Impedance | Wrong impedance calculations, DRC failures |
| A2 | IPC-2141 stripline formula: `Z0 = 60/sqrt(Er) * ln(1.9*(2*h+t)/(0.8*w+t))` | RQ3 Impedance | Same as A1 |
| A3 | Via cost of 5-10x grid resolution is typical for PCB routing | RQ2 Via Cost | Under/over-costed vias producing unrealizable or suboptimal routes |
| A4 | Sawtooth max detour ratio of 3:1 is a standard manufacturing constraint | RQ4 Sawtooth | Bumps may fail manufacturing if ratio is too aggressive |
| A5 | Bisection convergence in ~20 iterations for impedance inversion | RQ3 Impedance | Performance concern if convergence is slower |
| A6 | kiutils Board object exposes layer/stackup information | Architecture | Cannot read board stackup for impedance parameters |

**If this table is empty:** All claims in this research were verified or cited -- no user confirmation needed.

## Open Questions

1. **Stackup parameter source**
   - What we know: CONTEXT.md mentions "dielectric constant (Er) -- could be a stackup parameter or come from design rules". kiutils Board object has `.setup` which may contain stackup info.
   - What's unclear: Whether the existing IR exposes stackup parameters or if they must be user-supplied.
   - Recommendation: Add stackup parameters to `RoutingConstraints` with sensible FR4 defaults (Er=4.5, h=0.2mm, t=0.035mm). Let AutoRouteOp override these via the constraints flow.

2. **Layer ordering for via cost asymmetry**
   - What we know: CONTEXT.md gives Claude discretion on via cost weighting. In real PCBs, F.Cu-to-In1.Cu is cheaper than F.Cu-to-In2.Cu (blind via vs through-hole via).
   - What's unclear: Whether to implement per-layer-pair via costs or a single flat cost.
   - Recommendation: Start with flat `via_cost_mm` in RoutingConstraints. Per-layer-pair costs are an enhancement for Claude's discretion.

3. **Graph memory for large boards**
   - What we know: 50mm 4-layer at 0.5mm grid = ~160k nodes (safe). 100mm 4-layer at 0.5mm = ~640k nodes (over cap).
   - What's unclear: Typical board sizes users will route.
   - Recommendation: Raise `max_nodes` to 2_000_000 and validate `__post_init__` allows it. Memory impact: ~200MB for 2M nodes with edges, well within modern limits.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies identified -- all changes are to existing Python code with already-installed packages: networkx 3.6.1, kiutils, pydantic v2, math stdlib)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none -- see Wave 0 |
| Quick run command | `python3 -m pytest tests/test_routing.py -x -q` |
| Full suite command | `python3 -m pytest tests/test_routing.py -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ROUTE-05 | 3D graph builds with multiple layers | unit | `pytest tests/test_routing.py::test_3d_graph_construction -x` | Wave 0 |
| ROUTE-05 | Via edges connect same-xy across layers | unit | `pytest tests/test_routing.py::test_via_edges -x` | Wave 0 |
| ROUTE-05 | A* routes through via transitions | unit | `pytest tests/test_routing.py::test_multilayer_route -x` | Wave 0 |
| ROUTE-05 | Via cost is higher than same-layer edges | unit | `pytest tests/test_routing.py::test_via_cost_model -x` | Wave 0 |
| ROUTE-06 | Microstrip impedance calculation | unit | `pytest tests/test_routing.py::test_microstrip_z0 -x` | Wave 0 |
| ROUTE-06 | Stripline impedance calculation | unit | `pytest tests/test_routing.py::test_stripline_z0 -x` | Wave 0 |
| ROUTE-06 | Trace width bisection convergence | unit | `pytest tests/test_routing.py::test_impedance_bisection -x` | Wave 0 |
| ROUTE-07 | Sawtooth bump extra length calculation | unit | `pytest tests/test_routing.py::test_sawtooth_extra_length -x` | Wave 0 |
| ROUTE-07 | Sawtooth measure-and-refine convergence | unit | `pytest tests/test_routing.py::test_sawtooth_matching -x` | Wave 0 |
| ROUTE-07 | Sawtooth detour ratio capping | unit | `pytest tests/test_routing.py::test_sawtooth_max_ratio -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_routing.py -x -q`
- **Per wave merge:** `python3 -m pytest tests/test_routing.py -v`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_routing.py` -- add tests for 3D graph, impedance, sawtooth (existing file needs extension)
- [ ] `tests/conftest.py` -- shared routing fixtures (exists, may need multi-layer additions)

## Security Domain

> This phase is a pure algorithmic extension to the routing engine. No user input handling, no network access, no credentials, no external service interaction. Security enforcement is not applicable.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | -- |
| V3 Session Management | no | -- |
| V4 Access Control | no | -- |
| V5 Input Validation | yes | Pydantic schema validation on AutoRouteOp fields |
| V6 Cryptography | no | -- |

### Known Threat Patterns for PCB Routing Engine

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed AutoRouteOp fields | Tampering | Pydantic field validation (gt=0, pattern match on layer names) |
| Excessive graph size (DoS) | Denial of Service | max_nodes cap on RoutingConstraints |
| Invalid impedance parameters | Tampering | Bisection bounds clamping (min_width, max_width) |

## Sources

### Primary (HIGH confidence)
- Codebase: `src/kicad_agent/routing/graph.py` -- RoutingGraph class, node/edge construction, DRC penalty
- Codebase: `src/kicad_agent/routing/pathfinder.py` -- A* pathfinding, heuristic, RouteResult
- Codebase: `src/kicad_agent/routing/diff_pair.py` -- Accordion serpentine, measure-and-refine loop, geometry helpers
- Codebase: `src/kicad_agent/routing/bridge.py` -- TrackSegment, route_to_segments, S-expression generation
- Codebase: `src/kicad_agent/routing/constraints.py` -- RoutingConstraints frozen dataclass
- Codebase: `src/kicad_agent/ops/_schema_pcb.py` -- AutoRouteOp Pydantic schema
- Codebase: `src/kicad_agent/ops/executor.py` -- _handle_auto_route handler
- VERIFIED: `python3 -c "import networkx; print(networkx.__version__)"` = 3.6.1
- VERIFIED: IPC-2141 microstrip formula numerically: w=0.4697mm gives Z0=50.00 ohm at h=0.2mm, Er=4.5
- VERIFIED: IPC-2141 stripline formula numerically: w=0.0921mm gives Z0=50.00 ohm at h=0.15mm, Er=4.5
- VERIFIED: Sawtooth extra length: 0.281mm vs accordion 0.691mm at same amplitude/pitch

### Secondary (MEDIUM confidence)
- [ASSUMED] IPC-2141 formula coefficients (87, 5.98, 0.8, 60, 1.9) -- verified numerically but not against the official IPC-2141 publication document
- [ASSUMED] Via cost range 5-20x grid resolution based on PCB routing literature
- [ASSUMED] Sawtooth max detour ratio 3:1 based on PCB manufacturing guidelines

### Tertiary (LOW confidence)
- External research (WebSearch, Context7) was unavailable during this session due to API failures. All domain-specific claims are marked [ASSUMED] in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all dependencies already installed and in use
- Architecture: HIGH -- extending existing patterns (3D tuples, frozen dataclasses, measure-and-refine)
- Impedance formulas: MEDIUM -- numerically verified but coefficients from training data, not official IPC-2141 document
- Via cost model: MEDIUM -- reasonable defaults but not benchmarked against real routing results
- Sawtooth geometry: MEDIUM -- derived from existing accordion pattern, not yet tested
- Pitfalls: HIGH -- identified from direct codebase analysis

**Research date:** 2026-05-31
**Valid until:** 2026-06-30 (stable domain -- PCB physics and IPC standards do not change rapidly)
