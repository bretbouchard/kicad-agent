"""Manufacturing export wrappers for kicad-agent.

Provides Python wrappers for all kicad-cli export commands and board
statistics extraction. Each function validates inputs, invokes kicad-cli
(or parses directly for statistics), and returns structured results.

GEN-02: Manufacturing export via kicad-cli wrappers.

Usage:
    from kicad_agent.export import (
        export_gerber,
        export_drill,
        export_bom,
        export_position,
        export_netlist,
        export_step,
        export_schematic_pdf,
        get_board_statistics,
    )
"""

from kicad_agent.export.gerber import ExportResult, export_drill, export_gerber

__all__ = [
    "ExportResult",
    "export_gerber",
    "export_drill",
]
