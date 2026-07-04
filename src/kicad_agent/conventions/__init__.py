"""Phase 111 Convention Library.

D-03 (CONTEXT): Convention ABC with check() + apply() on a single class.
D-04 (CONTEXT): Dual-format output (JSON + markdown) on Violation.
P0-3 (Council): rule_id / severity declared at CLASS LEVEL on subclasses.
Phase 100 CR-01: LayoutView is a frozen dataclass; apply() returns new instance.
"""
from __future__ import annotations

from kicad_agent.conventions.base import Convention, Severity, Violation
from kicad_agent.conventions.layout_view import (
    ComponentView,
    LabelView,
    LayoutView,
    WireView,
)

__all__ = [
    "Convention",
    "Violation",
    "Severity",
    "LayoutView",
    "ComponentView",
    "WireView",
    "LabelView",
]
