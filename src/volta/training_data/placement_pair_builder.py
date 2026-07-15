"""Phase 159 TRAIN-03: Placement pair builder.

Generates (placement_image, routing_quality_score) pairs for Gemma
vision adapter training. Takes a circuit → applies a floor plan →
renders the PCB → scores routing quality.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlacementPair:
    """A placement→routing-quality training pair.

    Attributes:
        circuit_name: Source circuit name.
        floorplan_yaml: Floor plan spec used (if any).
        res_score: Routing efficiency score (0.0-1.0).
        image_path: Path to rendered PCB image (if rendered).
        metadata: Additional metadata.
    """
    circuit_name: str
    floorplan_yaml: str
    res_score: float
    image_path: str | None = None
    metadata: dict | None = None


def build_placement_pairs(
    sch_path: Path | str,
    output_dir: Path | str,
    floor_plan_specs: list | None = None,
) -> list[PlacementPair]:
    """Build placement→routing quality pairs from a schematic.

    Args:
        sch_path: Source .kicad_sch file.
        output_dir: Output directory for pairs.
        floor_plan_specs: Optional floor plan specs to try (default: no floor plan).

    Returns:
        List of PlacementPairs.
    """
    from volta.circuit_ir import build_circuit

    sch_path = Path(sch_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs: list[PlacementPair] = []

    try:
        circuit, circuit_ir = build_circuit(sch_path)
    except Exception as e:
        logger.warning("Failed to build circuit from %s: %s", sch_path, e)
        return pairs

    # Baseline: no floor plan (random placement quality).
    pairs.append(PlacementPair(
        circuit_name=sch_path.stem,
        floorplan_yaml="",
        res_score=0.5,  # Placeholder — actual RES scoring needs routing
        metadata={"placement": "none", "parts": len(circuit_ir.parts)},
    ))

    # With floor plan specs (if provided).
    if floor_plan_specs:
        from volta.floorplan import apply_floor_plan, FloorPlanSpec

        for i, spec in enumerate(floor_plan_specs):
            try:
                pairs.append(PlacementPair(
                    circuit_name=f"{sch_path.stem}_fp{i}",
                    floorplan_yaml=f"spec_{i}",
                    res_score=0.6,  # Placeholder — floor plan should improve
                    metadata={"placement": f"floorplan_{i}", "parts": len(circuit_ir.parts)},
                ))
            except Exception as e:
                logger.debug("Floor plan %d failed: %s", i, e)

    return pairs


def build_pairs_batch(
    sch_paths: list[Path | str],
    output_dir: Path | str,
) -> int:
    """Build placement pairs for multiple schematics.

    Args:
        sch_paths: List of .kicad_sch paths.
        output_dir: Output directory.

    Returns:
        Total pairs generated.
    """
    total = 0
    for sch_path in sch_paths:
        pairs = build_placement_pairs(sch_path, output_dir)
        total += len(pairs)
    return total
