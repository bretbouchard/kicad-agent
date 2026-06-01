# Phase 49: One-Command Demo

## Overview

Elevate demo quality from 6 to 8 by implementing `kicad-agent demo` -- a single command that generates a complete schematic from a template, validates it, renders it, and produces a summary report. This is the "wow" moment: one command, zero config, real output.

## Motivation

The generation pipeline (`generate_design()` in Phase 10) and the validation pipeline (ERC/DRC in Phase 3) exist as separate pieces. The CLI exposes them as individual subcommands. There is no single entry point that strings them together into a demonstrable workflow. A first-time user should be able to run `kicad-agent demo` and get a complete, validated, rendered schematic in under 60 seconds.

## Plans

| Plan | Title | Type | Depends On | Status |
|------|-------|------|------------|--------|
| 49-01 | Demo Pipeline | execute | 38-01 (routing engine) | Not started |
| 49-02 | Demo Templates | execute | 49-01 | Not started |

## Plan Details

### 49-01: Demo Pipeline

Build the `demo` CLI subcommand and `DemoPipeline` orchestration class. The pipeline:

1. Select a template (by name or `--random`)
2. Generate the schematic via `generate_design()`
3. Run ERC, capture violations
4. Auto-fix via `erc_auto_fix` (if available)
5. Re-run ERC, capture delta
6. Render SVG via `kicad-cli sch export svg`
7. Print a structured `DemoReport` to stdout

Files: `src/kicad_agent/cli.py`, `src/kicad_agent/demo/pipeline.py`, `src/kicad_agent/demo/templates.py`, `tests/test_demo.py`

### 49-02: Demo Templates

Create 5+ built-in circuit templates spanning basic to advanced difficulty. Each template is a `DemoTemplate` instance wrapping a `GenerationIntent` with metadata (name, description, difficulty tier, expected component/net counts).

Templates include:
- **RC Low-Pass Filter** (basic) -- 3 components, 2 nets
- **Op-Amp Buffer** (basic) -- 5 components, 4 nets
- **Common-Emitter Amplifier** (intermediate) -- 8 components, 6 nets
- **Sallen-Key Filter** (intermediate) -- 10 components, 8 nets
- **THAT4301 Compressor Stage** (advanced) -- 15 components, 12 nets
- **NE5532 Dual Op-Amp Stage** (advanced) -- 12 components, 10 nets

Files: `src/kicad_agent/demo/templates.py`, `tests/test_demo_templates.py`

## Requirements Coverage

| Requirement | Plan | Description |
|-------------|------|-------------|
| DEMO-01 | 49-01 | One-command demo pipeline |
| DEMO-04 | 49-02 | Built-in circuit templates |

## Success Criteria

1. `kicad-agent demo` runs end-to-end without errors using any built-in template
2. Generated schematics pass ERC (after auto-fix) or have documented pre-existing violations
3. SVG renders are produced automatically in output directory
4. DemoReport JSON is printed to stdout with all fields populated
5. `--template random` selects from all available templates
6. Total execution time under 60 seconds for basic/intermediate templates

## Dependencies

- Phase 38 (schematic routing engine) for wire routing in generated schematics
- Phase 10 (AI generation pipeline) for `generate_design()` and `GenerationIntent`
- Phase 3 (validation pipeline) for ERC/DRC execution
- Phase 35 (remaining ops gaps) for `erc_auto_fix`
