"""v1 Convention catalog entry point (Plan 02 Task 1 + Task 2).

D-01 (CONTEXT): v1 catalog is data-driven from ACTUAL Phase 108 autolayout
SRS-verification violation data (see 108-SRS-VERIFICATION.md). Phase 108's
observed factor deltas:
  - spacing +0.050 on Arduino_Mega (autolayout places components better)
  - all other factors unchanged (small fixtures at ceiling)

Task 1 (this file's initial state): only the 6 Phase 48.5 readability adapters.
Task 2 will append 4 new IEEE 315 conventions grounded in Phase 108's actual
mutation surface (move_symbol + insert_wire + insert_label).

Final v1 catalog count: 10 conventions (6 adapters + 4 new) — within D-01's
10-15 range.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from kicad_agent.conventions.catalog.readability_adapters import (
    get_adapted_readability_rules,
)

if TYPE_CHECKING:
    from kicad_agent.conventions.base import Convention


def get_v1_catalog() -> list["Convention"]:
    """Return v1 Convention catalog.

    Per D-01: data-driven from Phase 108 SRS-verification. Task 2 appends
    IEEE 315 conventions (signal_flow, pin_orientation, grid_alignment,
    wire_orthogonality) grounded in Phase 108's actual mutation surface.
    """
    catalog: list["Convention"] = list(get_adapted_readability_rules())  # 6 rules

    # Task 2 appends new conventions here. The try/except keeps Plan 02 Task 1
    # shippable independently (Task 2 modules don't exist yet at Task 1 commit).
    try:
        from kicad_agent.conventions.catalog.signal_flow import (
            SIGNAL_FLOW_DIRECTION_01,
        )
        from kicad_agent.conventions.catalog.grid_alignment import (
            GRID_ALIGNMENT_01,
        )
        from kicad_agent.conventions.catalog.wire_orthogonality import (
            WIRE_ORTHOGONALITY_01,
        )
        from kicad_agent.conventions.catalog.pin_orientation import (
            IEEE315_PIN_ORIENTATION_01,
        )

        catalog.extend(
            [
                SIGNAL_FLOW_DIRECTION_01(),
                IEEE315_PIN_ORIENTATION_01(),
                GRID_ALIGNMENT_01(),
                WIRE_ORTHOGONALITY_01(),
            ]
        )
    except ImportError:  # Task 2 modules not yet shipped
        pass

    return catalog
