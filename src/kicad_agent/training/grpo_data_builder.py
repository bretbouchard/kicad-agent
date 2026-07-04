"""GRPODataBuilder — controlled schematic variations for GRPO exploration (D-02).

Per CONTEXT.md D-02 GRPO path: take base schematics, generate N controlled
variations per base (placement perturbations via D-04 alignment jitter),
score each via the verified SRS chain, emit reward deltas for exploration
training. The reward delta (variation_srs - base_srs) is the per-step
advantage signal that GRPO trains on.

Verified chain (CR-110-02 / HI-110-06 fix):
    parse_schematic(path) -> ParseResult
    SchematicIR(_parse_result=parse_result) -> ir
    SchematicSpatialExtractor(ir) -> extractor
    SchematicReadabilityScorer(extractor).score() -> ReadabilityReport

Phase 63 H-12/H-13 deterministic seeding (HI-110-07 inlined constant):
    _SEED_SPACING = 1_000_000
    Per-variation seed offsets: var_seed = seed + i * _SEED_SPACING

Uses SchematicRawWriter for atomic mutation (NOT kiutils.to_file — corrupts
KiCad 10 files per Phase 101/102 lesson). Frozen per Phase 100 CR-01.
"""
from __future__ import annotations

import json
import logging
import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any

from kicad_agent.analysis.readability_scorer import (
    SchematicReadabilityScorer,
)
from kicad_agent.analysis.schematic_spatial import SchematicSpatialExtractor
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter
from kicad_agent.parser.schematic_parser import parse_schematic
from kicad_agent.io.atomic_write import atomic_write
from kicad_agent.training.rewards import AlignmentJitter

logger = logging.getLogger(__name__)

# Phase 63 H-12/H-13 deterministic seeding (inlined per HI-110-07).
# Rule: per-variation seed offsets use seed + variation_index * _SEED_SPACING.
# Purpose: deterministic RNG across workers/restarts for reproducible training.
_SEED_SPACING: int = 1_000_000

# Refs like "R?" or "U?" are uninstantiated KiCad placeholders. The raw
# writer refuses to move them (ambiguous match — many symbols share "?".
# Only instantiated refs matching this regex are perturbable.
_INSTANTIATED_REF_RE = re.compile(r"^[A-Z]+[0-9]+\Z")


class GRPODataBuilderError(Exception):
    """Raised when variation generation fails (empty schematic, parse error, etc.)."""


@dataclass(frozen=True)
class GRPODataBuilder:
    """Generate controlled schematic variations for GRPO exploration (D-02 GRPO path).

    Applies D-04 alignment jitter to base schematic components, scores each
    variation via the verified SRS chain (CR-110-02/HI-110-06 fix), emits
    reward deltas. Frozen per Phase 100 CR-01.

    Attributes:
        jitter: AlignmentJitter instance for coordinate perturbation.
        output_dir: Directory where variation .kicad_sch files are written.
    """

    jitter: AlignmentJitter = field(default_factory=lambda: AlignmentJitter(amplitude_mm=0.1))
    output_dir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="grpo_var_")))

    def __post_init__(self) -> None:
        # Ensure output_dir exists — atomic_write doesn't create parent dirs
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def perturb_schematic(self, base_path: Path, seed: int) -> Path:
        """Generate a perturbed variation of base_path. Deterministic in seed.

        Steps:
            1. Read raw bytes of base_path
            2. Parse to extract component refs + positions (validates count > 0)
            3. For each component: jitter X and Y via the seeded RNG
            4. Write mutated raw bytes atomically to output_dir / f"{stem}_var_{seed}.kicad_sch"

        Args:
            base_path: Path to a base .kicad_sch schematic.
            seed: Deterministic RNG seed for this variation.

        Returns:
            Path to the written variation file.

        Raises:
            GRPODataBuilderError: If base_path has zero components.
        """
        raw = base_path.read_text(encoding="utf-8")

        # Parse to count components and extract positions
        parse_result = parse_schematic(base_path)
        ir = SchematicIR(_parse_result=parse_result)
        components = list(ir.components)
        if not components:
            raise GRPODataBuilderError(
                f"{base_path}: no components to perturb (empty schematic)"
            )

        # Filter to instantiated refs only — "R?" / "U?" placeholders are
        # ambiguous (many symbols share them) and the raw writer refuses to
        # move them. If no instantiated refs exist, we can't perturb.
        perturbable = [
            (i, sym) for i, sym in enumerate(components)
            if _INSTANTIATED_REF_RE.match(ir.get_component_property(sym, "Reference") or "")
        ]
        if not perturbable:
            raise GRPODataBuilderError(
                f"{base_path}: no instantiated component refs to perturb "
                f"(all {len(components)} symbols are placeholders like 'R?')"
            )

        # Deterministic per-component perturbation. Each component gets its own
        # Random seeded as `seed + component_index` — this guarantees that
        # perturbing component N is independent of perturbing component M.
        mutated = raw
        for i, sym in perturbable:
            ref = ir.get_component_property(sym, "Reference") or ""
            # Original position from kiutils symbol
            orig_x = float(sym.position.X)
            orig_y = float(sym.position.Y)
            # Per-component deterministic RNG (NOT per-variation — variation
            # seed is consumed by the outer loop in build_exploration_rows)
            rng = Random(seed + i)
            new_x = self.jitter.perturb_coord(orig_x, rng)
            new_y = self.jitter.perturb_coord(orig_y, rng)
            mutation = {"op": "move_symbol", "ref": ref, "new_x": new_x, "new_y": new_y}
            mutated = SchematicRawWriter.apply_mutation(mutated, mutation)

        var_path = self.output_dir / f"{base_path.stem}_var_{seed}.kicad_sch"
        atomic_write(var_path, mutated)
        return var_path

    def score_variation(self, base_path: Path, variation_path: Path) -> dict:
        """Score base and variation, return dict with base_srs/variation_srs/reward_delta."""
        base_srs = self._score_schematic(base_path)
        variation_srs = self._score_schematic(variation_path)
        return {
            "base_srs": base_srs,
            "variation_srs": variation_srs,
            "reward_delta": variation_srs["overall_srs"] - base_srs["overall_srs"],
        }

    def _score_schematic(self, sch_path: Path) -> dict:
        """Verified SRS chain (CR-110-02 fix). Returns dict with 5 keys."""
        parse_result = parse_schematic(sch_path)
        ir = SchematicIR(_parse_result=parse_result)
        extractor = SchematicSpatialExtractor(ir)
        report = SchematicReadabilityScorer(extractor).score()
        return {
            "density": report.factors["density"],
            "clarity": report.factors["clarity"],
            "spacing": report.factors["spacing"],
            "organization": report.factors["organization"],
            "overall_srs": report.srs,
        }

    def build_exploration_rows(
        self,
        base_path: Path,
        n_variations: int,
        seed: int = 42,
    ) -> list[str]:
        """Generate N variations, score each, emit JSONL rows.

        Phase 63 H-12/H-13 deterministic seeding (HI-110-07 inlined):
            var_seed = seed + i * _SEED_SPACING for i in range(n_variations)
        """
        rows: list[str] = []
        base_srs_cache: dict | None = None
        for i in range(n_variations):
            var_seed = seed + i * _SEED_SPACING
            var_path = self.perturb_schematic(base_path, var_seed)
            scores = self.score_variation(base_path, var_path)
            # Cache base_srs — it doesn't change across variations
            if base_srs_cache is None:
                base_srs_cache = scores["base_srs"]
            # Compute perturbation summary (count of components moved)
            n_moved = self._count_components(base_path)
            row = {
                "base_path": str(base_path.resolve()),
                "variation_path": str(var_path.resolve()),
                "variation_id": i,
                "base_srs": scores["base_srs"],
                "variation_srs": scores["variation_srs"],
                "reward_delta": scores["reward_delta"],
                "perturbation_summary": {
                    "n_components_moved": n_moved,
                    "mean_displacement_mm": self.jitter.amplitude_mm,
                },
                "seed": var_seed,
            }
            rows.append(json.dumps(row))
        return rows

    def _count_components(self, sch_path: Path) -> int:
        """Count components in a schematic (for perturbation summary)."""
        parse_result = parse_schematic(sch_path)
        ir = SchematicIR(_parse_result=parse_result)
        return len(list(ir.components))
