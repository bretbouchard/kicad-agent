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
        render_pcb_3d,
        export_schematic_svg,
        export_symbol_svg,
        export_footprint_svg,
        export_pcb_svg,
        export_pcb_pdf,
    )
"""

from kicad_agent.export.gerber import ExportResult, export_drill, export_gerber
from kicad_agent.export.bom import BomResult, export_bom, parse_bom_csv
from kicad_agent.export.general import (
    export_netlist,
    export_position,
    export_schematic_pdf,
    export_step,
    get_board_statistics,
)
from kicad_agent.export.cli_wrappers import (
    export_footprint_svg,
    export_pcb_pdf,
    export_pcb_svg,
    export_schematic_svg,
    export_symbol_svg,
    render_pcb_3d,
)

__all__ = [
    "ExportResult",
    "export_gerber",
    "export_drill",
    "BomResult",
    "export_bom",
    "parse_bom_csv",
    "export_position",
    "export_netlist",
    "export_step",
    "export_schematic_pdf",
    "get_board_statistics",
    "render_pcb_3d",
    "export_schematic_svg",
    "export_symbol_svg",
    "export_footprint_svg",
    "export_pcb_svg",
    "export_pcb_pdf",
]
