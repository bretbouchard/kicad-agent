"""ConventionEngine (Plan 02 Task 1).

Runs Convention checks against a LayoutView. Error-tolerant. Mirrors Phase 48
DesignRuleEngine.

P2-1 (Council): passes per-convention config thresholds via check(layout, config).
T-111-07: broken convention → meta-Violation (severity=warning); engine continues.
"""
from __future__ import annotations

import logging
from typing import Optional

from kicad_agent.conventions.base import Convention, Violation
from kicad_agent.conventions.layout_view import LayoutView
from kicad_agent.conventions.loader import ConventionConfig

logger = logging.getLogger(__name__)

# Severity ordering (lower = more actionable, sorts first).
_SEVERITY_ORDER: dict[str, int] = {"error": 0, "warning": 1, "info": 2}


class ConventionEngine:
    """Runs Convention checks against a LayoutView. Error-tolerant.

    Mirrors Phase 48 DesignRuleEngine: disabled conventions skipped, broken
    convention produces a meta-Violation (severity=warning), results sorted
    by severity.
    """

    def __init__(
        self,
        conventions: list[Convention],
        config: Optional[ConventionConfig] = None,
    ):
        self._conventions = conventions
        self._disabled = (config.disabled_conventions if config else set()) or set()
        self._configs = (config.convention_configs if config else {}) or {}

    def run(self, layout: LayoutView) -> list[Violation]:
        """Run all enabled conventions against `layout`.

        Returns violations sorted by severity (error → warning → info).
        """
        all_violations: list[Violation] = []
        for conv in self._conventions:
            if conv.rule_id in self._disabled:
                continue
            try:
                # P2-1: pass per-convention config thresholds to check()
                cfg = self._configs.get(conv.rule_id)
                violations = conv.check(layout, config=cfg)
            except Exception as e:  # noqa: BLE001 — T-111-07 tolerance
                logger.error(
                    "Convention %s raised: %s", conv.rule_id, e, exc_info=True,
                )
                violations = [
                    Violation(
                        rule_id=conv.rule_id,
                        severity="warning",
                        message=f"Convention execution failed: {e}",
                        component_refs=(),
                        suggestion_relative=(
                            f"Report bug: convention {conv.rule_id} crashed"
                        ),
                    )
                ]
            all_violations.extend(violations)

        all_violations.sort(key=lambda v: _SEVERITY_ORDER.get(v.severity, 99))
        return all_violations
