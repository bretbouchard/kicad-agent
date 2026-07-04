"""SFTLabeller — scores real .kicad_sch files via Phase 48.5 SRS (Plan 02 D-02).

Per CONTEXT.md D-02: SFT path uses real schematics as ground-truth baseline.
Construction chain (CR-110-02 fix):
    parse_schematic(path) -> ParseResult
    SchematicIR(_parse_result=parse_result) -> ir
    SchematicSpatialExtractor(ir) -> extractor
    SchematicReadabilityScorer(extractor).score() -> ReadabilityReport
    report.srs is overall (NOT factors["overall"])

ReadabilityReport.factors has exactly 4 keys: density, clarity, spacing,
organization. The labeller emits them as a flat dict with overall_srs
sourced from report.srs.

Frozen per Phase 100 CR-01. The `stats` field is a mutable LabellerStats
holder passed by reference (accumulator pattern, documented CR-01 exception).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kicad_agent.analysis.readability_scorer import (
    SchematicReadabilityScorer,
)
from kicad_agent.analysis.schematic_spatial import SchematicSpatialExtractor
from kicad_agent.ir.schematic_ir import SchematicIR
from kicad_agent.parser.schematic_parser import parse_schematic

logger = logging.getLogger(__name__)


class SFTLabellerError(Exception):
    """Raised when a schematic cannot be scored (corrupt, unparseable, missing, oversized)."""


@dataclass
class LabellerStats:
    """Mutable counter holder. Exception to Phase 100 CR-01 (accumulator, not value object)."""
    n_scored: int = 0
    n_skipped: int = 0
    n_errors: int = 0


@dataclass(frozen=True)
class SFTLabeller:
    """Scores real .kicad_sch files with Phase 48.5 SRS via the verified chain.

    Per CONTEXT.md D-02: SFT path uses real schematics as ground-truth baseline.
    Frozen per Phase 100 CR-01 (stats is a mutable holder passed by reference).

    Construction chain (CR-110-02 fix):
        parse_schematic(path) -> ParseResult
        SchematicIR(_parse_result=parse_result) -> ir
        SchematicSpatialExtractor(ir) -> extractor
        SchematicReadabilityScorer(extractor).score() -> ReadabilityReport

    Attributes:
        source_tag: Tag emitted in JSONL `source` field (audit trail).
        max_file_mb: Skip files larger than this (ME-110-10 guard).
        stats: Mutable counter holder (n_scored, n_skipped, n_errors).
    """

    source_tag: str = "kicad-crawler"
    max_file_mb: int = 50  # ME-110-10: skip oversized files deterministically
    stats: LabellerStats = field(default_factory=LabellerStats)

    def score_file(self, sch_path: Path) -> dict[str, Any]:
        """Score a single schematic via the verified SRS chain.

        Returns:
            Dict with keys: density, clarity, spacing, organization,
            overall_srs, element_count.

        Raises:
            FileNotFoundError: If sch_path does not exist.
            SFTLabellerError: For any other failure (corrupt, oversized, etc.).
        """
        # 1. Size guard (ME-110-10): skip oversized files BEFORE parsing.
        size_mb = sch_path.stat().st_size / (1024 * 1024)
        if size_mb > self.max_file_mb:
            raise SFTLabellerError(
                f"{sch_path}: file size {size_mb:.1f}MB exceeds max_file_mb={self.max_file_mb}"
            )

        # 2-5. Verified SRS chain (CR-110-02 fix)
        try:
            parse_result = parse_schematic(sch_path)
            ir = SchematicIR(_parse_result=parse_result)
            extractor = SchematicSpatialExtractor(ir)
            report = SchematicReadabilityScorer(extractor).score()
        except FileNotFoundError:
            raise  # let caller decide
        except Exception as exc:
            # Wrap in clean error boundary (no kiutils leak)
            raise SFTLabellerError(f"{sch_path}: {type(exc).__name__}: {exc}") from exc

        # 6. Return dict — overall_srs from report.srs (NOT factors["overall"])
        return {
            "density": report.factors["density"],
            "clarity": report.factors["clarity"],
            "spacing": report.factors["spacing"],
            "organization": report.factors["organization"],
            "overall_srs": report.srs,
            "element_count": report.element_count,
        }

    def label_to_jsonl(self, sch_path: Path, score: dict) -> str:
        """Build a JSONL row string for the given schematic + score dict."""
        return json.dumps({
            "input_path": str(sch_path.resolve()),
            "labels": score,
            "source": self.source_tag,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        })

    def label_corpus(self, sch_paths: list[Path]) -> list[str]:
        """Score + label every schematic in the corpus.

        Corrupt or oversized schematics are skipped with a warning and counted
        in stats.n_skipped (not raised). FileNotFound counts as n_errors.

        Returns:
            List of JSONL row strings, one per successfully-scored schematic.
        """
        rows: list[str] = []
        for path in sch_paths:
            try:
                score = self.score_file(path)
                row = self.label_to_jsonl(path, score)
                rows.append(row)
                self.stats.n_scored += 1
            except SFTLabellerError as exc:
                logger.warning("SFT labeller skipped %s: %s", path, exc)
                self.stats.n_skipped += 1
                continue
            except FileNotFoundError as exc:
                logger.warning("SFT labeller file-not-found %s: %s", path, exc)
                self.stats.n_errors += 1
                continue
        return rows
