# Parser

Parse KiCad S-expression files into structured AST representations.

The parser module handles all four KiCad file types: schematics (.kicad_sch), PCB layouts (.kicad_pcb), symbol libraries (.kicad_sym), and footprint files (.kicad_mod). It uses kiutils for AST construction and sexpdata for raw S-expression handling.

::: volta.parser
    options:
      show_source: true
