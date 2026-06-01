# Phase 50: Visual Output Showcase

## Overview

Elevate demo quality from 8 to 9 by producing rich visual output: annotated SVG schematics with ERC violation markers, before/after visual diffs, and Markdown reports with embedded images. The demo output should be immediately useful for design reviews and documentation.

## Motivation

Phase 49 produces a schematic and an SVG render, but the SVG is raw kicad-cli output. There is no visual indication of where ERC violations occur, what was fixed, or what the design looks like relative to a known-good baseline. Professional EDA tools annotate schematics with error markers. kicad-agent should too.

## Plans

| Plan | Title | Type | Depends On | Status |
|------|-------|------|------------|--------|
| 50-01 | SVG Annotation Engine | execute | 49-01 | Not started |
| 50-02 | Visual Diff and Report Generator | execute | 50-01 | Not started |

## Plan Details

### 50-01: SVG Annotation Engine

Build `SvgAnnotator` that takes an SVG schematic + a list of violations/annotations and produces an annotated SVG with numbered red circles at violation positions, callout labels, and a summary legend. Also `svg_utils.py` for SVG parsing helpers (coordinate transforms, element queries).

Files: `src/kicad_agent/spatial/annotator.py`, `src/kicad_agent/spatial/svg_utils.py`, `tests/test_svg_annotation.py`

### 50-02: Visual Diff and Report Generator

Build `VisualDiffer` that compares two SVGs and highlights differences, and `ReportGenerator` that produces Markdown reports with embedded SVGs, statistics tables, and before/after comparison sections.

Files: `src/kicad_agent/spatial/visual_diff.py`, `src/kicad_agent/demo/report_generator.py`, `tests/test_visual_diff.py`

## Requirements Coverage

| Requirement | Plan | Description |
|-------------|------|-------------|
| DEMO-02 | 50-01 | SVG annotation engine with violation markers |
| DEMO-05 | 50-02 | Visual diff and annotated reports |

## Success Criteria

1. Annotated SVG shows ERC violations as red numbered circles with callout text
2. Annotation style is configurable (color, font size, circle radius, opacity)
3. SVG parsing handles KiCad-generated SVG namespace correctly
4. Visual diff highlights differences between two schematic SVGs
5. Markdown report includes embedded SVGs and statistics
6. Demo pipeline (Phase 49) can optionally produce annotated output

## Dependencies

- Phase 49 (one-command demo) for pipeline integration
- Phase 3 (validation pipeline) for ERC violation data
- Phase 8 (visual primitives) for renderer infrastructure
- Phase 48 (design rule intelligence) for design rule violation annotations
