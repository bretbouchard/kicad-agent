# Fix #15: Commit fixes and close issue

## Context

Two bugs found in `generate_schematic.py` via progressive binary search testing:

1. **Invalid label shape** (line 630): `"power_out"` is not a valid `global_label` shape in KiCad 10. Fixed to `"output"`.
2. **Malformed text element** (lines 645-657): Multi-line text split across multiple `"..."` strings, and `(size ...)` was a direct child of `(text ...)` instead of `(effects (font ...))`. Fixed to single string with `\n` escapes and proper wrapper.

## Already Done (edits applied before plan mode)

- `generate_schematic.py` line 630: `"power_out"` → `"output"`
- `generate_schematic.py` lines 645-657: Text element reformatted

## Steps

1. Commit the two fixes in `generate_schematic.py`
2. Close issue #15 via `gh issue close`

## Verification (already passed)

- `kicad-cli sch erc x65-button-grid.kicad_sch` → 767 violations (unconnected pins, expected)
- `kicad-cli sch export pdf` → Plotted successfully
