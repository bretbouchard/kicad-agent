"""Intelligent DRC analysis: enriched violations, fix suggestions, version checks.

VP-53-01: Transforms raw kicad-cli DRC output into actionable, coordinate-grounded
fix recommendations. Each violation is enriched with spatial context, constraint
classification, and concrete fix suggestions with confidence scores.

Architecture:
  IntelligentDrcAnalyzer consumes DrcResult and produces IntelligentDrcReport.
  Each EnrichedViolation wraps a SpatialViolation with:
    - ViolationClassification (constraint_violation, manufacturing, cosmetic)
    - FixSuggestion list from FixSuggester
    - Optional related PCBConstraint link (Phase 50, typed as Any)

Usage:
    from volta.validation.drc_intel import IntelligentDrcAnalyzer

    analyzer = IntelligentDrcAnalyzer()
    report = analyzer.analyze(drc_result)
    for ev in report.enriched_violations:
        print(ev.format_report())
        for s in ev.fix_suggestions:
            print(f"  -> {s.action} (confidence={s.confidence:.0%})")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, TYPE_CHECKING

from volta.spatial.primitives import SpatialPoint
from volta.validation.erc_drc import DrcResult
from volta.validation.spatial_drc import SpatialViolation, enrich_drc_result

if TYPE_CHECKING:
    pass  # Phase 50/51 types not yet implemented

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ViolationClassification(str, Enum):
    """Classification of DRC violation severity category.

    Uses str+Enum pattern matching existing Severity in erc_drc.py.
    """

    CONSTRAINT_VIOLATION = "constraint_violation"
    MANUFACTURING = "manufacturing"
    COSMETIC = "cosmetic"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpatialFixSuggestion:
    """A concrete fix suggestion for a DRC violation.

    Attributes:
        action: Suggested action (e.g. "increase_clearance", "move_component").
        confidence: Confidence score 0.0-1.0 for this suggestion.
        rationale: Human-readable explanation (max 500 chars).
        target_items: SpatialPoint items this fix applies to.
    """

    action: str
    confidence: float
    rationale: str
    target_items: tuple[SpatialPoint, ...] = ()

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption."""
        return {
            "action": self.action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "target_items": [p.to_json() for p in self.target_items],
        }


@dataclass(frozen=True)
class EnrichedViolation:
    """DRC violation enriched with classification, fix suggestions, and constraint link.

    Contains all fields from SpatialViolation plus additional intelligence layer.
    Use from_spatial_violation() factory to promote existing SpatialViolation objects.
    """

    # Fields inherited from SpatialViolation
    description: str
    severity: str
    violation_type: str
    items: tuple[SpatialPoint, ...]
    spatial_context: str
    raw_items: tuple[dict[str, Any], ...] = ()

    # Intelligence layer
    classification: ViolationClassification = ViolationClassification.CONSTRAINT_VIOLATION
    fix_suggestions: tuple[SpatialFixSuggestion, ...] = ()
    related_constraint: Optional[Any] = None
    kicad_version: str = ""

    @classmethod
    def from_spatial_violation(
        cls,
        sv: SpatialViolation,
        classification: ViolationClassification,
        fix_suggestions: tuple[SpatialFixSuggestion, ...] = (),
        related_constraint: Any | None = None,
        kicad_version: str = "",
    ) -> EnrichedViolation:
        """Create EnrichedViolation from an existing SpatialViolation.

        Args:
            sv: Source SpatialViolation with spatial data.
            classification: Computed violation classification.
            fix_suggestions: Generated fix suggestions.
            related_constraint: Optional linked PCBConstraint (Phase 50).
            kicad_version: KiCad version from DRC report.

        Returns:
            New EnrichedViolation with all spatial fields promoted.
        """
        return cls(
            description=sv.description,
            severity=sv.severity,
            violation_type=sv.violation_type,
            items=sv.items,
            spatial_context=sv.spatial_context,
            raw_items=sv.raw_items,
            classification=classification,
            fix_suggestions=fix_suggestions,
            related_constraint=related_constraint,
            kicad_version=kicad_version,
        )

    def to_json(self) -> dict:
        """Serialize to a plain dict for JSON consumption."""
        return {
            "description": self.description,
            "severity": self.severity,
            "violation_type": self.violation_type,
            "items": [p.to_json() for p in self.items],
            "spatial_context": self.spatial_context,
            "classification": self.classification.value,
            "fix_suggestions": [s.to_json() for s in self.fix_suggestions],
            "related_constraint": repr(self.related_constraint) if self.related_constraint else None,
            "kicad_version": self.kicad_version,
        }

    def format_report(self) -> str:
        """Format as extended report string with classification and fix suggestions.

        Extends SpatialViolation.format_report() with intelligence layer.
        """
        parts = [f"[{self.severity.upper()}] {self.description}"]
        for item in self.items:
            parts.append(
                f"  at <point> [{item.x:.4f}, {item.y:.4f}] ({item.entity_type})"
            )
        parts.append(f"  {self.spatial_context}")
        parts.append(f"  Classification: {self.classification.value}")
        if self.fix_suggestions:
            for s in self.fix_suggestions:
                parts.append(f"  Fix: {s.action} ({s.confidence:.0%}) -- {s.rationale}")
        return "\n".join(parts)


@dataclass(frozen=True)
class IntelligentDrcReport:
    """Complete DRC intelligence report with enriched violations and summary stats.

    Computed fields (total, by_classification, by_severity) are set in
    __post_init__ since the dataclass is frozen.
    """

    enriched_violations: tuple[EnrichedViolation, ...]
    kicad_version: str
    total: int = 0
    by_classification: dict[str, int] = None  # type: ignore[assignment]
    by_severity: dict[str, int] = None  # type: ignore[assignment]
    file_path: Path = Path("")

    def __post_init__(self) -> None:
        """Compute summary statistics from enriched violations."""
        total = len(self.enriched_violations)
        object.__setattr__(self, "total", total)

        by_classification: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        for ev in self.enriched_violations:
            cls_key = ev.classification.value
            by_classification[cls_key] = by_classification.get(cls_key, 0) + 1
            sev_key = ev.severity
            by_severity[sev_key] = by_severity.get(sev_key, 0) + 1
        object.__setattr__(self, "by_classification", by_classification)
        object.__setattr__(self, "by_severity", by_severity)

    def to_json(self) -> dict:
        """Serialize full report to dict for JSON consumption."""
        return {
            "enriched_violations": [ev.to_json() for ev in self.enriched_violations],
            "kicad_version": self.kicad_version,
            "total": self.total,
            "by_classification": self.by_classification,
            "by_severity": self.by_severity,
            "file_path": str(self.file_path),
        }


# ---------------------------------------------------------------------------
# FixSuggester: maps violation type to fix suggestions
# ---------------------------------------------------------------------------

# Type alias for suggestion rule
_SuggestionRule = tuple[
    Callable[[str, str], bool],  # match_fn(violation_type, description)
    str,                          # action
    float,                        # confidence
    Callable[[tuple[SpatialPoint, ...], str], str],  # rationale_fn(items, context)
]

_DEFAULT_RATIONALE = (
    lambda items, ctx: "Review and adjust layout parameters"
)


def _clearance_rationale(items: tuple[SpatialPoint, ...], ctx: str) -> str:
    return "Clearance violation detected -- increase spacing between copper features"


def _courtyard_rationale(items: tuple[SpatialPoint, ...], ctx: str) -> str:
    return "Courtyard overlap -- relocate component to resolve"


def _via_rationale(items: tuple[SpatialPoint, ...], ctx: str) -> str:
    return "Via-related issue -- consider adding teardrop for pad-via connection strength"


def _pad_rationale(items: tuple[SpatialPoint, ...], ctx: str) -> str:
    return "Pad-related issue -- review pad dimensions and annular ring"


def _silk_rationale(items: tuple[SpatialPoint, ...], ctx: str) -> str:
    return "Silkscreen issue -- typically cosmetic, review if intentional"


def _unconnected_rationale(items: tuple[SpatialPoint, ...], ctx: str) -> str:
    return "Unconnected item -- verify net routing completeness"


_SUGGESTION_RULES: list[_SuggestionRule] = [
    (
        lambda vt, desc: "clearance" in vt.lower(),
        "increase_clearance",
        0.85,
        _clearance_rationale,
    ),
    (
        lambda vt, desc: "courtyard" in vt.lower(),
        "move_component",
        0.75,
        _courtyard_rationale,
    ),
    (
        lambda vt, desc: "via" in vt.lower() or "via" in desc.lower(),
        "add_teardrop",
        0.70,
        _via_rationale,
    ),
    (
        lambda vt, desc: "pad" in vt.lower() or "pad" in desc.lower(),
        "resize_pad",
        0.70,
        _pad_rationale,
    ),
    (
        lambda vt, desc: "silk" in vt.lower() or "silkscreen" in vt.lower(),
        "check_net_class",
        0.60,
        _silk_rationale,
    ),
    (
        lambda vt, desc: "unconnected" in vt.lower(),
        "check_net_class",
        0.80,
        _unconnected_rationale,
    ),
]


class FixSuggester:
    """Maps (violation_type, spatial_context) to SpatialFixSuggestion list.

    Pure mapping function with no external dependencies. Uses an ordered list
    of suggestion rules -- first match wins. If no rules match, returns empty
    list (not a placeholder suggestion).
    """

    def suggest(
        self,
        violation_type: str,
        description: str,
        items: tuple[SpatialPoint, ...],
        spatial_context: str,
    ) -> list[SpatialFixSuggestion]:
        """Generate fix suggestions for a violation.

        Args:
            violation_type: Type string from DRC report (e.g. "clearance").
            description: Human-readable violation description.
            items: SpatialPoint items involved in the violation.
            spatial_context: Human-readable spatial context string.

        Returns:
            List of SpatialFixSuggestion objects. Empty if no rules match.
        """
        results: list[SpatialFixSuggestion] = []
        for match_fn, action, confidence, rationale_fn in _SUGGESTION_RULES:
            if match_fn(violation_type, description):
                results.append(
                    SpatialFixSuggestion(
                        action=action,
                        confidence=confidence,
                        rationale=rationale_fn(items, spatial_context),
                        target_items=items,
                    )
                )
                # First match wins
                break
        return results


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------

def _classify_violation(violation_type: str, description: str) -> ViolationClassification:
    """Classify a violation into CONSTRAINT_VIOLATION, MANUFACTURING, or COSMETIC.

    Args:
        violation_type: Type string from DRC report.
        description: Human-readable violation description.

    Returns:
        ViolationClassification enum value. Defaults to CONSTRAINT_VIOLATION
        for unknown types (conservative default).
    """
    vt_lower = violation_type.lower()

    # Manufacturing types
    if any(kw in vt_lower for kw in ("unconnected", "drill", "annular")):
        return ViolationClassification.MANUFACTURING

    # Cosmetic types
    if any(kw in vt_lower for kw in ("silk", "text")):
        return ViolationClassification.COSMETIC

    # Constraint types (explicit + conservative default)
    if any(kw in vt_lower for kw in ("clearance", "width", "courtyard", "track_width")):
        return ViolationClassification.CONSTRAINT_VIOLATION

    # Conservative default: unknown types treated as constraint violations
    return ViolationClassification.CONSTRAINT_VIOLATION


# ---------------------------------------------------------------------------
# Version check helper
# ---------------------------------------------------------------------------

def _check_drc_version(kicad_version: str) -> list[str]:
    """Check DRC report kicad_version for compatibility warnings.

    Args:
        kicad_version: Version string from DRC report (e.g. "10.0.1").

    Returns:
        List of warning strings. Empty list means version is OK.
    """
    if not kicad_version:
        return ["DRC report has no kicad_version -- defensive parsing active"]

    try:
        major_str = kicad_version.split(".")[0]
        major = int(major_str)
    except (ValueError, IndexError):
        return [f"DRC report has unparseable kicad_version '{kicad_version}' -- defensive parsing active"]

    if major < 10:
        return [
            f"DRC report from KiCad {major}.x -- expected 10.x format, parsing may be incomplete"
        ]

    # major >= 10: OK (forward compatible)
    return []


# ---------------------------------------------------------------------------
# IntelligentDrcAnalyzer
# ---------------------------------------------------------------------------

class IntelligentDrcAnalyzer:
    """Transforms DrcResult into IntelligentDrcReport with enriched violations.

    Consumes DrcResult from run_drc(), enriches each violation with spatial
    context via enrich_drc_result(), classifies them, generates fix suggestions,
    and optionally links PCBConstraint objects (Phase 50, typed as Any).

    Args:
        spatial_model: Optional PcbSpatialModel (Phase 51) for nearby component
            lookup. Not required -- backward compatible.
        constraints: Optional list of PCBConstraint objects (Phase 50) to link
            to violations by type matching.
    """

    def __init__(
        self,
        spatial_model: Any = None,
        constraints: list[Any] | None = None,
    ) -> None:
        self._spatial_model = spatial_model
        self._constraints = constraints
        self._fix_suggester = FixSuggester()

    def analyze(self, drc_result: DrcResult) -> IntelligentDrcReport:
        """Analyze DRC result and produce intelligent report.

        Args:
            drc_result: Structured DRC result from run_drc().

        Returns:
            IntelligentDrcReport with enriched violations and summary stats.
            Returns empty report if drc_result has error_message set.
        """
        # Guard: kicad-cli invocation failed
        if drc_result.error_message is not None:
            return IntelligentDrcReport(
                enriched_violations=(),
                kicad_version=drc_result.kicad_version,
                file_path=drc_result.file_path,
            )

        # Version compatibility warnings
        version_warnings = _check_drc_version(drc_result.kicad_version)
        for warning in version_warnings:
            logger.warning(warning)

        # Reuse existing spatial enrichment from Phase 8
        spatial_violations = enrich_drc_result(drc_result, pcb_ir=self._spatial_model)

        # Enrich each spatial violation with classification and fix suggestions
        enriched: list[EnrichedViolation] = []
        for sv in spatial_violations:
            classification = _classify_violation(sv.violation_type, sv.description)
            suggestions = self._fix_suggester.suggest(
                sv.violation_type,
                sv.description,
                sv.items,
                sv.spatial_context,
            )
            constraint = self._match_constraint(sv)

            enriched.append(
                EnrichedViolation.from_spatial_violation(
                    sv,
                    classification=classification,
                    fix_suggestions=tuple(suggestions),
                    related_constraint=constraint,
                    kicad_version=drc_result.kicad_version,
                )
            )

        return IntelligentDrcReport(
            enriched_violations=tuple(enriched),
            kicad_version=drc_result.kicad_version,
            file_path=drc_result.file_path,
        )

    def _match_constraint(self, violation: SpatialViolation) -> Any | None:
        """Find a related PCBConstraint by matching violation_type to constraint type.

        Uses duck-typed constraint objects (getattr) since Phase 50 types
        are not yet implemented. Matches by checking if violation_type keywords
        appear in the constraint's type name.

        Args:
            violation: SpatialViolation to match against constraints.

        Returns:
            Matching constraint object, or None if no match found.
        """
        if not self._constraints:
            return None

        vt_lower = violation.violation_type.lower()

        for constraint in self._constraints:
            # Duck-typed: try constraint_type attribute first
            ct = getattr(constraint, "constraint_type", None) or getattr(constraint, "type", "")
            ct_str = ct.value if hasattr(ct, "value") else str(ct)
            if ct_str and ct_str.lower() in vt_lower:
                return constraint

        return None
