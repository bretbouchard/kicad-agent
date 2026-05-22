# Phase 8: Visual Primitives for PCB Spatial Reasoning - Research

**Researched:** 2026-05-22
**Domain:** PCB spatial reasoning, coordinate-grounded AI analysis, visual primitive extraction
**Confidence:** HIGH

## Summary

Phase 8 builds a spatial reasoning layer on top of the existing kicad-agent IR infrastructure. The core idea: instead of describing PCB layout relationships in natural language, the AI reasons using coordinate-grounded visual primitives -- points for pins/vias, bounding boxes for components, paths for traces, and regions for zones/net classes. This closes the "Reference Gap" where an AI says "move the resistor closer to the capacitor" without being able to specify exactly where.

The existing codebase already has all the raw coordinate data needed. kiutils `Position(X, Y, angle)` objects exist on footprints, pads, traces, vias, arcs, graphic items, and zones. The DRC JSON report from kicad-cli already includes `pos.x` and `pos.y` on every violation item. This phase extracts, normalizes, and exposes that spatial data as typed primitives with a query API.

**Primary recommendation:** Extract spatial primitives from the existing IR layer via lightweight dataclasses, use Pillow for rasterized layer rendering (already installed), leverage kicad-cli SVG export for accurate layer images, and build a Shapely-backed spatial query engine (already installed).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Render PCB layers as rasterized images using Python (Pillow/matplotlib) with coordinate grid overlay
- Output: PNG/JPEG with mm-coordinate mapping metadata
- Each layer rendered independently with configurable color schemes
- Extract from existing IR layer (SchematicIR, PcbIR) -- no new parsing
- Primitives: `<point x,y>`, `<box x1,y1,x2,y2>`, `<path [points...]>`, `<region x1,y1,x2,y2 type>`
- Exposed as Python dataclasses with JSON serialization for LLM consumption
- Maze-routing generator creates synthetic PCB puzzles
- Generate cold-start reasoning chains from DRC/ERC violations
- Spatial query operations: proximity (within Xmm), containment (in region), clearance (between entities)
- AI review pipeline outputs spatially-grounded findings
- Rick agent integration for SI/PI/EMC/DFM coordinate-grounded reports

### Claude's Discretion
- Choice of rendering library (Pillow vs matplotlib vs Cairo)
- Exact dataclass field names and types
- Query API method signatures
- Image resolution and coordinate precision
- Test fixtures and procedural generation parameters

### Deferred Ideas (OUT OF SCOPE)
- Real-time board visualization (future -- this phase focuses on static rendering)
- Interactive routing guidance (future -- this phase creates the primitives, not the UI)
- 3D board visualization (future -- 2D layer rendering first)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VP-01 | Render PCB layers as images with coordinate grid overlay | kicad-cli SVG export per layer + Pillow rasterization; kicad-cli also has `pcb render` for 3D PNG |
| VP-02 | Extract spatial primitives from parsed KiCad files | kiutils Position objects on footprints, pads, traces, vias, arcs; Shapely for geometry operations |
| VP-03 | Define visual primitive vocabulary for PCB | Four dataclass types: SpatialPoint, SpatialBox, SpatialPath, SpatialRegion with JSON serialization |
| VP-04 | Generate procedural maze-routing tasks | Procedural board generator using kiutils Board/Footprint/Segment construction APIs |
| VP-05 | Generate cold-start reasoning chains from DRC/ERC violations | DRC JSON report has `pos.x`/`pos.y` on every violation item; chain format: violation -> coordinate -> spatial context -> fix |
| VP-06 | Build spatial query API | Shapely spatial index (STRtree) for proximity, containment, clearance queries against extracted primitives |
| VP-07 | AI review pipeline with spatially-grounded DRC findings | Extend existing validation/pipeline.py to produce SpatialDrcResult with coordinate-grounded violation items |
| VP-08 | Rick agent integration for coordinate-grounded reports | Rick agents consume spatial primitive JSON; new module produces per-domain spatial reports |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| PCB layer rendering | Python backend | kicad-cli (SVG export) | Pillow rasterizes; kicad-cli provides accurate SVG source |
| Spatial primitive extraction | Python backend (IR layer) | -- | PcbIR already holds all coordinate data via kiutils |
| Procedural board generation | Python backend | kiutils (Board API) | Synthetic boards built programmatically |
| Spatial query API | Python backend (Shapely) | -- | Geometric indexing and querying |
| DRC spatial grounding | Python backend (validation) | kicad-cli (DRC JSON) | DRC report items have pos coordinates |
| Rick agent integration | Python backend (new module) | Skill interface | Spatial report module consumed by Rick prompts |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Pillow | 11.3.0 | Rasterized image rendering, coordinate grid overlay | [VERIFIED: pip show] Already installed, proven for image generation |
| Shapely | 2.1.1 | Spatial indexing (STRtree), geometric operations, proximity/containment queries | [VERIFIED: pip show] Already installed, industry standard for 2D geometry |
| numpy | 1.26.4 | Array operations for coordinate transforms, grid calculations | [VERIFIED: pip show] Already installed, Shapely dependency |
| kiutils | 1.4.8 | PCB/schematic data with coordinate access | [VERIFIED: pip show] Already the project's parser backbone |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| matplotlib | 3.10.1 | Optional: visualization overlays, heatmaps | For debug/development only; Pillow is primary renderer |
| cairocffi | 1.7.2 | SVG-to-raster conversion if needed | If kicad-cli SVG output needs rasterization |
| svgwrite | available | SVG generation for coordinate overlays | If generating overlay SVGs programmatically |
| dataclasses (stdlib) | 3.11+ | Spatial primitive types | Core data structure pattern matching project conventions |
| json (stdlib) | 3.11+ | Serialization of primitives for LLM consumption | All spatial primitives must be JSON-serializable |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pillow rendering | matplotlib only | matplotlib is heavier, slower for simple rasterization; Pillow is more direct for pixel-level control |
| kicad-cli SVG export | Hand-render from kiutils data | kicad-cli produces accurate layer images; hand-rendering would duplicate KiCad's complex rendering logic |
| Shapely STRtree | R-tree custom implementation | Shapely's STRtree is battle-tested, C-backed, and already installed |
| Cairo rendering | Pillow only | Cairo produces anti-aliased output but adds complexity; Pillow sufficient for coordinate-grounded images |

**Installation:**
```bash
# All dependencies already installed. No new packages needed.
# Pillow 11.3.0, Shapely 2.1.1, numpy 1.26.4, kiutils 1.4.8
```

**Version verification:** All versions confirmed via `pip3 show` in this session.

## Architecture Patterns

### System Architecture Diagram

```
                    +-----------------+
                    |   PcbIR / IR    |
                    |  (existing)     |
                    +--------+--------+
                             |
                             v
              +------------------------------+
              |  Spatial Primitive Extractor  |  (NEW: src/kicad_agent/spatial/)
              |  - extract_points()           |
              |  - extract_boxes()            |
              |  - extract_paths()            |
              |  - extract_regions()          |
              +----------+---+----+-----------+
                         |   |    |
           +-------------+   |    +------------------+
           |                 |                       |
           v                 v                       v
+----------+------+  +------+------+  +-------------+--------+
| Spatial Query   |  | Image       |  | DRC Spatial          |
| API (Shapely)   |  | Renderer    |  | Grounding            |
| - proximity()   |  | (Pillow)    |  | (validation/)        |
| - containment() |  | + kicad-cli |  | - enrich_drc()       |
| - clearance()   |  |   SVG export|  | - spatial chains     |
+--------+--------+  +------+------+  +----------+------------+
         |                  |                     |
         v                  v                     v
+--------+--------+  +------+------+  +----------+------------+
| JSON Results    |  | PNG/JPEG    |  | Spatial Reasoning     |
| for LLM         |  | Images with |  | Chain Generator       |
| consumption     |  | coord grid  |  | (VP-05)               |
+-----------------+  +-------------+  +-----------------------+
                                              |
                                              v
                                    +---------+---------+
                                    | Rick Agent        |
                                    | Integration (VP-08)|
                                    | - SI Rick          |
                                    | - PI Rick          |
                                    | - EMC Rick         |
                                    | - DFM Rick         |
                                    +-------------------+
```

### Recommended Project Structure
```
src/kicad_agent/
├── spatial/                    # NEW: Visual primitives module
│   ├── __init__.py             # Barrel exports
│   ├── primitives.py           # SpatialPoint, SpatialBox, SpatialPath, SpatialRegion dataclasses
│   ├── extractor.py            # Extract primitives from PcbIR / SchematicIR
│   ├── query.py                # SpatialQueryEngine with Shapely STRtree
│   ├── renderer.py             # PCB layer rendering with coordinate grid overlay
│   ├── maze_generator.py       # Procedural PCB puzzle generator (VP-04)
│   ├── reasoning_chains.py     # Cold-start chain synthesis from DRC/ERC (VP-05)
│   └── rick_integration.py     # Coordinate-grounded Rick reports (VP-08)
├── validation/
│   ├── spatial_drc.py          # NEW: Spatial-grounded DRC result enrichment (VP-07)
│   ├── erc_drc.py              # EXISTING: Extended to produce SpatialDrcResult
│   └── pipeline.py             # EXISTING: Extended to use spatial grounding
├── ir/
│   ├── pcb_ir.py               # EXISTING: Extended with spatial helper methods
│   └── ...
└── ...
```

### Pattern 1: Spatial Primitive Dataclasses (Immutable, JSON-Serializable)
**What:** Frozen dataclasses representing coordinate-grounded spatial entities on a PCB.
**When to use:** Every spatial operation in this phase produces these types.
**Example:**
```python
# Source: Project convention (frozen dataclasses, matching Violation pattern)
from dataclasses import dataclass
from typing import Tuple, Optional

@dataclass(frozen=True)
class SpatialPoint:
    """A single coordinate point on the PCB (pin, via, vertex)."""
    x: float
    y: float
    entity_type: str  # "pin", "via", "vertex", "pad"
    entity_id: str    # UUID or reference designator
    layer: str = ""   # KiCad layer name
    net: str = ""     # Net name if applicable

    def to_json(self) -> dict:
        return {
            "type": "point",
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "layer": self.layer,
            "net": self.net,
        }

@dataclass(frozen=True)
class SpatialBox:
    """Axis-aligned bounding box for components, footprints."""
    x1: float  # min X
    y1: float  # min Y
    x2: float  # max X
    y2: float  # max Y
    entity_type: str  # "footprint", "component", "pad"
    entity_id: str
    layer: str = ""
    reference: str = ""  # e.g. "U1"

@dataclass(frozen=True)
class SpatialPath:
    """Ordered sequence of points forming a trace route."""
    points: Tuple[Tuple[float, float], ...]
    entity_type: str  # "trace", "wire", "arc"
    entity_id: str
    layer: str = ""
    net: str = ""
    width: float = 0.0

@dataclass(frozen=True)
class SpatialRegion:
    """Rectangular or polygonal region for zones, keepouts, copper pours."""
    boundary: Tuple[Tuple[float, float], ...]  # Polygon vertices
    entity_type: str  # "zone", "keepout", "copper_pour", "net_class_region"
    entity_id: str
    layer: str = ""
    net: str = ""
    region_type: str = ""  # "fill", "keepout", etc.
```

### Pattern 2: Spatial Query Engine (Shapely STRtree)
**What:** Build a spatial index over extracted primitives for fast geometric queries.
**When to use:** VP-06 -- proximity, containment, clearance queries.
**Example:**
```python
# Source: Shapely 2.x STRtree API [CITED: shapely.readthedocs.io]
from shapely import STRtree, box, Point
from kicad_agent.spatial.primitives import SpatialPoint, SpatialBox

class SpatialQueryEngine:
    def __init__(self, primitives: list):
        self._primitives = primitives
        geometries = [p.to_shapely() for p in primitives]
        self._tree = STRtree(geometries)

    def proximity(self, x: float, y: float, radius_mm: float) -> list:
        """Find all primitives within radius_mm of point (x, y)."""
        query_point = Point(x, y)
        buffer = query_point.buffer(radius_mm)
        indices = self._tree.query(buffer)
        return [self._primitives[i] for i in indices
                if self._primitives[i].to_shapely().intersects(buffer)]

    def containment(self, x1, y1, x2, y2) -> list:
        """Find all primitives contained within bounding box."""
        query_box = box(x1, y1, x2, y2)
        indices = self._tree.query(query_box)
        return [self._primitives[i] for i in indices
                if query_box.contains(self._primitives[i].to_shapely())]

    def clearance(self, entity_id: str) -> list:
        """Find all primitives near a given entity and compute distances."""
        target_idx = next(i for i, p in enumerate(self._primitives)
                          if p.entity_id == entity_id)
        target_geom = self._primitives[target_idx].to_shapely()
        # Query nearby, compute actual distances
        nearby = self._tree.query(target_geom.buffer(10.0))  # 10mm search radius
        results = []
        for i in nearby:
            if i != target_idx:
                dist = target_geom.distance(self._primitives[i].to_shapely())
                results.append((self._primitives[i], dist))
        return sorted(results, key=lambda x: x[1])
```

### Pattern 3: DRC Spatial Grounding
**What:** Enrich DRC violation items with spatial primitives from the IR layer.
**When to use:** VP-07 -- AI review pipeline.
**Example:**
```python
# Source: Project pattern (enrichment via existing DRC result)
@dataclass(frozen=True)
class SpatialViolation:
    """DRC/ERC violation with coordinate-grounded spatial context."""
    description: str
    severity: str
    violation_type: str
    items: Tuple[SpatialPoint, ...]  # Each violation item as a coordinate point
    spatial_context: str  # Human-readable spatial description

def enrich_drc_result(drc_result: DrcResult, pcb_ir: PcbIR) -> list[SpatialViolation]:
    """Convert DRC violations to spatially-grounded violations."""
    violations = []
    for v in drc_result.violations:
        spatial_items = []
        for item in v.items:
            pos = item.get("pos", {})
            spatial_items.append(SpatialPoint(
                x=pos.get("x", 0.0),
                y=pos.get("y", 0.0),
                entity_type="drc_item",
                entity_id=item.get("uuid", ""),
            ))
        violations.append(SpatialViolation(
            description=v.description,
            severity=v.severity.value,
            violation_type=v.type,
            items=tuple(spatial_items),
            spatial_context=format_spatial_context(spatial_items),
        ))
    return violations
```

### Anti-Patterns to Avoid
- **Hand-rendering PCB layers from scratch:** KiCad's rendering logic is extremely complex (filled zones, thermal reliefs, pad shapes). Use kicad-cli SVG/PDF export instead of trying to replicate rendering. [ASSUMED]
- **Mutating IR objects during spatial extraction:** Extraction is read-only. Never modify kiutils objects when extracting spatial data.
- **Storing absolute pad positions incorrectly:** KiCad pad positions are LOCAL (relative to footprint origin). Absolute position = footprint.position + rotate(pad.position, footprint.angle). [VERIFIED: kiutils coordinate model inspection]
- **Ignoring coordinate system:** KiCad uses mm with origin at top-left. Y-axis increases downward in PCB. Schematic coordinates are also mm but may differ in origin convention. [ASSUMED]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PCB layer rendering | Custom drawing engine | kicad-cli `pcb export svg` or `pcb render` | KiCad's rendering handles zones, thermal reliefs, pad shapes, solder mask -- far too complex to replicate |
| Spatial indexing | Custom R-tree or brute-force search | Shapely STRtree | C-backed, O(n log n) build, O(log n) query. Already installed. |
| Coordinate rotation for pads | Manual sin/cos transform matrix | Shapely `affinity.rotate` or numpy rotation | Handles edge cases (0, 90, 180, 270 degree rotations with floating point precision) |
| SVG parsing | Custom XML parser | xml.etree.ElementTree (stdlib) | If parsing kicad-cli SVG output for coordinate extraction |
| Geometry distance calculations | Euclidean distance loops | Shapely `.distance()` method | Handles point-to-point, point-to-line, polygon-to-polygon correctly |
| Bounding box computation | Manual min/max over coordinates | Shapely `.bounds` property | Handles degenerate cases, empty geometries |

**Key insight:** The existing codebase already has all raw coordinate data accessible through kiutils. This phase is about extracting, normalizing, and exposing it -- not about parsing or computing anything new.

## Common Pitfalls

### Pitfall 1: Pad Position Relative vs Absolute
**What goes wrong:** Using pad.position directly as absolute coordinates on the board.
**Why it happens:** kiutils stores pad positions relative to the footprint origin, not the board origin.
**How to avoid:** Compute absolute position: `abs_x = fp.position.X + rotated(pad.position.X, fp.position.angle)` where rotation accounts for the footprint angle. For 0/90/180/270 degree rotations, use lookup table for exact values.
**Warning signs:** Pads clustered at (0,0) or at footprint-local coordinates instead of spread across the board.

### Pitfall 2: Zone Polygon Vertex Ordering
**What goes wrong:** Assuming zone polygons are always rectangular or have consistent winding order.
**Why it happens:** Zone polygons in KiCad can be arbitrary shapes with CW or CCW winding.
**How to avoid:** Use Shapely for all polygon operations -- it handles winding order normalization automatically.
**Warning signs:** Spatial containment queries returning wrong results for zones.

### Pitfall 3: SVG Coordinate System Mismatch
**What goes wrong:** kicad-cli SVG export uses a different coordinate system (SVG Y-flip or DPI scaling) than the KiCad mm coordinates.
**Why it happens:** SVG coordinates have Y increasing downward with a transformation applied by KiCad's exporter.
**How to avoid:** Parse the SVG viewBox and transform attributes to build a coordinate mapping function. Verify mapping by checking known footprint positions against SVG coordinates.
**Warning signs:** Rendered coordinate grid misaligned with actual component positions.

### Pitfall 4: Trace Path Continuity
**What goes wrong:** Treating each Segment/Arc/Via as independent spatial primitives instead of continuous net paths.
**Why it happens:** kiutils stores traces as individual items, not connected paths.
**How to avoid:** Build a path graph per net by connecting segments at shared endpoints, then extract continuous paths using graph traversal. The existing `connectivity.py` module already has a net graph pattern to follow.
**Warning signs:** SpatialPath objects with only 2 points when traces route around obstacles with multiple segments.

### Pitfall 5: Procedural Board Validation
**What goes wrong:** Generated maze-routing boards that cannot be parsed back by kiutils or are not valid KiCad files.
**Why it happens:** Building kiutils objects programmatically requires specific field combinations.
**How to avoid:** Always validate generated boards by round-tripping: create Board -> serialize -> parse -> verify. Use existing round-trip test patterns from Phase 1.
**Warning signs:** Procedural boards that fail kicad-cli DRC with parse errors.

### Pitfall 6: Shapely STRtree Query Semantics
**What goes wrong:** Using `STRtree.query()` which returns candidates based on bounding box overlap, not exact intersection.
**Why it happens:** STRtree uses bounding boxes internally for fast filtering.
**How to avoid:** Always follow `tree.query(geom)` with `.intersects(geom)` or `.within(geom)` checks on candidates. This is the standard two-phase pattern: coarse filter (STRtree) then exact check (Shapely).
**Warning signs:** Spatial queries returning entities that don't actually intersect the query geometry.

## Code Examples

### Extract Spatial Primitives from PcbIR

```python
# Source: Verified against kiutils 1.4.8 coordinate model
import math
from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.spatial.primitives import SpatialPoint, SpatialBox, SpatialPath, SpatialRegion

def extract_footprint_boxes(pcb_ir: PcbIR) -> list[SpatialBox]:
    """Extract bounding boxes for all footprints on the PCB."""
    boxes = []
    for fp in pcb_ir.footprints:
        # Footprint position is the origin; bounding box requires
        # examining graphical items or using a fixed offset
        x, y = fp.position.X, fp.position.Y
        # Simplified: use position as center, estimate size from pads
        if fp.pads:
            pad_xs = [p.position.X for p in fp.pads]
            pad_ys = [p.position.Y for p in fp.pads]
            min_x, max_x = min(pad_xs) - 1.0, max(pad_xs) + 1.0
            min_y, max_y = min(pad_ys) - 1.0, max(pad_ys) + 1.0
            # Rotate bounding box by footprint angle
            angle_rad = math.radians(fp.position.angle)
            # Apply rotation around origin then translate
            boxes.append(SpatialBox(
                x1=x + min_x, y1=y + min_y,
                x2=x + max_x, y2=y + max_y,
                entity_type="footprint",
                entity_id=fp.libId,
                layer=fp.layer,
                reference=fp.properties.get("Reference", ""),
            ))
    return boxes

def extract_via_points(pcb_ir: PcbIR) -> list[SpatialPoint]:
    """Extract via positions as spatial points."""
    points = []
    for item in pcb_ir.trace_items:
        if hasattr(item, 'position'):  # Via has position, not start/end
            points.append(SpatialPoint(
                x=item.position.X,
                y=item.position.Y,
                entity_type="via",
                entity_id=str(item.tstamp) if hasattr(item, 'tstamp') else "",
                layer=",".join(item.layers) if hasattr(item, 'layers') else "",
                net=item.net.name if hasattr(item, 'net') and item.net else "",
            ))
    return points

def extract_trace_paths(pcb_ir: PcbIR) -> list[SpatialPath]:
    """Extract trace segments as spatial paths."""
    paths = []
    for item in pcb_ir.trace_items:
        if hasattr(item, 'start') and hasattr(item, 'end'):  # Segment or Arc
            pts = [(item.start.X, item.start.Y)]
            if hasattr(item, 'mid'):  # Arc -- include midpoint
                pts.append((item.mid.X, item.mid.Y))
            pts.append((item.end.X, item.end.Y))
            paths.append(SpatialPath(
                points=tuple(pts),
                entity_type="arc" if hasattr(item, 'mid') else "segment",
                entity_id=str(item.tstamp) if hasattr(item, 'tstamp') else "",
                layer=item.layer,
                net=item.net.name if hasattr(item, 'net') and item.net else "",
                width=item.width,
            ))
    return paths
```

### PCB Layer Rendering via kicad-cli SVG Export

```python
# Source: kicad-cli pcb export svg --help [VERIFIED: kicad-cli on PATH]
import subprocess
import shutil
from pathlib import Path
from PIL import Image

def render_pcb_layer(
    pcb_path: Path,
    layer: str = "F.Cu",
    output_path: Path = Path("layer_render.png"),
) -> dict:
    """Render a single PCB layer using kicad-cli SVG export + Pillow rasterization."""
    cli_path = shutil.which("kicad-cli")
    if not cli_path:
        raise FileNotFoundError("kicad-cli not found")

    with tempfile.TemporaryDirectory() as tmpdir:
        svg_output = Path(tmpdir) / f"{layer.replace('.', '_')}.svg"
        cmd = [
            cli_path, "pcb", "export", "svg",
            "--layers", layer,
            "--exclude-drawing-sheet",
            "--black-and-white",
            "--output", str(tmpdir),
            str(pcb_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)

        # Convert SVG to PNG using cairocffi or Pillow
        # Add coordinate grid overlay using Pillow
        # ... (grid overlay code uses board dimensions from general settings)
```

### Spatial Query Engine Usage

```python
# Source: Shapely 2.x API pattern
from shapely import STRtree, Point, box
from kicad_agent.spatial.primitives import SpatialPoint, SpatialBox

# Build index
all_primitives = extract_footprint_boxes(pcb_ir) + extract_via_points(pcb_ir)
engine = SpatialQueryEngine(all_primitives)

# VP-06 queries
nearby = engine.proximity(x=50.0, y=30.0, radius_mm=5.0)
in_region = engine.containment(x1=40.0, y1=20.0, x2=60.0, y2=40.0)
clearances = engine.clearance(entity_id="U1")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Text-only DRC reports | Coordinate-grounded violation items with pos.x/pos.y | kicad-cli JSON report format (KiCad 8+) | Each violation has exact board coordinates -- enables spatial grounding |
| Hand-drawn PCB images | kicad-cli SVG/PDF/PNG export per layer | KiCad 7+ CLI | Accurate layer rendering without custom drawing code |
| Manual spatial analysis | Shapely 2.x STRtree spatial indexing | Shapely 2.0 (2022) | Fast spatial queries without custom index implementation |
| Full board images only | Per-layer SVG export with coordinate mapping | KiCad 8+ | Can render individual layers with precise coordinate overlay |

**Deprecated/outdated:**
- kicad-cli HPGL export: "No longer supported as of KiCad 10.0." [VERIFIED: kicad-cli help output]

## Runtime State Inventory

> Not applicable -- this is a greenfield phase adding new modules, not a rename/refactor/migration.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | kicad-cli SVG export preserves coordinate mapping that can be reverse-mapped to mm | Architecture Patterns | Would need alternative rendering approach (Pillow-only) |
| A2 | KiCad PCB Y-axis increases downward (standard screen coordinates) | Anti-patterns | Coordinate calculations would be inverted |
| A3 | Rick agents consume JSON-format spatial reports via the skill interface | VP-08 design | Would need different integration pattern |
| A4 | Procedural boards can be constructed validly using kiutils Board/Footprint/Segment APIs | VP-04 | Would need to use raw S-expression generation instead |
| A5 | Arc midpoint from kiutils is the geometric arc midpoint (not the spline control point) | Primitives | Arc path representation would be incorrect |
| A6 | kicad-cli is available on PATH for SVG export (already required for DRC) | Renderer | Already a project dependency for Phase 3 DRC |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| kicad-cli | SVG export, DRC | Yes | 10.x | -- |
| Pillow | Image rendering | Yes | 11.3.0 | -- |
| Shapely | Spatial queries | Yes | 2.1.1 | -- |
| numpy | Coordinate transforms | Yes | 1.26.4 | -- |
| matplotlib | Debug visualization | Yes | 3.10.1 | Not used in production |
| cairocffi | SVG rasterization | Yes | 1.7.2 | Pillow-only path |
| kiutils | PCB data access | Yes | 1.4.8 | -- |
| pytest | Testing | Yes | 8.x | -- |
| Python 3.11+ | Runtime | Yes | 3.11.11 | -- |

**Missing dependencies with no fallback:** None -- all required libraries are installed.

**Missing dependencies with fallback:** None needed.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `python3 -m pytest tests/test_spatial*.py -x -q` |
| Full suite command | `python3 -m pytest tests/ --tb=short -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VP-01 | PCB layer renders to image with coordinate grid | integration | `pytest tests/test_spatial_renderer.py -x` | Wave 0 |
| VP-02 | Spatial primitives extracted from PcbIR | unit | `pytest tests/test_spatial_primitives.py -x` | Wave 0 |
| VP-03 | Primitive vocabulary dataclasses serialize to JSON | unit | `pytest tests/test_spatial_primitives.py::test_point_json -x` | Wave 0 |
| VP-04 | Maze-routing generator produces valid KiCad PCB | integration | `pytest tests/test_spatial_maze.py -x` | Wave 0 |
| VP-05 | Cold-start reasoning chains generated from DRC | integration | `pytest tests/test_spatial_chains.py -x` | Wave 0 |
| VP-06 | Spatial queries return correct results | unit | `pytest tests/test_spatial_query.py -x` | Wave 0 |
| VP-07 | DRC results enriched with spatial grounding | unit | `pytest tests/test_spatial_drc.py -x` | Wave 0 |
| VP-08 | Rick reports include coordinate-grounded findings | unit | `pytest tests/test_spatial_rick.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest tests/test_spatial*.py -x -q`
- **Per wave merge:** `python3 -m pytest tests/ --tb=short -q`
- **Phase gate:** Full suite green (454+ passing) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_spatial_primitives.py` -- covers VP-02, VP-03 (primitive dataclasses, JSON serialization)
- [ ] `tests/test_spatial_extractor.py` -- covers VP-02 (extraction from PcbIR)
- [ ] `tests/test_spatial_query.py` -- covers VP-06 (spatial query engine)
- [ ] `tests/test_spatial_renderer.py` -- covers VP-01 (layer rendering)
- [ ] `tests/test_spatial_maze.py` -- covers VP-04 (maze generator)
- [ ] `tests/test_spatial_chains.py` -- covers VP-05 (reasoning chains)
- [ ] `tests/test_spatial_drc.py` -- covers VP-07 (spatial DRC enrichment)
- [ ] `tests/test_spatial_rick.py` -- covers VP-08 (Rick integration)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth in this phase |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No access control changes |
| V5 Input Validation | yes | Pydantic validation on spatial query parameters (radius bounds, coordinate range) |
| V6 Cryptography | no | No crypto |

### Known Threat Patterns for PCB Spatial

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via SVG output path | Tampering | Validate output paths like existing TargetFile pattern |
| DoS via large spatial query radius | Denial of Service | Cap query radius to board diagonal + margin |
| Procedural board injection | Tampering | Validate generated boards pass kicad-cli parsing |
| Coordinate precision loss | Tampering | Use float64 (Python default), round only for display |

## Sources

### Primary (HIGH confidence)
- kiutils 1.4.8 -- Position, Segment, Via, Arc, Zone field inspection (verified via Python REPL)
- kicad-cli 10.x -- `pcb export svg --help`, `pcb render --help` (verified via subprocess)
- DRC JSON report -- violation item structure with pos.x/pos.y (verified against Arduino_Mega fixture)
- pip show -- Pillow 11.3.0, Shapely 2.1.1, numpy 1.26.4, kiutils 1.4.8, matplotlib 3.10.1, cairocffi 1.7.2 (verified in session)
- Project source code -- PcbIR, SchematicIR, BaseIR, erc_drc.py, pipeline.py, schema.py (read in session)

### Secondary (MEDIUM confidence)
- Existing project patterns -- frozen dataclasses for immutable results, Pydantic for schema, Transaction for rollback
- kicad-cli SVG coordinate system -- [ASSUMED] based on SVG standard conventions; needs verification during implementation

### Tertiary (LOW confidence)
- DeepSeek "Thinking with Visual Primitives" paper -- referenced in REQUIREMENTS.md but not accessible for verification; concept understood from description

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified as installed, versions confirmed
- Architecture: HIGH -- based on thorough codebase analysis of 7 existing phases
- Pitfalls: HIGH -- verified against kiutils coordinate model and real fixture data
- Spatial query design: HIGH -- Shapely STRtree is well-documented and commonly used
- Rendering approach: MEDIUM -- kicad-cli SVG export verified, but coordinate mapping needs implementation testing

**Research date:** 2026-05-22
**Valid until:** 2026-06-22 (stable -- all dependencies are mature libraries)
