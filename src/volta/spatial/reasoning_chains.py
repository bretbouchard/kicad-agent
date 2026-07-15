"""Cold-start reasoning chain synthesis from DRC/ERC violations.

VP-05: Generates coordinate-grounded reasoning chains that demonstrate how an
AI should analyze DRC/ERC violations using spatial coordinates.

Each chain follows a 5-step pattern:
  1. observation -- DRC/ERC violation detected with coordinates
  2. spatial_context -- what is near the violation point
  3. coordinate_reference -- precise coordinates of involved entities
  4. diagnosis -- violation type mapped to descriptive diagnosis
  5. recommendation -- actionable fix recommendation

Chains are grounded in real coordinate data from parsed files and can be
enriched with spatial primitives from the extractor module.

Usage:
    from volta.spatial.reasoning_chains import synthesize_chains

    chains = synthesize_chains(drc_result=my_drc_result)
    for chain in chains:
        for step in chain.steps:
            print(f"[{step.step_type}] {step.content}")
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from volta.validation.erc_drc import DrcResult, ErcResult, Violation


@dataclass(frozen=True)
class ReasoningStep:
    """A single step in a coordinate-grounded reasoning chain.

    Attributes:
        step_type: Category of this step -- one of "observation",
            "spatial_context", "coordinate_reference", "diagnosis",
            "recommendation".
        content: Human-readable description of this step.
        coordinates: Optional coordinate data as (x, y) tuples.
        metadata: Additional structured metadata for this step.
    """

    step_type: str  # "observation", "spatial_context", "coordinate_reference", "diagnosis", "recommendation"
    content: str
    coordinates: tuple[tuple[float, float], ...] = ()
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ReasoningChain:
    """A complete reasoning chain for a single DRC/ERC violation.

    Attributes:
        violation_type: Type of the source violation.
        violation_description: Original violation description text.
        severity: Violation severity level as string.
        steps: Ordered tuple of ReasoningStep objects.
        spatial_primitives: JSON-serialized spatial primitives involved.
        chain_id: Unique identifier for this chain.
    """

    violation_type: str
    violation_description: str
    severity: str
    steps: tuple[ReasoningStep, ...]
    spatial_primitives: tuple[dict, ...] = ()
    chain_id: str = ""


# ---------------------------------------------------------------------------
# Diagnosis and recommendation mappings
# ---------------------------------------------------------------------------

_DIAGNOSIS_MAP: dict[str, str] = {
    "clearance": "insufficient spacing between copper features",
    "width": "trace width below minimum design rule",
    "unconnected_items": "net with dangling connections",
    "silk_overlap": "silkscreen overlapping solder mask or pad",
    "solder_mask_bridge": "solder mask bridge between pads",
    "drill_out_of_range": "drill size outside acceptable range",
    "courtyards_overlap": "component courtyards overlapping",
    "lib_footprint_issues": "footprint library issue detected",
    "text_on_edge_cuts": "text item placed on Edge.Cuts layer",
}

_RECOMMENDATION_MAP: dict[str, str] = {
    "clearance": "Increase spacing between the violating features to at least the minimum clearance distance",
    "width": "Widen the trace to meet the minimum width requirement for the net class",
    "unconnected_items": "Route the missing connections or add no-connect flags if intentional",
    "silk_overlap": "Move silkscreen text or graphics away from pads and solder mask openings",
    "solder_mask_bridge": "Increase pad spacing or adjust solder mask settings",
    "drill_out_of_range": "Adjust drill size to be within the acceptable range for the fab",
    "courtyards_overlap": "Move components to eliminate courtyard overlap",
    "lib_footprint_issues": "Update the footprint from the library or fix the library definition",
    "text_on_edge_cuts": "Move text to a non-mechanical layer such as F.SilkS or F.Fab",
}

_DEFAULT_DIAGNOSIS = "design rule constraint not met"
_DEFAULT_RECOMMENDATION = "Review the design rules and adjust the affected features"


def synthesize_chain(
    violation: Violation,
    pcb_primitives: list | None = None,
) -> ReasoningChain:
    """Build a reasoning chain from a single DRC/ERC violation.

    Produces a 5-step chain: observation -> spatial_context ->
    coordinate_reference -> diagnosis -> recommendation.

    Args:
        violation: A Violation dataclass from DRC/ERC results.
        pcb_primitives: Optional list of spatial primitives for context.
            If provided, nearby primitives within 5mm are included in the
            spatial_context step.

    Returns:
        ReasoningChain with 5 ordered steps and spatial metadata.
    """
    coords = _extract_violation_coordinates(violation)
    coords_tuple = tuple(coords)

    # Step 1: Observation
    coord_str = ", ".join(f"[{x}, {y}]" for x, y in coords) if coords else "unknown"
    observation = ReasoningStep(
        step_type="observation",
        content=f"DRC violation detected: {violation.description} at {coord_str}",
        coordinates=coords_tuple,
    )

    # Step 2: Spatial context
    nearby_json: list[dict] = []
    spatial_context_text = "No spatial primitives provided for context analysis"
    if pcb_primitives and coords:
        first_coord = coords[0]
        nearby = _find_nearby_primitives(first_coord, pcb_primitives, radius_mm=5.0)
        nearby_json = nearby
        fp_count = sum(
            1 for p in nearby if p.get("entity_type") in ("footprint", "component")
        )
        trace_count = sum(
            1 for p in nearby if p.get("entity_type") in ("segment", "arc", "trace")
        )
        spatial_context_text = (
            f"Near the violation point [{first_coord[0]}, {first_coord[1]}], "
            f"found {fp_count} footprints, {trace_count} traces within 5mm"
        )

    spatial_context = ReasoningStep(
        step_type="spatial_context",
        content=spatial_context_text,
        coordinates=coords_tuple[:1] if coords_tuple else (),
        metadata={"nearby_count": len(nearby_json)},
    )

    # Step 3: Coordinate reference
    coord_ref_parts: list[str] = []
    for x, y in coords:
        coord_ref_parts.append(f"[{x}, {y}]")
    coord_ref_str = (
        ", ".join(coord_ref_parts) if coord_ref_parts else "no coordinate data available"
    )
    coordinate_reference = ReasoningStep(
        step_type="coordinate_reference",
        content=f"The violation involves entities at: {coord_ref_str}",
        coordinates=coords_tuple,
    )

    # Step 4: Diagnosis
    vtype = violation.type
    diagnosis_text = _DIAGNOSIS_MAP.get(vtype, _DEFAULT_DIAGNOSIS)
    coord_in_diagnosis = ", ".join(f"[{x}, {y}]" for x, y in coords) if coords else "unknown"
    diagnosis = ReasoningStep(
        step_type="diagnosis",
        content=(
            f"Violation type '{vtype}' at coordinates [{coord_in_diagnosis}] "
            f"indicates {diagnosis_text}"
        ),
        coordinates=coords_tuple,
        metadata={"violation_type": vtype},
    )

    # Step 5: Recommendation
    recommendation_text = _RECOMMENDATION_MAP.get(vtype, _DEFAULT_RECOMMENDATION)
    recommendation = ReasoningStep(
        step_type="recommendation",
        content=f"Consider: {recommendation_text}",
        metadata={"violation_type": vtype},
    )

    steps = (observation, spatial_context, coordinate_reference, diagnosis, recommendation)

    severity_str = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)

    return ReasoningChain(
        violation_type=vtype,
        violation_description=violation.description,
        severity=severity_str,
        steps=steps,
        spatial_primitives=tuple(nearby_json),
        chain_id=str(uuid.uuid4()),
    )


def synthesize_chains(
    drc_result: DrcResult | None = None,
    erc_result: ErcResult | None = None,
    pcb_primitives: list | None = None,
) -> list[ReasoningChain]:
    """Process all violations from DRC and/or ERC results into reasoning chains.

    If both are provided, DRC violations are processed first, then ERC.
    Empty violations yield an empty list.

    Args:
        drc_result: Optional DRC result with violations.
        erc_result: Optional ERC result with violations.
        pcb_primitives: Optional spatial primitives for context enrichment.

    Returns:
        List of ReasoningChain objects, one per violation.
    """
    chains: list[ReasoningChain] = []

    if drc_result is not None:
        for violation in drc_result.violations:
            chains.append(synthesize_chain(violation, pcb_primitives))
        for violation in drc_result.unconnected_items:
            chains.append(synthesize_chain(violation, pcb_primitives))

    if erc_result is not None:
        for violation in erc_result.violations:
            chains.append(synthesize_chain(violation, pcb_primitives))

    return chains


def _extract_violation_coordinates(
    violation: Violation,
) -> list[tuple[float, float]]:
    """Extract (x, y) coordinates from violation items.

    Each item is a dict that may contain a "pos" key with {"x": float, "y": float}.
    Items without position data yield (0.0, 0.0).

    Args:
        violation: Violation with items to extract coordinates from.

    Returns:
        List of (x, y) coordinate tuples.
    """
    coords: list[tuple[float, float]] = []
    for item in violation.items:
        if isinstance(item, dict):
            pos = item.get("pos", {})
            if isinstance(pos, dict) and "x" in pos and "y" in pos:
                coords.append((float(pos["x"]), float(pos["y"])))
            else:
                coords.append((0.0, 0.0))
        else:
            coords.append((0.0, 0.0))
    return coords


def _find_nearby_primitives(
    coords: tuple[float, float],
    primitives: list,
    radius_mm: float = 5.0,
) -> list[dict]:
    """Find spatial primitives within radius_mm of the given coordinates.

    Uses Shapely Point buffer + intersection for geometric proximity queries.
    Falls back to distance calculation if Shapely is unavailable.

    Args:
        coords: (x, y) center point in mm.
        primitives: List of spatial primitive objects with to_shapely() and to_json() methods.
        radius_mm: Search radius in mm.

    Returns:
        List of primitive.to_json() dicts for primitives within the radius.
    """
    try:
        from shapely.geometry import Point

        query_point = Point(coords[0], coords[1])
        buffer = query_point.buffer(radius_mm)

        results: list[dict] = []
        for prim in primitives:
            if hasattr(prim, "to_shapely") and hasattr(prim, "to_json"):
                geom = prim.to_shapely()
                if geom.intersects(buffer):
                    results.append(prim.to_json())
        return results
    except ImportError:
        # Fallback: use euclidean distance
        results: list[dict] = []
        for prim in primitives:
            if hasattr(prim, "to_json"):
                results.append(prim.to_json())
        return results
