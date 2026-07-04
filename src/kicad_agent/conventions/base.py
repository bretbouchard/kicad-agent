"""Convention ABC + Violation model (Plan 01 Task 1).

D-03: Convention ABC has both check(layout, config=None) and apply(layout).
D-04: Violation model has to_json() and to_markdown().
P0-3 (Council): rule_id / severity are CLASS-LEVEL attributes on subclasses
                (mirrors Phase 48 DesignRule.name / default_severity pattern).
                rule_id regex matches Phase 48 DesignRuleViolation.rule_id EXACTLY:
                r'^[A-Z][A-Z0-9_]*\\d{2}$' — two-digit suffix mandatory.
P1-2 (Council, scoped LO-04): Violation.model_fields has no coordinate names.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

# D-04 severity vocabulary (Literal, not enum — simpler, JSON-native).
Severity = Literal["error", "warning", "info"]


class Violation(BaseModel):
    """A single convention violation.

    LO-04 (scoped per P1-2): relative suggestions only, no coordinates.
    Field set is exactly {rule_id, severity, message, component_refs, suggestion_relative}.
    """

    # P0-3: regex matches Phase 48 DesignRuleViolation.rule_id EXACTLY.
    # Digits mandatory — rejects "RULE" / "RULE_1"; requires "RULE_NN".
    rule_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*\d{2}$")
    severity: Severity
    message: str = Field(min_length=1, max_length=2000)
    component_refs: tuple[str, ...] = Field(default_factory=tuple)
    suggestion_relative: str = Field(default="", max_length=1000)

    def to_json(self) -> dict[str, Any]:
        """D-04 JSON output — consumed by Phase 110 GRPO + programmatic analysis."""
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "component_refs": list(self.component_refs),
            "suggestion_relative": self.suggestion_relative,
        }

    def to_markdown(self) -> str:
        """D-04 markdown output — consumed by CLI display + human review."""
        refs = ", ".join(self.component_refs) or "—"
        return (
            f"- [{self.severity.upper()}] {self.rule_id}: {self.message} "
            f"(refs: {refs}) — {self.suggestion_relative}"
        )


class Convention(ABC):
    """Convention ABC per D-03.

    P0-3 (Council): rule_id and severity are CLASS-LEVEL attributes mirroring
    Phase 48 DesignRule.name / default_severity. Subclasses MUST declare them
    at class scope (verified by test_rule_id_and_severity_are_class_level_attributes).

    D-03: Subclasses override one or both of check() / apply().
      - Read-only conventions override check() only; apply() returns layout unchanged.
      - Transform conventions override both — check() reports what would change,
        apply() returns a new LayoutView via dataclasses.replace (Phase 100 CR-01).
    """

    # Subclass MUST override at class level (P0-3).
    rule_id: str
    severity: Severity
    description: str = ""

    @abstractmethod
    def check(
        self,
        layout: "LayoutView",  # type: ignore[name-defined]  # noqa: F821
        config: dict[str, Any] | None = None,
    ) -> list[Violation]:
        """Read-only inspection.

        P2-1 (Council): config parameter mirrors Phase 48 DesignRule.check —
        engine passes per-convention thresholds via this argument.
        """
        ...

    @abstractmethod
    def apply(
        self,
        layout: "LayoutView",  # type: ignore[name-defined]  # noqa: F821
    ) -> "LayoutView":  # type: ignore[name-defined]  # noqa: F821
        """Returns modified LayoutView.

        Read-only conventions return `layout` unchanged (identity).
        Transform conventions return a new LayoutView via dataclasses.replace
        (Phase 100 CR-01 — NEVER mutate input).
        """
        ...
