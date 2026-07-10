# Stack — v7.0 Vendor-Neutral Manufacturing Layer

## Existing Stack (No Changes Needed)

All required dependencies are already installed and verified in the codebase. v7.0 adds **zero new dependencies** — it is built entirely on the existing KiCad CLI + Python stack.

| Technology | Version | Purpose | Status |
|------------|---------|---------|--------|
| Python | 3.11 | Runtime | Existing |
| kicad-cli | 10.0.1 | DRC, Gerber/drill/BOM/pos/STEP export, renders | Existing — all v7.0 exports use it |
| kiutils | 1.4.8 | S-expression parsing | Existing — used for title_block parsing |
| sexpdata | 1.0.0 | Low-level S-expression parsing | Existing |
| Pydantic | 2.x | Operation schemas, BoardSpec model, Build record | Existing — already used for all 142 ops |
| stdlib zipfile | — | Build handoff zip bundling | stdlib — no new dep |
| stdlib hashlib | — | SHA256 artifact hashing | stdlib — already used in ManufacturingManifest |
| stdlib json | — | Manifest serialization | stdlib |

## What We Do NOT Need (Explicitly Avoided)

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| New HTTP client library | Vendor API adapters are deferred (P6) | stdlib urllib/requests (already a dep) when P6 activates |
| New PDF generation library | Fab notes generated as Markdown → existing kicad-cli PDF export for plots | Markdown readme + kicad-cli plot PDFs |
| New ZIP library | stdlib `zipfile` / `shutil.make_archive` suffices | stdlib |
| New schema/serialization framework | Pydantic already handles all ops | Pydantic |
| Cloud storage SDK | Builds are local artifacts on disk | Local filesystem under project `builds/` dir |

## Integration Points

1. **kicad-cli DRC** — `kicad-cli pcb drc <file.kicad_pcb> --custom-rules <profile.kicad_dru>` already supports custom rule files. v7.0 wires up vendor profiles directly.
2. **Existing export wrappers** (`src/kicad_agent/export/`) — gerber, drill, bom, pos, step, netlist, pdf, render all exist. v7.0 orchestrates them into a single bundle.
3. **Existing ops registry** (`src/kicad_agent/ops/registry.py`) — 142 ops with a clear extension pattern (add schema class + registry entry + handler). v7.0 adds ~8 new ops.
4. **Existing MCP auto-generation** (`src/kicad_agent/mcp/edit_server.py:133`) — new ops in the Operation union are auto-exposed as MCP tools. Zero MCP wiring needed.

## Version Compatibility Notes

- `kicad-cli pcb drc --custom-rules` flag is stable across KiCad 9/10 — the `.kicad_dru` format is versioned (`(version 1)`) and backward compatible.
- `.kicad_dru` files from PCBWay (2023-10) and AISLER (2026-01) both use `(version 1)` — compatible with KiCad 10.
- JLCPCB community files (Cimos aggregator, MIT) are also `(version 1)` format.

## Sources

- kicad-cli custom rules: https://dev-docs.kicad.org/en/kicad-cli-cli-reference/#_pcb_drc
- KiCad DRC rule file format: https://docs.kicad.org/9.0/en/pcbnew/pcbnew.html#_custom_design_rules
- Verified in-session: kicad-cli 10.0.1 installed at /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
