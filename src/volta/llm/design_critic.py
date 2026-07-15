"""Design critic with spatial reasoning via Claude extended thinking.

Analyzes PCB layouts for clearance violations, routing congestion, and
thermal hotspots using spatial data from SpatialQueryEngine. Uses Claude
extended thinking for deeper spatial reasoning.

Exports:
    CritiqueSeverity: Enum with INFO, WARNING, CRITICAL values.
    CritiqueFinding: Frozen dataclass for individual critique findings.
    CritiqueReport: Frozen dataclass for the complete critique report.
    build_spatial_context: Converts SpatialQueryEngine data to LLM-readable text.
    DesignCritic: Main class that uses LLMClient with extended thinking.

Security (threat model):
  T-15-07: Component box output capped at 20 entries to prevent context overflow.
  T-15-08: CritiqueFinding validated from tool_use output; coordinates are floats only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from volta.llm.context_builder import ContextBuilder

if TYPE_CHECKING:
    from volta.llm.backend import LLMBackend
    from volta.llm.provider import LLMProvider


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class CritiqueSeverity(str, Enum):
    """Severity level for a design critique finding."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class CritiqueFinding:
    """A single design critique finding with spatial reference.

    Attributes:
        severity: How serious this finding is.
        category: Type of issue (clearance, congestion, thermal, placement).
        description: Human-readable description of the issue.
        coordinates: Tuple of (x, y) coordinate pairs marking affected areas.
    """

    severity: CritiqueSeverity
    category: str
    description: str
    coordinates: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class CritiqueReport:
    """Complete design critique report with findings and quality score.

    Attributes:
        findings: Tuple of individual critique findings.
        summary: High-level summary of the critique.
        overall_quality_score: Computed quality score from 0.0 (poor) to 1.0 (excellent).
    """

    findings: tuple[CritiqueFinding, ...]
    summary: str
    overall_quality_score: float


# ---------------------------------------------------------------------------
# Spatial context builder
# ---------------------------------------------------------------------------

_MAX_COMPONENT_BOXES = 20


def build_spatial_context(engine: Any) -> str:
    """Convert SpatialQueryEngine data into a compact LLM-readable summary.

    Retrieves all entities via a large-radius proximity query, groups them
    by entity_type, and formats component bounding boxes for LLM consumption.
    Component box output is capped at 20 entries to manage context window.

    Args:
        engine: SpatialQueryEngine instance.

    Returns:
        Multi-line string suitable for inclusion in an LLM prompt.
    """
    all_entities = engine.proximity(0, 0, radius_mm=10000)
    total = len(all_entities)

    if total == 0:
        return "Total entities on board: 0"

    # Group by entity_type
    by_type: dict[str, list] = {}
    for entity in all_entities:
        etype = entity.entity_type
        by_type.setdefault(etype, []).append(entity)

    lines: list[str] = [f"Total entities on board: {total}"]

    for etype, entities in sorted(by_type.items()):
        lines.append(f"{etype}: {len(entities)}")

        # Include bounding boxes for components, capped
        if etype == "component":
            for entity in entities[:_MAX_COMPONENT_BOXES]:
                lines.append(
                    f"  {entity.entity_id}: "
                    f"box({entity.x1:.1f},{entity.y1:.1f},"
                    f"{entity.x2:.1f},{entity.y2:.1f}) "
                    f"layer={entity.layer} ref={entity.reference}"
                )

            remaining = len(entities) - _MAX_COMPONENT_BOXES
            if remaining > 0:
                lines.append(f"  ... and {remaining} more components")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt and tool definition
# ---------------------------------------------------------------------------

CRITIC_SYSTEM_PROMPT = (
    "You are a PCB design critic. Analyze the spatial layout data for "
    "clearance issues (components too close together), routing congestion "
    "(dense component clusters with many nets between them), and thermal "
    "hotspots (clustered power components). For each issue, provide: "
    "severity (info/warning/critical), category, description with specific "
    "coordinate references, and the coordinates of the affected area."
)

CRITIC_TOOL = {
    "name": "design_critique",
    "description": (
        "Provide a structured critique of a PCB layout including "
        "clearance, congestion, thermal, and placement findings"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "description": "List of design critique findings",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["info", "warning", "critical"],
                            "description": "Severity level",
                        },
                        "category": {
                            "type": "string",
                            "description": "Issue category (clearance, congestion, thermal, placement)",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the issue",
                        },
                        "coordinates": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            "description": "Coordinate pairs [x, y] of affected areas",
                        },
                    },
                    "required": ["severity", "category", "description", "coordinates"],
                },
            },
            "summary": {
                "type": "string",
                "description": "High-level summary of the design critique",
            },
            "overall_quality_score": {
                "type": "number",
                "description": "Overall quality score from 0.0 (poor) to 1.0 (excellent)",
            },
        },
        "required": ["findings", "summary", "overall_quality_score"],
    },
}

# Quality score deductions per severity
_SEVERITY_PENALTY = {
    CritiqueSeverity.CRITICAL: 0.3,
    CritiqueSeverity.WARNING: 0.1,
    CritiqueSeverity.INFO: 0.02,
}


# ---------------------------------------------------------------------------
# DesignCritic
# ---------------------------------------------------------------------------


class DesignCritic:
    """PCB design critic using Claude extended thinking for spatial analysis.

    Analyzes board layouts for clearance violations, routing congestion,
    and thermal hotspots by sending spatial context to Claude with tool
    use for structured output.

    Args:
        model: Optional model override for LLMClient.
        client: Optional LLMBackend instance. If provided, used instead of
                creating a new LLMClient.
        provider: Optional LLMProvider instance. Takes priority over client
                  and model when provided.
    """

    def __init__(
        self,
        model: str | None = None,
        client: LLMBackend | None = None,
        provider: LLMProvider | None = None,
    ) -> None:
        if provider is not None:
            self._client = provider
        else:
            from volta.llm.client import LLMClient
            self._client = client or LLMClient(model=model)

    def critique(
        self,
        engine: Any,
        erc_result: Any | None = None,
        drc_result: Any | None = None,
    ) -> CritiqueReport:
        """Analyze spatial layout and return a structured critique report.

        Args:
            engine: SpatialQueryEngine with indexed PCB primitives.
            erc_result: Optional ErcResult with ERC violations.
            drc_result: Optional DrcResult with DRC violations.

        Returns:
            CritiqueReport with findings, summary, and quality score.
        """
        # Build spatial context
        spatial_context = build_spatial_context(engine)

        # Build error context if violations provided
        error_context = ""
        if erc_result is not None:
            error_context = "\n\n" + ContextBuilder.build_error_summary(
                erc_result, drc_result
            )

        user_content = f"Analyze this PCB layout:\n\n{spatial_context}{error_context}"

        # Call Claude with extended thinking
        message = self._client.create_message(
            max_tokens=16000,
            system=CRITIC_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            tools=[CRITIC_TOOL],
            tool_choice={"type": "tool", "name": "design_critique"},
            thinking={"type": "enabled", "budget_tokens": 8000},
        )

        # Extract tool_use block
        tool_block = None
        for block in message.content:
            if block.type == "tool_use" and block.name == "design_critique":
                tool_block = block
                break

        if tool_block is None:
            return CritiqueReport(
                findings=(),
                summary="No critique available - tool use not returned",
                overall_quality_score=1.0,
            )

        # Parse findings from tool output
        raw_findings = tool_block.input.get("findings", [])
        findings: list[CritiqueFinding] = []
        for raw in raw_findings:
            severity = CritiqueSeverity(raw["severity"])
            coords = tuple(
                (float(c[0]), float(c[1])) for c in raw.get("coordinates", [])
            )
            findings.append(
                CritiqueFinding(
                    severity=severity,
                    category=raw["category"],
                    description=raw["description"],
                    coordinates=coords,
                )
            )

        # Compute quality score from severities
        score = 1.0
        for finding in findings:
            score -= _SEVERITY_PENALTY[finding.severity]
        score = max(0.0, min(1.0, score))

        return CritiqueReport(
            findings=tuple(findings),
            summary=tool_block.input.get("summary", ""),
            overall_quality_score=score,
        )
