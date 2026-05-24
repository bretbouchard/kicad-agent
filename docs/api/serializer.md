# Serializer

Write valid KiCad files with UUID re-injection and normalization.

The serializer module converts modified AST structures back into valid KiCad S-expression files. It handles UUID preservation, normalization of output formatting, and ensures byte-identical or semantically equivalent round-trips.

::: kicad_agent.serializer
    options:
      show_source: true
