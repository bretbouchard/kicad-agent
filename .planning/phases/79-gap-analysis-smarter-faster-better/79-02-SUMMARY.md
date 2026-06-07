---
phase: 79-gap-analysis-smarter-faster-better
plan: 02
subsystem: export
tags: [kicad-cli, wrappers, render, svg, pdf, export]
requirements: [CLI-01]

dependency_graph:
  requires: []
  provides: [render_pcb_3d, export_schematic_svg, export_symbol_svg, export_footprint_svg, export_pcb_svg, export_pcb_pdf]
  affects: [export/__init__.py]

tech_stack:
  added: []
  patterns: [shared-infrastructure-reuse, subprocess-mock-testing]

key_files:
  created:
    - src/kicad_agent/export/cli_wrappers.py
    - tests/test_cli_wrappers.py
    - tests/test_export_position_formats.py
  modified:
    - src/kicad_agent/export/__init__.py

decisions:
  - "render_pcb_3d returns dict (not ExportResult) because it has different fields (image_path, width_px, height_px)"
  - "All 5 export wrappers return ExportResult for consistency with existing gerber/general patterns"
  - "Background color validated with hex regex (#RRGGBB) to prevent CLI flag injection (T-79-06)"

metrics:
  duration_seconds: 110
  completed_date: 2026-06-07
---

# Phase 79 Plan 02: kicad-cli Wrappers Summary

Filled the kicad-cli completeness gap by adding Python wrappers for 6 previously unwrapped commands: pcb render (3D), sch export svg, sym export svg, fp export svg, pcb export svg, and pcb export pdf. All wrappers reuse shared infrastructure from gerber.py (_find_kicad_cli, _validate_pcb_path, _run_kicad_export, ExportResult) with zero subprocess duplication.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create cli_wrappers.py with 6 kicad-cli wrappers (TDD) | b602001, 113ac4b | cli_wrappers.py, __init__.py, test_cli_wrappers.py |
| 2 | Verify export_position format completeness | 4330e73 | test_export_position_formats.py |

## Deviations from Plan

None - plan executed exactly as written.

## Key Decisions

1. **render_pcb_3d returns dict** -- Different return type (dict with image_path, width_px, height_px) than ExportResult because 3D rendering has unique fields that don't fit the directory-based ExportResult pattern.

2. **Background color hex validation (T-79-06)** -- Added regex validation `^#[0-9a-fA-F]{6}$` to prevent CLI flag injection through the background parameter.

3. **export_position already complete** -- Confirmed the gap analysis claim was already resolved; csv, ascii, and gerber formats all supported with side and units options.

## TDD Gate Compliance

- RED gate: `b602001` (test commit before implementation)
- GREEN gate: `113ac4b` (implementation commit after failing tests)
- REFACTOR gate: Not needed (clean implementation, no refactoring required)

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: input_validation | cli_wrappers.py | Background color hex regex prevents CLI flag injection (T-79-06) |
