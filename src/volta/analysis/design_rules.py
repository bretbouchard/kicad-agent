"""Design rule schemas and ABC for pluggable rule engine.

DOMAIN-04: Domain-specific DRC beyond KiCad ERC/DRC.

Defines the contract for design rules:
- DesignRule ABC: name, category, severity, check() method
- DesignRuleViolation: structured violation output
- DesignRuleReport: aggregated report with summary stats
- RuleSeverity: severity enum
- RuleCategory: category enum

Security:
  T-48-01: Violations list capped at 500 per report (DoS prevention).
  T-48-02: suggestion text max 1000 chars.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from volta.analysis.topology_graph import CircuitTopology

from pydantic import BaseModel, Field


class RuleSeverity(str, Enum):
    """Design rule violation severity."""

    INFO = "INFO"
    SUGGESTION = "SUGGESTION"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RuleCategory(str, Enum):
    """Design rule category for grouping."""

    BYPASS_CAPS = "bypass_caps"
    FEEDBACK = "feedback"
    IMPEDANCE = "impedance"
    THERMAL = "thermal"
    GROUND = "ground"
    POWER = "power"
    SIGNAL = "signal"
    LAYOUT = "layout"


class DesignRuleViolation(BaseModel):
    """A single design rule violation.

    Attributes:
        rule_id: Rule identifier (e.g. "BYPASS_CAP_01").
        description: What was found and why it matters.
        severity: Violation severity level.
        location: Where in the design (component ref, net name, or position).
        suggestion: Concrete fix recommendation.
        affected_components: Component refs involved.
        details: Additional context (optional).
    """

    rule_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*\d{2}$")
    description: str = Field(min_length=1, max_length=2000)
    severity: RuleSeverity
    location: str = Field(min_length=1, max_length=512)
    suggestion: str = Field(default="", max_length=1000)
    affected_components: tuple[str, ...] = Field(default_factory=tuple)
    details: dict[str, Any] = Field(default_factory=dict)


class DesignRuleReport(BaseModel):
    """Aggregated report from design rule checks.

    Attributes:
        violations: All violations found, sorted by severity.
        schematic_path: Path to the checked schematic.
        rules_run: Number of rules that were executed.
        rules_passed: Number of rules with no violations.
        rules_failed: Number of rules with violations.
        summary: Severity counts.
        elapsed_ms: Total execution time.
    """

    violations: tuple[DesignRuleViolation, ...] = Field(
        default_factory=tuple, max_length=500,
    )
    schematic_path: str = Field(default="")
    rules_run: int = Field(default=0, ge=0)
    rules_passed: int = Field(default=0, ge=0)
    rules_failed: int = Field(default=0, ge=0)
    summary: dict[str, int] = Field(default_factory=dict)
    elapsed_ms: float = Field(default=0.0, ge=0.0)

    def model_post_init(self, __context: Any) -> None:
        counts = {s.value: 0 for s in RuleSeverity}
        for v in self.violations:
            counts[v.severity.value] += 1
        self.summary = counts


class DesignRule(ABC):
    """Abstract base class for design rules.

    Subclass this to create custom rules. Register with
    DesignRuleEngine to run them against circuit topologies.

    Attributes:
        name: Rule identifier (e.g. "BYPASS_CAP_01").
        category: Rule category for grouping.
        default_severity: Default severity for violations.
        description: What this rule checks.
    """

    name: str
    category: RuleCategory
    default_severity: RuleSeverity
    description: str = ""

    @abstractmethod
    def check(
        self,
        topology: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DesignRuleViolation]:
        """Check the topology for this rule's violations.

        Args:
            topology: CircuitTopology to check.
            config: Optional configuration overrides (thresholds, etc.).

        Returns:
            List of violations found. Empty list if no violations.
        """
        ...
