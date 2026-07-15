"""Schematic readability reviewer -- orchestrates spatial rules + scoring + vision.

READ-01/02/03/04: Combines the 6 readability rules, SRS scorer,
and optional Claude vision review into a single review pipeline.

Usage:
    from volta.analysis.schematic_reviewer import SchematicReviewer

    reviewer = SchematicReviewer(schematic_ir)
    report = reviewer.review()
    print(f"SRS: {report.srs:.2f}")

    # With vision review
    report = reviewer.review(vision=True)
"""
from __future__ import annotations

import atexit
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from volta.ir.schematic_ir import SchematicIR

from volta.analysis.design_rules import DesignRuleReport
from volta.analysis.design_rule_engine import DesignRuleEngine
from volta.analysis.readability_rules import get_schematic_readability_rules
from volta.analysis.readability_scorer import (
    ReadabilityReport,
    SchematicReadabilityScorer,
)
from volta.analysis.schematic_spatial import SchematicSpatialExtractor

logger = logging.getLogger(__name__)

# Prompt template for Claude vision review
_VISION_REVIEW_PROMPT = """\
You are reviewing a KiCad schematic for readability and visual quality.

Analyze this schematic image for:
1. **Overlapping elements**: Are any components, labels, or text overlapping?
2. **Label clarity**: Are net labels readable and non-redundant?
3. **Signal flow**: Does the layout follow left-to-right or top-to-bottom signal flow?
4. **Functional grouping**: Are related components visually grouped together?
5. **Spacing**: Is there adequate spacing between elements for readability?
6. **Wire routing**: Are wires clean, or do they cross through component bodies?

For each issue found, provide:
- The approximate location (describe what you see)
- The severity: critical, warning, or suggestion
- A concrete fix suggestion

End with an overall readability rating: excellent / good / fair / poor.
"""


@dataclass(frozen=True)
class VisionFinding:
    """A finding from Claude's vision review."""
    description: str
    severity: str  # critical, warning, suggestion
    location: str
    suggestion: str


@dataclass(frozen=True)
class SchematicReviewReport:
    """Complete schematic readability review report.

    Attributes:
        srs: Schematic Readability Score (0.0-1.0).
        readability: ReadabilityReport with factor scores.
        rule_report: DesignRuleReport from rule engine.
        vision_findings: Findings from Claude vision review (empty if not run).
        rendered_path: Path to rendered schematic image (None if not rendered).
        file_path: Path to reviewed schematic.
    """

    srs: float
    readability: ReadabilityReport
    rule_report: DesignRuleReport
    vision_findings: tuple[VisionFinding, ...] = ()
    rendered_path: str | None = None
    file_path: str = ""

    def cleanup_rendered(self) -> None:
        """Delete the rendered PDF temp file if it exists."""
        if self.rendered_path and os.path.exists(self.rendered_path):
            try:
                os.unlink(self.rendered_path)
            except OSError:
                pass


class SchematicReviewer:
    """Orchestrates schematic readability review.

    Args:
        schematic_ir: Parsed SchematicIR to review.
        topology: Optional CircuitTopology for organization scoring.
    """

    def __init__(
        self,
        schematic_ir: "SchematicIR",
        topology: Any | None = None,
    ) -> None:
        self._ir = schematic_ir
        self._topology = topology
        self._extractor = SchematicSpatialExtractor(schematic_ir)

    def review(
        self,
        vision: bool = False,
        disabled_rules: set[str] | None = None,
        config: dict[str, dict] | None = None,
    ) -> SchematicReviewReport:
        """Run complete schematic readability review.

        Args:
            vision: Whether to include Claude vision review.
            disabled_rules: Rules to skip.
            config: Per-rule configuration overrides.

        Returns:
            SchematicReviewReport with SRS, rule violations, and optional vision findings.
        """
        # Run readability rules
        # If no topology provided, create a lightweight wrapper so rules can
        # access the schematic IR via topology._schematic_ir.
        topology = self._topology
        if topology is None:
            topology = type("_TopologyWrapper", (), {"_schematic_ir": self._ir})()

        rules = get_schematic_readability_rules()
        engine = DesignRuleEngine(
            rules=rules,
            disabled_rules=disabled_rules,
            config=config,
        )
        rule_report = engine.run(topology)

        # Compute SRS score
        scorer = SchematicReadabilityScorer(self._extractor, topology)
        readability = scorer.score()

        # Optional vision review
        vision_findings: tuple[VisionFinding, ...] = ()
        rendered_path = None
        if vision:
            rendered_path = self.render_schematic()
            if rendered_path:
                vision_findings = self.vision_review(rendered_path)

        return SchematicReviewReport(
            srs=readability.srs,
            readability=readability,
            rule_report=rule_report,
            vision_findings=vision_findings,
            rendered_path=rendered_path,
            file_path=getattr(self._ir, "file_path", ""),
        )

    def render_schematic(self) -> str | None:
        """Render schematic to PDF using kicad-cli.

        Returns:
            Path to rendered PDF, or None if rendering fails.
            Caller should call cleanup_rendered() on the report when done.
        """
        file_path = getattr(self._ir, "file_path", None)
        if not file_path:
            logger.warning("No file_path on SchematicIR, cannot render")
            return None

        # Validate path before passing to subprocess
        try:
            path = Path(file_path).resolve()
        except (ValueError, OSError):
            logger.warning("Invalid file_path: %s", file_path)
            return None

        if path.suffix != ".kicad_sch":
            logger.warning("file_path is not a .kicad_sch file: %s", path)
            return None
        if not path.is_file():
            logger.warning("file_path does not exist: %s", path)
            return None

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".pdf", delete=False, prefix="schematic_review_",
            ) as tmp:
                output_path = tmp.name

            # Schedule cleanup so temp files don't leak
            atexit.register(os.unlink, output_path)

            result = subprocess.run(
                ["kicad-cli", "sch", "export", "pdf", str(path), "-o", output_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return output_path
            logger.warning("kicad-cli render failed: %s", result.stderr)
            # Clean up failed render temp file
            try:
                os.unlink(output_path)
            except OSError:
                pass
            return None
        except Exception as e:
            logger.warning("Schematic rendering failed: %s", e)
            return None

    def vision_review(self, image_path: str) -> tuple[VisionFinding, ...]:
        """Run Claude vision review on rendered schematic.

        Args:
            image_path: Path to rendered schematic PDF/PNG.

        Returns:
            Tuple of VisionFinding objects from Claude's review.
        """
        try:
            from volta.llm.client import LLMClient
        except ImportError:
            logger.warning("LLM client not available, skipping vision review")
            return ()

        try:
            client = LLMClient()
            with open(image_path, "rb") as f:
                image_data = f.read()

            import base64
            encoded = base64.b64encode(image_data).decode("utf-8")

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_REVIEW_PROMPT},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": encoded,
                            },
                        },
                    ],
                },
            ]

            response = client.create_message(messages=messages)
            # Anthropic SDK returns Message object with .content list of ContentBlocks
            if response.content:
                review_text = response.content[0].text
            else:
                review_text = ""

            return self._parse_vision_findings(review_text)
        except Exception as e:
            logger.warning("Vision review failed: %s", e)
            return ()

    @staticmethod
    def _parse_vision_findings(text: str) -> tuple[VisionFinding, ...]:
        """Parse Claude's vision review text into structured findings."""
        findings = []
        current_severity = "suggestion"

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            lower = line.lower()
            if "critical" in lower or "severe" in lower:
                current_severity = "critical"
            elif "warning" in lower:
                current_severity = "warning"
            elif "suggestion" in lower or "consider" in lower or "info" in lower:
                current_severity = "suggestion"

            if line.startswith(("-", "*", "•")) or (len(line) > 2 and line[0].isdigit() and "." in line[:4]):
                findings.append(VisionFinding(
                    description=line.lstrip("-*•0123456789. "),
                    severity=current_severity,
                    location="(vision review)",
                    suggestion="See description",
                ))

        return tuple(findings)
