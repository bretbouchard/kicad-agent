"""Manufacturing export wrappers for volta.

Provides Python wrappers for all kicad-cli export commands, 3D rendering,
and board statistics extraction. Each function validates inputs, invokes
kicad-cli (or parses directly for statistics), and returns structured results.

GEN-02: Manufacturing export via kicad-cli wrappers.

Usage:
    from volta.export import (
        export_gerber,
        export_drill,
        export_bom,
        export_position,
        export_netlist,
        export_step,
        export_schematic_pdf,
        export_schematic_svg,
        export_symbol_svg,
        export_footprint_svg,
        export_pcb_svg,
        export_pcb_pdf,
        render_pcb,
        render_pcb_3d,
        get_board_statistics,
    )
"""

from volta.export.gerber import ExportResult, export_drill, export_gerber
from volta.export.bom import BomResult, export_bom, parse_bom_csv
from volta.export.general import (
    export_netlist,
    export_position,
    export_schematic_pdf,
    export_step,
    get_board_statistics,
)
from volta.export.cli_wrappers import (
    export_footprint_svg,
    export_pcb_pdf,
    export_pcb_svg,
    export_schematic_svg,
    export_symbol_svg,
    render_pcb_3d,
)
from volta.export.render import (
    RenderResult,
    render_pcb,
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
    "export_schematic_svg",
    "export_symbol_svg",
    "export_footprint_svg",
    "export_pcb_svg",
    "export_pcb_pdf",
    "RenderResult",
    "render_pcb",
    "render_pcb_3d",
    "get_board_statistics",
]
