"""Spatial reasoning benchmark dataset generator.

Generates 150+ deterministic spatial reasoning tasks for evaluating
LLM spatial understanding on PCB design problems. Each task has a
ground-truth answer computed from geometry (no LLM judgment required).

Six task categories:
  1. coordinate_proximity -- distance between spatial primitives
  2. routing_feasibility -- can A* find a path between pads?
  3. clearance_diagnosis -- root cause of synthetic DRC violations
  4. net_completion -- suggest routing path for partial nets
  5. drc_fix_selection -- pick the correct fix from candidates
  6. unrouted_cause -- identify what blocks an unrouted net

Distribution: 20% easy, 60% medium, 20% hard.
Vision tasks include a placeholder render_path (actual PNG in 80-02).

Usage:
    from volta.analysis.spatial_benchmark import TaskGenerator

    gen = TaskGenerator(pcb_paths=["tests/fixtures/RPi/board.kicad_pcb"], seed=42)
    tasks = gen.generate_all()
    assert len(tasks) >= 150
"""

from __future__ import annotations

import logging
import random
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from shapely.geometry import Point as ShapelyPoint
from shapely.geometry import box as shapely_box

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TaskCategory(str, Enum):
    """Categories of spatial reasoning tasks."""

    COORDINATE_PROXIMITY = "coordinate_proximity"
    ROUTING_FEASIBILITY = "routing_feasibility"
    CLEARANCE_DIAGNOSIS = "clearance_diagnosis"
    NET_COMPLETION = "net_completion"
    DRC_FIX_SELECTION = "drc_fix_selection"
    UNROUTED_CAUSE = "unrouted_cause"


class Difficulty(str, Enum):
    """Task difficulty levels."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class BoardContext(BaseModel):
    """Context metadata for the PCB board a task is derived from."""

    component_count: int
    net_count: int
    board_bounds_mm: tuple[float, float, float, float]
    layer_count: int
    source_file: str


class SpatialReasoningTask(BaseModel):
    """A single spatial reasoning evaluation task.

    Attributes:
        task_id: Unique identifier, e.g. ``"coord_prox_001"``.
        task_type: Category of spatial reasoning required.
        difficulty: Easy, medium, or hard.
        board_context: PCB metadata for this task.
        question: Natural-language question posed to the model.
        ground_truth: Deterministically computed correct answer.
        input_type: ``"text"`` or ``"vision"``.
        render_path: Path to PCB render PNG for vision tasks (placeholder).
        metadata: Arbitrary generation metadata (source fixture, params).
    """

    task_id: str
    task_type: TaskCategory
    difficulty: Difficulty
    board_context: BoardContext
    question: str
    ground_truth: str
    input_type: str
    render_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Short ID prefixes for each category.
_CATEGORY_PREFIXES: dict[TaskCategory, str] = {
    TaskCategory.COORDINATE_PROXIMITY: "coord_prox",
    TaskCategory.ROUTING_FEASIBILITY: "route_feas",
    TaskCategory.CLEARANCE_DIAGNOSIS: "clear_diag",
    TaskCategory.NET_COMPLETION: "net_comp",
    TaskCategory.DRC_FIX_SELECTION: "drc_fix",
    TaskCategory.UNROUTED_CAUSE: "unrouted",
}

# Target task counts per category (totals 162).
_TARGET_COUNTS: dict[TaskCategory, int] = {
    TaskCategory.COORDINATE_PROXIMITY: 30,
    TaskCategory.ROUTING_FEASIBILITY: 27,
    TaskCategory.CLEARANCE_DIAGNOSIS: 27,
    TaskCategory.NET_COMPLETION: 27,
    TaskCategory.DRC_FIX_SELECTION: 27,
    TaskCategory.UNROUTED_CAUSE: 24,
}

# Difficulty distribution ratios.
_DIFFICULTY_RATIOS: dict[Difficulty, float] = {
    Difficulty.EASY: 0.20,
    Difficulty.MEDIUM: 0.60,
    Difficulty.HARD: 0.20,
}

# Default synthetic board when no PCB files can be loaded.
_DEFAULT_BOARD_CTX = BoardContext(
    component_count=12,
    net_count=8,
    board_bounds_mm=(0.0, 0.0, 85.0, 56.0),
    layer_count=2,
    source_file="synthetic",
)


def _assign_difficulty(rng: random.Random, index: int, total: int) -> Difficulty:
    """Determine difficulty based on target distribution ratios.

    Uses index within category to distribute evenly.
    """
    frac = index / max(total, 1)
    if frac < _DIFFICULTY_RATIOS[Difficulty.EASY]:
        return Difficulty.EASY
    if frac < _DIFFICULTY_RATIOS[Difficulty.EASY] + _DIFFICULTY_RATIOS[Difficulty.MEDIUM]:
        return Difficulty.MEDIUM
    return Difficulty.HARD


def _synthetic_primitives(
    rng: random.Random, bounds: tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    """Generate synthetic spatial primitives for testing.

    Returns a list of dicts with ``x``, ``y``, ``x1``, ``y1``, ``x2``,
    ``y2``, ``entity_type``, ``entity_id``, ``net`` keys suitable for
    building Shapely geometries.
    """
    min_x, min_y, max_x, max_y = bounds
    pad = 2.0
    primitives: list[dict[str, Any]] = []

    # Generate 30 synthetic points (pads/pins).
    for i in range(30):
        x = rng.uniform(min_x + pad, max_x - pad)
        y = rng.uniform(min_y + pad, max_y - pad)
        primitives.append({
            "x": x,
            "y": y,
            "entity_type": "pad",
            "entity_id": f"P{i + 1}",
            "net": f"net_{i % 8}",
        })

    # Generate 10 synthetic boxes (footprints).
    for i in range(10):
        cx = rng.uniform(min_x + pad + 3, max_x - pad - 3)
        cy = rng.uniform(min_y + pad + 3, max_y - pad - 3)
        hw = rng.uniform(1.0, 3.0)
        hh = rng.uniform(1.0, 3.0)
        primitives.append({
            "x1": cx - hw,
            "y1": cy - hh,
            "x2": cx + hw,
            "y2": cy + hh,
            "entity_type": "footprint",
            "entity_id": f"U{i + 1}",
            "net": "",
        })

    return primitives


def _try_load_pcb(
    pcb_path: str,
) -> tuple[BoardContext, list[dict[str, Any]]] | None:
    """Attempt to load a real PCB and extract spatial data.

    Returns None if the file cannot be parsed (graceful fallback to
    synthetic data).
    """
    path = Path(pcb_path)
    if not path.exists():
        logger.debug("PCB fixture not found: %s", pcb_path)
        return None

    try:
        from volta.ir.pcb_ir import PcbIR
        from volta.spatial.extractor import extract_all

        pcb_ir = PcbIR.from_file(path)
        spatial_result = extract_all(pcb_ir)

        # Build board context from IR.
        comp_count = len(pcb_ir.footprints) if hasattr(pcb_ir, "footprints") else 0
        net_count = len(pcb_ir.nets) if hasattr(pcb_ir, "nets") else 0

        # Derive board bounds from outline.
        outline_pts = []
        if hasattr(pcb_ir, "gr_rects"):
            for rect in pcb_ir.gr_rects:
                if hasattr(rect, "start") and hasattr(rect, "end"):
                    outline_pts.append((float(rect.start.x), float(rect.start.y)))
                    outline_pts.append((float(rect.end.x), float(rect.end.y)))

        if outline_pts:
            xs = [p[0] for p in outline_pts]
            ys = [p[1] for p in outline_pts]
            bounds = (min(xs), min(ys), max(xs), max(ys))
        else:
            bounds = (0.0, 0.0, 100.0, 80.0)

        layer_count = 2
        if hasattr(pcb_ir, "layers"):
            copper = [l for l in pcb_ir.layers if ".Cu" in str(l)]
            layer_count = max(len(copper), 2)

        ctx = BoardContext(
            component_count=comp_count,
            net_count=net_count,
            board_bounds_mm=bounds,
            layer_count=layer_count,
            source_file=str(path),
        )

        # Convert extracted spatial primitives to plain dicts.
        primitives: list[dict[str, Any]] = []
        for pt in spatial_result.points:
            primitives.append({
                "x": pt.x,
                "y": pt.y,
                "entity_type": pt.entity_type,
                "entity_id": pt.entity_id,
                "net": pt.net,
            })
        for bx in spatial_result.boxes:
            primitives.append({
                "x1": bx.x1,
                "y1": bx.y1,
                "x2": bx.x2,
                "y2": bx.y2,
                "entity_type": bx.entity_type,
                "entity_id": bx.entity_id,
                "net": "",
            })

        return ctx, primitives

    except Exception:
        logger.debug("Failed to load PCB: %s", pcb_path, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# TaskGenerator
# ---------------------------------------------------------------------------


class TaskGenerator:
    """Generate spatial reasoning benchmark tasks from PCB data.

    Falls back to synthetic geometry when real PCB fixtures are
    unavailable, ensuring the generator always produces tasks.

    Args:
        pcb_paths: List of ``.kicad_pcb`` file paths to extract spatial
            data from. If empty or all fail to load, synthetic data is
            used.
        seed: Random seed for reproducibility. When ``None``, uses
            default ``random.Random()`` seeding.
    """

    def __init__(
        self,
        pcb_paths: list[str] | None = None,
        seed: int | None = None,
        use_astar: bool = False,
    ) -> None:
        self._rng = random.Random(seed)
        self._seed = seed
        self._use_astar = use_astar

        # Attempt to load real PCB data; fall back to synthetic.
        self._board_context = _DEFAULT_BOARD_CTX
        self._primitives: list[dict[str, Any]] = _synthetic_primitives(
            self._rng, _DEFAULT_BOARD_CTX.board_bounds_mm,
        )

        loaded = False
        for pcb_path in pcb_paths or []:
            result = _try_load_pcb(pcb_path)
            if result is not None:
                self._board_context, self._primitives = result
                loaded = True
                break

        if not loaded:
            logger.info("Using synthetic spatial data for benchmark generation")

        # Re-seed after potential PCB loading (which consumes RNG state).
        self._rng = random.Random(seed)

        # Extract point and box primitives for convenience.
        self._points = [p for p in self._primitives if "x" in p and "y" in p]
        self._boxes = [p for p in self._primitives if "x1" in p and "y1" in p]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_all(self) -> list[SpatialReasoningTask]:
        """Generate tasks across all six categories.

        Returns at least 150 tasks with difficulty distribution
        approximately 20/60/20 (easy/medium/hard). Seeded RNG
        ensures identical output for the same seed.
        """
        all_tasks: list[SpatialReasoningTask] = []
        counters: dict[TaskCategory, int] = {}

        generators = [
            self._gen_coordinate_proximity,
            self._gen_routing_feasibility,
            self._gen_clearance_diagnosis,
            self._gen_net_completion,
            self._gen_drc_fix_selection,
            self._gen_unrouted_cause,
        ]

        for gen_fn in generators:
            tasks = gen_fn()
            for t in tasks:
                cat = t.task_type
                counters[cat] = counters.get(cat, 0) + 1
            all_tasks.extend(tasks)

        logger.info(
            "Generated %d benchmark tasks across %d categories",
            len(all_tasks),
            len(counters),
        )
        return all_tasks

    # ------------------------------------------------------------------
    # Category 1: Coordinate proximity
    # ------------------------------------------------------------------

    def _gen_coordinate_proximity(self) -> list[SpatialReasoningTask]:
        """Generate distance-based proximity questions.

        Picks pairs of spatial primitives, computes Shapely distance,
        and asks the model for the clearance in mm.
        """
        count = _TARGET_COUNTS[TaskCategory.COORDINATE_PROXIMITY]
        tasks: list[SpatialReasoningTask] = []
        rng = self._rng

        pairs = self._generate_primitive_pairs(rng, count)

        for i, (pa, pb) in enumerate(pairs):
            geom_a = self._to_shapely(pa)
            geom_b = self._to_shapely(pb)
            distance = round(geom_a.distance(geom_b), 4)

            label_a = f"{pa['entity_type']} {pa['entity_id']}"
            label_b = f"{pb['entity_type']} {pb['entity_id']}"

            task = SpatialReasoningTask(
                task_id=f"coord_prox_{i + 1:03d}",
                task_type=TaskCategory.COORDINATE_PROXIMITY,
                difficulty=_assign_difficulty(rng, i, count),
                board_context=self._board_context,
                question=(
                    f"What is the clearance between {label_a} and "
                    f"{label_b} in mm?"
                ),
                ground_truth=f"{distance:.4f}",
                input_type="text",
                metadata={
                    "primitive_a": pa.get("entity_id", ""),
                    "primitive_b": pb.get("entity_id", ""),
                },
            )
            tasks.append(task)

        return tasks

    # ------------------------------------------------------------------
    # Category 2: Routing feasibility
    # ------------------------------------------------------------------

    def _gen_routing_feasibility(self) -> list[SpatialReasoningTask]:
        """Generate A* routing feasibility questions.

        Picks two pads, builds a routing graph, and asks whether a
        route exists. Uses RoutingGraph and route_net for deterministic
        ground truth.
        """
        count = _TARGET_COUNTS[TaskCategory.ROUTING_FEASIBILITY]
        tasks: list[SpatialReasoningTask] = []
        rng = self._rng

        for i in range(count):
            source, target = self._pick_two_points(rng)
            net_name = source.get("net", f"net_{i}")

            # Build obstacles from boxes.
            obstacles = self._boxes_as_spatial_boxes()
            feasible = self._check_routing_feasibility(source, target, obstacles)

            src_id = source["entity_id"]
            tgt_id = target["entity_id"]

            task = SpatialReasoningTask(
                task_id=f"route_feas_{i + 1:03d}",
                task_type=TaskCategory.ROUTING_FEASIBILITY,
                difficulty=_assign_difficulty(rng, i, count),
                board_context=self._board_context,
                question=(
                    f"Can net '{net_name}' route between pad {src_id} at "
                    f"({source['x']:.2f}, {source['y']:.2f}) and pad "
                    f"{tgt_id} at ({target['x']:.2f}, {target['y']:.2f})?"
                ),
                ground_truth="yes" if feasible else "no",
                input_type="vision",
                render_path=f"renders/route_feas_{i + 1:03d}.png",
                metadata={
                    "source_id": src_id,
                    "target_id": tgt_id,
                    "net": net_name,
                    "feasible": feasible,
                },
            )
            tasks.append(task)

        return tasks

    # ------------------------------------------------------------------
    # Category 3: Clearance diagnosis
    # ------------------------------------------------------------------

    def _gen_clearance_diagnosis(self) -> list[SpatialReasoningTask]:
        """Generate DRC violation root-cause diagnosis questions.

        Creates synthetic DRC violations with known causes and asks
        the model to identify the root cause.
        """
        count = _TARGET_COUNTS[TaskCategory.CLEARANCE_DIAGNOSIS]
        tasks: list[SpatialReasoningTask] = []
        rng = self._rng

        causes = [
            "pad_to_pad_clearance",
            "trace_to_pad_clearance",
            "copper_keepout_violation",
            "drill_hit_copper",
            "silk_over_copper",
            "annular_ring_insufficient",
        ]

        for i in range(count):
            cause = causes[i % len(causes)]
            point = self._pick_point(rng)
            severity = _assign_difficulty(rng, i, count)

            ground_truth = self._clearance_ground_truth(cause)

            task = SpatialReasoningTask(
                task_id=f"clear_diag_{i + 1:03d}",
                task_type=TaskCategory.CLEARANCE_DIAGNOSIS,
                difficulty=severity,
                board_context=self._board_context,
                question=(
                    f"A DRC violation is reported near ({point['x']:.2f}, "
                    f"{point['y']:.2f}) with clearance below minimum. "
                    f"What is the root cause of this DRC violation?"
                ),
                ground_truth=ground_truth,
                input_type="text",
                metadata={
                    "synthetic_cause": cause,
                    "violation_x": round(point["x"], 4),
                    "violation_y": round(point["y"], 4),
                },
            )
            tasks.append(task)

        return tasks

    # ------------------------------------------------------------------
    # Category 4: Net completion
    # ------------------------------------------------------------------

    def _gen_net_completion(self) -> list[SpatialReasoningTask]:
        """Generate partial-net routing path suggestion questions.

        Picks a net with coordinates for all but one connection,
        and asks for the optimal path to complete the net.
        """
        count = _TARGET_COUNTS[TaskCategory.NET_COMPLETION]
        tasks: list[SpatialReasoningTask] = []
        rng = self._rng

        for i in range(count):
            # Pick two endpoints for the missing connection.
            pa, pb = self._pick_two_points(rng)
            net_name = f"net_{rng.randint(0, 7)}"

            obstacles = self._boxes_as_spatial_boxes()
            path_str = self._compute_path_description(pa, pb, obstacles)

            task = SpatialReasoningTask(
                task_id=f"net_comp_{i + 1:03d}",
                task_type=TaskCategory.NET_COMPLETION,
                difficulty=_assign_difficulty(rng, i, count),
                board_context=self._board_context,
                question=(
                    f"Net '{net_name}' needs a route from ({pa['x']:.2f}, "
                    f"{pa['y']:.2f}) to ({pb['x']:.2f}, {pb['y']:.2f}). "
                    f"Suggest the optimal path."
                ),
                ground_truth=path_str,
                input_type="vision",
                render_path=f"renders/net_comp_{i + 1:03d}.png",
                metadata={
                    "source": (round(pa["x"], 4), round(pa["y"], 4)),
                    "target": (round(pb["x"], 4), round(pb["y"], 4)),
                    "net": net_name,
                },
            )
            tasks.append(task)

        return tasks

    # ------------------------------------------------------------------
    # Category 5: DRC fix selection
    # ------------------------------------------------------------------

    def _gen_drc_fix_selection(self) -> list[SpatialReasoningTask]:
        """Generate multiple-choice DRC fix selection questions.

        Creates a synthetic violation with three candidate fixes,
        exactly one of which is correct.
        """
        count = _TARGET_COUNTS[TaskCategory.DRC_FIX_SELECTION]
        tasks: list[SpatialReasoningTask] = []
        rng = self._rng

        violation_templates = [
            {
                "type": "clearance",
                "desc": "pad-to-pad clearance violation (0.15mm < 0.20mm required)",
                "fixes": [
                    "Increase pad-to-pad clearance by moving component U2 0.5mm right",
                    "Decrease minimum clearance rule to 0.15mm",
                    "Add a copper pour between the pads",
                ],
                "correct": 0,
            },
            {
                "type": "unrouted",
                "desc": "unrouted net SDA with 2 disconnected pins",
                "fixes": [
                    "Delete the net from the netlist",
                    "Route a trace between pin U1.5 and pin R3.2 on F.Cu",
                    "Change the net class to allow tighter clearance",
                ],
                "correct": 1,
            },
            {
                "type": "short",
                "desc": "copper short between nets VCC and GND at (25.3, 18.7)",
                "fixes": [
                    "Merge VCC and GND into a single net",
                    "Add a via to transition VCC to B.Cu near the short",
                    "Increase board size to spread components",
                ],
                "correct": 1,
            },
            {
                "type": "silk",
                "desc": "silkscreen overlaps copper pad on R5",
                "fixes": [
                    "Remove silkscreen layer from board stackup",
                    "Move silkscreen text away from R5 pad by 0.3mm",
                    "Change R5 footprint to a smaller package",
                ],
                "correct": 1,
            },
            {
                "type": "drill",
                "desc": "drill hole (0.8mm) exceeds pad diameter (0.6mm) on via V12",
                "fixes": [
                    "Reduce drill diameter to 0.4mm and pad to 0.6mm",
                    "Increase via pad diameter to at least 1.0mm",
                    "Remove via V12 from the design",
                ],
                "correct": 1,
            },
            {
                "type": "annular",
                "desc": "annular ring (0.05mm) below minimum (0.10mm) on via V7",
                "fixes": [
                    "Increase via pad diameter to provide at least 0.10mm annular ring",
                    "Decrease minimum annular ring rule",
                    "Route around via V7 using a longer path",
                ],
                "correct": 0,
            },
        ]

        for i in range(count):
            tmpl = violation_templates[i % len(violation_templates)]
            point = self._pick_point(rng)

            fixes_text = "\n".join(
                f"  Fix {idx}: {fx}" for idx, fx in enumerate(tmpl["fixes"])
            )

            correct_idx = tmpl["correct"]
            fixes = list(tmpl["fixes"])
            rng.shuffle(fixes)
            correct_idx = fixes.index(tmpl["fixes"][correct_idx])

            ground_truth = f"Fix {correct_idx}: {fixes[correct_idx]}"

            task = SpatialReasoningTask(
                task_id=f"drc_fix_{i + 1:03d}",
                task_type=TaskCategory.DRC_FIX_SELECTION,
                difficulty=_assign_difficulty(rng, i, count),
                board_context=self._board_context,
                question=(
                    f"A DRC violation is reported near ({point['x']:.2f}, "
                    f"{point['y']:.2f}): {tmpl['desc']}\n"
                    f"Which fix is correct?\n{fixes_text}"
                ),
                ground_truth=ground_truth,
                input_type="vision",
                render_path=f"renders/drc_fix_{i + 1:03d}.png",
                metadata={
                    "violation_type": tmpl["type"],
                    "correct_fix_index": correct_idx,
                },
            )
            tasks.append(task)

        return tasks

    # ------------------------------------------------------------------
    # Category 6: Unrouted cause
    # ------------------------------------------------------------------

    def _gen_unrouted_cause(self) -> list[SpatialReasoningTask]:
        """Generate questions about what blocks an unrouted net.

        Creates a net with known obstacles blocking the path and
        asks the model to identify the blocking feature.
        """
        count = _TARGET_COUNTS[TaskCategory.UNROUTED_CAUSE]
        tasks: list[SpatialReasoningTask] = []
        rng = self._rng

        obstacle_types = [
            ("component", "footprint"),
            ("copper_pour", "copper zone"),
            ("keepout", "keepout zone"),
            ("via_array", "cluster of vias"),
            ("pad_array", "pad array"),
        ]

        for i in range(count):
            obs_type, obs_desc = obstacle_types[i % len(obstacle_types)]
            pa, pb = self._pick_two_points(rng)
            net_name = f"net_{rng.randint(0, 7)}"

            # Ground truth is the obstacle description.
            blocker = self._identify_blocker(rng, obs_type, obs_desc)

            task = SpatialReasoningTask(
                task_id=f"unrouted_{i + 1:03d}",
                task_type=TaskCategory.UNROUTED_CAUSE,
                difficulty=_assign_difficulty(rng, i, count),
                board_context=self._board_context,
                question=(
                    f"Net '{net_name}' from ({pa['x']:.2f}, {pa['y']:.2f}) "
                    f"to ({pb['x']:.2f}, {pb['y']:.2f}) cannot be routed. "
                    f"What feature is blocking this net?"
                ),
                ground_truth=blocker,
                input_type="vision",
                render_path=f"renders/unrouted_{i + 1:03d}.png",
                metadata={
                    "obstacle_type": obs_type,
                    "source": (round(pa["x"], 4), round(pa["y"], 4)),
                    "target": (round(pb["x"], 4), round(pb["y"], 4)),
                    "net": net_name,
                },
            )
            tasks.append(task)

        return tasks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_primitive_pairs(
        self, rng: random.Random, count: int,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Generate ``count`` unique pairs of primitives."""
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        all_prims = self._primitives
        if len(all_prims) < 2:
            # Not enough real data -- synthesize pairs.
            for _ in range(count):
                pairs.append((
                    {"x": rng.uniform(5, 80), "y": rng.uniform(5, 50), "entity_type": "pad", "entity_id": "syn_A"},
                    {"x": rng.uniform(5, 80), "y": rng.uniform(5, 50), "entity_type": "pad", "entity_id": "syn_B"},
                ))
            return pairs

        for _ in range(count):
            idx_a = rng.randint(0, len(all_prims) - 1)
            idx_b = rng.randint(0, len(all_prims) - 1)
            while idx_b == idx_a:
                idx_b = rng.randint(0, len(all_prims) - 1)
            pairs.append((all_prims[idx_a], all_prims[idx_b]))

        return pairs

    def _pick_point(self, rng: random.Random) -> dict[str, Any]:
        """Pick a random point primitive, or synthesize one."""
        if self._points:
            return rng.choice(self._points)
        bounds = self._board_context.board_bounds_mm
        return {
            "x": rng.uniform(bounds[0] + 5, bounds[2] - 5),
            "y": rng.uniform(bounds[1] + 5, bounds[3] - 5),
            "entity_type": "pad",
            "entity_id": "syn_0",
        }

    def _pick_two_points(
        self, rng: random.Random,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Pick two distinct point primitives."""
        if len(self._points) >= 2:
            idx_a = rng.randint(0, len(self._points) - 1)
            idx_b = rng.randint(0, len(self._points) - 1)
            while idx_b == idx_a:
                idx_b = rng.randint(0, len(self._points) - 1)
            return self._points[idx_a], self._points[idx_b]

        bounds = self._board_context.board_bounds_mm
        pa = {"x": rng.uniform(bounds[0] + 5, bounds[2] - 5),
              "y": rng.uniform(bounds[1] + 5, bounds[3] - 5),
              "entity_type": "pad", "entity_id": "syn_A"}
        pb = {"x": rng.uniform(bounds[0] + 5, bounds[2] - 5),
              "y": rng.uniform(bounds[1] + 5, bounds[3] - 5),
              "entity_type": "pad", "entity_id": "syn_B"}
        return pa, pb

    @staticmethod
    def _to_shapely(prim: dict[str, Any]):
        """Convert a primitive dict to a Shapely geometry."""
        if "x" in prim and "y" in prim:
            return ShapelyPoint(prim["x"], prim["y"])
        return shapely_box(prim["x1"], prim["y1"], prim["x2"], prim["y2"])

    def _boxes_as_spatial_boxes(self) -> list:
        """Convert box primitives to SpatialBox objects for routing."""
        from volta.spatial.primitives import SpatialBox

        result: list[SpatialBox] = []
        for b in self._boxes:
            result.append(SpatialBox(
                x1=b["x1"], y1=b["y1"],
                x2=b["x2"], y2=b["y2"],
                entity_type=b.get("entity_type", "footprint"),
                entity_id=b.get("entity_id", ""),
            ))
        return result

    def _check_routing_feasibility(
        self,
        source: dict[str, Any],
        target: dict[str, Any],
        obstacles: list,
    ) -> bool:
        """Check if A* can route between source and target.

        Returns True if a path exists, False otherwise.
        Catches any import/runtime errors and falls back to
        geometric heuristics.
        """
        if self._use_astar:
            try:
                from volta.routing.constraints import RoutingConstraints
                from volta.routing.graph import RoutingGraph
                from volta.routing.pathfinder import route_net

                bounds = self._board_context.board_bounds_mm
                constraints = RoutingConstraints(
                    clearance_mm=0.2,
                    grid_resolution_mm=1.0,
                    max_nodes=50_000,
                )
                graph = RoutingGraph(
                    board_bounds=bounds,
                    obstacles=obstacles,
                    constraints=constraints,
                    required_nodes={
                        (source["x"], source["y"]),
                        (target["x"], target["y"]),
                    },
                )
                result = route_net(
                    graph,
                    (source["x"], source["y"]),
                    (target["x"], target["y"]),
                    "benchmark_net",
                )
                return bool(result)

            except Exception:
                logger.debug("A* routing failed, using geometric fallback")

        # Fast geometric heuristic: check if direct line crosses any obstacle.
        from shapely.geometry import LineString

        line = LineString([
            (source["x"], source["y"]),
            (target["x"], target["y"]),
        ])
        for obs in self._boxes:
            obs_geom = shapely_box(obs["x1"], obs["y1"], obs["x2"], obs["y2"])
            if line.crosses(obs_geom):
                return False
        return True

    def _compute_path_description(
        self,
        pa: dict[str, Any],
        pb: dict[str, Any],
        obstacles: list,
    ) -> str:
        """Compute a ground-truth path description between two points.

        Returns a string describing the route, either from A* or
        from a geometric fallback.
        """
        if self._use_astar:
            try:
                from volta.routing.constraints import RoutingConstraints
                from volta.routing.graph import RoutingGraph
                from volta.routing.pathfinder import route_net

                bounds = self._board_context.board_bounds_mm
                constraints = RoutingConstraints(
                    clearance_mm=0.2,
                    grid_resolution_mm=1.0,
                    max_nodes=50_000,
                )
                graph = RoutingGraph(
                    board_bounds=bounds,
                    obstacles=obstacles,
                    constraints=constraints,
                    required_nodes={
                        (pa["x"], pa["y"]),
                        (pb["x"], pb["y"]),
                    },
                )
                result = route_net(
                    graph,
                    (pa["x"], pa["y"]),
                    (pb["x"], pb["y"]),
                    "benchmark_net",
                )
                if result:
                    waypoints = [
                        f"({w[0]:.2f}, {w[1]:.2f})" for w in result.path
                    ]
                    return (
                        f"Route via waypoints: {' -> '.join(waypoints)}. "
                        f"Length: {result.length_mm:.2f}mm."
                    )

            except Exception:
                logger.debug("A* path computation failed, using fallback")

        # Geometric fallback: direct line with clearance.
        dx = pb["x"] - pa["x"]
        dy = pb["y"] - pa["y"]
        length = (dx ** 2 + dy ** 2) ** 0.5
        return (
            f"Direct route from ({pa['x']:.2f}, {pa['y']:.2f}) to "
            f"({pb['x']:.2f}, {pb['y']:.2f}). Length: {length:.2f}mm."
        )

    @staticmethod
    def _clearance_ground_truth(cause: str) -> str:
        """Map a synthetic DRC cause to a ground-truth diagnosis."""
        mapping = {
            "pad_to_pad_clearance": (
                "Adjacent pads are placed too close together, "
                "violating the minimum pad-to-pad clearance rule."
            ),
            "trace_to_pad_clearance": (
                "A routed trace passes too close to a copper pad, "
                "violating the minimum trace-to-pad clearance rule."
            ),
            "copper_keepout_violation": (
                "Copper geometry overlaps a designated keepout zone "
                "where copper is prohibited."
            ),
            "drill_hit_copper": (
                "A drill hole passes through existing copper on an "
                "inner layer, creating an unintended short circuit."
            ),
            "silk_over_copper": (
                "Silkscreen text or graphics overlap exposed copper, "
                "which can interfere with soldering."
            ),
            "annular_ring_insufficient": (
                "The annular ring around a via or pad drill hole is "
                "below the minimum required width for reliable "
                "manufacturing."
            ),
        }
        return mapping.get(cause, f"Unknown violation type: {cause}")

    @staticmethod
    def _identify_blocker(
        rng: random.Random, obs_type: str, obs_desc: str,
    ) -> str:
        """Generate a deterministic blocker description."""
        descriptions = {
            "component": "A component footprint blocks the direct path between source and target pads.",
            "copper_pour": "A copper zone pour occupies the routing corridor, preventing trace placement.",
            "keepout": "A keepout zone prohibits copper in the direct path area.",
            "via_array": "A cluster of vias blocks the routing channel with insufficient clearance for a new trace.",
            "pad_array": "A dense pad array (e.g., BGA or connector) leaves no routing channel between source and target.",
        }
        return descriptions.get(obs_type, f"A {obs_desc} blocks the routing path.")
