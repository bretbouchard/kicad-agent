# Validation

ERC/DRC gates via kicad-cli, structural validation, and round-trip fidelity checks.

The validation module runs electrical rule checks (ERC) and design rule checks (DRC) via KiCad's kicad-cli tool after every edit. Files that fail validation are automatically rolled back.

::: kicad_agent.validation
    options:
      show_source: true
