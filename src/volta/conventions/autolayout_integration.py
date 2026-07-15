"""Phase 108 autolayout integration — load conventions as placement constraints.

Consumed by Phase 108's autolayout engine. The engine calls:
1. load_conventions_as_constraints(config) at startup → enabled conventions
2. evaluate_placement(layout, conventions) after each placement iteration → score
3. suggest_placement_adjustments(layout, violations, conventions) → apply TRANSFORM conventions

P1-3 fix (Council Round 1): suggest_placement_adjustments dedupes by rule_id.
Each convention's apply() runs at most ONCE per call (whole-layout transform
semantics), not once per violation.

Phase 100 CR-01: suggest_placement_adjustments returns a new LayoutView; input
never mutated. Read-only conventions (identity apply) are no-ops.

This module is the stable integration surface — Phase 108 imports from here,
not from engine.py directly, so the contract holds even if engine internals
change.
"""
from __future__ import annotations

import logging
from typing import Optional

from volta.conventions.base import Convention, Violation
from volta.conventions.catalog import get_v1_catalog
from volta.conventions.engine import ConventionEngine
from volta.conventions.layout_view import LayoutView
from volta.conventions.loader import ConventionConfig, ConventionConfigLoader

logger = logging.getLogger(__name__)


def load_conventions_as_constraints(
    config: Optional[ConventionConfig] = None,
) -> list[Convention]:
    """Return enabled conventions for Phase 108 autolayout constraints.

    Args:
        config: Optional ConventionConfig. Disabled conventions are filtered out.

    Returns:
        List of Convention instances from the v1 catalog, minus any disabled.
    """
    catalog = get_v1_catalog()
    if config is None:
        return list(catalog)
    disabled = config.disabled_conventions
    return [c for c in catalog if c.rule_id not in disabled]


def evaluate_placement(
    layout: LayoutView,
    conventions: list[Convention],
) -> list[Violation]:
    """Run all convention check() methods against a candidate layout.

    Used by Phase 108 after each placement iteration to score the layout.
    """
    engine = ConventionEngine(conventions=conventions)
    return engine.run(layout)


def suggest_placement_adjustments(
    layout: LayoutView,
    violations: list[Violation],
    conventions: list[Convention],
) -> LayoutView:
    """Apply TRANSFORM conventions to the layout.

    P1-3 fix (Council Round 1): dedupe violations by rule_id. Each convention's
    apply() runs AT MOST ONCE per call (whole-layout transform semantics).
    For 100 violations across one convention, apply() runs 1 time — not 100.

    Phase 100 CR-01: returns a NEW LayoutView. Input is never mutated.
    Read-only conventions (identity apply) are no-ops here.
    """
    convention_map = {c.rule_id: c for c in conventions}
    current = layout
    seen_rule_ids: set[str] = set()
    for v in violations:
        if v.rule_id in seen_rule_ids:
            continue  # P1-3: skip — this convention already applied once
        seen_rule_ids.add(v.rule_id)
        conv = convention_map.get(v.rule_id)
        if conv is None:
            continue
        # apply() is identity for read-only conventions, transform for others.
        current = conv.apply(current)
    return current


def discover_config() -> ConventionConfig:
    """Auto-discover and load .kicad-agent/conventions.yaml.

    Returns empty ConventionConfig if the file is absent or invalid. This is
    the convenience wrapper Phase 108 calls at startup.
    """
    path = ConventionConfigLoader.discover()
    loader = ConventionConfigLoader(path)
    try:
        return loader.load()
    except ValueError as e:
        logger.warning("Convention config invalid, using defaults: %s", e)
        return ConventionConfig()
