"""Design rule engine -- orchestrates rule execution and report generation.

DOMAIN-04: Runs pluggable design rules against circuit topologies.

Usage:
    from volta.analysis.design_rule_engine import DesignRuleEngine
    from volta.analysis.builtin_rules import get_builtin_rules

    engine = DesignRuleEngine(rules=get_builtin_rules())
    report = engine.run(topology)
    for v in report.violations:
        print(f"[{v.severity.value}] {v.rule_id}: {v.description}")
"""
from __future__ import annotations

import logging
import time
from typing import Any

from volta.analysis.design_rules import (
    DesignRule,
    DesignRuleReport,
    DesignRuleViolation,
    RuleSeverity,
)

logger = logging.getLogger(__name__)


class DesignRuleEngine:
    """Orchestrates design rule execution.

    Loads rules, runs them against a topology, and produces
    a structured report with all violations.

    Args:
        rules: List of DesignRule instances to run.
        disabled_rules: Set of rule names to skip.
        config: Per-rule configuration overrides.

    Usage:
        engine = DesignRuleEngine(rules=get_builtin_rules())
        report = engine.run(topology)
    """

    def __init__(
        self,
        rules: list[DesignRule] | None = None,
        disabled_rules: set[str] | None = None,
        config: dict[str, dict[str, Any]] | None = None,
    ):
        self._rules = rules or []
        self._disabled = disabled_rules or set()
        self._config = config or {}

    def run(self, topology: Any) -> DesignRuleReport:
        """Run all enabled rules against the topology.

        Algorithm:
        1. Filter out disabled rules
        2. For each enabled rule, call check() with config
        3. Collect violations, handle errors gracefully
        4. Sort violations by severity (CRITICAL first)
        5. Build and return DesignRuleReport

        Error handling: if a rule raises an exception, log it
        and continue with remaining rules. Never let one broken
        rule kill the entire check.

        Args:
            topology: CircuitTopology from Phase 45.

        Returns:
            DesignRuleReport with all violations and summary.
        """
        start = time.monotonic()
        all_violations: list[DesignRuleViolation] = []
        rules_run = 0
        rules_passed = 0
        rules_failed = 0

        for rule in self._rules:
            if rule.name in self._disabled:
                logger.debug("Skipping disabled rule: %s", rule.name)
                continue

            rules_run += 1
            rule_config = self._config.get(rule.name, {})

            try:
                violations = rule.check(topology, config=rule_config)
            except Exception as e:
                logger.error(
                    "Rule %s raised exception: %s", rule.name, e,
                    exc_info=True,
                )
                # Create a meta-violation for the broken rule
                violations = [DesignRuleViolation(
                    rule_id=rule.name,
                    description=f"Rule execution failed: {e}",
                    severity=RuleSeverity.WARNING,
                    location="(rule engine)",
                    suggestion=f"Report this as a bug: rule {rule.name} crashed",
                )]

            if violations:
                rules_failed += 1
                all_violations.extend(violations)
            else:
                rules_passed += 1

        # Sort: CRITICAL > WARNING > SUGGESTION > INFO
        severity_order = {
            RuleSeverity.CRITICAL: 0,
            RuleSeverity.WARNING: 1,
            RuleSeverity.SUGGESTION: 2,
            RuleSeverity.INFO: 3,
        }
        all_violations.sort(key=lambda v: severity_order[v.severity])

        elapsed = (time.monotonic() - start) * 1000

        return DesignRuleReport(
            violations=tuple(all_violations),
            schematic_path=getattr(topology, "schematic_path", ""),
            rules_run=rules_run,
            rules_passed=rules_passed,
            rules_failed=rules_failed,
            elapsed_ms=elapsed,
        )

    def add_rule(self, rule: DesignRule) -> None:
        """Add a rule to the engine."""
        self._rules.append(rule)

    def disable_rule(self, rule_name: str) -> None:
        """Disable a rule by name."""
        self._disabled.add(rule_name)

    def enable_rule(self, rule_name: str) -> None:
        """Re-enable a previously disabled rule."""
        self._disabled.discard(rule_name)

    @property
    def rule_names(self) -> list[str]:
        """List all registered rule names."""
        return [r.name for r in self._rules]
